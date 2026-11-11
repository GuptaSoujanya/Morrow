"""What happens when the subscription's window runs out in the middle of a run.

A real run met "You've hit your session limit" eight minutes in and then spent
thirty-five more minutes on it: 187 CLI calls that could not answer, all fifty
browser-agent tries burned on three-second failures, and fifty-three good
postings written down as errors.
"""

import subprocess
from types import SimpleNamespace

import pytest

from common import llm
from common.models import ApplyStatus, Settings


SESSION_LIMIT = "You've hit your session limit · resets 3pm (Asia/Calcutta)"


def _client(monkeypatch, returncode, output, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=output, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", run)
    return llm.ClaudeCLIClient(Settings())


def test_the_clis_own_words_for_a_spent_window_are_recognised():
    assert llm.note_out_of_quota(SESSION_LIMIT) is True
    assert "session limit" in llm.out_of_quota()


@pytest.mark.parametrize("output", [
    "Error: not signed in",
    "",
    "Daily quota of jobs exceeded",
])
def test_other_failures_are_not_mistaken_for_a_spent_window(output):
    """Naukri's own 403 says 'quota' too, and that one must not mute the model."""
    llm.note_out_of_quota(output)
    assert llm.out_of_quota() == ""


def test_the_pipeline_cli_raises_a_quota_error_for_a_spent_window(monkeypatch):
    from common import ai_cli

    class Spent:
        args = ["claude"]
        returncode = 1
        pid = 1

        def __init__(self, *a, **k):
            pass

        def communicate(self, timeout=None):
            return "", SESSION_LIMIT

    monkeypatch.setattr(ai_cli.subprocess, "Popen", Spent)
    monkeypatch.setattr(ai_cli, "chosen_cli", lambda wanted=None: "claude")
    monkeypatch.setattr(ai_cli, "shutdown_event", None)
    llm.allow_quota_again()
    with pytest.raises(ai_cli.QuotaError):
        ai_cli.ask("write the notes", cli="claude", timeout_s=5)
    assert llm.out_of_quota(), "the spent window is remembered for every later caller"
    llm.allow_quota_again()

    class Broken(Spent):
        def communicate(self, timeout=None):
            return "", "Error: not signed in"

    monkeypatch.setattr(ai_cli.subprocess, "Popen", Broken)
    with pytest.raises(ai_cli.AIError) as caught:
        ai_cli.ask("write the notes", cli="claude", timeout_s=5)
    assert not isinstance(caught.value, ai_cli.QuotaError)


def test_the_window_can_be_opened_again():
    llm.note_out_of_quota(SESSION_LIMIT)
    llm.allow_quota_again()
    assert llm.out_of_quota() == ""


def test_the_first_refusal_is_remembered(monkeypatch):
    client = _client(monkeypatch, 1, SESSION_LIMIT)
    assert client.complete_json("score this job", "{}") is None
    assert "session limit" in llm.out_of_quota()


def test_once_the_window_is_spent_no_further_call_is_made(monkeypatch):
    calls = []
    client = _client(monkeypatch, 1, SESSION_LIMIT, calls)
    client.complete_json("score this job", "{}")
    spent = len(calls)
    for _ in range(5):
        assert client.complete_json("score another job", "{}") is None
    assert len(calls) == spent


def test_an_ordinary_failure_still_lets_the_next_question_through(monkeypatch):
    calls = []
    client = _client(monkeypatch, 1, "Error: not signed in", calls)
    client.complete_json("score this job", "{}")
    client.complete_json("score another job", "{}")
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# The browser agent
# ---------------------------------------------------------------------------


def _stopped_short():
    from sites_bot import external as ext

    return ext.ExternalResult(
        status=ApplyStatus.EXTERNAL_MANUAL, url="https://example.com/apply",
        detail="needs you for: Address Line 1*")


class _Driver:
    current_url = "https://example.com/apply"
    window_handles = ["one"]

    def find_element(self, by, value):
        assert (by, value) == ("tag name", "body")
        return SimpleNamespace(text="Application form: Address Line 1*")

    def execute_script(self, script):
        return []


def _agent_settings(tmp_path):
    return Settings(
        browser_agent=True, browser_agent_limit=50,
        data_dir=str(tmp_path / "inputs"),
        report_dir=str(tmp_path / "reports"),
        resume_out_dir=str(tmp_path / "resume"),
    )


def _hand_over(monkeypatch, tmp_path, run):
    from sites_bot import browser_agent
    from common.models import JobPosting, Profile

    browser_agent.reset()
    monkeypatch.setattr(browser_agent, "run_agent", lambda *a, **k: run)
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path)
    settings = _agent_settings(tmp_path)
    before = browser_agent.tasks_left(settings)
    browser_agent.finish_application(
        driver=_Driver(),
        job=JobPosting(job_id="1", url="https://naukri.test/1", title="Engineer", company="Acme"),
        profile=Profile(full_name="A", email="a@example.com"), settings=settings,
        resume_pdf=None, dry_run=False, previous=_stopped_short())
    return before, browser_agent.tasks_left(settings)


def test_the_agent_stands_down_while_the_model_is_out(tmp_path):
    from sites_bot import browser_agent

    browser_agent.reset()
    assert browser_agent.should_take_over(_agent_settings(tmp_path), _stopped_short()) is True
    llm.note_out_of_quota(SESSION_LIMIT)
    assert browser_agent.should_take_over(_agent_settings(tmp_path), _stopped_short()) is False


def test_a_try_the_spent_window_wasted_is_given_back(monkeypatch, tmp_path):
    from sites_bot import browser_agent

    run = browser_agent.AgentRun(
        report=None, workdir=tmp_path, seconds=3.0,
        problem="claude stopped: api_error (%s)" % SESSION_LIMIT)
    before, after = _hand_over(monkeypatch, tmp_path, run)
    assert after == before
    assert "session limit" in llm.out_of_quota()


def test_a_try_the_agent_really_spent_is_counted(monkeypatch, tmp_path):
    from sites_bot import browser_agent

    run = browser_agent.AgentRun(
        report=None, workdir=tmp_path, seconds=240.0,
        problem="it ran past 900 seconds and was stopped")
    before, after = _hand_over(monkeypatch, tmp_path, run)
    assert after == before - 1
    assert llm.out_of_quota() == ""
