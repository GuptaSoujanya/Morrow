"""Claude Code as the bot's browser agent, for one company-site task at a time.

The scripted filler in external.py knows the common forms. When a site beats it
(an odd widget, a page that will not move on, a resume step it cannot find),
this module starts `claude -p` with a Playwright MCP server attached over CDP to
the bot's own Chrome, so the sign-ins, cookies and the half-filled page carry
over. Claude works the page through the browser tools only, from the facts
given in the task, and replies with a JSON report. A "submitted" report counts
only when the confirmation it quotes is on the page Selenium reads afterwards.
"""

import argparse
import json
import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from common.models import ApplyStatus, JobPosting, Profile, Settings
from common import paths

logger = logging.getLogger(__name__)

SERVER = "browser"
# The agent types this name; the MCP server swaps in the real password and
# redacts it from every page snapshot, so the password never reaches the model.
SECRET_NAME = "COMPANY_SITE_PASSWORD"
MIN_QUOTE_CHARS = 12
FACTS_RESUME_CHARS = 6000
FACTS_POSTING_CHARS = 3000
STOP_GRACE_S = 10

# Reasons only a person can clear. After a Submit click a second attempt could
# apply twice, so those never go to the agent either.
_NOT_FOR_AGENT = (
    "captcha",
    "a check only a person",
    "needs a code it emails",
    "verification email",
    "verified first",
    "submit was clicked",
    "already exists on",
    "did not take the saved password",
    "session; finish this one by hand",
    "browser agent",
)

_started = 0


@dataclass
class AgentRun:
    report: Optional[Dict[str, Any]]
    workdir: Path
    seconds: float
    cost_usd: Optional[float] = None
    turns: Optional[int] = None
    problem: str = ""


def reset() -> None:
    """Start a new run's count of agent tasks."""
    global _started
    _started = 0


def tasks_left(settings: Settings) -> int:
    return max(0, settings.browser_agent_limit - _started)


def cdp_endpoint(driver: Any) -> str:
    """The DevTools address chromedriver (or msedgedriver) opened for this browser."""
    capabilities = getattr(driver, "capabilities", None) or {}
    for key in ("goog:chromeOptions", "ms:edgeOptions"):
        address = (capabilities.get(key) or {}).get("debuggerAddress")
        if address:
            return address if "://" in address else "http://%s" % address
    return ""


def should_take_over(settings: Settings, result: Any) -> bool:
    if not settings.browser_agent or tasks_left(settings) <= 0:
        return False
    if result.status not in (ApplyStatus.EXTERNAL_MANUAL, ApplyStatus.ERROR):
        return False
    detail = (result.detail or "").casefold()
    return not any(reason in detail for reason in _NOT_FOR_AGENT)


# ---------------------------------------------------------------------------
# What the agent is told
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def facts_text(profile: Profile, settings: Settings) -> str:
    """Every fact they gave: profile.yaml, their answers.txt answers, then the resume."""
    from common.answers import PER_JOB, AnswerBook, answers_file_path
    from .external import known_values

    lines = []  # type: List[str]
    seen = set()
    for source in (known_values(profile), profile.known_facts(), profile.extra_facts or {}):
        for key, value in source.items():
            if key in seen or value is None or value == "" or value == [] or value == {}:
                continue
            seen.add(key)
            lines.append("- %s: %s" % (key.replace("_", " "), _text(value)))
    answered = [
        (questions, answer)
        for questions, answer in AnswerBook(answers_file_path(settings)).source_entries
        if answer and answer.strip() != PER_JOB
    ]
    if answered:
        lines += ["", "Their own answers to screening questions:"]
        for questions, answer in answered:
            lines.append("- Q: %s\n  A: %s" % (" / ".join(questions), " ".join(answer.split())))
    if profile.resume_text:
        lines += ["", "Their resume (plain text):", profile.resume_text[:FACTS_RESUME_CHARS]]
    return "\n".join(lines)


_RULES = """Rules, in order of importance:
1. Never solve, skip or work around a CAPTCHA, "I am not a robot" box, puzzle or
   image-text check, and never try to get past bot detection. Stop and report
   needs_you.
2. Stop and report needs_you for a verification code or link sent by email or
   SMS, a two-factor prompt, any payment, or an identity number (PAN, SSN,
   passport number) they have not given.
3. Use only the facts below. Never invent a fact, a number, a date or a yes/no.
   When a required question is not answered by them, do not guess and do not pick
   any option just to move on: leave it, finish what you can, and list the
   question in "missing". Leave optional questions the facts do not answer empty.
   When a choice list has no exact match for a known number, pick the option whose
   range holds it; for a notice period or joining time pick the shortest option
   that is not shorter than the fact (15 days -> "1 Month"), never "Immediately",
   and say which option you picked in "filled".
4. Voluntary questions about gender, race, ethnicity, disability or veteran
   status: choose the decline / prefer-not-to-say option when there is one.
5. Some fields may already be filled by the bot. Check them against the facts and
   fix wrong ones; do not retype correct ones.
6. Work only in the tab named below, on that site and the sign-in pages it sends
   you to. Do not close tabs and do not open other websites.
7. Report exactly what happened. If you are unsure whether something worked, say
   so in "why"."""

_APPLY_REPORT = (
    '{"status": "submitted|ready|needs_you|gone|failed", "why": "one or two sentences", '
    '"filled": ["field label", "..."], "missing": ["question you could not answer from the facts"], '
    '"written": [{"question": "", "answer": ""}], "account": "created|signed_in|none", '
    '"confirmation": "the confirmation sentence copied word for word from the page after Submit, or empty"}'
)


def application_prompt(
    job: JobPosting,
    url: str,
    facts: str,
    email: str,
    resume_file: Optional[Path],
    dry_run: bool,
    previous: str,
    has_password: bool = True,
) -> str:
    host = urlparse(url).netloc or url
    if dry_run:
        goal = (
            "This is a DRY RUN. Fill in every page you can, moving on with Next or Continue, "
            "but do NOT click the final Submit / Apply / Send button. Stop on the last page and "
            'report status "ready". Do not create a new account in a dry run; signing in to an '
            "existing one is fine."
        )
    else:
        goal = (
            "Complete the application and submit it. Click the final Submit button at most once, "
            "and only when every required field holds an answer taken from the facts. After it, "
            "wait for the page to change and copy the site's confirmation sentence word for word."
        )
    if resume_file is not None:
        resume = (
            "Attach the resume file %s wherever the form asks for a resume or CV: click the upload "
            "control so the file chooser opens, then use the file upload tool with that path. If the "
            "site reads the resume and pre-fills fields, check those against the facts." % resume_file
        )
    else:
        resume = "There is no resume file for this task; if the form requires one, list it in missing."
    return "\n\n".join([
        "You are completing a job application on a company career site for %s, in a Chrome "
        "window their job bot already has open. You control the browser only through the browser "
        "tools." % (job_owner(facts) or "the candidate"),
        "Job: %s at %s\nApplication page: %s\nWhat the bot managed before it stopped: %s"
        % (job.title or "(title unknown)", job.company or "(company unknown)", url, previous or "nothing yet"),
        "First list the browser tabs and select the tab whose address is on %s. Work in that tab." % host,
        "Goal: " + goal,
        "Resume: " + resume,
        ("Accounts: if the site wants you to sign in or create an account, use the email %s. For the "
         "password, type exactly the word %s into the password box: the browser substitutes their saved "
         "password, which you never see. Creating an account with that email and password is allowed "
         "(except in a dry run). Use \"Continue with Google\" only if it signs in without asking for a "
         "password or code." % (email or "(none given; report needs_you)", SECRET_NAME))
        if has_password else _NO_PASSWORD,
        "A required free-text question such as \"Why do you want to join us?\": write two or three "
        "plain first-person sentences using only facts from their resume and the posting, and list the "
        'question and your text under "written".',
        _RULES,
        "The facts:\n" + facts,
        "The posting:\n" + ((job.description or "")[:FACTS_POSTING_CHARS] or "(not available)"),
        "When you finish or stop, reply with ONE JSON object and nothing else:\n" + _APPLY_REPORT,
    ])


def job_owner(facts: str) -> str:
    for line in facts.splitlines():
        if line.startswith("- full name: "):
            return line[len("- full name: "):]
    return ""


# Without a saved password the placeholder word would itself become the password.
_NO_PASSWORD = (
    "Accounts: no password is saved for career sites. Do not create an account and do not type "
    "anything into a password box. Use \"Continue with Google\" only if it signs in without asking "
    "for a password or code; otherwise stop and report needs_you."
)


_TASK_REPORT = ('When you finish or stop, reply with ONE JSON object and nothing else:\n'
                '{"status": "done|needs_you|failed", "why": "one or two sentences", "notes": "anything they should know"}')


def task_prompt(instruction: str, url: str, facts: str, email: str, files: Tuple[Path, ...] = (),
                has_password: bool = True, report: str = _TASK_REPORT) -> str:
    host = urlparse(url).netloc or url
    uploads = (
        "Files you may upload when the task needs them (click the upload control so the file "
        "chooser opens, then use the file upload tool with the path): %s" % ", ".join(str(path) for path in files)
        if files else "There are no files to upload for this task."
    )
    return "\n\n".join([
        "You are helping a job seeker in a Chrome window their job bot already has open. You control "
        "the browser only through the browser tools.",
        "First list the browser tabs and select the tab whose address is on %s." % host,
        "Task: " + instruction,
        uploads,
        ("Never submit an application, send a message or accept terms unless the task says so. If a "
         "sign-in is needed, use the email %s and type exactly the word %s as the password (the "
         "browser substitutes the real one)." % (email or "(none given)", SECRET_NAME))
        if has_password else "Never submit an application, send a message or accept terms unless the task "
        "says so. " + _NO_PASSWORD,
        _RULES,
        "The facts:\n" + facts,
        report,
    ])


# ---------------------------------------------------------------------------
# Running claude
# ---------------------------------------------------------------------------


def workdir_for(settings: Settings, label: str, now: Optional[datetime] = None) -> Path:
    from common.resume import _folder_name

    now = now or datetime.now()
    return (
        Path(settings.report_dir or paths.user("reports"))
        / now.strftime("%Y-%m-%d")
        / "agent"
        / ("%s %s %s" % (now.strftime("%H%M%S"), _folder_name(label) or "task", uuid.uuid4().hex[:12]))
    )


def stage_files(workdir: Path, files: Tuple[Path, ...]) -> Tuple[Path, ...]:
    """Copy the files the agent may upload into its run folder and return those paths.

    The MCP server may only upload from its own output folder (the run folder), so a task
    that names the original path gets "outside allowed roots" from the upload tool and the
    resume never lands. Every prompt must name the copy, never the original.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    staged = []
    for path in files:
        path = Path(path)
        if not path.is_file():
            logger.warning("browser agent: %s is not a file; the agent gets nothing to upload", path)
            continue
        copy = workdir / path.name
        if copy.resolve() != path.resolve():
            shutil.copy2(str(path), str(copy))
        staged.append(copy.resolve())
    return tuple(staged)


def _dotenv_value(value: str) -> str:
    if "'" not in value:
        return "'%s'" % value
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def mcp_config(settings: Settings, endpoint: str, workdir: Path, secrets: Optional[Path]) -> Dict[str, Any]:
    parts = shlex.split(settings.browser_agent_mcp)
    args = parts[1:] + ["--cdp-endpoint", endpoint, "--output-dir", str(workdir)]
    if secrets is not None:
        args += ["--secrets", str(secrets)]
    return {"mcpServers": {SERVER: {"command": parts[0], "args": args}}}


def claude_command(settings: Settings, prompt: str, config_path: Path, system: str = "") -> List[str]:
    command = [
        "claude", "-p", prompt,
        "--mcp-config", str(config_path),
        "--strict-mcp-config",
        # The browser tools are all it gets: no shell, no file edits, no web fetch.
        "--tools", "",
        "--allowedTools", "mcp__%s" % SERVER,
        # Closing the only tab ends the bot's browser session; Chrome quits with it.
        # run_code_unsafe runs code in the MCP server on their Mac, not in the page:
        # a posting could talk the agent into using it.
        "--disallowedTools", "mcp__%s__browser_close,mcp__%s__browser_run_code_unsafe" % (SERVER, SERVER),
        "--permission-mode", "dontAsk",
        # One JSON event per line, so every browser step lands in transcript.jsonl.
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence",
        "--max-budget-usd", "%g" % settings.browser_agent_budget_usd,
    ]
    if system:
        # The agent's role and standing instructions, kept apart from the task itself.
        command += ["--append-system-prompt", system]
    if settings.browser_agent_model:
        command += ["--model", settings.browser_agent_model]
    return command


def keep_awake(command: List[str]) -> List[str]:
    """Run the agent under `caffeinate -i` on a Mac so idle sleep cannot freeze it mid-edit.

    A 40-minute profile run on a laptop outlives the idle-sleep timer; asleep, the browser
    tools hang, the clock the timeout counts stops, and the agent wakes to a reset tab.
    Closing the lid on battery still sleeps the Mac; `-i` only stops the idle timer.
    """
    caffeinate = shutil.which("caffeinate")
    if caffeinate is None:
        return command
    return [caffeinate, "-i"] + command


def _stop(process: subprocess.Popen) -> None:
    """Stop claude and the MCP server it started; they share a process group."""
    for sig, wait_s in ((signal.SIGTERM, STOP_GRACE_S), (signal.SIGKILL, None)):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def _events(out: str) -> List[Dict[str, Any]]:
    """The JSON events claude printed: one per line, or a single object from older runs."""
    try:
        whole = json.loads(out)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, dict):
        return [dict(whole, type=whole.get("type") or "result")]
    events = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _steps(events: List[Dict[str, Any]]) -> List[str]:
    """One readable line per browser action the agent took."""
    steps = []
    for event in events:
        message = event.get("message") if event.get("type") == "assistant" else None
        for part in (message or {}).get("content") or []:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                name = str(part.get("name") or "").replace("mcp__%s__" % SERVER, "")
                steps.append("%d. %s %s" % (len(steps) + 1, name, json.dumps(part.get("input") or {})[:200]))
    return steps


def _stop_reason(outer: Dict[str, Any]) -> str:
    """Why claude stopped, from its result event: the terminal reason and the first line of its message.

    A run killed by an API error still carries subtype "success", so the subtype alone would hide
    the cause.
    """
    reason = str(outer.get("terminal_reason") or "").strip()
    if reason in ("", "success"):
        reason = str(outer.get("subtype") or "").strip()
    message = str(outer.get("result") or "").strip().splitlines()
    first = message[0][:160] if message else ""
    if reason and first and first != reason:
        return "%s (%s)" % (reason, first)
    return reason or first or "error"


def run_agent(
    driver: Any,
    settings: Settings,
    prompt: str,
    workdir: Path,
    files: Tuple[Path, ...] = (),
    system: str = "",
) -> AgentRun:
    """Run one `claude -p` task against this browser; the report is None when it gave none.

    `system` is appended to claude's system prompt: the agent's role and skill.
    """
    from common.llm import _extract_json

    started = time.monotonic()
    workdir.mkdir(parents=True, exist_ok=True)
    run = AgentRun(report=None, workdir=workdir, seconds=0.0)
    endpoint = cdp_endpoint(driver)
    if not endpoint:
        run.problem = "the browser exposes no DevTools address to attach to"
        return run
    if shutil.which("claude") is None:
        run.problem = "the claude command is not on PATH"
        return run
    stage_files(workdir, files)
    secrets = None  # type: Optional[Path]
    if settings.company_site_password:
        # Outside the agent folder: --output-dir is where the browser may upload
        # from, so a hostile page could talk the agent into attaching it.
        secrets = Path(tempfile.mkdtemp(prefix="browser-agent-")) / "secrets.env"
        fd = os.open(str(secrets), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("%s=%s\n" % (SECRET_NAME, _dotenv_value(settings.company_site_password)))
    config_path = workdir / "mcp.json"
    config_path.write_text(json.dumps(mcp_config(settings, endpoint, workdir, secrets), indent=1), encoding="utf-8")
    (workdir / "task.md").write_text(prompt, encoding="utf-8")
    if system:
        (workdir / "system.md").write_text(system, encoding="utf-8")
    try:
        process = subprocess.Popen(
            keep_awake(claude_command(settings, prompt, config_path, system)),
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = process.communicate(timeout=settings.browser_agent_timeout_s)
        except subprocess.TimeoutExpired:
            _stop(process)
            out, err = process.communicate()
            run.problem = "it ran past %d seconds and was stopped" % settings.browser_agent_timeout_s
        except BaseException:
            # Ctrl-C or any other way out: the agent runs in its own session, so stop it here
            # or it keeps driving the browser with nobody watching.
            _stop(process)
            raise
    except OSError as exc:
        out, err = "", ""
        run.problem = "claude could not be started: %s" % exc
    finally:
        if secrets is not None:
            shutil.rmtree(str(secrets.parent), ignore_errors=True)
    run.seconds = round(time.monotonic() - started, 1)
    (workdir / "transcript.jsonl").write_text(out or "", encoding="utf-8")
    if err:
        (workdir / "claude.err").write_text(err, encoding="utf-8")
    events = _events(out or "")
    steps = _steps(events)
    if steps:
        (workdir / "steps.txt").write_text("\n".join(steps) + "\n", encoding="utf-8")
    outer = next((event for event in reversed(events) if event.get("type") == "result"), {})
    if isinstance(outer, dict):
        run.cost_usd = outer.get("total_cost_usd")
        run.turns = outer.get("num_turns")
        if outer.get("is_error") and not run.problem:
            run.problem = "claude stopped: %s" % _stop_reason(outer)
        run.report = _extract_json(str(outer.get("result") or ""))
    if run.report is None and not run.problem:
        run.problem = "its reply held no JSON report"
    return run


# ---------------------------------------------------------------------------
# Company-site applications
# ---------------------------------------------------------------------------


def _flat(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def quote_on_page(driver: Any, quote: str) -> bool:
    """Whether the quoted confirmation is on any open tab; the current tab stays current."""
    from .external import _page_text

    wanted = _flat(quote)
    if len(wanted) < MIN_QUOTE_CHARS:
        return False
    try:
        home = driver.current_window_handle
        handles = [home] + [handle for handle in driver.window_handles if handle != home]
    except Exception:
        return False
    found = False
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            if wanted in _flat(_page_text(driver)):
                found = True
                break
        except Exception:
            continue
    try:
        driver.switch_to.window(home)
    except Exception:
        pass
    return found


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [" ".join(str(item).split()) for item in value if str(item).strip()]


def to_result(driver: Any, run: AgentRun, previous: Any, dry_run: bool) -> Any:
    """The agent's report as an ExternalResult; a submit counts only with its proof on the page."""
    from .external import DRY_RUN, GONE

    report = run.report or {}
    status = str(report.get("status", "")).strip().lower()
    why = " ".join(str(report.get("why", "")).split())
    missing = _strings(report.get("missing"))
    filled = list(previous.filled) + [item for item in _strings(report.get("filled")) if item not in previous.filled]
    result = replace(previous, filled=filled, missing=missing)
    if run.report is None:
        result.status = ApplyStatus.ERROR
        result.detail = "the browser agent did not report (%s); check the site before trying again: %s" % (
            run.problem, run.workdir)
    elif status == "submitted":
        quote = " ".join(str(report.get("confirmation", "")).split())
        if quote_on_page(driver, quote):
            result.status = ApplyStatus.APPLIED_EXTERNAL
            result.detail = "submitted by the browser agent; the site says: %s" % quote
        else:
            result.status = ApplyStatus.ERROR
            result.detail = "Submit was clicked by the browser agent but its confirmation is not on the page (%s)" % (
                quote or why or "no quote")
    elif status == "ready" and dry_run:
        result.status = DRY_RUN
        result.detail = "dry run: the browser agent filled the form and stopped before Submit (%s)" % why
    elif status == "gone":
        result.status = GONE
        result.detail = "the posting is gone (browser agent: %s)" % why
    elif status == "needs_you" and missing:
        result.status = ApplyStatus.EXTERNAL_MANUAL
        result.detail = "needs you for: %s (browser agent: %s)" % ("; ".join(missing), why)
    else:
        result.status = ApplyStatus.EXTERNAL_MANUAL
        result.detail = "the browser agent stopped (%s): %s" % (status or "no status", why or run.problem)
    return result


def _keep_written(settings: Settings, job: JobPosting, report: Dict[str, Any]) -> None:
    from common import assist
    from common.resume import tailored_dir

    written = [item for item in report.get("written") or [] if isinstance(item, dict) and item.get("answer")]
    if not written:
        return
    folder = tailored_dir(settings, job)
    kept = folder / "answers.md"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with kept.open("a", encoding="utf-8") as handle:
            for item in written:
                question = " ".join(str(item.get("question", "")).split())
                answer = str(item.get("answer", "")).strip()
                handle.write("## %s\n\n%s\n\n" % (question, answer))
                assist.record_change(settings, assist.Change(
                    file=str(kept), item=question, value=answer,
                    source="browser agent (resume and posting)", evidence="", kind="written"))
    except OSError as exc:
        logger.warning("Could not keep the agent's long answers in %s: %s", kept, exc)


def _keep_account(settings: Settings, url: str, email: str, report: Dict[str, Any]) -> None:
    from .accounts import has_account, record_account

    host = urlparse(url).netloc
    account = str(report.get("account", "")).strip().lower()
    if not host or account not in ("created", "signed_in"):
        return
    if account == "signed_in" and has_account(settings, host):
        return
    what = "created by the browser agent" if account == "created" else "signed in by the browser agent"
    record_account(settings, host, email, what)


def _write_record(run: AgentRun, job: JobPosting, url: str, result: Any) -> None:
    record = {
        "job": {"title": job.title, "company": job.company, "naukri": job.url},
        "site": url,
        "status": result.status,
        "detail": result.detail,
        "report": run.report,
        "problem": run.problem,
        "seconds": run.seconds,
        "cost_usd": run.cost_usd,
        "turns": run.turns,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        (run.workdir / "report.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s: %s", run.workdir / "report.json", exc)


def finish_application(
    driver: Any,
    job: JobPosting,
    profile: Profile,
    settings: Settings,
    resume_pdf: Optional[Path],
    dry_run: bool,
    previous: Any,
) -> Any:
    """Hand the open application page to the agent and turn its report into an ExternalResult."""
    from .accounts import account_email
    from .external import _current_url

    global _started
    _started += 1
    url = _current_url(driver) or previous.url
    label = "%s - %s" % (job.company or "Company", job.title or "Role")
    workdir = workdir_for(settings, label)
    resume_copy = workdir / resume_pdf.name if resume_pdf is not None and Path(resume_pdf).is_file() else None
    email = account_email(settings)
    prompt = application_prompt(
        job, url, facts_text(profile, settings), email,
        resume_copy.resolve() if resume_copy is not None else None, dry_run, previous.detail,
        has_password=bool(settings.company_site_password))
    logger.info("      browser agent: Claude Code takes over %s (task %d of %d)", url, _started,
                settings.browser_agent_limit)
    run = run_agent(driver, settings, prompt, workdir, (Path(resume_pdf),) if resume_copy is not None else ())
    result = to_result(driver, run, previous, dry_run)
    if run.report:
        _keep_written(settings, job, run.report)
        _keep_account(settings, url, email, run.report)
    _write_record(run, job, url, result)
    logger.info(
        "      browser agent: %s in %.0fs%s (%s)", result.status, run.seconds,
        "" if run.cost_usd is None else ", $%.2f" % run.cost_usd, result.detail[:300])
    return result


def take_over(
    driver: Any,
    job: JobPosting,
    profile: Profile,
    settings: Settings,
    resume_pdf: Optional[Path],
    dry_run: bool,
    result: Any,
) -> Any:
    """The scripted result, or the agent's when the scripted filler stopped short."""
    if not should_take_over(settings, result):
        return result
    return finish_application(driver, job, profile, settings, resume_pdf, dry_run, result)


def records_for(settings: Settings, day: str) -> List[Dict[str, Any]]:
    """The day's agent tasks, oldest first, from user/reports/<day>/agent/*/report.json."""
    folder = Path(settings.report_dir or paths.user("reports")) / day / "agent"
    records = []
    for path in sorted(folder.glob("*/report.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        record["folder"] = str(path.parent)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m sites_bot.browser_agent",
        description=(
            "Let Claude Code drive the bot's Chrome (through Playwright MCP) for one task: by default, "
            "finish the application at --url from your facts; with --task, anything you describe."
        ),
    )
    parser.add_argument("--url", required=True, help="the page to start on")
    parser.add_argument("--title", default="", help="job title, for the records and the tailored resume")
    parser.add_argument("--company", default="", help="company name, for the records and the tailored resume")
    parser.add_argument("--task", default="", help="a specific job for the agent instead of finishing the application")
    parser.add_argument("--dry-run", action="store_true", help="fill the application but never click its final Submit")
    parser.add_argument("--no-resume", action="store_true", help="do not hand the agent a resume PDF")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import browser, config, profile as profile_module, resume as resume_module
    from .accounts import account_email
    from common.browser import human_pause, safe_get
    from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging, keep_log
    from .external import GONE, ExternalResult, forget_company_site, record_company_site

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env, {"dry_run": True} if args.dry_run else {})
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    keep_log(settings, "browser-agent")
    job = JobPosting(
        job_id="agent-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"),
        url=args.url, title=args.title, company=args.company,
    )
    resume_pdf = None  # type: Optional[Path]
    if not args.no_resume:
        try:
            resume_pdf = resume_module.build_base_pdf(settings)
        except resume_module.ResumeError as exc:
            logger.warning("No resume PDF to hand over (%s)", exc)

    driver = browser.create_driver(settings)
    try:
        if not safe_get(driver, args.url):
            logger.error("Could not open %s", args.url)
            return EXIT_FAILED
        human_pause(1.5, 3.0)
        if args.task:
            workdir = workdir_for(settings, args.task[:60])
            files = (resume_pdf,) if resume_pdf is not None else ()
            prompt = task_prompt(args.task, args.url, facts_text(profile, settings), account_email(settings),
                                 tuple((workdir / path.name).resolve() for path in files),
                                 has_password=bool(settings.company_site_password))
            run = run_agent(driver, settings, prompt, workdir, files)
            print(json.dumps(run.report or {"status": "failed", "why": run.problem}, indent=1, ensure_ascii=False))
            logger.info("Agent folder: %s (%.0fs)", workdir, run.seconds)
            return EXIT_OK if run.report and run.report.get("status") == "done" else EXIT_FAILED
        start = ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url=args.url, detail="opened by hand for the agent",
                               resume=str(resume_pdf or ""))
        result = finish_application(driver, job, profile, settings, resume_pdf, args.dry_run, start)
    finally:
        driver.quit()

    logger.info("Outcome: %s - %s", result.status, result.detail)
    if result.status == ApplyStatus.APPLIED_EXTERNAL or result.status == GONE:
        forget_company_site(settings, job)
        return EXIT_OK if result.status == ApplyStatus.APPLIED_EXTERNAL else EXIT_FAILED
    if result.status in (ApplyStatus.EXTERNAL_MANUAL, ApplyStatus.ERROR):
        logger.info("Recorded in %s", record_company_site(settings, job, result))
    return EXIT_OK if args.dry_run and result.status != ApplyStatus.ERROR else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
