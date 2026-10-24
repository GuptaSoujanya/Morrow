"""The control site: the commands it builds, the to-dos it reads and writes, and its server."""
import datetime as dt
import http.client
import json
import os
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from web import server, state
from web.state import Command


def test_naukri_command_passes_only_the_options_you_set():
    assert state.naukri_command().argv[1:] == ("-m", "naukri_bot")
    command = state.naukri_command(dry_run=True, limit=5, answer_mode="propose", keywords=" LLM, RAG ")
    assert command.argv[1:] == (
        "-m", "naukri_bot", "--dry-run", "--limit", "5", "--answer-mode", "propose", "--keywords", "LLM, RAG",
    )
    assert command.label == "Practice run on Naukri"
    assert command.shown.startswith("venv/bin/python -m naukri_bot --dry-run")


def test_early_access_only_wins_over_early_access():
    argv = state.naukri_command(early_access=True, early_access_only=True).argv
    assert "--early-access-only" in argv and "--early-access" not in argv


def test_bad_limit_is_refused():
    with pytest.raises(ValueError):
        state.naukri_command(limit=0)


def test_external_needs_a_link():
    with pytest.raises(ValueError):
        state.external_command(url="")
    with pytest.raises(ValueError):
        state.external_command(url="jobs.example.com")
    argv = state.external_command(url="https://jobs.example.com/1", company="Acme", dry_run=True).argv
    assert argv[1:] == ("-m", "sites_bot.external", "--url", "https://jobs.example.com/1", "--company", "Acme", "--dry-run")


def test_linkedin_post_takes_an_optional_draft():
    assert state.linkedin_command(mode="post").argv[1:] == ("-m", "linkedin_bot", "--post")
    assert state.linkedin_command(mode="post", draft="d.md").argv[-1] == "d.md"
    assert state.linkedin_command(mode="dry-run", draft="d.md").argv[1:] == ("-m", "linkedin_bot", "--dry-run")


def test_report_date_is_checked():
    assert state.report_command().argv[1:] == ("-m", "common.report")
    assert state.report_command(day="2026-01-02").argv[-2:] == ("--date", "2026-01-02")
    with pytest.raises(ValueError):
        state.report_command(day="yesterday")


def test_resume_needs_an_existing_file(tmp_path):
    with pytest.raises(ValueError):
        state.resume_command(jd_file=str(tmp_path / "missing.txt"))
    jd = tmp_path / "jd.txt"
    jd.write_text("Build RAG systems")
    assert state.resume_command(jd_file=str(jd), company="Acme").argv[3:] == ("--tailor", str(jd), "--company", "Acme")


def test_reads_what_is_waiting_for_you(tmp_path):
    answers = tmp_path / "answers.txt"
    answers.write_text("# comment\nQ: Notice period?\nA: 15 days\n\nQ: Country*\nQ: Where do you live?\nA:\nQ: CTC?\nA:   \n")
    assert state.unanswered_questions(answers) == [(7, ["Country*", "Where do you live?"]), (9, ["CTC?"])]

    profile = tmp_path / "profile.yaml"
    profile.write_text('first_name: "Sam"\nctc: 16  # FILL\npan: null  # FILL only if asked\nnote: ""  # FILL\nother:  # FILL\n')
    assert state.blank_facts(profile) == [(3, "pan"), (4, "note"), (5, "other")]
    assert state.first_name(profile) == "Sam"

    sites = tmp_path / "company_sites.md"
    sites.write_text("# Applications\n\n## 2026-10-10 22:05 | Dscout | Applied AI Engineer\n- Status: needs you\n")
    assert state.waiting_company_sites(sites) == ["Dscout · Applied AI Engineer"]


def make_course(root):
    for path in ("README.md", "news.md", "01-sd/README.md", "01-sd/01-basics.md", "02-dsa/01-arrays.md", "02-dsa/02-graphs.md"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"# {path}\n")
    (root / "_sidebar.md").write_text(
        "- [Home](README.md)\n- [News](news.md)\n\n"
        "- **1. System Design**\n  - [Overview](01-sd/README.md)\n  - [1.1 Basics](01-sd/01-basics.md)\n"
        "  - [1.2 Missing](01-sd/02-missing.md)\n\n"
        "- **2. DSA**\n  - [2.1 Arrays](02-dsa/01-arrays.md)\n  - [2.2 Graphs](02-dsa/02-graphs.md)\n"
    )
    return root


def test_course_modules_follow_the_sidebar(tmp_path):
    modules = state.course_modules(make_course(tmp_path))
    assert [(m.track, m.title) for m in modules] == [
        ("Start here", "Home"),
        ("1. System Design", "Overview"),
        ("1. System Design", "1.1 Basics"),
        ("2. DSA", "2.1 Arrays"),
        ("2. DSA", "2.2 Graphs"),
    ]
    assert modules[2].file == (tmp_path / "01-sd/01-basics.md").resolve()


def test_todays_module_matches_the_report_plan(tmp_path, monkeypatch):
    course = make_course(tmp_path)
    modules = state.course_modules(course)
    monkeypatch.setattr(state, "REPORTS", tmp_path / "reports")
    monkeypatch.setenv("COURSE_START_DATE", "2026-01-01")
    first = state.todays_module(modules, dt.date(2026, 1, 1), course)
    assert (first.module.title, first.number, first.total, first.tomorrow.title) == ("2.1 Arrays", 1, 3, "2.2 Graphs")
    later = state.todays_module(modules, dt.date(2026, 1, 3), course)
    assert later.module.title == "1.1 Basics" and not later.revising
    assert state.todays_module(modules, dt.date(2026, 1, 4), course).revising
    assert state.todays_module(modules, dt.date(2025, 12, 31), course) is None


def test_read_marks_are_saved(tmp_path):
    saved = tmp_path / "studied.json"
    assert state.studied(saved) == set()
    state.mark_studied("02-dsa/01-arrays.md", path=saved)
    state.mark_studied("01-sd/01-basics.md", path=saved)
    state.mark_studied("02-dsa/01-arrays.md", done=False, path=saved)
    assert state.studied(saved) == {"01-sd/01-basics.md"}
    saved.write_text("not json")
    assert state.studied(saved) == set()


def test_greeting_follows_the_clock():
    assert state.greeting(dt.datetime(2026, 1, 1, 9)) == "Good morning"
    assert state.greeting(dt.datetime(2026, 1, 1, 20)) == "Good evening"


def test_course_routes_match_the_course_site(tmp_path):
    modules = {m.path: m.route for m in state.course_modules(make_course(tmp_path))}
    assert modules == {
        "README.md": "",
        "01-sd/README.md": "01-sd/",
        "01-sd/01-basics.md": "01-sd/01-basics",
        "02-dsa/01-arrays.md": "02-dsa/01-arrays",
        "02-dsa/02-graphs.md": "02-dsa/02-graphs",
    }


def test_company_sites_keep_each_entrys_details(tmp_path):
    sites = tmp_path / "company_sites.md"
    sites.write_text(
        "# Applications\n\n## 2026-10-10 22:05 | Dscout | Applied AI Engineer\n- Status: needs you\n"
        "- Site: https://jobs.example.com/1\n\n## Old style entry\n- Why: no form\n"
    )
    first, second = state.company_sites(sites)
    assert first["name"] == "Dscout · Applied AI Engineer"
    assert (first["when"], first["status"], first["site"]) == ("2026-10-10 22:05", "needs you", "https://jobs.example.com/1")
    assert (second["name"], second["why"]) == ("Old style entry", "no form")


def test_an_answer_lands_on_its_empty_line(tmp_path):
    answers = tmp_path / "answers.txt"
    answers.write_text("Q: Notice period?\nA: 15 days\n\nQ: Country*\n  A:\nQ: CTC?\nA:\n")
    state.save_answer(5, "  India \n", answers)
    assert answers.read_text() == "Q: Notice period?\nA: 15 days\n\nQ: Country*\n  A: India\nQ: CTC?\nA:\n"
    assert state.unanswered_questions(answers) == [(7, ["CTC?"])]
    for line, answer in ((2, "30 days"), (5, "Japan"), (99, "x"), (7, "   ")):
        with pytest.raises(ValueError):
            state.save_answer(line, answer, answers)


def test_a_fact_is_filled_and_keeps_its_comment(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "ctc: 16  # FILL\nextra:\n  address: null          # FILL: street\n  pin: null  # FILL\n  ok: true  # FILL\n"
    )
    state.save_fact(3, '12 "MG" Road', profile)
    state.save_fact(4, "452001", profile)
    lines = profile.read_text().splitlines()
    assert lines[2] == '  address: "12 \\"MG\\" Road" # FILL: street'
    assert lines[3] == "  pin: 452001 # FILL"
    assert state.blank_facts(profile) == []
    with pytest.raises(ValueError):
        state.save_fact(5, "false", profile)


def test_report_links_point_at_its_saved_files(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "REPORTS", tmp_path)
    day = dt.date(2026, 10, 12)
    (tmp_path / "2026-10-12").mkdir()
    (tmp_path / "2026-10-12" / "report.md").write_text(
        "# Report\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[log](logs/run.log) [job](https://example.com/j) <b>raw</b>\n"
    )
    html = state.report_html(day)
    assert '<a href="/reports/2026-10-12/logs/run.log">log</a>' in html
    assert '<a href="https://example.com/j" target="_blank" rel="noopener">job</a>' in html
    assert "<table>" in html and "<b>" not in html



def at(day, hour):
    """A ledger timestamp (UTC, like the bots write) for a local day and hour."""
    return dt.datetime(2026, 10, day, hour).astimezone().astimezone(dt.timezone.utc).isoformat()


def make_ledger(path):
    from common.ledger import Ledger

    Ledger(str(path)).close()
    connection = sqlite3.connect(path)
    connection.executemany(
        "INSERT INTO applications(job_id, status, quota_consumed, at) VALUES (?, ?, ?, ?)",
        [
            ("111", "applied", 1, at(12, 11)),
            ("hirist:5", "applied_platform", 0, at(12, 12)),
            ("222", "external_manual", 0, at(12, 12)),
            ("333", "abstained", 0, at(12, 12)),
            ("444", "naukri_refused", 0, at(12, 12)),
            ("555", "applied", 1, at(13, 9)),
            ("666", "applied", 1, at(6, 9)),
        ],
    )
    connection.executemany(
        "INSERT INTO jobs_seen(job_id, source, first_seen, score) VALUES (?, ?, ?, ?)",
        [
            ("1", "search:AI Engineer", at(12, 10), 50.0),
            ("2", "hirist:search:AI Engineer", at(12, 10), 30.0),
            ("3", "recommended:similar_jobs", at(13, 8), None),
            ("4", "cutshort:feed", at(13, 8), 95.0),
            ("5", "search:AI Engineer", at(6, 8), 70.0),
            ("6", "search:AI Engineer", at(1, 8), 20.0),
        ],
    )
    naukri = {"collected": 10, "too_old": 2, "ranked": 8, "below_score": 5, "eligible": 3, "attempted": 2,
              "applied": 1, "external_manual": 1, "dry_run": False}
    connection.executemany(
        "INSERT INTO runs(started_at, finished_at, summary_json) VALUES (?, ?, ?)",
        [
            (at(12, 10), at(12, 11), json.dumps(naukri)),
            (at(12, 14), at(12, 15), json.dumps({"board": "hirist", "dry_run": True, "collected": 4, "eligible": 1})),
            (at(13, 8), None, None),
        ],
    )
    connection.commit()
    connection.close()
    return path


def test_source_names_the_board_and_the_search():
    assert state.source_parts("search:AI Engineer") == ("naukri", "AI Engineer")
    assert state.source_parts("hirist:search:LLM: evals") == ("hirist", "LLM: evals")
    assert state.source_parts("recommended:similar_jobs") == ("naukri", "Recommended: similar jobs")
    assert state.source_parts("cutshort:feed") == ("cutshort", "Cutshort feed")


def test_overview_counts_what_the_ledger_holds(tmp_path, monkeypatch):
    for key in ("MIN_SCORE", "DAILY_QUOTA", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(state, "APPLY", tmp_path)
    (tmp_path / ".env").write_text("MIN_SCORE=45\nDAILY_QUOTA=40\n")
    db = make_ledger(tmp_path / "ledger.db")
    now = dt.datetime(2026, 10, 13, 12).astimezone()
    data = state.overview(7, today=dt.date(2026, 10, 13), now=now, db=db)

    assert (data["start"], data["end"], data["first"], data["min_score"]) == ("2026-10-07", "2026-10-13", "2026-10-01", 45)
    days = {d["day"]: d for d in data["daily"]}
    assert len(days) == 7
    assert days["2026-10-12"] == {"day": "2026-10-12", "naukri": 1, "boards": 1, "company": 0, "waiting": 2,
                                  "skipped": 0, "failed": 1}
    assert days["2026-10-13"]["naukri"] == 1
    # The ledger starts on 1 October, inside the 7 days before, so there is nothing fair to compare with.
    assert data["sent"] == {"total": 3, "naukri": 2, "boards": 1, "company": 0, "before": None}
    assert data["quota"] == {"used": 1, "limit": 40}
    assert data["attempts"] == 6
    assert data["outcomes"][0] == {"status": "applied", "label": "Applied on Naukri", "kind": "sent", "count": 2}
    assert {o["status"]: o["kind"] for o in data["outcomes"]}["naukri_refused"] == "failed"

    assert data["found"] == {"total": 4, "over": 2, "unscored": 1, "before": None}
    assert [n for n, b in enumerate(data["scores"]) if b["count"]] == [6, 10, 19]
    assert data["scores"][9] == {"from": 45, "to": 50, "count": 0} and data["scores"][-1]["to"] == 100
    boards = {b["key"]: b for b in data["boards"]}
    assert boards["naukri"] == {"key": "naukri", "name": "Naukri", "sent": 2, "found": 2, "over": 1, "average": 50.0}
    assert boards["hirist"]["sent"] == 1 and boards["cutshort"]["over"] == 1
    assert data["searches"][0] == {"search": "AI Engineer", "boards": ["Hirist", "Naukri"], "found": 2, "over": 1,
                                   "average": 40.0}

    funnel = data["funnel"]["naukri"]
    assert funnel["runs"] == 1 and data["funnel"]["boards"]["runs"] == 0
    assert [s["count"] for s in funnel["steps"]] == [10, 8, 3, 2, 1]
    assert funnel["dropped"] == [{"label": "Too old", "count": 2}, {"label": "Under the minimum score", "count": 5}]
    assert funnel["unsent"] == [{"label": "Left for you on a company site", "count": 1}]
    assert data["funnel"]["all"]["steps"] == funnel["steps"]
    assert data["funnel"]["left_out"] == {"practice": 1, "older": 0, "unfinished": 1}

    runs = data["runs"]
    assert [r["bot"] for r in runs] == ["Naukri", "Hirist", "Naukri"]
    assert runs[0]["finished"] is False and runs[0]["sent"] is None
    assert runs[1]["practice"] is True and runs[2]["seconds"] == 3600 and runs[2]["sent"] == 1

    five = state.overview(5, today=dt.date(2026, 10, 13), now=now, db=db)
    assert five["sent"]["before"] == 1 and five["found"]["before"] == 1
    everything = state.overview(0, today=dt.date(2026, 10, 13), now=now, db=db)
    assert everything["start"] == "2026-10-01" and everything["sent"]["total"] == 4 and everything["sent"]["before"] is None
    assert state.overview(7, db=tmp_path / "missing.db")["sent"]["total"] == 0
    with pytest.raises(ValueError):
        state.overview(-1, db=db)

# --- the server ---------------------------------------------------------------------


@pytest.fixture
def site(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "inputs").mkdir(parents=True)
    monkeypatch.setattr(state, "APPLY", tmp_path)
    monkeypatch.setattr(state, "ANSWERS", data / "inputs" / "answers.txt")
    monkeypatch.setattr(state, "PROFILE", data / "inputs" / "profile.yaml")
    monkeypatch.setattr(state, "COMPANY_SITES", data / "inputs" / "company_sites.md")
    monkeypatch.setattr(state, "REPORTS", data / "reports")
    monkeypatch.setattr(state, "STUDIED", data / "reports" / "studied.json")
    monkeypatch.setattr(state, "COURSE", make_course(tmp_path / "course"))
    monkeypatch.delenv("DB_PATH", raising=False)
    state.ANSWERS.write_text("Q: Country*\nA:\n")
    state.PROFILE.write_text('first_name: "Sam"\npin: null  # FILL\n')
    (tmp_path / ".env").write_text("SECRET=1\n")
    httpd = server.ControlServer(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.runner.shutdown()
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path, body=None, headers=None):
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    conn.request(method, path, json.dumps(body) if body is not None else None, sent)
    reply = conn.getresponse()
    data = reply.read()
    conn.close()
    kind = reply.getheader("Content-Type", "")
    return reply.status, json.loads(data) if kind.startswith("application/json") else data


def test_status_shows_what_waits(site):
    status, data = call(site, "GET", "/api/status")
    assert status == 200
    assert data["name"] == "Sam"
    assert data["questions"] == [{"line": 2, "questions": ["Country*"]}]
    assert data["facts"] == [{"line": 2, "key": "pin"}]
    assert data["study"]["total"] == 5 and data["run"]["running"] is False


def test_answers_and_facts_are_saved_from_the_page(site):
    assert call(site, "POST", "/api/answer", {"line": 2, "answer": "India"})[0] == 200
    assert state.unanswered_questions(state.ANSWERS) == []
    status, data = call(site, "POST", "/api/answer", {"line": 2, "answer": "Japan"})
    assert status == 400 and "changed" in data["error"]
    assert call(site, "POST", "/api/fact", {"line": 2, "value": "452001"})[0] == 200
    assert state.blank_facts(state.PROFILE) == []


def test_files_open_and_save_only_by_name(site):
    status, data = call(site, "GET", "/api/file?name=answers")
    assert status == 200 and data["path"] == "data/inputs/answers.txt" and data["line"] == 2
    assert call(site, "POST", "/api/file", {"name": "env", "text": "SECRET=2\n"})[0] == 200
    assert (state.APPLY / ".env").read_text() == "SECRET=2\n"
    assert call(site, "GET", "/api/file?name=../../etc/passwd")[0] == 400


def test_other_hosts_and_pages_are_refused(site):
    assert call(site, "GET", "/api/status", headers={"Host": "evil.example:80"})[0] == 403
    assert call(site, "POST", "/api/stop", {}, headers={"Origin": "https://evil.example"})[0] == 403
    port = site.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/stop", "{}", {"Host": f"127.0.0.1:{port}", "Content-Type": "text/plain"})
    assert conn.getresponse().status == 403


def test_static_files_never_leave_their_folder(site):
    assert call(site, "GET", "/course/02-dsa/01-arrays.md")[0] == 200
    assert call(site, "GET", "/course/../.env")[0] == 404
    assert call(site, "GET", "/course/%2e%2e/.env")[0] == 404
    assert call(site, "GET", "/reports/../inputs/answers.txt")[0] == 404
    status, page = call(site, "GET", "/")
    assert status == 200 and b"<html" in page


def test_preview_explains_what_is_missing(site):
    status, data = call(site, "POST", "/api/preview", {"action": "naukri", "options": {"dry_run": True, "limit": "3"}})
    assert status == 200 and data["shown"] == "DRY_RUN=true venv/bin/python -m naukri_bot --dry-run --limit 3"
    status, data = call(site, "POST", "/api/preview", {"action": "external", "options": {}})
    assert status == 200 and data["needed"] == "paste the application page link"


def test_overview_reads_the_ledger_for_the_days_asked(site):
    make_ledger(state.database())
    status, data = call(site, "GET", "/api/overview?days=30")
    assert status == 200 and data["days"] == 30 and len(data["daily"]) == 30 and data["first"] == "2026-10-01"
    assert call(site, "GET", "/api/overview")[1]["days"] == 14
    status, data = call(site, "GET", "/api/overview?days=week")
    assert status == 400 and "whole number" in data["error"]
    assert call(site, "GET", "/api/overview?days=-3")[0] == 400


def test_marking_a_module_read(site):
    assert call(site, "POST", "/api/course/read", {"path": "02-dsa/01-arrays.md", "read": True})[0] == 200
    status, data = call(site, "GET", "/api/course")
    assert data["read"] == 1
    assert call(site, "POST", "/api/course/read", {"path": "nope.md"})[0] == 400


def wait_until_idle(httpd, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = call(httpd, "GET", "/api/run?after=0")[1]
        if not data["running"]:
            return data
        time.sleep(0.05)
    raise AssertionError("the command is still running")


def test_a_run_streams_its_output_and_duplicate_action_is_blocked(site, monkeypatch):
    monkeypatch.setitem(server.ACTIONS, "echo", lambda o, save: Command(
        "Echo", (sys.executable, "-c", "import time; print('\\x1b[32mhello\\x1b[0m'); time.sleep(0.5)")))
    status, data = call(site, "POST", "/api/run", {"action": "echo"})
    assert status == 200 and data["label"] == "Echo"
    status, data = call(site, "POST", "/api/run", {"action": "echo"})
    assert status == 409 and "still running" in data["error"]
    data = wait_until_idle(site)
    texts = [line[1] for line in data["lines"]]
    assert "hello" in texts and texts[-1].startswith("✓ Echo: done in")
    assert data["last"]["exit"] == 0 and data["last"]["action"] == "echo"
    assert call(site, "GET", f"/api/run?after={data['next']}")[1]["lines"] == []


def test_stop_interrupts_the_run(site, monkeypatch):
    monkeypatch.setitem(server.ACTIONS, "sleep", lambda o, save: Command(
        "Sleep", (sys.executable, "-c", "import time; time.sleep(30)")))
    call(site, "POST", "/api/run", {"action": "sleep"})
    data = call(site, "POST", "/api/stop", {})[1]
    assert data["ok"] and data["message"].startswith("Stopping")
    data = wait_until_idle(site)
    assert data["last"]["stopped"] and "stopped after" in data["lines"][-1][1]


def test_independent_agents_overlap_and_stop_targets_only_selected_run(site, monkeypatch):
    for action in ("first", "second"):
        monkeypatch.setitem(server.ACTIONS, action, lambda o, save: Command(
            "Test agent", (sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(30)")))
    first = call(site, "POST", "/api/run", {"action": "first"})[1]["id"]
    second = call(site, "POST", "/api/run", {"action": "second"})[1]["id"]
    snapshot = call(site, "GET", "/api/run")[1]
    assert snapshot["active_count"] == 2
    assert {run["id"] for run in snapshot["runs"] if run["running"]} == {first, second}
    assert not call(site, "POST", "/api/stop", {})[1]["ok"]
    assert not call(site, "POST", "/api/stop", {"id": "missing"})[1]["ok"]
    assert call(site, "POST", "/api/stop", {"id": first})[1]["ok"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = call(site, "GET", "/api/run")[1]
        if snapshot["active_count"] == 1:
            break
        time.sleep(0.02)
    assert snapshot["active_count"] == 1 and snapshot["running"]
    by_id = {run["id"]: run for run in snapshot["runs"]}
    assert by_id[first]["status"] == "stopped" and by_id[second]["running"]
    # A repeated stop for an old run must never fall through to the remaining run.
    assert not call(site, "POST", "/api/stop", {"id": first})[1]["ok"]
    assert call(site, "POST", "/api/stop", {"id": second})[1]["ok"]
    snapshot = wait_until_idle(site)
    assert {line[2] for line in snapshot["lines"]} == {first, second}
    assert all(len(line) == 4 for line in snapshot["lines"])


def read_run_event(response):
    """Read one SSE frame without buffering until the long-lived response ends."""
    event = {}
    while True:
        line = response.readline().decode().rstrip("\r\n")
        if not line:
            return event
        key, _, value = line.partition(": ")
        event[key] = json.loads(value) if key == "data" else value


def test_live_events_push_output_and_replay_cursor(site, monkeypatch):
    monkeypatch.setattr(server, "EVENT_HEARTBEAT_S", 0.05)
    monkeypatch.setitem(server.ACTIONS, "stream", lambda o, save: Command(
        "Stream", (sys.executable, "-c", "import time; print('live message', flush=True); time.sleep(0.4)")))
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/event-stream")
    assert response.getheader("Content-Length") is None
    initial = read_run_event(response)
    assert initial["event"] == "run" and initial["data"]["lines"] == []
    run_id = call(site, "POST", "/api/run", {"action": "stream"})[1]["id"]
    received = []
    while True:
        event = read_run_event(response)
        received.extend(event["data"]["lines"])
        if event["data"]["last"]:
            break
    assert any(line[1] == "live message" and line[2] == run_id for line in received)
    assert len({line[0] for line in received}) == len(received)
    assert event["data"]["runs"][0]["status"] == "completed"
    response.close()
    connection.close()
    site.runner.say("after reconnect", run_id)
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=5)
    connection.request("GET", "/api/events", headers={"Last-Event-ID": event["id"]})
    response = connection.getresponse()
    replay = read_run_event(response)
    assert [line[1] for line in replay["data"]["lines"]] == ["after reconnect"]
    response.close()
    connection.close()


def test_event_cursor_resets_after_restart_and_rejects_cross_site(site):
    site.runner.say("retained")
    data = call(site, "GET", "/api/run?after=100&epoch=old-server")[1]
    assert data["reset"] and data["lines"][0][1] == "retained"
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=5)
    connection.request("GET", "/api/events", headers={"Last-Event-ID": "old-server:100"})
    response = connection.getresponse()
    event = read_run_event(response)
    assert event["data"]["reset"] and event["data"]["lines"][0][1] == "retained"
    response.close()
    connection.close()
    assert call(site, "GET", "/api/events", headers={"Origin": "https://evil.example"})[0] == 403
    assert call(site, "GET", "/api/events", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(site, "GET", "/api/events?after=-1")[0] == 400
    assert call(site, "GET", "/api/events", headers={"Last-Event-ID": "invalid"})[0] == 400


def test_stream_closes_when_owner_access_is_revoked(site, monkeypatch):
    monkeypatch.setattr(server, "EVENT_HEARTBEAT_S", 0.02)
    monkeypatch.setattr(server, "EVENT_AUTH_CHECK_S", 0.02)
    class Bridge:
        allowed = True
        def identity(self, handler):
            return {"id": "owner"} if self.allowed else None
        def is_owner(self, handler, user):
            return user is not None
    site.account_bridge = Bridge()
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert read_run_event(response)["event"] == "run"
    site.account_bridge.allowed = False
    assert read_run_event(response)["event"] == "access-revoked"
    assert response.read() == b""
    response.close()
    connection.close()


def test_bounded_log_retention_reports_gap_and_run_limit(monkeypatch, tmp_path):
    from web.runner import Runner
    monkeypatch.setattr(state, "APPLY", tmp_path)
    runner = Runner()
    runner.MAX_LINES = 3
    for number in range(5):
        runner.say(str(number))
    snapshot = runner.snapshot(after=0)
    assert snapshot["truncated"] and snapshot["first"] == 2
    assert [line[0] for line in snapshot["lines"]] == [2, 3, 4]
    runner.MAX_ACTIVE = 1
    command = Command("Limit", (sys.executable, "-c", "import time; time.sleep(30)"))
    try:
        runner.start(command, "first")
        with pytest.raises(RuntimeError, match="already running"):
            runner.start(command, "second")
    finally:
        runner.shutdown()
    with pytest.raises(RuntimeError, match="shutting down"):
        runner.start(command, "third")


def test_resource_conflicts_allow_independent_agents_and_protect_shared_files():
    from web.runner import conflicts, resources_for
    def resources(action, *args):
        return resources_for(Command(action, (sys.executable, *args)), action)
    naukri, linkedin = resources("naukri"), resources("linkedin")
    learn = resources("pipeline", "-m", "pipeline", "continue", "--only", "learn")
    news = resources("pipeline", "-m", "pipeline", "continue", "--only", "brief:tech-news")
    papers = resources("pipeline", "-m", "pipeline", "continue", "--only", "brief:papers")
    brief = resources("pipeline", "-m", "pipeline", "continue", "--only", "brief")
    fresh = resources("pipeline", "-m", "pipeline", "continue", "--only", "learn", "--fresh")
    assert not conflicts(naukri, linkedin)
    assert not conflicts(learn, news) and not conflicts(news, papers)
    assert not conflicts(resources("resume"), news)
    assert conflicts(naukri, resources("boards"))
    assert conflicts(naukri, resources("resume"))
    assert conflicts(resources("cold_email"), resources("resume"))
    assert conflicts(news, brief) and conflicts(learn, learn)
    assert conflicts(fresh, news)
    assert conflicts(resources("install"), news)


def test_parallel_resume_requests_keep_separate_job_descriptions(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(state, "LOGS", tmp_path)
    descriptions = [f"Job description {number}" for number in range(10)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(state.save_job_description, descriptions))
    assert len(set(paths)) == len(descriptions)
    assert [path.read_text().strip() for path in paths] == descriptions
