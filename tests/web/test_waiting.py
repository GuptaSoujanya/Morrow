"""The "Jobs waiting on you" page: one list from the Naukri ledger, the browser agent's attempts
and company_sites.md, each job with what it still needs and its answer line when there is one."""
import datetime as dt
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from web import waiting


def _utc(**delta):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(**delta)).isoformat()


def _sqlite_stamp(**delta):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def make_ledger(path):
    from common.ledger import Ledger

    Ledger(str(path)).close()
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO applications(job_id, url, title, company, status, detail, quota_consumed, at) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("111", "https://www.naukri.com/job-listings-x-111", "Backend Dev", "Acme", "applied", "", 1, _utc(hours=30)),
            ("111", "https://www.naukri.com/job-listings-x-111", "Backend Dev", "Acme", "abstained",
             "How many years of experience do you have in C++?", 1, _utc(hours=3)),
            ("222", "https://www.naukri.com/job-listings-x-222", "ML Dev", "Beta", "chatbot_timeout",
             "stalled at question='Notice period?' after 90s", 1, _utc(hours=4)),
            ("333", "https://www.naukri.com/job-listings-x-333", "Old", "Gamma", "abstained", "Ancient question?", 1, _utc(days=9)),
            ("444", "https://corp.example.com/apply", "Platform Eng", "Delta", "error",
             "Submit was clicked by the browser agent but its confirmation is not on the page", 0, _utc(hours=5)),
            ("555", "https://www.naukri.com/job-listings-x-555", "Applied", "Eps", "applied", "", 1, _utc(hours=1)),
        ],
    )
    con.executemany(
        "INSERT INTO jobs_seen(job_id, url, title, company, source, first_seen, score, experience) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("111", "https://www.naukri.com/job-listings-x-111", "Backend Dev", "Acme", "search:x", _utc(days=1), 61.0, "5-8 Yrs"),
            ("hirist:77", "https://www.hirist.tech/j/zeta-77", "Senior AI Engineer", "Zeta", "hirist:search", _utc(days=1), 48.5, "2-4 Yrs"),
        ],
    )
    con.commit()
    con.close()
    return path


def make_agent_db(path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE attempts(job_id TEXT PRIMARY KEY, title TEXT, company TEXT, url TEXT, state TEXT,
        next_step TEXT, detail TEXT, report_json TEXT, owner_pid INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    report = {"why": "Captcha appeared after the resume upload.", "steps": [
        {"state": "inspect", "observation": "Form has 6 fields", "action": "Filled name and email"},
        {"state": "fill", "observation": "Captcha", "action": "Stopped"}]}
    con.executemany("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("hirist:77", "Senior AI Engineer", "Zeta", "https://zeta.example.com/careers/77", "needs_you",
         "Solve the captcha and click Submit.",
         "needs you for: Captcha (a check only a person may answer); Mobile Phone (browser agent: stopped at the captcha)",
         json.dumps(report), 0, _sqlite_stamp(hours=2)),
        ("wellfound:9", "Full Stack", "Omega", "javascript:alert(1)", "uncertain",
         "Check the page or Sent before allowing another attempt.", "the browser agent stopped: hCaptcha after Next", "{}", 0, _sqlite_stamp(hours=6)),
        ("cutshort:AbCdEfGh", "Product Eng", "Venxr", "https://cutshort.io/profile/all-jobs?jobid=1", "needs_you",
         "Decide whether the salary works.", "needs you for: This job offers ₹7L - ₹10L. Does this work for you?", "{}", 0, _sqlite_stamp(hours=7)),
        ("yc:1", "Founding Eng", "Rho", "https://rho.example.com", "needs_you", "Record the Loom.",
         "needs you for: Record a Loom (10 min max) walking through code", "{}", 0, _sqlite_stamp(hours=8)),
        ("hn:2", "Eng", "Sigma", "https://sigma.example.com", "running", "Inspect", "", "{}", 1, _sqlite_stamp(days=3)),
        ("hn:3", "Eng", "Tau", "https://tau.example.com", "running", "Inspect", "", "{}", 1, _sqlite_stamp(minutes=5)),
        ("hn:4", "Eng", "Ups", "https://ups.example.com", "confirmed", "Do not send again.", "", "{}", 0, _sqlite_stamp(hours=1)),
    ])
    con.commit()
    con.close()
    return path


SITES = """# Applications on company websites that need you

## 2026-11-11 09:30 | Zeta | Senior AI Engineer
- Status: needs you
- Why: needs you for: Captcha; Mobile Phone
- Site: https://zeta.example.com/careers/77
- Naukri: https://www.hirist.tech/j/zeta-senior-ai-engineer-77
- Resume to send: /tmp/resume.pdf
- Already filled: First Name *, Email *
- Left for you: Captcha; Mobile Phone

## 2026-11-10 18:00 | Kappa | Data Engineer
- Status: needs you
- Why: needs you for: Gender *; Date of Birth
- Site: https://kappa.example.com/jobs/5
- Naukri: https://www.naukri.com/job-listings-data-engineer-kappa-301126500999
- Left for you: Gender *; Date of Birth
"""

ANSWERS = """# 2026-11-11 08:04 | while applying to Backend Dev at Acme | no answer | options: ['0', '1']
Q: How many years of experience do you have in C++?
A:

Q: Notice period?
A: 15 days

# 2026-10-28 18:49 | while applying to AI / ML Engineer at Muks Robotics Ai | file upload
Q: Upload your CV*
A:
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))
    (tmp_path / "answers.txt").write_text(ANSWERS, encoding="utf-8")
    (tmp_path / "company_sites.md").write_text(SITES, encoding="utf-8")
    (tmp_path / "profile.yaml").write_text("total_experience_years: 2.9\npan: null  # FILL only if asked\n", encoding="utf-8")
    return dict(db=make_ledger(tmp_path / "ledger.db"), agent_db=make_agent_db(tmp_path / "agent.sqlite"),
                answers=tmp_path / "answers.txt", sites=tmp_path / "company_sites.md", profile=tmp_path / "profile.yaml")


def test_every_source_is_merged_into_one_list(workspace):
    data = waiting.waiting_json({"days": "0"}, **workspace)
    by_id = {item["job_id"]: item for item in data["items"]}
    # Naukri: an unanswered screener question within 7 days, a timed-out one, an unconfirmed submit; the 9-day-old one is gone.
    assert by_id["111"]["kind"] == "question" and by_id["111"]["question"] == {
        "text": "How many years of experience do you have in C++?", "line": 3, "answered": False}
    assert by_id["111"]["needs"] == ["Answer: How many years of experience do you have in C++?"]
    assert by_id["111"]["score"] == 61.0 and by_id["111"]["odds"] == "asks 5+ years, profile has 2.9"
    assert by_id["222"]["kind"] == "ready" and by_id["222"]["question"]["answered"] is True and by_id["222"]["question"]["line"] is None
    assert by_id["444"]["kind"] == "review" and by_id["444"]["board"] == "external" and by_id["444"]["reviewable"] is False
    assert "333" not in by_id and "555" not in by_id
    # The agent: needs_you forms classified, uncertain outcome reviewable, abandoned run listed, live run and confirmed skipped.
    zeta = by_id["hirist:77"]
    assert zeta["kind"] == "access" and zeta["board"] == "hirist" and zeta["source"] == "agent"
    assert zeta["needs"] == ["Captcha (a check only a person may answer)", "Mobile Phone"]
    assert zeta["why"] == "Captcha appeared after the resume upload." and len(zeta["steps"]) == 2
    assert zeta["odds"] == "senior title (Senior)" and zeta["score"] == 48.5
    assert by_id["wellfound:9"]["kind"] == "review" and by_id["wellfound:9"]["reviewable"] is True and by_id["wellfound:9"]["links"] == {"job": ""}
    assert by_id["cutshort:AbCdEfGh"]["kind"] == "decision" and by_id["yc:1"]["kind"] == "video" and by_id["yc:1"]["board"] == "startups"
    assert by_id["hn:2"]["kind"] == "review" and by_id["hn:2"]["reviewable"] is True
    assert "hn:3" not in by_id and "hn:4" not in by_id
    # company_sites.md: the Zeta entry merged into the agent's record, Kappa stands alone under its Naukri id.
    assert zeta["links"] == {"job": "https://zeta.example.com/careers/77", "site": "https://zeta.example.com/careers/77",
                             "naukri": "https://www.hirist.tech/j/zeta-senior-ai-engineer-77", "resume": "/tmp/resume.pdf"}
    assert zeta["already_filled"] == ["First Name *", "Email *"]
    kappa = by_id["301126500999"]
    assert kappa["source"] == "sites" and kappa["board"] == "naukri" and kappa["needs"] == ["Gender *", "Date of Birth"]
    assert data["total"] == len(data["items"]) == 9
    assert data["items"] == sorted(data["items"], key=lambda item: item["when"], reverse=True)
    assert {k["key"]: k["count"] for k in data["kinds"]} == {
        "question": 1, "review": 3, "access": 1, "video": 1, "decision": 1, "form": 1, "ready": 1}
    # The sheet's blank answers: the C++ one is linked to a job, the CV upload is not.
    assert data["questions"] == [
        {"line": 3, "questions": ["How many years of experience do you have in C++?"], "title": "Backend Dev", "company": "Acme",
         "asked": "2026-11-11 08:04", "linked": True},
        {"line": 10, "questions": ["Upload your CV*"], "title": "AI / ML Engineer", "company": "Muks Robotics Ai",
         "asked": "2026-10-28 18:49", "linked": False}]
    assert data["facts"] == [{"line": 2, "key": "pan"}]


def test_filters_and_pages_apply_after_the_tallies(workspace):
    data = waiting.waiting_json({"days": "0", "kind": "review", "size": "2"}, **workspace)
    assert data["total"] == 9 and data["matched"] == 3 and data["pages"] == 2 and len(data["items"]) == 2
    assert all(item["kind"] == "review" for item in data["items"])
    assert {k["key"] for k in data["kinds"]} >= {"question", "form"}
    searched = waiting.waiting_json({"days": "0", "q": "loom"}, **workspace)
    assert [item["job_id"] for item in searched["items"]] == ["yc:1"]
    board = waiting.waiting_json({"days": "0", "board": "naukri"}, **workspace)
    assert {item["job_id"] for item in board["items"]} == {"111", "222", "301126500999"}
    recent = waiting.waiting_json({"days": "1"}, **workspace)
    assert "301126500999" not in {item["job_id"] for item in recent["items"]} or dt.date.today().isoformat() == "2026-11-10"
    with pytest.raises(ValueError):
        waiting.waiting_json({"days": "soon"}, **workspace)
    with pytest.raises(ValueError):
        waiting.waiting_json({"size": "0"}, **workspace)


def test_missing_files_give_an_empty_page(tmp_path):
    data = waiting.waiting_json({}, db=tmp_path / "none.db", agent_db=tmp_path / "none.sqlite", answers=tmp_path / "a.txt",
                                sites=tmp_path / "s.md", profile=tmp_path / "p.yaml")
    assert data["total"] == 0 and data["items"] == [] and data["kinds"] == [] and data["questions"] == []


@pytest.mark.parametrize("url, job_id", [
    ("https://www.naukri.com/job-listings-foo-271026501739", "271026501739"),
    ("https://www.hirist.tech/j/ixigo-senior-sde-1680801", "hirist:1680801"),
    ("https://www.hirist.tech/job/1682958/screening?", "hirist:1682958"),
    ("https://www.instahyre.com/job-403079-full-stack/", "instahyre:403079"),
    ("https://wellfound.com/jobs/4875173-ai-engineer", "wellfound:4875173"),
    ("https://cutshort.io/job/Applied-AI-Engineer-Transcurators-kU90thCu", "cutshort:kU90thCu"),
    ("https://news.ycombinator.com/item?id=50341833", "hn:50341833"),
    ("https://cloudesign.keka.com/careers/jobdetails/145615", ""),
    ("", ""),
])
def test_listing_links_name_the_ledgers_job(url, job_id):
    assert waiting.listing_job_id(url) == job_id


def test_needs_are_split_outside_brackets():
    assert waiting._split("A (options 1-3; 3-5); B; C") == ["A (options 1-3; 3-5)", "B", "C"]
    assert waiting._needs_from_detail("needs you for: Phone*; captcha (a check) (browser agent: it stopped; really)") == ["Phone*", "captcha (a check)"]
    assert waiting._needs_from_detail("the browser agent stopped (needs_you): hCaptcha after Next") == ["hCaptcha after Next"]
