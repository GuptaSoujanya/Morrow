import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import Settings
from diagnose import local, report, resume, rootcause
from leads import store

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


def test_action_plan_lists_each_lead_to_answer_first():
    causes = [{"id": "unanswered-messages", "fix_kind": "code", "fix": ["Today: open inboxes.", "Code: inbox stage."],
               "evidence": ["[questionnaire] instahyre Shreya: please fill", "The bots never read board inboxes."]}]
    plan = report.action_plan(causes)
    assert plan["today"][0] == "Answer: [questionnaire] instahyre Shreya: please fill"
    assert plan["today"][1] == "Today: open inboxes."


NOW = datetime(2026, 11, 11, 10, 0)


def _journal(settings):
    """A questionnaire waiting since yesterday, a mail answered today, an assessment only the person can take."""
    waiting = store.make_lead("board", "instahyre", "QUESTION", company="GreyOrange", title="Software Engineer II | Python",
                              who="Shreya Rani", text="Please answer three questions", received_at="Nov 10")
    answered = store.make_lead("mail", "employer", "INTERVIEW", company="Acme", who="Priya", subject="Interview at Acme",
                               text="Can we talk on Friday?", received_at="2026-11-10")
    person = store.make_lead("board", "cutshort", "ASSESSMENT", company="Zeta", title="Backend Engineer", who="Ravi",
                             text="Take the coding test", received_at="Nov 11")
    store.record(settings, [waiting, answered], now=datetime(2026, 11, 10, 9, 0))
    store.record(settings, [person], now=datetime(2026, 11, 11, 8, 0))
    store.update(settings, answered["id"], "answered", why="replied from the saved facts", answer="Friday works.",
                 now=datetime(2026, 11, 11, 9, 30))
    store.update(settings, person["id"], "needs_you", why="an assessment to take", now=datetime(2026, 11, 11, 9, 45))


def test_leads_journal_reaches_the_causes_the_plan_and_both_reports(settings):
    _journal(settings)
    data = local.analyse(settings, now=NOW)
    leads = data["leads"]
    assert (leads["total"], leads["waiting"], leads["needs_you"], leads["answered"], leads["day"]) == (3, 1, 1, 1, "2026-11-11")
    assert leads["today"] == {"new": 1, "answered": 1, "needs_you": 1}
    cv = resume.analyse(settings, data["applications"], data["profile"])
    causes = rootcause.rank(data, None, None, cv)
    by_id = {cause["id"]: cause for cause in causes}
    waiting = by_id["leads-waiting"]
    assert (waiting["severity"], waiting["fix_kind"], waiting["confidence"]) == ("critical", "manual", 0.95)
    assert waiting["evidence"][:2] == [
        "2 leads in the journal still unanswered: 1 waiting for the bots, 1 waiting for you; answered so far 1 (1 today)",
        "instahyre question from Shreya Rani: Software Engineer II | Python (received Nov 10, state new)"]
    assert waiting["where"] == ["user/inputs/leads.json", "leads/"]
    assert by_id["leads-need-you"]["evidence"][1] == (
        "cutshort assessment from Ravi: Backend Engineer (received Nov 11); why: an assessment to take")
    assert by_id["leads-answered"]["title"] == "1 recruiter threads were answered today by the leads bot"
    assert by_id["leads-answered"]["evidence"] == ["employer interview from Priya: Interview at Acme (answered at 09:30)"]
    plan = report.action_plan(causes)
    assert plan["today"][:2] == waiting["fix"] and plan["today"][0].startswith("Today: run `python3 -m leads`")
    assert by_id["leads-need-you"]["fix"][0] in plan["today"]
    assert not any(line.startswith("Nothing to do") for line in plan["today"])

    written = report.write(settings, data, None, None, cv, causes)
    text = written["markdown"].read_text()
    section = text.index("## Leads: recruiter threads and what was done")
    assert text.index("## What to do, in order") < section < text.index("## Every cause with its evidence")
    assert "show 3 recruiter threads in the leads journal (1 answered, 2 still open)" in text
    assert ("The journal holds 3 recruiter threads: 1 waiting for the bots, 1 waiting for you and 1 answered, "
            "1 of them today; 1 came in today.") in text
    assert "| received | platform | kind | company / role | from | state | answered | why |" in text
    assert "| Nov 10 | instahyre | question | GreyOrange · Software Engineer II \\| Python | Shreya Rani | new | - | - |" in text
    assert "| 2026-11-10 | employer | interview | Acme · Interview at Acme | Priya | answered | 2026-11-11 09:30 |" in text
    assert "| instahyre | 1 | 1 | 0 | 0 |" in text and "| cutshort | 1 | 0 | 0 | 1 |" in text
    payload = json.loads(written["json"].read_text())
    assert payload["leads"]["total"] == 3 and payload["leads"]["by_state"] == {"needs_you": 1, "answered": 1, "new": 1}
    assert {cause["id"] for cause in payload["causes"]} >= {"leads-waiting", "leads-need-you", "leads-answered"}


def test_a_lead_first_seen_today_is_high_not_critical(settings):
    store.record(settings, [store.make_lead("board", "hirist", "REPLY", company="Acme", who="Asha")], now=NOW)
    data = local.analyse(settings, now=NOW)
    causes = rootcause.rank(data, None, None, resume.analyse(settings, data["applications"], data["profile"]))
    waiting = next(cause for cause in causes if cause["id"] == "leads-waiting")
    assert waiting["severity"] == "high" and waiting["evidence"][1] == "hirist reply from Asha: (no subject) (received 2026-11-11, state new)"


def test_the_leads_section_says_what_it_could_not_read(settings):
    data = local.analyse(settings, now=NOW)
    assert (data["leads"]["total"], data["leads"]["items"]) == (0, [])
    cv = resume.analyse(settings, data["applications"], data["profile"])
    causes = rootcause.rank(data, None, None, cv)
    assert not [cause for cause in causes if cause["id"].startswith("leads-")]
    assert "No lead recorded yet; the inbox:<board> and leads:mail stages fill this." in report.build_markdown(data, None, None, cv, causes)
    older = {key: value for key, value in data.items() if key != "leads"}
    assert "The leads journal was not read for this audit." in report.build_markdown(older, None, None, cv, rootcause.rank(older, None, None, cv))
    assert json.loads(report.write(settings, older, None, None, cv, causes)["json"].read_text())["leads"] == {}
    Path(settings.data_dir, "leads.json").write_text("{not json")
    broken = local.analyse(settings, now=NOW)["leads"]
    assert broken["total"] == 0 and "not valid JSON" in broken["error"]
    assert "The leads journal could not be read: " in report.build_markdown({**data, "leads": broken}, None, None, cv, causes)


def test_mail_the_leads_bot_answered_is_not_asked_for_again(settings):
    _journal(settings)
    data = local.analyse(settings, now=NOW)
    cv = resume.analyse(settings, data["applications"], data["profile"])
    mail = {"error": "", "days": 30, "scanned": 50, "folders": {"INBOX": 50}, "positive_total": 2,
            "positives": [{"platform": "employer", "kind": "INTERVIEW", "from": "Priya <priya@acme.com>",
                           "subject": "Re: Interview at Acme", "date": "2026-11-10"},
                          {"platform": "naukri", "kind": "SHORTLIST", "from": "Naukri <info@naukri.com>",
                           "subject": "You are shortlisted", "date": "2026-11-09"}],
            "positive_by_kind": {"INTERVIEW": 1, "SHORTLIST": 1}, "by_platform": {"naukri": {"SHORTLIST": 1}},
            "spam_hiring": [], "account": "a@x.com", "llm_used": 0}
    causes = rootcause.rank(data, mail, None, cv)
    evidence = next(cause for cause in causes if cause["id"] == "calls-exist")["evidence"]
    assert 'employer interview from Priya <priya@acme.com>: "Re: Interview at Acme" (answered by the leads bot)' in evidence
    assert evidence[-2] == "1 of these threads have since been answered by the leads bot (see Leads)"
    assert evidence[-1].startswith("The reply reader")
    answers = [line for line in report.action_plan(causes)["today"] if line.startswith("Answer: ")]
    assert answers == ['Answer: naukri shortlist from Naukri <info@naukri.com>: "You are shortlisted"']
