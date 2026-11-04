"""Applications go out in working hours on working days; outside them a run stops before any browser opens."""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import Settings
from common.run import outside_run_window

IST = ZoneInfo("Asia/Kolkata")


def _at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def test_the_default_window_is_weekdays_ten_to_six_ist():
    settings = Settings()
    assert outside_run_window(settings, _at(4, 10)) == ""          # Wednesday 10:00
    assert outside_run_window(settings, _at(4, 17, 59)) == ""
    assert "17:59" not in outside_run_window(settings, _at(4, 18))  # 18:00 is closed
    assert "18:00" in outside_run_window(settings, _at(4, 18))
    assert "09:59" in outside_run_window(settings, _at(4, 9, 59))
    assert "Saturday" in outside_run_window(settings, _at(7, 12))
    assert "Sunday" in outside_run_window(settings, _at(8, 12))


def test_the_clock_is_read_in_the_configured_zone():
    settings = Settings()
    utc_morning = datetime(2026, 11, 4, 5, 0, tzinfo=ZoneInfo("UTC"))   # 10:30 IST
    assert outside_run_window(settings, utc_morning) == ""
    assert "Asia/Kolkata" in outside_run_window(settings, datetime(2026, 11, 4, 14, 0, tzinfo=ZoneInfo("UTC")))


@pytest.mark.parametrize("days,weekday_open", [
    ("mon-fri", {0, 1, 2, 3, 4}),
    ("mon,wed,fri", {0, 2, 4}),
    ("sat-mon", {5, 6, 0}),
    ("", set(range(7))),
    ("any", set(range(7))),
])
def test_run_days_spell_out_which_days(days, weekday_open):
    settings = Settings(run_days=days)
    for day in range(2, 9):   # 2026-11-02 is a Monday
        open_now = outside_run_window(settings, _at(day, 12)) == ""
        assert open_now == (_at(day, 12).weekday() in weekday_open), days


def test_an_empty_window_allows_any_time():
    assert outside_run_window(Settings(run_window=""), _at(8, 3)) == ""


def test_an_unreadable_window_is_logged_and_ignored(caplog):
    with caplog.at_level("WARNING"):
        assert outside_run_window(Settings(run_window="ten-to-six"), _at(8, 3)) == ""
    assert "could not be read" in caplog.text


def test_a_window_that_crosses_midnight_runs_overnight():
    settings = Settings(run_window="22:00-06:00", run_days="")
    assert outside_run_window(settings, _at(4, 23)) == ""
    assert outside_run_window(settings, _at(5, 5, 59)) == ""
    assert "12:00" in outside_run_window(settings, _at(4, 12))
    assert "06:00" in outside_run_window(settings, _at(5, 6))


@pytest.fixture
def closed_today(monkeypatch, tmp_path):
    """A window open every hour of tomorrow only, so it is closed now, whatever the clock says.

    DRY_RUN is set explicitly because a dry run never waits for the window, and a developer's
    .env (setup writes DRY_RUN=true) would otherwise decide what these tests check.
    """
    tomorrow = (datetime.now(IST).weekday() + 1) % 7
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("RUN_WINDOW", "00:00-23:59")
    monkeypatch.setenv("RUN_DAYS", ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[tomorrow])
    monkeypatch.setenv("RUN_TIMEZONE", "Asia/Kolkata")
    from common import browser, profile as profile_module
    from common.models import Profile

    opened = []
    monkeypatch.setattr(browser, "create_driver", lambda settings: opened.append(settings) or pytest.fail("browser opened"))
    monkeypatch.setattr(profile_module, "load_profile", lambda settings: Profile(full_name="T"))
    return opened


def _bots():
    from sites_bot import external, platforms
    from startup_bot import cli as startups

    return [("boards", lambda flags: platforms.main(["--site", "hirist"] + flags)),
            ("startups", lambda flags: startups.main(flags)),
            ("company sites", lambda flags: external.main(["--retry-pending"] + flags))]


@pytest.mark.parametrize("name", ["boards", "startups", "company sites"])
def test_board_startup_and_company_site_runs_wait_for_the_window(closed_today, caplog, name):
    run = dict(_bots())[name]
    with caplog.at_level("INFO"):
        assert run([]) == 0
    assert "Not applying now" in caplog.text and "--ignore-window" in caplog.text
    assert closed_today == []


class _PastTheWindow(Exception):
    pass


def test_a_board_profile_update_is_not_an_application_and_ignores_the_window(closed_today, monkeypatch):
    from common import ledger
    from sites_bot import platforms

    def past(settings):
        raise _PastTheWindow()

    monkeypatch.setattr(ledger, "open_ledger", past)
    with pytest.raises(_PastTheWindow):
        platforms.main(["--site", "hirist", "--profile-only"])


@pytest.mark.parametrize("name", ["boards", "startups", "company sites"])
def test_ignore_window_runs_anyway(closed_today, monkeypatch, name):
    from common import ledger

    def past(settings):
        raise _PastTheWindow()

    monkeypatch.setattr(ledger, "open_ledger", past)
    monkeypatch.setattr("common.browser.create_driver", lambda settings: (_ for _ in ()).throw(_PastTheWindow()))
    with pytest.raises(_PastTheWindow):
        dict(_bots())[name](["--ignore-window"])


def test_the_pipeline_passes_ignore_window_to_every_apply_stage(monkeypatch):
    from pipeline import run

    monkeypatch.setattr(run, "_startup_jobs_on", lambda env: True)
    args = run.parse_args(["--ignore-window"])
    args.today = None
    stages = {stage.name: stage for stage in run.build_stages(args, ["hirist"])}
    for name in ("apply:naukri", "apply:hirist", "apply:startups"):
        assert "--ignore-window" in stages[name].command, name
    assert "--ignore-window" not in stages["profile:naukri"].command
    plain = run.parse_args([])
    plain.today = None
    assert "--ignore-window" not in {s.name: s for s in run.build_stages(plain, ["hirist"])}["apply:naukri"].command
