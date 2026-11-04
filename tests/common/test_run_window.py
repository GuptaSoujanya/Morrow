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
