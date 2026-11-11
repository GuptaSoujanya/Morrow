import json

from common.models import Profile, Settings
from leads import boards, store


def _settings(tmp_path, **over):
    values = dict(data_dir=str(tmp_path / "inputs"), report_dir=str(tmp_path / "reports"), browser_agent=True,
                  browser_agent_limit=5, leads_limit=10)
    values.update(over)
    return Settings(**values)


READ = {"state": "read", "message": "", "pages": [], "evidence": [],
        "summary": {"messages": [
            {"date": "Nov 02", "who": "Shreya Rani", "about": "Software Engineer II at GreyOrange",
             "text": "Please fill the questionnaire for the role", "action": "questionnaire", "rejection": False},
            {"date": "Oct 20", "who": "Atul", "about": "Backend Engineer at Foo",
             "text": "not fulfilling the eligibility criteria", "action": "", "rejection": True},
        ]}}


def test_state_for_covers_every_report_shape():
    assert boards.state_for(None, False, "claude is not installed") == ("failed", "claude is not installed")
    assert boards.state_for({"status": "done", "why": "Sent it", "action": "replied"}, True) == ("answered", "Sent it")
    assert boards.state_for({"status": "done", "action": "replied"}, False)[0] == "failed"
    assert boards.state_for({"status": "done", "action": "nothing", "why": "Already answered"}, False) == (
        "skipped", "Already answered")
    assert boards.state_for({"status": "needs_you", "blocker": "human_check"}, False)[0] == "deferred"
    state, why = boards.state_for({"status": "needs_you", "why": "Asked for CTC", "missing": ["current CTC"]}, False)
    assert state == "needs_you" and "current CTC" in why
    assert boards.state_for({"status": "failed", "why": "Page broke"}, False) == ("failed", "Page broke")


def test_instruction_names_the_thread_and_forbids_applying():
    lead = {"kind": "QUESTION", "who": "Shreya Rani", "company": "GreyOrange", "title": "Software Engineer II",
            "text": "Please fill the questionnaire"}
    text = boards.instruction("instahyre", lead)
    assert "Shreya Rani" in text and "Software Engineer II at GreyOrange" in text
    assert "questionnaire" in text.lower() and "Never apply to a job" in text
    assert "Do not start or take it" in boards.instruction("hirist", dict(lead, kind="ASSESSMENT"))


def test_mirror_cutshort_turns_questionnaire_results_into_leads(tmp_path):
    settings = _settings(tmp_path)
    results = [{"thread": "abc", "state": "done"}, {"thread": "def", "state": "retry_later"},
               {"thread": "ghi", "state": "needs_you"}, {"thread": "", "state": "done"}]

    assert boards._mirror_cutshort(settings, results, "f1") == 3

    by_url = {lead["url"].rsplit("/", 1)[-1]: lead for lead in store.load(settings).values()}
    assert by_url["abc"]["state"] == "answered" and by_url["abc"]["platform"] == "cutshort"
    assert by_url["def"]["state"] == "deferred" and by_url["def"]["retry_after"]
    assert by_url["ghi"]["state"] == "needs_you" and by_url["ghi"]["facts"] == "f1"


def _wire(monkeypatch, read=READ, answer=("answered", "Answered on the board.", {"written": "Done"})):
    from common import answers
    from sites_bot import browser_agent

    monkeypatch.setattr(boards, "read_inbox", lambda driver, site, settings, folder: dict(read))
    monkeypatch.setattr(answers, "facts_fingerprint", lambda profile, settings: "f1")
    monkeypatch.setattr(browser_agent, "reserve_task", lambda settings: True)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "the facts")
    calls = []
    monkeypatch.setattr(boards, "answer_lead", lambda driver, settings, profile, site, lead, facts:
                        calls.append(lead["id"]) or answer)
    return calls


def test_process_board_records_the_threads_and_answers_each_once(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls = _wire(monkeypatch)

    counts = boards.process_board(object(), "instahyre", settings, Profile(), 10, False)

    assert counts["state"] == "read" and counts["found"] == 1 and counts["new"] == 1 and counts["answered"] == 1
    lead = next(iter(store.load(settings).values()))
    assert lead["company"] == "GreyOrange" and lead["kind"] == "QUESTION" and lead["who"] == "Shreya Rani"
    assert lead["state"] == "answered" and lead["answer"] == "Done" and lead["facts"] == "f1"
    assert len(calls) == 1

    counts = boards.process_board(object(), "instahyre", settings, Profile(), 10, False)
    assert counts["new"] == 0 and counts["answered"] == 0 and len(calls) == 1


def test_process_board_defers_when_the_agent_needs_you_and_retries_only_on_new_facts(tmp_path, monkeypatch):
    from common import answers

    settings = _settings(tmp_path)
    calls = _wire(monkeypatch, answer=("needs_you", "Asked for CTC", {}))
    boards.process_board(object(), "instahyre", settings, Profile(), 10, False)
    boards.process_board(object(), "instahyre", settings, Profile(), 10, False)
    assert len(calls) == 1
    monkeypatch.setattr(answers, "facts_fingerprint", lambda profile, settings: "f2")
    boards.process_board(object(), "instahyre", settings, Profile(), 10, False)
    assert len(calls) == 2


def test_process_board_dry_run_and_signed_out_write_nothing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls = _wire(monkeypatch)
    counts = boards.process_board(object(), "hirist", settings, Profile(), 10, True)
    assert counts["found"] == 1 and calls == [] and not store.path(settings).exists()

    _wire(monkeypatch, read={"state": "needs_sign_in", "message": "Signed out", "summary": {"messages": []}})
    counts = boards.process_board(object(), "hirist", settings, Profile(), 10, False)
    assert counts["state"] == "needs_sign_in" and not store.path(settings).exists()


def test_process_board_without_the_agent_records_for_you(tmp_path, monkeypatch):
    settings = _settings(tmp_path, browser_agent=False)
    calls = _wire(monkeypatch)
    counts = boards.process_board(object(), "hirist", settings, Profile(), 10, False)
    assert counts["new"] == 1 and counts["answered"] == 0 and calls == []
    assert next(iter(store.load(settings).values()))["state"] == "new"


def test_process_board_stops_and_flags_quota_when_no_task_is_left(tmp_path, monkeypatch):
    from common import llm
    from sites_bot import browser_agent

    settings = _settings(tmp_path)
    calls = _wire(monkeypatch)
    monkeypatch.setattr(browser_agent, "reserve_task", lambda settings: False)
    monkeypatch.setattr(llm, "out_of_quota", lambda: "limit reached")

    counts = boards.process_board(object(), "wellfound", settings, Profile(), 10, False)

    assert counts["quota"] is True and calls == []
    lead = next(iter(store.load(settings).values()))
    assert lead["state"] == "deferred" and lead["retry_after"]


def test_answer_lead_verifies_the_confirmation_and_keeps_a_report(tmp_path, monkeypatch):
    from sites_bot import browser_agent

    settings = _settings(tmp_path)
    workdir = tmp_path / "work"
    monkeypatch.setattr(boards, "safe_get", lambda driver, url: True, raising=False)
    monkeypatch.setattr("common.browser.safe_get", lambda driver, url: True)
    monkeypatch.setattr(boards.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "task_prompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: workdir)
    report = {"status": "done", "action": "replied", "confirmation": "Thanks, Tuesday works for me.", "written": "Thanks"}
    monkeypatch.setattr(browser_agent, "run_agent", lambda driver, settings, prompt, wd:
                        browser_agent.AgentRun(report=dict(report), workdir=wd, seconds=1.0))
    seen = []
    monkeypatch.setattr(browser_agent, "quote_on_page", lambda driver, quote, allowed_handles=None: seen.append(quote) or True)

    class Driver:
        window_handles = ["h1"]

    lead = {"id": "board:hirist:x", "kind": "REPLY", "who": "Asha", "url": "https://www.hirist.tech/chats"}
    state, why, got = boards.answer_lead(Driver(), settings, Profile(email="me@x.com"), "hirist", lead, "facts")

    assert (state, why) == ("answered", "Answered on the board.")
    assert seen == ["Thanks, Tuesday works for me."]
    saved = json.loads((workdir / "lead-report.json").read_text())
    assert saved["state"] == "answered" and saved["verified"] is True and got["workdir"] == str(workdir)


def test_main_maps_the_outcome_to_exit_codes(tmp_path, monkeypatch):
    from common import browser, config, profile as profile_module, report
    from common.run import EXIT_LOGIN, EXIT_OK, EXIT_QUOTA
    from sites_bot import browser_agent

    class Driver:
        def quit(self):
            pass

    monkeypatch.setattr(config, "load_settings", lambda env=None, overrides=None: _settings(tmp_path, leads_limit=3))
    monkeypatch.setattr(profile_module, "load_profile", lambda settings: Profile())
    monkeypatch.setattr(browser, "create_driver", lambda settings: Driver())
    monkeypatch.setattr(browser_agent, "reset", lambda: None)
    monkeypatch.setattr(report, "update_quietly", lambda settings: None)
    outcomes = iter([{"state": "read", "quota": False}, {"state": "read", "quota": True}, {"state": "needs_sign_in"}])
    seen = []
    monkeypatch.setattr(boards, "process_board", lambda driver, site, settings, profile, limit, dry:
                        seen.append((site, limit, dry)) or next(outcomes))

    assert boards.main(["--board", "hirist"]) == EXIT_OK
    assert boards.main(["--board", "cutshort", "--limit", "1", "--dry-run"]) == EXIT_QUOTA
    assert boards.main(["--board", "naukri"]) == EXIT_LOGIN
    assert seen == [("hirist", 3, False), ("cutshort", 1, True), ("naukri", 3, False)]
