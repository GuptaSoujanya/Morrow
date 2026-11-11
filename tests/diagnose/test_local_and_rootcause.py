import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import Settings
from diagnose import local, report, resume, rootcause

SCHEMA = """
CREATE TABLE applications(id INTEGER PRIMARY KEY, job_id TEXT, url TEXT, title TEXT, company TEXT, status TEXT,
  detail TEXT, quota_consumed INTEGER, questions_answered INTEGER, questions_abstained INTEGER, at TEXT, facts_fingerprint TEXT);
CREATE TABLE jobs_seen(job_id TEXT PRIMARY KEY, url TEXT, title TEXT, company TEXT, source TEXT, first_seen TEXT,
  last_seen TEXT, score REAL, gaps_json TEXT, description TEXT);
CREATE TABLE answers(question_norm TEXT PRIMARY KEY, question_text TEXT, answer TEXT, field_type TEXT, grounded_in TEXT,
  source TEXT, confidence REAL, created_at TEXT, updated_at TEXT, times_used INTEGER, profile_fingerprint TEXT, facts_fingerprint TEXT);
"""


def _ledger(path: Path, rows):
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    for index, (job_id, title, status, at, score, source, gaps) in enumerate(rows):
        connection.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (index + 1, job_id, "https://x/%s" % job_id, title, "Co", status, "", 0, 0, 0, at, ""))
        connection.execute("INSERT OR IGNORE INTO jobs_seen VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (job_id, "https://x/%s" % job_id, title, "Co", source, at, at, score, json.dumps(gaps),
                            "We need Python, Kubernetes and PostgreSQL experience, 4+ years"))
    connection.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("current location", "What is your current location?", "Others", "text", "", "llm", 0.9, "", "", 0, "", ""))
    connection.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("notice", "Notice period", "15", "text", "", "profile", 1.0, "", "", 3, "", ""))
    connection.commit()
    connection.close()


@pytest.fixture
def settings(tmp_path):
    db = tmp_path / "db"
    db.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "profile.yaml").write_text("name: A\nemail: a@x.com\ntotal_experience_years: 2.9\npreferred_locations: [Remote, Pune]\nskills: [Python, Kubernetes]\n")
    (inputs / "employer_replies.jsonl").write_text(json.dumps({"from": "jobs@wellfound.com", "kind": "ACKNOWLEDGEMENT"}) + "\n")
    (inputs / "job_contacts.jsonl").write_text("".join(json.dumps({"email": "r%d@c.com" % i}) + "\n" for i in range(30)))
    (inputs / "cutshort_questionnaires.json").write_text(json.dumps({"abc": {"state": "needs_you"}, "def": {"state": "done"}}))
    (tmp_path / "resume.txt").write_text("Jane Doe\nSoftware Engineer · Python\nBuilt a mock provider prototype.\nCut latency by 40% for 2k users.\n")
    live = db / "naukri_bot.db"
    _ledger(live, [
        ("j1", "Senior Backend Engineer", "applied", "2026-11-05T10:00:00", 41.0, "search", ["4+ years of experience"]),
        ("j2", "Software Engineer", "applied", "2026-11-05T11:00:00", 66.0, "search", []),
        ("j3", "ML Engineer", "applied_platform", "2026-11-06T09:00:00", 38.0, "instahyre:search:x", ["TensorFlow"]),
        ("j4", "Software Engineer", "error", "2026-11-06T09:30:00", 55.0, "search", []),
        ("j5", "Developer", "abstained", "2026-11-06T09:40:00", 52.0, "search", []),
    ])
    _ledger(db / "naukri_bot.before-wipe.db", [
        ("j2", "Software Engineer", "applied", "2026-11-05T11:00:00", 66.0, "search", []),  # duplicate of live
        ("old1", "React Native Developer", "applied_platform", "2026-10-29T10:00:00", 44.0, "hirist:feed", []),
    ])
    return Settings(db_path=str(live), profile_path=str(inputs / "profile.yaml"), data_dir=str(inputs),
                    resume_path=str(tmp_path / "resume.txt"), report_dir=str(tmp_path / "reports"), min_score=55.0,
                    gmail_app_password="")


def test_backups_merge_without_double_counting(settings):
    data = local.analyse(settings)
    assert data["funnel_all"]["submitted_total"] == 4
    assert data["funnel_live"]["submitted_total"] == 3
    assert data["funnel_all"]["submitted_by_channel"] == {"naukri": 2, "instahyre": 1, "hirist": 1}


def test_fit_answers_and_journal_signals(settings):
    data = local.analyse(settings)
    assert data["fit"]["mismatched_titles"] == 2
    assert data["fit"]["below_min_score"] == 3
    assert data["fit"]["top_gaps"][0] == ("4+ years of experience", 1)
    assert data["answers"]["suspicious"][0]["answer"] == "Others"
    assert data["cutshort"]["unfinished"] == 1
    assert data["profile"]["under_three_years"] is True


def test_rootcause_orders_and_names_fixes(settings):
    data = local.analyse(settings)
    cv = resume.analyse(settings, data["applications"], data["profile"])
    mail = {"error": "", "days": 30, "scanned": 500, "folders": {"[Gmail]/All Mail": 500}, "positive_total": 0,
            "positives": [], "positive_by_kind": {}, "by_platform": {"wellfound": {"ACKNOWLEDGEMENT": 3}},
            "spam_hiring": [{"subject": "Interview at Acme", "date": "", "from": ""}], "account": "a@x.com", "llm_used": 0}
    causes = rootcause.rank(data, mail, None, cv, "a@x.com")
    ids = [cause["id"] for cause in causes]
    assert ids.index("bad-answers") < ids.index("title-mismatch")
    assert "spam" in ids and "silence-confirmed" in ids and "naukri-mail-missing" in ids
    answers_fix = next(c for c in causes if c["id"] == "bad-answers")
    assert answers_fix["fix_kind"] == "answers" and "answers.txt" in " ".join(answers_fix["where"])
    assert "mock" in next(c for c in causes if c["id"] == "resume")["evidence"][0] or any(
        "mock" in line for c in causes if c["id"] == "resume" for line in c["evidence"])


def test_report_writes_markdown_and_json(settings):
    data = local.analyse(settings)
    cv = resume.analyse(settings, data["applications"], data["profile"])
    causes = rootcause.rank(data, None, None, cv)
    written = report.write(settings, data, None, None, cv, causes)
    text = written["markdown"].read_text()
    assert "The root cause, in plain words" in text and "What to do, in order" in text
    assert "Every cause with its evidence" in text and "Skipped (--skip-mail)" in text
    payload = json.loads(written["json"].read_text())
    assert "applications" not in payload["local"]
    assert payload["causes"][0]["severity"] in ("critical", "high")


def test_action_plan_groups_fixes_by_who_does_them():
    causes = [
        {"id": "unanswered-messages", "fix_kind": "code", "fix": ["Today: open each board inbox.", "Code: add an inbox stage."]},
        {"id": "low-fit", "fix_kind": "env", "fix": ["MIN_SCORE=65 in .env.", "Code: honour min_score in lanes."]},
        {"id": "silence-confirmed", "fix_kind": "manual", "fix": ["Fix the causes below."]},
        {"id": "contacts-unused", "fix_kind": "manual", "fix": ["Send 5 mails a day."]},
    ]
    plan = report.action_plan(causes)
    assert plan["today"] == ["Today: open each board inbox.", "Send 5 mails a day."]
    assert plan["week"] == ["MIN_SCORE=65 in .env."]
    assert plan["code"] == ["Code: add an inbox stage.", "Code: honour min_score in lanes."]
