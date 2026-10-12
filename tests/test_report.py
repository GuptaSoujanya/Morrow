"""reports/<date>/report.md: the day's work and what is left, from the records alone."""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sites_bot import external as ext
from common import ledger as ledger_module
from common import report
from common.ledger import Ledger
from common.models import ApplyResult, ApplyStatus, JobPosting, Settings


DAY = date(2026, 10, 10)
NOON = datetime(2026, 10, 10, 15, 0)

SIDEBAR = """- [Home & Study Plan](README.md)
- [Live AI & Tech News](news.md)

- **1. System Design**
  - [Track Overview](01-system-design/README.md)
  - [1.1 Fundamentals](01-system-design/01-fundamentals.md)
  - [1.2 Storage & Databases](01-system-design/02-storage-and-databases.md)

- **2. DSA**
  - [Track Overview & Big-O](02-dsa/README.md)
  - [2.1 Arrays, Strings & Hashing](02-dsa/01-arrays-strings-hashing.md)
  - [2.2 Two Pointers & Sliding Window](02-dsa/02-two-pointers-sliding-window.md)

- **5. Behavioral & Leadership**
  - [5.1 STAR Framework & Story Bank](05-behavioral-leadership/01-star-framework-and-stories.md)
"""


@pytest.fixture(autouse=True)
def _isolated_linkedin(monkeypatch, tmp_path):
    monkeypatch.setenv("LINKEDIN_STATE_PATH", str(tmp_path / "linkedin" / "state.json"))
    monkeypatch.setenv("LINKEDIN_DRAFT_DIR", str(tmp_path / "linkedin" / "drafts"))


def _settings(tmp_path, **overrides):
    course = tmp_path / "course"
    course.mkdir(exist_ok=True)
    (course / "_sidebar.md").write_text(SIDEBAR, encoding="utf-8")
    values = dict(
        email="t@example.com",
        password="secret",
        db_path=str(tmp_path / "naukri_bot.db"),
        profile_path=str(tmp_path / "data" / "profile.yaml"),
        profile_update_state_path=str(tmp_path / "logs" / "profile_update.json"),
        resume_out_dir=str(tmp_path / "resume" / "out"),
        report_dir=str(tmp_path / "reports"),
        course_dir=str(course),
        course_start_date="2026-10-10",
    )
    values.update(overrides)
    return Settings(**values)


def _utc(local):
    return local.astimezone().astimezone(timezone.utc).isoformat()


def _record(monkeypatch, settings, when, jid, status, detail=""):
    monkeypatch.setattr(ledger_module, "_now", lambda: _utc(when))
    ledger = Ledger(settings.db_path)
    try:
        ledger.record_attempt(
            ApplyResult(job_id=jid, url="https://www.naukri.com/job-%s" % jid, status=status, detail=detail,
                        quota_consumed=status == ApplyStatus.APPLIED),
            title="Role %s" % jid,
            company="Co %s" % jid,
        )
    finally:
        ledger.close()


def test_the_day_lists_what_was_applied_and_what_was_not(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    _record(monkeypatch, settings, datetime(2026, 10, 10, 9, 5), "a", ApplyStatus.APPLIED)
    _record(monkeypatch, settings, datetime(2026, 10, 10, 9, 9), "b", ApplyStatus.APPLIED_EXTERNAL, "greenhouse | thank you")
    _record(monkeypatch, settings, datetime(2026, 10, 10, 9, 12), "c", ApplyStatus.EXTERNAL_MANUAL, "needs you for: Why us")
    _record(monkeypatch, settings, datetime(2026, 10, 10, 9, 15), "d", ApplyStatus.ABSTAINED, "expected CTC unknown")
    _record(monkeypatch, settings, datetime(2026, 10, 9, 23, 50), "old", ApplyStatus.APPLIED)
    _record(monkeypatch, settings, datetime(2026, 10, 11, 0, 5), "next", ApplyStatus.APPLIED)

    text = report.build_report(settings, DAY, NOON)

    assert text.startswith("# Daily report: Saturday, 10 October 2026")
    assert "- Applied: 1 on Naukri, 0 on other job boards, 1 on company sites" in text
    assert "- Tried without applying: 2" in text
    assert "| 09:05 | Co a | Role a | Naukri | [job](https://www.naukri.com/job-a) |" in text
    assert "| 09:09 | Co b | Role b | Company site |" in text
    assert "| 09:12 | Co c | Role c | Company site, needs you | needs you for: Why us |" in text
    assert "| 09:15 | Co d | Role d | Skipped, a question had no answer | expected CTC unknown |" in text
    assert "Role old" not in text and "Role next" not in text


def test_runs_are_tabled_with_their_company_site_counts(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ledger_module, "_now", lambda: _utc(datetime(2026, 10, 10, 8, 30)))
    ledger = Ledger(settings.db_path)
    run_id = ledger.start_run()
    monkeypatch.setattr(ledger_module, "_now", lambda: _utc(datetime(2026, 10, 10, 9, 40)))
    ledger.finish_run(run_id, {"collected": 120, "attempted": 9, "applied": 5, "applied_external": 1, "external_manual": 2, "errors": 1, "dry_run": False})
    ledger.close()

    text = report.build_report(settings, DAY, NOON)

    assert "| 08:30 | 09:40 | 120 | 9 | 5 | 1 | 2 | 1 | real |" in text


def test_the_report_says_where_the_collected_jobs_went(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ledger_module, "_now", lambda: _utc(datetime(2026, 10, 10, 8, 30)))
    ledger = Ledger(settings.db_path)
    run_id = ledger.start_run()
    ledger.finish_run(run_id, {
        "collected": 370, "too_old": 8, "not_ranked": 212, "below_score": 122,
        "already_applied": 0, "held_back": 0, "eligible": 28, "attempted": 28,
        "applied": 17, "applied_external": 0, "min_score": 55.0, "target": 50,
    })
    ledger.close()

    text = report.build_report(settings, DAY, NOON)

    assert "### Where the collected jobs went" in text
    assert (
        "- 08:30: collected 370; dropped 8 too old, 212 not ranked (LLM_RANK_TOP_N), "
        "122 scored under 55 (MIN_SCORE); 28 eligible, 28 tried, 17 applied" in text
    )


def test_a_run_that_reached_its_target_says_so():
    short = report.funnel_text({"collected": 90, "eligible": 60, "attempted": 55, "applied": 48,
                                "applied_external": 2, "target": 50, "min_score": 45})
    full = report.funnel_text({"collected": 90, "eligible": 60, "attempted": 55, "applied": 50,
                               "applied_external": 2, "target": 50, "min_score": 45})

    assert short == "collected 90; 60 eligible, 55 tried, 50 applied"
    assert full == "collected 90; 60 eligible, 55 tried, 52 applied (stopped at the target of 50)"
    assert report.funnel_text({"collected": 5}) == ""


def test_a_day_without_a_run_says_so_and_creates_no_database(tmp_path):
    settings = _settings(tmp_path)

    text = report.build_report(settings, DAY, NOON)

    assert "Nothing was applied to today." in text
    assert "The Naukri bot did not run today." in text
    assert not os.path.exists(settings.db_path)


def test_what_is_left_comes_from_the_data_folder(tmp_path):
    settings = _settings(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "answers.txt").write_text("Q: Expected CTC\nA:\n\nQ: Notice period\nA: 30 days\n", encoding="utf-8")
    (data / "profile.yaml").write_text("full_name: Jane\ncurrent_ctc_lpa: null\nextra_facts:\n  gender:\n  country: India\n", encoding="utf-8")
    ext.record_company_site(
        settings,
        JobPosting(job_id="j1", url="https://www.naukri.com/job-j1", title="SDE", company="Acme"),
        ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url="https://jobs.lever.co/acme/1", detail="needs you for: Why us", resume="/r/Jane.pdf"),
    )

    text = report.build_report(settings, DAY, NOON)

    assert "- Company-site applications waiting for you: 1" in text
    assert "needs you for: Why us. [Open the site](https://jobs.lever.co/acme/1); resume: `/r/Jane.pdf`" in text
    assert "- Questions waiting for your answer in answers.txt: 1" in text
    assert "- Expected CTC\n" in text and "Notice period" not in text
    assert "- current_ctc_lpa\n- extra_facts.gender\n" in text


def test_profile_slots_say_done_failed_and_later(tmp_path):
    settings = _settings(tmp_path)
    state = {
        "2026-10-10 09:00": {"done": True, "attempts": 1},
        "2026-10-10 13:30": {"done": False, "attempts": 2},
        "resume": {"file": "/x/Jane_Doe_Resume.pdf", "date": "2026-10-10"},
    }
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "profile_update.json").write_text(json.dumps(state), encoding="utf-8")

    text = report.build_report(settings, DAY, NOON)

    assert "- Naukri profile: 09:00: headline refreshed; 13:30: failed after 2 attempt(s); 18:30: later today" in text
    assert "- Resume on the profile: Jane_Doe_Resume.pdf, uploaded 2026-10-10" in text
    assert "18:30: did not run" in report.build_report(settings, DAY, datetime(2026, 10, 11, 8, 0))


def test_only_resumes_made_today_are_listed(tmp_path):
    settings = _settings(tmp_path)
    for folder, stamp in (("Acme - SDE", "2026-10-10T09:04:00"), ("Beta - ML", "2026-10-09T09:04:00")):
        target = tmp_path / "resume" / "out" / "tailored" / folder
        target.mkdir(parents=True)
        (target / "tailoring.json").write_text(
            json.dumps({"company": folder.split(" - ")[0], "title": folder.split(" - ")[1], "generated_at": stamp, "notes": ["skills reordered"]}),
            encoding="utf-8",
        )

    text = report.build_report(settings, DAY, NOON)

    assert "- Acme, SDE: `%s` (skills reordered)" % (tmp_path / "resume" / "out" / "tailored" / "Acme - SDE") in text
    assert "Beta" not in text


def test_linkedin_shows_the_post_or_the_waiting_draft(tmp_path):
    settings = _settings(tmp_path)
    drafts = tmp_path / "linkedin" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "2026-10-10.md").write_text("---\nsource_title: Next.js 16.4\n---\nbody\n", encoding="utf-8")

    text = report.build_report(settings, DAY, NOON)
    assert "- LinkedIn: draft ready, not posted" in text
    assert 'about "Next.js 16.4"' in text

    (tmp_path / "linkedin" / "state.json").write_text(
        json.dumps({"posted": [{"url": "https://nextjs.org/blog/next-16-4", "title": "Next.js 16.4", "date": "2026-10-10"}]}),
        encoding="utf-8",
    )
    text = report.build_report(settings, DAY, NOON)
    assert '- LinkedIn: posted "Next.js 16.4"' in text
    assert "- Posted about [Next.js 16.4](https://nextjs.org/blog/next-16-4)" in text


def test_the_study_plan_runs_dsa_first_one_module_a_day(tmp_path):
    settings = _settings(tmp_path)
    modules = report.course_modules(tmp_path / "course")
    assert [title for title, _ in modules] == [
        "2.1 Arrays, Strings & Hashing",
        "2.2 Two Pointers & Sliding Window",
        "1.1 Fundamentals",
        "1.2 Storage & Databases",
        "5.1 STAR Framework & Story Bank",
    ]

    first = report.learning_for(settings, DAY)
    assert first[0] == "Today: **2.1 Arrays, Strings & Hashing** (day 1 of 5)"
    assert first[2] == (
        'On the site: `python3 "%s"`, then http://localhost:8000/#/02-dsa/01-arrays-strings-hashing'
        % ((tmp_path / "course").resolve() / "serve.py")
    )
    assert first[3] == "Tomorrow: 2.2 Two Pointers & Sliding Window"
    assert report.learning_for(settings, DAY + timedelta(days=3))[0] == "Today: **1.2 Storage & Databases** (day 4 of 5)"
    assert report.learning_for(settings, DAY + timedelta(days=5))[0].startswith("Revise: **2.1 Arrays")


def test_without_a_start_date_the_plan_starts_on_the_first_report_and_keeps_counting(tmp_path):
    settings = _settings(tmp_path, course_start_date="")

    assert report.learning_for(settings, DAY)[0].startswith("Today: **2.1")
    assert json.loads((tmp_path / "reports" / "learning.json").read_text()) == {"start": "2026-10-10"}
    assert report.learning_for(settings, DAY + timedelta(days=1))[0].startswith("Today: **2.2")


def test_a_missing_course_folder_is_named(tmp_path):
    settings = _settings(tmp_path, course_dir=str(tmp_path / "nowhere"))
    assert report.learning_for(settings, DAY) == [
        "The course folder %s was not found; set COURSE_DIR in .env." % (tmp_path / "nowhere")
    ]


def test_the_report_is_written_to_a_folder_per_day(tmp_path):
    settings = _settings(tmp_path)

    path = report.write_daily_report(settings, DAY, NOON)

    assert path == tmp_path / "reports" / "2026-10-10" / "report.md"
    assert path.read_text(encoding="utf-8").startswith("# Daily report:")


def test_a_failing_report_never_fails_the_run(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(report, "write_daily_report", broken)
    assert report.update_quietly(_settings(tmp_path)) is None


def test_a_bad_date_on_the_command_line_is_refused(monkeypatch, tmp_path):
    from common import config

    monkeypatch.setattr(config, "load_settings", lambda env_path=None, overrides=None: _settings(tmp_path))
    assert report.main(["--date", "10/10/2026"]) == 1
    assert not (tmp_path / "reports" / "10").exists()


def test_each_run_keeps_its_log_next_to_the_report(tmp_path):
    import logging

    from common import run

    settings = _settings(tmp_path)
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.INFO)
    try:
        first = run.keep_log(settings, "naukri", now=datetime(2026, 10, 10, 9, 5, 1))
        second = run.keep_log(settings, "naukri", now=datetime(2026, 10, 10, 18, 30, 0))
        logging.getLogger("naukri_bot.cli").info("applied to Acme")
    finally:
        for handler in [h for h in root.handlers if isinstance(h, run._KeptLog)]:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(level)

    assert first == tmp_path / "reports" / "2026-10-10" / "logs" / "naukri-090501.log"
    assert "applied to Acme" not in first.read_text(encoding="utf-8")
    assert "applied to Acme" in second.read_text(encoding="utf-8")
    text = report.build_report(settings, DAY, NOON)
    assert "- [naukri-090501.log](logs/naukri-090501.log)" in text
    assert "- [naukri-183000.log](logs/naukri-183000.log)" in text
