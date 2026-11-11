"""Cutshort follow-ups are separate from applications and ordinary chat."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from common.models import Profile, Settings
from cutshort_bot import questionnaires as q
from sites_bot import browser_agent, platforms as pf

THREAD = "6ae9cec32b5c589cb358e966"
URL = q.PENDING_URL + "&thread=" + THREAD
# The job card links through this alias; the conversation page redirects to URL.
JOB_CARD_HREF = "https://cutshort.io/profile/conversations/candidate?i=all&thread=" + THREAD + "&stage=awaiting"


class Driver:
    current_url = "https://cutshort.io/profile/all-jobs?jobid=6adcb18b69c2ccfd11e7159a"

    def execute_script(self, script):
        if script == q._PROOF_SCRIPT:
            return getattr(self, "proof", [])
        return [URL]


def test_existing_application_is_recognized_on_its_signed_in_job_view():
    assert q.application_conversation(Driver()) == URL
    assert pf.shows_applied(Driver(), pf.BOARDS["cutshort"])


def test_real_job_card_conversation_alias_counts_as_existing_application():
    driver = Driver()
    driver.execute_script = lambda script: [JOB_CARD_HREF]
    assert q.thread_id(JOB_CARD_HREF) == THREAD
    assert q.application_conversation(driver) == JOB_CARD_HREF
    assert pf.shows_applied(driver, pf.BOARDS["cutshort"])


def test_thread_identity_is_case_normalized():
    assert q.thread_id(URL.replace(THREAD, THREAD.upper())) == THREAD


@pytest.mark.parametrize("url", [
    JOB_CARD_HREF.replace("cutshort.io", "cutshort.io.evil.example"),
    JOB_CARD_HREF.replace("/conversations/candidate", "/conversations/employer"),
    JOB_CARD_HREF.replace("/conversations/candidate", "/conversations/candidate/extra"),
    JOB_CARD_HREF.replace(THREAD, "not-a-thread"),
    JOB_CARD_HREF + "&thread=" + "b" * 24,
    JOB_CARD_HREF.replace('https:', 'http:'),
    JOB_CARD_HREF.replace('https://', 'https://user:password@'),
])
def test_conversation_alias_keeps_exact_host_route_and_single_thread_guards(url):
    assert q.thread_id(url) == ""


@pytest.mark.parametrize("url", [
    "https://cutshort.io/profile/all-jobs",
    "https://cutshort.io/job/Other-role-12345678",
    q.PENDING_URL,
    "https://cutshort.io.evil.example/profile/all-jobs?jobid=abc",
])
def test_general_conversation_links_never_prove_a_job_was_applied(url):
    driver = Driver()
    driver.current_url = url
    assert q.application_conversation(driver) == ""


def test_multiple_conversation_links_are_ambiguous():
    driver = Driver()
    driver.execute_script = lambda script: [URL, URL.replace(THREAD, "a" * 24)]
    assert q.application_conversation(driver) == ""


def settings(tmp_path):
    return Settings(data_dir=str(tmp_path / "inputs"), report_dir=str(tmp_path / "reports"),
                    browser_agent=True, browser_agent_limit=10)


def test_claim_persists_before_submission_and_does_not_repeat_uncertain_results(tmp_path):
    config = settings(tmp_path)
    assert q._claim(config, THREAD, "facts1", URL)
    assert not q._claim(config, THREAD, "facts2", URL)
    q._record(config, THREAD, state="uncertain")
    assert not q._claim(config, THREAD, "facts2", URL)
    q._record(config, THREAD, state="done")
    assert not q._claim(config, THREAD, "facts2", URL)


def test_missing_facts_retry_only_after_saved_facts_change(tmp_path):
    config = settings(tmp_path)
    q._claim(config, THREAD, "facts1", URL)
    q._record(config, THREAD, state="needs_you")
    assert not q._claim(config, THREAD, "facts1", URL)
    assert q._claim(config, THREAD, "facts2", URL)


def test_no_send_login_or_captcha_can_retry_after_cooldown_without_facts_change(tmp_path):
    config = settings(tmp_path)
    q._claim(config, THREAD, "facts1", URL)
    q._record(config, THREAD, state="retry_later", retry_after=(datetime.now() + timedelta(minutes=15)).isoformat())
    assert not q._claim(config, THREAD, "facts1", URL)
    q._record(config, THREAD, retry_after=(datetime.now() - timedelta(seconds=1)).isoformat())
    assert q._claim(config, THREAD, "facts1", URL)


def test_damaged_journal_never_resets_duplicate_protection(tmp_path):
    config = settings(tmp_path)
    q._journal(config).parent.mkdir(parents=True)
    q._journal(config).write_text("{")
    with pytest.raises(ValueError):
        q._claim(config, THREAD, "facts1", URL)


@pytest.mark.parametrize('record', [{}, {'state': 'sending'}, {'state': None}])
def test_unknown_journal_state_never_releases_a_possible_send(tmp_path, record):
    config = settings(tmp_path)
    q._journal(config).parent.mkdir(parents=True)
    q._journal(config).write_text(json.dumps({THREAD: record}))
    with pytest.raises(ValueError, match='unknown saved state'):
        q._claim(config, THREAD, 'new facts', URL)


def test_uppercase_legacy_thread_still_holds_its_uncertain_send(tmp_path):
    config = settings(tmp_path)
    q._journal(config).parent.mkdir(parents=True)
    q._journal(config).write_text(json.dumps({THREAD.upper(): {'state': 'uncertain'}}))
    assert not q._claim(config, THREAD, 'new facts', URL)


def test_questionnaire_task_authorizes_only_supported_form_answers():
    task = q.prompt(URL, "Acme", "AI Engineer", "- notice period days: 15", "jane@example.com")
    assert "You may submit this questionnaire" in task
    assert "Type your message..." in task and "Do not apply again" in task
    assert "skills test" in task and "unknown required fact" in task
    assert "- notice period days: 15" in task


def test_confirmation_requires_same_thread_and_saved_questionnaire_proof(monkeypatch):
    driver = Driver()
    driver.current_url = URL
    monkeypatch.setattr(q.ext, "_page_text", lambda d: "Your questionnaire answers were submitted")
    report = {"confirmation": "Your questionnaire answers were submitted"}
    driver.proof = [report["confirmation"]]
    assert q._verified(driver, URL, report)
    assert not q._verified(driver, URL.replace(THREAD, "b" * 24), report)
    assert not q._verified(driver, URL, {"confirmation": "I am interested in this role"})
    assert not q._verified(driver, URL, {"confirmation": "Your application was submitted"})
    assert q._verified(driver, JOB_CARD_HREF, report), "route alias redirects preserve the exact thread"


@pytest.mark.parametrize("quote", ["Questionnaire answers were not submitted", "Questionnaire answers failed to save",
                                   "Questionnaire answers aren't saved", "Questionnaire answers submitted with error",
                                   "Questionnaire answers saved as draft", "Questionnaire received",
                                   "Answers saved", "Questionnaire answers recorded", "Questionnaire completed",
                                   "After the questionnaire is submitted, wait", "Once answers have been submitted",
                                   "Submit questionnaire answers", "Questionnaire was sent to you"])
def test_failure_text_is_not_questionnaire_confirmation(monkeypatch, quote):
    driver = Driver()
    driver.current_url = URL
    monkeypatch.setattr(q.ext, "_page_text", lambda d: quote)
    driver.proof = [quote]
    assert not q._verified(driver, URL, {"confirmation": quote})


@pytest.mark.parametrize('quote', ['Your questionnaire has been submitted', 'Your answers have been submitted successfully',
                                   'Your responses were received', 'Successfully submitted your questionnaire'])
def test_explicit_completed_submission_receipts_are_accepted(quote):
    driver = Driver()
    driver.current_url = URL
    driver.proof = [quote]
    assert q._verified(driver, URL, {'confirmation': quote})


def test_wrong_or_ambiguous_selected_conversation_never_matches_a_row():
    driver = Driver()
    row = {'company': 'Acme', 'title': 'AI Engineer'}
    context = {'companies': ['Acme'], 'titles': ['AI Engineer'], 'jobs': ['https://cutshort.io/job/Engineer-12345678']}
    driver.execute_script = lambda script: context
    assert q._selected_thread_matches(driver, row)
    for field, wrong in [('companies', ['Other company']), ('titles', ['Other role']), ('jobs', []), ('jobs', ['a', 'b'])]:
        driver.execute_script = lambda script, value={**context, field: wrong}: value
        assert not q._selected_thread_matches(driver, row)


@pytest.mark.parametrize("report,state,observed_click", [
    ({"status": "done", "confirmation": "Questionnaire answers submitted", "submission_attempted": True}, "done", True),
    ({"status": "done", "confirmation": "Pending applications", "submission_attempted": True}, "uncertain", True),
    ({"status": "needs_you", "submission_attempted": False, "missing": ["Last working day"]}, "needs_you", False),
    ({"status": "needs_you", "submission_attempted": True}, "uncertain", False),
    ({"status": "needs_you", "submission_attempted": False}, "uncertain", True),
    ({"status": "needs_you", "submission_attempted": False, "blocker": "sign_in"}, "retry_later", False),
])
def test_pending_pass_records_results_separately_from_job_applications(tmp_path, monkeypatch, report, state, observed_click):
    from sites_bot import application_brain
    config = settings(tmp_path)
    browser_agent.reset()
    driver = Driver()
    driver.proof = ["Questionnaire answers submitted"]
    opened, calls = [], []
    def get(d, url):
        opened.append(url)
        d.current_url = url
        return True
    monkeypatch.setattr(q, "safe_get", get)
    monkeypatch.setattr(q.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(q, "facts_fingerprint", lambda *a: "facts")
    monkeypatch.setattr(q, "pending_rows", lambda d: [{"key": "Acme|AI Engineer", "element": "row",
                                                      "company": "Acme", "title": "AI Engineer"}])
    monkeypatch.setattr(q, '_selected_thread_matches', lambda *a: True)
    monkeypatch.setattr(q.ext, "_click", lambda d, el: setattr(d, "current_url", URL))
    monkeypatch.setattr(q.ext, "_page_text", lambda d: "Questionnaire answers submitted")
    monkeypatch.setattr(browser_agent, "facts_text", lambda *a: "saved facts")
    monkeypatch.setattr(application_brain, "submission_click_recorded", lambda *a: observed_click)
    def run(d, s, task, workdir):
        saved = json.loads(q._journal(s).read_text())
        assert saved[THREAD]["state"] == "running", "recorded before any agent may submit"
        calls.append(task)
        return SimpleNamespace(report=report, problem="")
    monkeypatch.setattr(browser_agent, "run_agent", run)
    result = q.finish_pending(driver, Profile(email="jane@example.com"), config)
    assert result == [{"thread": THREAD, "state": state, "company": "Acme", "title": "AI Engineer"}]
    assert len(calls) == 1
    if state == "done":
        assert URL in opened, "reload proof after Submit"
    assert json.loads(q._journal(config).read_text())[THREAD]["state"] == state
    assert q.finish_pending(driver, Profile(), config) == []
    assert len(calls) == 1


def test_questionnaire_task_shares_agent_limit_and_does_not_run_when_disabled(tmp_path):
    browser_agent.reset()
    config = settings(tmp_path)
    config.browser_agent_limit = 1
    assert browser_agent.reserve_task(config)
    assert not browser_agent.reserve_task(config)
    assert q.finish_pending(Driver(), Profile(), config) == []
    browser_agent.reset()
    config.browser_agent = False
    assert not browser_agent.reserve_task(config)
    assert q.finish_pending(Driver(), Profile(), config) == []


@pytest.mark.parametrize("dry_run,expected", [(False, [10]), (True, [])])
def test_cutshort_apply_run_checks_questionnaires_even_with_no_new_jobs(tmp_path, monkeypatch, dry_run, expected):
    from common.ledger import Ledger
    from naukri_bot import ranking
    config = settings(tmp_path)
    config.db_path = str(tmp_path / "test.db")
    calls = []
    monkeypatch.setattr(pf, "safe_get", lambda *a: True)
    monkeypatch.setattr(pf.time, "sleep", lambda *a: None)
    monkeypatch.setattr(pf, "signed_out", lambda *a: False)
    monkeypatch.setattr(pf, "collect", lambda *a: [])
    monkeypatch.setattr(ranking, "rank", lambda *a, **kw: [])
    monkeypatch.setattr(q, "finish_pending", lambda *a, limit: calls.append(limit))
    with Ledger(config.db_path) as ledger:
        summary = pf.run_board(Driver(), pf.BOARDS["cutshort"], config, Profile(), ledger, None, None,
                               100, dry_run, None)
    assert calls == expected
    assert summary.applied == 0, "questionnaires do not inflate application counts"


def test_bad_questionnaire_journal_stops_only_the_questionnaire_pass(tmp_path, monkeypatch):
    config = settings(tmp_path)
    browser_agent.reset()
    driver = Driver()
    driver.current_url = URL
    q._journal(config).parent.mkdir(parents=True)
    q._journal(config).write_text("{")
    monkeypatch.setattr(q, "safe_get", lambda *a: True)
    monkeypatch.setattr(q.time, "sleep", lambda *a: None)
    monkeypatch.setattr(q, "facts_fingerprint", lambda *a: "facts")
    monkeypatch.setattr(q, "pending_rows", lambda d: [{"key": "Acme|AI Engineer", "element": "row"}])
    monkeypatch.setattr(q, '_selected_thread_matches', lambda *a: True)
    monkeypatch.setattr(q.ext, "_click", lambda *a: None)
    monkeypatch.setattr(browser_agent, "run_agent", lambda *a: pytest.fail("must not send without duplicate journal"))
    assert q.finish_pending(driver, Profile(), config) == []


def test_held_rows_do_not_spend_questionnaire_attempt_limit(tmp_path, monkeypatch):
    config = settings(tmp_path)
    browser_agent.reset()
    driver = Driver()
    rows = [{"key": str(n), "element": "%024x" % n, "company": "Acme", "title": "Engineer"}
            for n in range(1, 14)]
    for row in rows[:-1]:
        q._claim(config, row["element"], "facts", URL)
        q._record(config, row["element"], state="done")
    monkeypatch.setattr(q, "safe_get", lambda *a: True)
    monkeypatch.setattr(q.time, "sleep", lambda *a: None)
    monkeypatch.setattr(q, "facts_fingerprint", lambda *a: "facts")
    monkeypatch.setattr(q, "pending_rows", lambda d: rows)
    monkeypatch.setattr(q, '_selected_thread_matches', lambda *a: True)
    monkeypatch.setattr(q.ext, "_click", lambda d, el: setattr(d, "current_url", q.PENDING_URL + "&thread=" + el))
    monkeypatch.setattr(browser_agent, "facts_text", lambda *a: "facts")
    calls = []
    def run(*args):
        calls.append(1)
        return SimpleNamespace(report={"status": "needs_you", "submission_attempted": False, "blocker": "missing_facts"}, problem="")
    monkeypatch.setattr(browser_agent, "run_agent", run)
    assert q.finish_pending(driver, Profile(), config, limit=1) == [
        {"thread": rows[-1]["element"], "state": "needs_you", "company": "Acme", "title": "Engineer"}]
    assert calls == [1]


def test_wrong_thread_is_never_claimed_or_answered(tmp_path, monkeypatch):
    config = settings(tmp_path)
    browser_agent.reset()
    driver = Driver()
    driver.current_url = URL
    monkeypatch.setattr(q, 'safe_get', lambda *a: True)
    monkeypatch.setattr(q.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(q, 'facts_fingerprint', lambda *a: 'facts')
    monkeypatch.setattr(q, 'pending_rows', lambda d: [{'key': 'Acme|AI Engineer', 'element': 'stale', 'company': 'Acme', 'title': 'AI Engineer'}])
    monkeypatch.setattr(q.ext, '_click', lambda *a: None)
    monkeypatch.setattr(browser_agent, 'run_agent', lambda *a: pytest.fail('wrong conversation must never be handed over'))
    assert q.finish_pending(driver, Profile(), config) == []
    assert not q._journal(config).exists()


def test_questionnaire_storage_error_does_not_abort_new_applications(tmp_path, monkeypatch):
    from common.ledger import Ledger
    from naukri_bot import ranking
    config = settings(tmp_path)
    config.db_path = str(tmp_path / 'test.db')
    collected = []
    monkeypatch.setattr(pf, 'safe_get', lambda *a: True)
    monkeypatch.setattr(pf.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(pf, 'signed_out', lambda *a: False)
    monkeypatch.setattr(pf, 'collect', lambda *a: collected.append(True) or [])
    monkeypatch.setattr(ranking, 'rank', lambda *a, **kw: [])
    def fail(*a, **kw):
        raise PermissionError('questionnaire journal unavailable')
    monkeypatch.setattr(q, 'finish_pending', fail)
    with Ledger(config.db_path) as ledger:
        summary = pf.run_board(Driver(), pf.BOARDS['cutshort'], config, Profile(), ledger, None, None, 100, False, None)
    assert collected == [True]
    assert summary.applied == 0
