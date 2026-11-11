import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from diagnose import autofix  # noqa: E402
from diagnose.trail import Trail  # noqa: E402

CAUSES = [
    {"id": "low-fit", "fix_kind": "env", "fix": ["MIN_SCORE=65 in .env (local_setup VOLUME_DEFAULTS still says 40).",
                                                 "Code: make hirist_bot drop candidates under settings.min_score."], "where": ["hirist_bot/"]},
    {"id": "title-mismatch", "fix_kind": "env", "fix": ["EXCLUDE_TITLES=Senior,Sr,Lead,Data Scientist,III", "Code: apply ranking.excluded_title() in every board lane."]},
    {"id": "experience-filter", "fix_kind": "profile", "fix": ["Apply only where the minimum is 2 years (MAX_YEARS_OVER=0).", "State experience as years and months everywhere."]},
    {"id": "volume", "fix_kind": "env", "fix": ["TARGET_APPLICATIONS=20, DAILY_QUOTA=25, MAX_CANDIDATES=300.", "Code: turn on resume tailoring per application (common/resume.py)."]},
    {"id": "calls-exist", "fix_kind": "code", "where": ["sites_bot/replies.py"],
     "fix": ["Today: answer every item above.", "sites_bot/replies.py: stop dropping mail from board domains in link().", "Read Spam and All Mail too; the reader only scans INBOX."]},
    {"id": "spam", "fix_kind": "manual", "fix": ["Mark each as 'Not spam'."]},
]


def test_proposed_settings_reads_values_and_stops_at_the_next_sentence():
    found = autofix.proposed_settings(CAUSES)
    assert found["MIN_SCORE"] == {"value": "65", "cause": "low-fit"}
    assert found["EXCLUDE_TITLES"]["value"] == "Senior,Sr,Lead,Data Scientist,III"
    assert found["MAX_YEARS_OVER"]["value"] == "0" and found["DAILY_QUOTA"]["value"] == "25"
    assert found["TARGET_APPLICATIONS"]["value"] == "20" and found["MAX_CANDIDATES"]["value"] == "300"


def test_proposed_settings_keeps_the_stricter_of_two_proposals_and_rejects_nonsense():
    causes = [{"id": "a", "fix_kind": "env", "fix": ["MIN_SCORE=55"]}, {"id": "b", "fix_kind": "env", "fix": ["MIN_SCORE=70", "DAILY_QUOTA=0"]},
              {"id": "c", "fix_kind": "env", "fix": ["EXCLUDE_TITLES=Senior"]}, {"id": "d", "fix_kind": "env", "fix": ["EXCLUDE_TITLES=Lead,Senior"]}]
    found = autofix.proposed_settings(causes)
    assert found["MIN_SCORE"]["value"] == "70" and "DAILY_QUOTA" not in found
    assert found["EXCLUDE_TITLES"]["value"] == "Senior,Lead"


def test_fix_settings_rewrites_only_weaker_values_and_keeps_a_backup(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DRY_RUN=false\nMIN_SCORE=30\n# Empty on purpose: apply to every title\nEXCLUDE_TITLES=\nDAILY_QUOTA=20\nMAX_YEARS_OVER=5\nMIN_SCORE=31\n")
    trail = Trail()
    result = autofix.fix_settings(env, CAUSES, "2026-11-11", trail, False, tmp_path / "work")
    assert set(result["changes"]) == {"MIN_SCORE", "EXCLUDE_TITLES", "MAX_YEARS_OVER", "TARGET_APPLICATIONS", "MAX_CANDIDATES"}
    assert [s["key"] for s in result["skipped"]] == ["DAILY_QUOTA"]
    assert result["overrode_notes"] == ["EXCLUDE_TITLES"]
    text = env.read_text()
    assert "MIN_SCORE=65\n" in text and text.count("MIN_SCORE=") == 1 and "was '31'" in text
    assert "EXCLUDE_TITLES=Senior,Sr,Lead,Data Scientist,III\n" in text and "DAILY_QUOTA=20\n" in text
    assert "MAX_YEARS_OVER=0\n" in text and "TARGET_APPLICATIONS=20" in text and "DRY_RUN=false" in text
    assert autofix.current_env(env)["MIN_SCORE"] == "65"
    assert list((tmp_path / "work").glob("env.before-*")) and trail.steps[-1].ok and trail.steps[-1].numbers["changed"] == 5
    again = autofix.fix_settings(env, CAUSES, "2026-11-11", Trail(), False, tmp_path / "work")
    assert again["changes"] == {} and not again["written"]


def test_fix_settings_dry_run_changes_nothing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MIN_SCORE=30\n")
    result = autofix.fix_settings(env, CAUSES, "2026-11-11", Trail(), True, tmp_path / "work")
    assert "MIN_SCORE" in result["changes"] and not result["written"] and env.read_text() == "MIN_SCORE=30\n"


def test_fix_answers_rewrites_bad_locations_from_the_profile(tmp_path, monkeypatch):
    db = tmp_path / "bot.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE answers(question_norm TEXT PRIMARY KEY, question_text TEXT, answer TEXT)")
    connection.executemany("INSERT INTO answers VALUES (?, ?, ?)", [
        ("what is your current location", "What is your current location?", "Others"),
        ("preferred location", "Preferred Location *", "Remote"),
        ("notice period", "Notice period", "15")])
    connection.commit()
    connection.close()
    answers = tmp_path / "answers.txt"
    answers.write_text("Q: What is your current location?\nA: Others\n\nQ: Preferred work location\nA: Remote\n\nQ: Current CTC\nA: 16\n")
    settings = SimpleNamespace(db_path=str(db), data_dir=str(tmp_path))
    profile = SimpleNamespace(current_location="Gurugram", preferred_locations=["Pune", "Remote", "Delhi NCR", "Gurugram"])
    monkeypatch.setattr("common.profile.load_profile", lambda s: profile)
    trail = Trail()
    result = autofix.fix_answers(settings, trail, False)
    assert result["deleted"] == ["What is your current location?", "Preferred Location *"]
    assert result["rewritten"] == [{"question": "What is your current location?", "old": "Others", "new": "Gurugram"},
                                   {"question": "Preferred work location", "old": "Remote", "new": "Gurugram, Pune, Delhi NCR"}]
    assert answers.read_text() == "Q: What is your current location?\nA: Gurugram\n\nQ: Preferred work location\nA: Gurugram, Pune, Delhi NCR\n\nQ: Current CTC\nA: 16\n"
    rows = sqlite3.connect(db).execute("SELECT question_text FROM answers").fetchall()
    assert rows == [("Notice period",)]
    assert trail.steps[-1].ok and trail.steps[-1].numbers == {"deleted": 2, "rewritten": 2}
    assert autofix.fix_answers(settings, Trail(), False) == {"deleted": [], "rewritten": [], "written": False}


def test_fix_answers_refuses_without_a_city(tmp_path, monkeypatch):
    answers = tmp_path / "answers.txt"
    answers.write_text("Q: Current city\nA: Others\n")
    settings = SimpleNamespace(db_path=str(tmp_path / "none.db"), data_dir=str(tmp_path))
    monkeypatch.setattr("common.profile.load_profile", lambda s: SimpleNamespace(current_location="", preferred_locations=["Remote"]))
    trail = Trail()
    result = autofix.fix_answers(settings, trail, False)
    assert result["error"] and not trail.steps[-1].ok and answers.read_text() == "Q: Current city\nA: Others\n"


def test_code_tasks_keeps_code_lines_only_and_dedupes():
    tasks = autofix.code_tasks(CAUSES, {"code": ["Code: make hirist_bot drop candidates under settings.min_score.", "Wellfound: record the 15-minute AI interview once."]})
    texts = [t["task"] for t in tasks]
    assert texts[0] == "sites_bot/replies.py: stop dropping mail from board domains in link()."
    assert "Read Spam and All Mail too; the reader only scans INBOX." not in texts  # names no file: a person's note
    assert "make hirist_bot drop candidates under settings.min_score." in texts and texts.count("make hirist_bot drop candidates under settings.min_score.") == 1
    assert "Wellfound: record the 15-minute AI interview once." in texts
    assert all("Today" not in t for t in texts) and tasks[0]["cause"] == "calls-exist" and tasks[0]["where"] == "sites_bot/replies.py"


def test_cli_order_follows_the_request_then_the_environment_then_the_default(monkeypatch):
    installed = {"opencode": None, "claude": "/bin/claude", "kiro-cli": "/bin/kiro-cli"}
    which = installed.get
    monkeypatch.delenv("AUTOFIX_CLI", raising=False)
    assert autofix.cli_order("auto", which) == ["claude", "kiro"]
    assert autofix.cli_order("kiro,claude", which) == ["kiro", "claude"]
    assert autofix.cli_order("opencode", which) == []
    monkeypatch.setenv("AUTOFIX_CLI", "kiro")
    assert autofix.cli_order(None, which) == ["kiro"]
    assert autofix.command_for("claude", "do it", Path("/r"))[:3] == ["claude", "-p", "do it"]
    assert autofix.command_for("opencode", "do it", Path("/r"))[-1] == "do it" and "--auto" in autofix.command_for("opencode", "x", Path("/r"))
    assert autofix.command_for("kiro", "do it", Path("/r"))[0] == "kiro-cli"
    with pytest.raises(ValueError):
        autofix.command_for("codex", "x", Path("/r"))


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "common").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "common" / "answers.py").write_text("def f():\n    return 1\n")
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    (repo / ".env").write_text("MIN_SCORE=30\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
           "HOME": str(tmp_path)}
    for args in (["init", "-q"], ["add", "common", "tests"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True)
    return repo


def test_fix_code_keeps_edits_that_pass_and_falls_through_failed_clis(tmp_path):
    repo = _repo(tmp_path)
    calls = []

    def cli_runner(command, cwd, timeout):
        calls.append(command[0])
        if command[0] == "opencode":
            return 1, "", "Cannot connect to API"
        (repo / "common" / "answers.py").write_text("def f():\n    return 2\n")
        (repo / "tests" / "test_b.py").write_text("def test_b():\n    assert True\n")
        return 0, "Changed common/answers.py (task 1)\n", ""

    tests_seen = []

    def test_runner(command, cwd, timeout):
        tests_seen.append(1)
        return 0, "2 passed\n"

    trail = Trail()
    result = autofix.fix_code(repo, "2026-11-11", CAUSES, {"code": []}, trail, clis=["opencode", "claude"], timeout_s=5, dry_run=False,
                              folder=tmp_path / "work", cli_runner=cli_runner, test_runner=test_runner)
    assert calls == ["opencode", "claude"] and result["used"] == "claude" and result["kept"]
    assert result["files"] == ["common/answers.py", "tests/test_b.py"] and len(tests_seen) == 2
    assert result["attempts"][0]["error"].startswith("opencode exited 1") and result["attempts"][1]["error"] == ""
    assert (repo / "common" / "answers.py").read_text().endswith("return 2\n")
    patch = Path(result["patch"]).read_text()
    assert "return 2" in patch and "new file: tests/test_b.py" in patch
    assert trail.steps[-1].ok and trail.steps[-1].numbers["cli"] == "claude" and (tmp_path / "work" / "prompt.txt").is_file()
    prompt = (tmp_path / "work" / "prompt.txt").read_text()
    assert "1. sites_bot/replies.py: stop dropping mail" in prompt and "Never touch .env" in prompt


def test_fix_code_reverts_when_tests_get_worse_or_a_forbidden_file_is_touched(tmp_path):
    repo = _repo(tmp_path)

    def bad_cli(command, cwd, timeout):
        (repo / "common" / "answers.py").write_text("broken(\n")
        (repo / "common" / "new_helper.py").write_text("x = 1\n")
        return 0, "done", ""

    outcomes = iter([(0, "1 passed\n"), (1, "FAILED tests/test_a.py::test_a - SyntaxError\n1 failed\n")])
    trail = Trail()
    result = autofix.fix_code(repo, "2026-11-11", CAUSES, {}, trail, clis=["claude"], timeout_s=5, dry_run=False,
                              folder=tmp_path / "work", cli_runner=bad_cli, test_runner=lambda c, w, t: next(outcomes))
    assert not result["kept"] and not trail.steps[-1].ok and "new failing tests: tests/test_a.py::test_a" in trail.steps[-1].check
    assert (repo / "common" / "answers.py").read_text() == "def f():\n    return 1\n"
    assert not (repo / "common" / "new_helper.py").exists() and (tmp_path / "work" / "rejected" / "common" / "new_helper.py").is_file()

    def env_cli(command, cwd, timeout):
        (repo / ".env").write_text("MIN_SCORE=0\n")
        (repo / "tests" / "test_a.py").unlink()
        return 0, "done", ""

    trail = Trail()
    result = autofix.fix_code(repo, "2026-11-11", CAUSES, {}, trail, clis=["claude"], timeout_s=5, dry_run=False,
                              folder=tmp_path / "work2", cli_runner=env_cli, test_runner=lambda c, w, t: (0, "ok"))
    assert not trail.steps[-1].ok and "deleted tests: tests/test_a.py" in trail.steps[-1].check
    assert "touched forbidden paths: .env" in trail.steps[-1].check
    assert (repo / "tests" / "test_a.py").is_file() and result["env_restored"]
    assert (repo / ".env").read_text() == "MIN_SCORE=30\n"


def test_fix_code_without_a_cli_or_baseline_changes_nothing(tmp_path):
    repo = _repo(tmp_path)
    trail = Trail()
    result = autofix.fix_code(repo, "2026-11-11", CAUSES, {}, trail, clis=[], timeout_s=5, dry_run=False, folder=tmp_path / "w")
    assert not trail.steps[-1].ok and "no coding CLI" in trail.steps[-1].verify and result["attempts"] == []
    trail = Trail()
    autofix.fix_code(repo, "2026-11-11", CAUSES, {}, trail, clis=["claude"], timeout_s=5, dry_run=False, folder=tmp_path / "w",
                     cli_runner=lambda *a: (0, "x", ""), test_runner=lambda c, w, t: (2, "pytest: error"))
    assert not trail.steps[-1].ok and "test baseline" in trail.steps[-1].check
    trail = Trail()
    result = autofix.fix_code(repo, "2026-11-11", CAUSES, {}, trail, clis=["claude"], timeout_s=5, dry_run=True, folder=tmp_path / "w",
                              cli_runner=lambda *a: (0, "x", ""), test_runner=lambda c, w, t: (0, "ok"))
    assert trail.steps[-1].ok and "dry run" in trail.steps[-1].execute and "prompt" in result


def test_run_cli_records_timeouts_and_missing_binaries(tmp_path):
    def slow(command, cwd, timeout):
        raise OSError("no such file")
    run = autofix.run_cli("claude", "p", tmp_path, 1, tmp_path / "log.txt", runner=slow)
    assert "could not be started" in run.error
    run = autofix.run_cli("kiro", "p", tmp_path, 1, tmp_path / "log.txt", runner=lambda c, w, t: ("timeout", "", ""))
    assert "ran past 1 seconds" in run.error and (tmp_path / "log.txt").read_text().startswith("$ kiro-cli chat")
    run = autofix.run_cli("claude", "p", tmp_path, 1, tmp_path / "log.txt", runner=lambda c, w, t: (0, "\x1b[32mPONG\x1b[0m", ""))
    assert run.error == "" and run.output == "PONG"


def test_run_writes_the_report_from_the_latest_audit(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    folder = reports / "2026-11-11"
    folder.mkdir(parents=True)
    (folder / "diagnostics.json").write_text(json.dumps({"generated_at": "2026-11-11T13:00", "causes": CAUSES, "plan": {"code": []}}))
    env = tmp_path / ".env"
    env.write_text("MIN_SCORE=30\n")
    settings = SimpleNamespace(report_dir=str(reports), db_path=str(tmp_path / "none.db"), data_dir=str(tmp_path), autofix=True)
    monkeypatch.setattr("common.profile.load_profile", lambda s: SimpleNamespace(current_location="Gurugram", preferred_locations=["Pune"]))
    payload = autofix.run(settings, day=None, clis=[], timeout_s=5, dry_run=False, env_path=env, repo=tmp_path, do_code=False)
    assert payload["day"] == "2026-11-11" and payload["settings"]["changes"]["MIN_SCORE"]["value"] == "65"
    assert payload["code"] == {"skipped_by_flag": True} and payload["failed_steps"] == []
    text = (folder / "autofix.md").read_text()
    assert "# Fixes from the audit — 2026-11-11" in text and "| MIN_SCORE | 30 | 65 | low-fit |" in text and "## How each step was checked" in text
    data = json.loads((folder / "autofix.json").read_text())
    assert data["trail"][0]["name"] == "Read the audit" and data["trail"][0]["numbers"]["causes"] == len(CAUSES)
    with pytest.raises(FileNotFoundError):
        autofix.run(SimpleNamespace(report_dir=str(tmp_path / "empty"), db_path="", data_dir=""), day=None, clis=[], timeout_s=1, dry_run=True)


def test_main_turns_autofix_false_into_a_dry_run(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    (reports / "2026-11-11").mkdir(parents=True)
    (reports / "2026-11-11" / "diagnostics.json").write_text(json.dumps({"causes": CAUSES, "plan": {}}))
    env = tmp_path / ".env"
    env.write_text("MIN_SCORE=30\nAUTOFIX=false\n")
    monkeypatch.setattr(autofix.config, "load_settings", lambda path: SimpleNamespace(
        report_dir=str(reports), db_path=str(tmp_path / "none.db"), data_dir=str(tmp_path), autofix=False))
    monkeypatch.setattr("common.profile.load_profile", lambda s: SimpleNamespace(current_location="Gurugram", preferred_locations=[]))
    assert autofix.main(["--env", str(env), "--no-code"]) == 0
    assert env.read_text() == "MIN_SCORE=30\nAUTOFIX=false\n"
    assert json.loads((reports / "2026-11-11" / "autofix.json").read_text())["dry_run"] is True
    assert autofix.main(["--env", str(env), "--day", "bad"]) == autofix.EXIT_CONFIG
