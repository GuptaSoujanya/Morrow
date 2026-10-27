"""The browser agent: Claude Code drives the bot's own Chrome for a stuck company site.

claude itself is replaced by a fake process that records the command line and
replies with a canned report, so these tests check what the agent is allowed to
do, what it is told, and how much of its report the bot believes.
"""

import json
import os
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import apply as apply_module
from sites_bot import browser_agent as agent
from sites_bot import external as ext
from common.models import ApplyStatus, JobPosting, Profile, Settings

PASSWORD = "Ab#9$x'Q!z"
SITE = "https://jobs.acme.test/apply"
THANKS = "Thank you for applying to Acme Labs. Your application has been received."


class _Body:
    def __init__(self, driver):
        self.driver = driver

    @property
    def text(self):
        return self.driver.texts[self.driver.current]


class _Switch:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.current = handle


class _Driver:
    def __init__(self, texts=None, capabilities=None):
        self.texts = texts or {"naukri": "Naukri job page", "site": "Application form"}
        self.window_handles = list(self.texts)
        self.current = self.window_handles[-1]
        self.capabilities = (
            capabilities if capabilities is not None
            else {"goog:chromeOptions": {"debuggerAddress": "localhost:9222"}}
        )
        self.switch_to = _Switch(self)

    @property
    def current_window_handle(self):
        return self.current

    @property
    def current_url(self):
        return SITE

    def find_element(self, by, value):
        return _Body(self)


class _Claude:
    """Stands in for `claude -p`: records how it was started, replies with `report`."""

    calls = []
    report = None
    hang = False

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode = 0
        workdir = kwargs["cwd"]
        args = json.load(open(os.path.join(workdir, "mcp.json")))["mcpServers"]["browser"]["args"]
        secrets = args[args.index("--secrets") + 1] if "--secrets" in args else None
        self.secrets_path = secrets
        self.secrets = open(secrets).read() if secrets and os.path.exists(secrets) else None
        self.timeouts = 0
        _Claude.calls.append(self)

    def communicate(self, timeout=None):
        if _Claude.hang and self.timeouts == 0:
            self.timeouts += 1
            raise subprocess.TimeoutExpired(self.command, timeout)
        if _Claude.report is None:
            return json.dumps({"result": "I could not finish.", "total_cost_usd": 0.4, "num_turns": 3}), ""
        reply = "```json\n%s\n```" % json.dumps(_Claude.report)
        step = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__browser__browser_click", "input": {"element": "Submit"}}]}}
        result = {"type": "result", "result": reply, "total_cost_usd": 1.25, "num_turns": 30, "is_error": False}
        return "\n".join([json.dumps({"type": "system", "subtype": "init"}), json.dumps(step), json.dumps(result)]), ""

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def claude(monkeypatch):
    _Claude.calls = []
    _Claude.report = None
    _Claude.hang = False
    monkeypatch.setattr(agent.subprocess, "Popen", _Claude)
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None)
    agent.reset()
    return _Claude


@pytest.fixture
def settings(tmp_path):
    data = tmp_path / "user" / "inputs"
    data.mkdir(parents=True)
    (data / "answers.txt").write_text(
        "Q: What is your notice period?\nA: 15 days\n\n"
        "Q: Why do you want to work with us?\nA: [AI writes this for each job]\n\n"
        "Q: Your favourite book?\nA:\n",
        encoding="utf-8",
    )
    return Settings(
        report_dir=str(tmp_path / "reports"),
        data_dir=str(data),
        resume_out_dir=str(tmp_path / "out"),
        browser_agent=True,
        browser_agent_limit=5,
        company_site_email="jane.jobs@example.com",
        company_site_password=PASSWORD,
    )


@pytest.fixture
def profile():
    return Profile(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="+91 90000 00000",
        current_location="Indore",
        expected_ctc_lpa=20.0,
        notice_period_days=15,
        extra_facts={"country": "India", "pan_number": None},
        resume_text="Jane Doe. Software Engineer at Acme. Python, LangChain, FastAPI.",
    )


@pytest.fixture
def job():
    return JobPosting(job_id="j1", url="https://www.naukri.com/job-listings-j1", title="AI Engineer",
                      company="Acme Labs", description="Build LLM evaluation tooling in Python.")


def _stuck(detail="page 2 did not move on: the Next button stayed"):
    return ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url=SITE, ats="workday",
                              detail=detail, filled=["First name", "Email"])


def _resume(tmp_path):
    pdf = tmp_path / "Jane_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 resume")
    return pdf


# ---------------------------------------------------------------------------
# When the agent is called at all
# ---------------------------------------------------------------------------


def test_the_devtools_address_comes_from_the_driver():
    assert agent.cdp_endpoint(_Driver()) == "http://localhost:9222"
    edge = {"ms:edgeOptions": {"debuggerAddress": "127.0.0.1:9333"}}
    assert agent.cdp_endpoint(_Driver(capabilities=edge)) == "http://127.0.0.1:9333"
    assert agent.cdp_endpoint(_Driver(capabilities={})) == ""


@pytest.mark.parametrize("detail", [
    "needs you for: captcha (a check only a person may answer)",
    "Submit was clicked but no confirmation appeared",
    "the site needs a code it emails to jane@example.com",
    "the site sent a verification email; open it first",
    "an account already exists on jobs.acme.test",
    "workday applications need a linkedin session; finish this one by hand",
    "the browser agent did not report (timeout); check the site before trying again",
])
def test_what_only_a_person_can_clear_never_goes_to_the_agent(settings, detail):
    assert not agent.should_take_over(settings, _stuck(detail))


def test_only_stuck_results_go_to_the_agent_and_only_while_it_is_on(settings):
    assert agent.should_take_over(settings, _stuck())
    assert agent.should_take_over(settings, _stuck("needs you for: Address Line 1*"))
    applied = ext.ExternalResult(status=ApplyStatus.APPLIED_EXTERNAL, url=SITE, detail="the site says thanks")
    assert not agent.should_take_over(settings, applied)
    assert not agent.should_take_over(settings, ext.ExternalResult(status=ext.GONE, url=SITE, detail="closed"))
    settings.browser_agent = False
    assert not agent.should_take_over(settings, _stuck())


def test_the_per_run_limit_holds(claude, settings, profile, job):
    settings.browser_agent_limit = 1
    claude.report = {"status": "failed", "why": "the page kept reloading"}
    driver = _Driver()
    agent.take_over(driver, job, profile, settings, None, False, _stuck())
    untouched = _stuck()
    assert agent.take_over(driver, job, profile, settings, None, False, untouched) is untouched
    assert len(claude.calls) == 1
    agent.reset()
    assert agent.tasks_left(settings) == 1


# ---------------------------------------------------------------------------
# What the agent is told and allowed
# ---------------------------------------------------------------------------


def test_the_task_carries_her_facts_but_never_her_password(settings, profile, job, tmp_path):
    facts = agent.facts_text(profile, settings)
    assert "- full name: Jane Doe" in facts
    assert "- expected ctc lpa: 20" in facts
    assert "Q: What is your notice period?\n  A: 15 days" in facts
    assert "[AI writes this for each job]" not in facts
    assert "favourite book" not in facts
    assert "pan number" not in facts
    assert "Python, LangChain" in facts

    prompt = agent.application_prompt(job, SITE, facts, "jane.jobs@example.com", tmp_path / "cv.pdf", True, "page 2 stuck")
    assert "DRY RUN" in prompt and "do NOT click the final Submit" in prompt
    assert agent.SECRET_NAME in prompt and PASSWORD not in prompt
    assert "jane.jobs@example.com" in prompt
    assert str(tmp_path / "cv.pdf") in prompt
    assert "jobs.acme.test" in prompt
    assert "CAPTCHA" in prompt
    real = agent.application_prompt(job, SITE, facts, "e@x.test", None, False, "")
    assert "Click the final Submit button at most once" in real


def test_claude_gets_only_the_browser_tools_and_the_password_as_a_secret(claude, settings, profile, job, tmp_path):
    claude.report = {"status": "submitted", "why": "done", "filled": ["Phone"], "confirmation": THANKS}
    driver = _Driver({"naukri": "Naukri", "site": "Acme Labs " + THANKS})
    pdf = _resume(tmp_path)

    result = agent.take_over(driver, job, profile, settings, pdf, False, _stuck())

    call = claude.calls[0]
    command = call.command
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--allowedTools") + 1] == "mcp__browser"
    assert command[command.index("--disallowedTools") + 1] == (
        "mcp__browser__browser_close,mcp__browser__browser_run_code_unsafe")
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in command
    assert command[command.index("--max-budget-usd") + 1] == "5"
    assert command[command.index("--output-format") + 1] == "stream-json" and "--verbose" in command
    assert PASSWORD not in " ".join(command)
    assert call.kwargs["start_new_session"] is True
    workdir = call.kwargs["cwd"]
    config = json.load(open(os.path.join(workdir, "mcp.json")))
    args = config["mcpServers"]["browser"]["args"]
    assert config["mcpServers"]["browser"]["command"] == "npx"
    assert args[args.index("--cdp-endpoint") + 1] == "http://localhost:9222"
    assert "--secrets" in args
    assert call.secrets == 'COMPANY_SITE_PASSWORD="%s"\n' % PASSWORD
    assert not os.path.exists(os.path.join(workdir, "secrets.env"))
    # The agent may upload from its own folder, so the password file lives elsewhere.
    assert not os.path.realpath(call.secrets_path).startswith(os.path.realpath(workdir))
    assert not os.path.exists(call.secrets_path)
    assert os.path.exists(os.path.join(workdir, pdf.name))
    assert str(os.path.join(workdir, pdf.name)) in open(os.path.join(workdir, "task.md")).read()

    assert result.status == ApplyStatus.APPLIED_EXTERNAL
    assert THANKS in result.detail
    assert result.filled == ["First name", "Email", "Phone"]
    record = json.load(open(os.path.join(workdir, "report.json")))
    assert record["status"] == ApplyStatus.APPLIED_EXTERNAL and record["cost_usd"] == 1.25
    assert open(os.path.join(workdir, "steps.txt")).read() == '1. browser_click {"element": "Submit"}\n'
    assert len(open(os.path.join(workdir, "transcript.jsonl")).read().splitlines()) == 3
    assert agent.records_for(settings, os.path.basename(os.path.dirname(os.path.dirname(workdir))))[0]["site"] == SITE


def test_a_password_with_quotes_is_written_so_dotenv_reads_it_back(tmp_path):
    from dotenv import dotenv_values

    for password in ("Ab#9$x!z", "Ab#9$x'Q!z", 'a"b\'c#d'):
        path = tmp_path / "s.env"
        path.write_text("K=%s\n" % agent._dotenv_value(password))
        assert dotenv_values(str(path))["K"] == password


# ---------------------------------------------------------------------------
# How much of the report the bot believes
# ---------------------------------------------------------------------------


def test_a_submit_without_its_confirmation_on_the_page_is_never_retried(claude, settings, profile, job):
    claude.report = {"status": "submitted", "why": "clicked Submit", "confirmation": THANKS}
    result = agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    assert result.status == ApplyStatus.ERROR
    assert result.detail.startswith("Submit was clicked by the browser agent")
    assert not ext.retryable({"site": SITE, "why": result.detail})
    assert not agent.should_take_over(settings, result)


def test_a_short_quote_proves_nothing(claude, settings, profile, job):
    claude.report = {"status": "submitted", "confirmation": "Thanks"}
    driver = _Driver({"site": "Thanks for visiting"})
    assert agent.take_over(driver, job, profile, settings, None, False, _stuck()).status == ApplyStatus.ERROR


def test_questions_it_could_not_answer_come_back_to_her(claude, settings, profile, job):
    claude.report = {"status": "needs_you", "why": "salary in USD is not in the facts",
                     "missing": ["Expected salary (USD)*"], "filled": ["Phone"]}
    result = agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail.startswith("needs you for: Expected salary (USD)*")
    assert result.missing == ["Expected salary (USD)*"]


@pytest.mark.parametrize("report, dry_run, status", [
    ({"status": "gone", "why": "the posting is closed"}, False, ext.GONE),
    ({"status": "ready", "why": "all three pages filled"}, True, ext.DRY_RUN),
    ({"status": "ready", "why": "stopped early"}, False, ApplyStatus.EXTERNAL_MANUAL),
    ({"status": "needs_you", "why": "a captcha appeared"}, False, ApplyStatus.EXTERNAL_MANUAL),
    ({"status": "failed", "why": "Next does nothing"}, False, ApplyStatus.EXTERNAL_MANUAL),
])
def test_each_reported_status_maps_to_an_outcome(claude, settings, profile, job, report, dry_run, status):
    claude.report = report
    assert agent.take_over(_Driver(), job, profile, settings, None, dry_run, _stuck()).status == status


def test_a_dry_run_report_of_submitted_still_needs_proof(claude, settings, profile, job):
    claude.report = {"status": "submitted", "confirmation": "nothing like it on the page here"}
    assert agent.take_over(_Driver(), job, profile, settings, None, True, _stuck()).status == ApplyStatus.ERROR


def test_no_report_means_check_by_hand(claude, settings, profile, job):
    claude.report = None
    result = agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    assert result.status == ApplyStatus.ERROR
    assert "the browser agent did not report" in result.detail
    assert not ext.retryable({"site": SITE, "why": result.detail})


def test_a_task_that_runs_too_long_is_stopped_with_its_mcp_server(claude, settings, profile, job, monkeypatch):
    claude.hang = True
    signals = []
    monkeypatch.setattr(agent.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    result = agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    assert signals == [(4242, signal.SIGTERM)]
    assert result.status == ApplyStatus.ERROR
    assert "ran past 900 seconds" in result.detail


def test_without_a_devtools_address_claude_is_not_started(claude, settings, profile, job):
    result = agent.take_over(_Driver(capabilities={}), job, profile, settings, None, False, _stuck())
    assert claude.calls == []
    assert "no DevTools address" in result.detail


def test_long_answers_and_new_accounts_are_kept(claude, settings, profile, job):
    claude.report = {
        "status": "needs_you", "why": "address missing", "missing": ["Address Line 1*"],
        "written": [{"question": "Why Acme Labs?", "answer": "I build LLM evaluation pipelines in Python."}],
        "account": "created",
    }
    agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    answers = os.path.join(settings.resume_out_dir, "tailored", "Acme Labs - AI Engineer", "answers.md")
    assert "I build LLM evaluation pipelines in Python." in open(answers).read()
    accounts = open(os.path.join(settings.data_dir, "accounts.md")).read()
    assert "| jobs.acme.test | jane.jobs@example.com | created by the browser agent |" in accounts


# ---------------------------------------------------------------------------
# Wired into the company-site flow
# ---------------------------------------------------------------------------


def _company_site(monkeypatch, scripted):
    monkeypatch.setattr(apply_module, "classify_apply_button", lambda driver: (object(), "external"))
    monkeypatch.setattr(ext, "open_company_site", lambda driver, button: SITE)
    monkeypatch.setattr(ext, "apply_here", lambda *args: scripted)
    monkeypatch.setattr(ext, "return_to", lambda driver, handle, keep: None)


def test_the_company_site_flow_hands_a_stuck_page_to_the_agent(claude, settings, profile, job, monkeypatch):
    _company_site(monkeypatch, _stuck())
    claude.report = {"status": "submitted", "confirmation": THANKS}
    driver = _Driver({"naukri": "Naukri", "site": THANKS})

    result = ext.apply_on_company_site(driver, job, profile, None, settings)

    assert result.status == ApplyStatus.APPLIED_EXTERNAL
    assert len(claude.calls) == 1
    assert ext.pending_company_sites(settings) == []


def test_with_the_agent_off_the_page_is_left_for_her(claude, settings, profile, job, monkeypatch):
    settings.browser_agent = False
    _company_site(monkeypatch, _stuck())
    result = ext.apply_on_company_site(_Driver(), job, profile, None, settings)
    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert claude.calls == []
    assert ext.pending_company_sites(settings)[0]["why"].startswith("page 2 did not move on")


def test_the_daily_report_lists_the_agent_tasks(claude, settings, profile, job):
    from datetime import date

    from common import report

    claude.report = {"status": "needs_you", "why": "no address", "missing": ["Address Line 1*"]}
    agent.take_over(_Driver(), job, profile, settings, None, False, _stuck())
    text = report.build_report(settings, date.today())
    assert "## Browser agent (Claude Code on the company sites)" in text
    assert "| Acme Labs | AI Engineer | external_manual: needs you for: Address Line 1*" in text


def test_a_single_json_reply_from_an_older_claude_still_reads():
    events = agent._events(json.dumps({"result": "ok", "total_cost_usd": 0.1}))
    assert events == [{"result": "ok", "total_cost_usd": 0.1, "type": "result"}]
    assert agent._events("not json\n") == []


def test_the_prompt_says_how_to_pick_a_bucket_for_a_notice_period():
    assert '15 days -> "1 Month"' in agent._RULES and 'never "Immediately"' in agent._RULES


def test_uploads_are_staged_in_the_run_folder_and_named_from_there(tmp_path):
    original = tmp_path / "private" / "resume.pdf"
    original.parent.mkdir()
    original.write_bytes(b"%PDF")
    workdir = tmp_path / "run"
    staged = agent.stage_files(workdir, (original, tmp_path / "missing.pdf"))
    assert staged == ((workdir / "resume.pdf").resolve(),)
    assert (workdir / "resume.pdf").read_bytes() == b"%PDF"
    assert agent.stage_files(workdir, staged) == staged, "a file already in the folder is left alone"


def test_the_agent_runs_under_caffeinate_so_the_mac_does_not_sleep_on_it(claude, settings, profile, job, tmp_path, monkeypatch):
    claude.report = {"status": "submitted", "why": "done", "filled": [], "confirmation": THANKS}
    paths = {"claude": "/usr/local/bin/claude", "caffeinate": "/usr/bin/caffeinate"}
    monkeypatch.setattr(agent.shutil, "which", paths.get)
    driver = _Driver({"naukri": "Naukri", "site": "Acme Labs " + THANKS})

    agent.take_over(driver, job, profile, settings, _resume(tmp_path), False, _stuck())

    command = claude.calls[0].command
    assert command[:4] == ["/usr/bin/caffeinate", "-i", "claude", "-p"]
    assert agent.keep_awake(["claude", "-p", "x"])[:2] == ["/usr/bin/caffeinate", "-i"]
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    assert agent.keep_awake(["claude", "-p", "x"]) == ["claude", "-p", "x"], "no caffeinate: run claude as it is"


def test_the_stop_reason_names_the_api_error_hidden_behind_a_success_subtype():
    outer = {"type": "result", "subtype": "success", "is_error": True, "terminal_reason": "api_error",
             "result": "API Error: 502 An error occurred while processing your request\nCheck the gateway."}
    assert agent._stop_reason(outer) == "api_error (API Error: 502 An error occurred while processing your request)"
    assert agent._stop_reason({"subtype": "error_max_budget_usd", "is_error": True}) == "error_max_budget_usd"
    assert agent._stop_reason({"subtype": "error_max_budget_usd", "result": "error_max_budget_usd"}) == \
        "error_max_budget_usd"
    assert agent._stop_reason({}) == "error"
