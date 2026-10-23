"""Ask the claude or kiro command line for a piece of writing, with web search on.

The morning pipeline uses this to write the day's study notes and the briefing
agents' files. The CLI only gets web tools; it answers on stdout and the pipeline
checks the text before writing any file, so a bad answer never lands on disk.

    PIPELINE_AI_CLI=both|claude|kiro   (default: both; the briefing agents then ask claude
                                        and kiro and merge the two answers, see team())
    PIPELINE_AI_TIMEOUT_S=1800    (seconds one answer may take; web research can be slow)
"""

import logging
import os
import re
import shutil
import signal
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

TIMEOUT_S = int(os.getenv("PIPELINE_AI_TIMEOUT_S") or 1800)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class AIError(RuntimeError):
    pass


def chosen_cli(wanted: Optional[str] = None) -> str:
    """The CLI to use: the one asked for, else claude, else kiro-cli."""
    wanted = (wanted or os.getenv("PIPELINE_AI_CLI") or "").strip().lower()
    if wanted == "both":
        wanted = ""
    if wanted in ("kiro", "kiro-cli"):
        return "kiro" if shutil.which("kiro-cli") else ""
    if wanted == "claude" or not wanted:
        if shutil.which("claude"):
            return "claude"
        if not wanted and shutil.which("kiro-cli"):
            return "kiro"
    return ""


def team(wanted: Optional[str] = None) -> List[str]:
    """The CLIs that research together: every installed one for 'both' (the default), else the one asked for."""
    wanted = (wanted or os.getenv("PIPELINE_AI_CLI") or "both").strip().lower()
    if wanted == "both":
        return [cli for cli, binary in (("claude", "claude"), ("kiro", "kiro-cli")) if shutil.which(binary)]
    chosen = chosen_cli(wanted)
    return [chosen] if chosen else []


def command_for(cli: str, prompt: str, web: bool = True) -> List[str]:
    """The command line for one answer; web=False gives the CLI no tools at all."""
    if cli == "kiro":
        trust = "--trust-tools=web_search,web_fetch" if web else "--trust-tools="
        return ["kiro-cli", "chat", "--no-interactive", trust, prompt]
    # Web research only (or nothing): no shell, no file edits.
    tools = ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch"] if web else ["--tools", ""]
    command = ["claude", "-p", prompt] + tools + [
        "--permission-mode", "dontAsk",
        # None of the user's MCP servers: they are slow to start and can outlive the answer.
        "--strict-mcp-config",
        "--output-format", "text",
        "--no-session-persistence",
    ]
    model = os.getenv("PIPELINE_AI_MODEL", "")
    if model:
        command += ["--model", model]
    return command


def ask(prompt: str, cli: Optional[str] = None, timeout_s: int = TIMEOUT_S, web: bool = True) -> str:
    """The CLI's answer as plain text; AIError when there is no CLI or it failed."""
    chosen = chosen_cli(cli)
    if not chosen:
        raise AIError("neither claude nor kiro-cli is on PATH (or PIPELINE_AI_CLI names a missing one)")
    logger.info("Asking %s (this can take a few minutes)...", chosen)
    try:
        # Its own process group, so a timeout kills the CLI and everything it started.
        proc = subprocess.Popen(command_for(chosen, prompt, web), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        raise AIError("%s could not be started: %s" % (chosen, exc))
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        raise AIError("%s ran past %d seconds" % (chosen, timeout_s))
    out = _ANSI.sub("", stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise AIError("%s exited %d: %s" % (chosen, proc.returncode, (stderr or out or "no output")[-400:]))
    return out


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("The AI CLI's output pipes stayed open after it was killed.")


def markdown_from(answer: str, first_heading: str = "#") -> str:
    """The answer from its first markdown heading on, without a wrapping ``` fence."""
    text = answer.strip()
    fenced = re.match(r"^```(?:markdown|md)?\n(.*)\n```$", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = re.search(r"^%s" % re.escape(first_heading), text, re.M)
    return (text[start.start():] if start else text).strip() + "\n"
