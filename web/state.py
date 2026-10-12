"""What the control site reads, runs and writes, kept apart from the server so it can be tested.

Every command is the same one you would type in apply/ by hand; the site only
collects the options, shows the command, and streams its output.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from common.report import course_modules as plan_order

APPLY = Path(__file__).resolve().parent.parent
COURSE = APPLY / "course"
PYTHON = sys.executable
ANSWERS = APPLY / "data" / "inputs" / "answers.txt"
PROFILE = APPLY / "data" / "inputs" / "profile.yaml"
COMPANY_SITES = APPLY / "data" / "inputs" / "company_sites.md"
RESUMES = APPLY / "data" / "resume"
REPORTS = APPLY / "data" / "reports"
LOGS = APPLY / "data" / "logs"
STUDIED = REPORTS / "studied.json"
#: Pages that only work in a browser: the news page fetches its headlines with JavaScript.
BROWSER_ONLY = {"news.md"}
START_HERE = "Start here"


@dataclass(frozen=True)
class Command:
    label: str
    argv: Tuple[str, ...]

    @property
    def shown(self) -> str:
        """The command as you would type it in apply/."""
        args = list(self.argv)
        if args and args[0] == PYTHON:
            args[0] = "venv/bin/python"
        return " ".join(shlex.quote(a) for a in args)


def py(label: str, *args: str) -> Command:
    return Command(label, (PYTHON, *args))


def script(label: str, name: str) -> Command:
    return Command(label, ("/bin/zsh", f"scripts/{name}"))


# --- commands -----------------------------------------------------------------


def naukri_command(
    *,
    dry_run: bool = False,
    headless: bool = False,
    limit: Optional[int] = None,
    answer_mode: str = "",
    early_access: bool = False,
    early_access_only: bool = False,
    keywords: str = "",
    location: str = "",
) -> Command:
    args = ["-m", "naukri_bot"]
    if early_access_only:
        args.append("--early-access-only")
    elif early_access:
        args.append("--early-access")
    if dry_run:
        args.append("--dry-run")
    if headless:
        args.append("--headless")
    if limit is not None:
        if limit < 1:
            raise ValueError("the limit has to be 1 or more")
        args += ["--limit", str(limit)]
    if answer_mode:
        args += ["--answer-mode", answer_mode]
    if keywords.strip():
        args += ["--keywords", keywords.strip()]
    if location.strip():
        args += ["--location", location.strip()]
    if early_access_only:
        label = "Share Early Access interest"
    elif dry_run:
        label = "Practice run on Naukri"
    else:
        label = "Apply on Naukri"
    return py(label, *args)


def assist_command(*, dry_run: bool = False) -> Command:
    args = ["-m", "common.assist"] + (["--dry-run"] if dry_run else [])
    return py("Preview waiting company forms" if dry_run else "Fill waiting company forms", *args)


def external_command(
    *,
    url: str,
    title: str = "",
    company: str = "",
    dry_run: bool = False,
    no_tailor: bool = False,
    headless: bool = False,
) -> Command:
    url = url.strip()
    if not url:
        raise ValueError("paste the application page link")
    if not url.startswith(("http://", "https://")):
        raise ValueError("the link has to start with http:// or https://")
    args = ["-m", "sites_bot.external", "--url", url]
    if title.strip():
        args += ["--title", title.strip()]
    if company.strip():
        args += ["--company", company.strip()]
    for flag, on in (("--dry-run", dry_run), ("--no-tailor", no_tailor), ("--headless", headless)):
        if on:
            args.append(flag)
    return py(f"Apply on {company.strip() or 'company site'}", *args)


def profile_command(*, dry_run: bool = False, if_due: bool = False, headless: bool = False) -> Command:
    args = ["-m", "naukri_bot.update_profile"]
    for flag, on in (("--dry-run", dry_run), ("--if-due", if_due), ("--headless", headless)):
        if on:
            args.append(flag)
    return py("Check the profile editor" if dry_run else "Refresh Naukri profile", *args)


LINKEDIN_MODES = {
    "dry-run": "Draft a LinkedIn post",
    "propose": "Save a LinkedIn draft",
    "post": "Publish on LinkedIn",
    "if-due": "Today's LinkedIn step",
}


def linkedin_command(*, mode: str, draft: str = "", headless: bool = False) -> Command:
    if mode not in LINKEDIN_MODES:
        raise ValueError(f"unknown LinkedIn mode {mode!r}")
    args = ["-m", "linkedin_bot", f"--{mode}"]
    if mode == "post" and draft.strip():
        args.append(draft.strip())
    if headless:
        args.append("--headless")
    return py(LINKEDIN_MODES[mode], *args)


def resume_command(
    *, jd_file: str, title: str = "", company: str = "", headless: bool = False, must_exist: bool = True
) -> Command:
    jd_file = jd_file.strip()
    if not jd_file:
        raise ValueError("paste the job description, or give the path of a file with it")
    path = Path(jd_file).expanduser()
    if not path.is_absolute():
        path = APPLY / path
    if must_exist and not path.is_file():
        raise ValueError(f"no file at {jd_file}")
    args = ["-m", "common.resume", "--tailor", str(path)]
    if title.strip():
        args += ["--title", title.strip()]
    if company.strip():
        args += ["--company", company.strip()]
    if headless:
        args.append("--headless")
    return py(f"Tailor resume for {company.strip() or 'this job'}", *args)


def parse_day(text: str) -> dt.date:
    text = text.strip()
    if not text:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError("write the date as YYYY-MM-DD") from None


def report_command(*, day: str = "") -> Command:
    date = parse_day(day)
    args = ["-m", "common.report"]
    if date != dt.date.today():
        args += ["--date", date.isoformat()]
    return py(f"Build the report for {date.isoformat()}", *args)


def save_job_description(text: str) -> Path:
    """Keep a pasted job description as a file, since the resume tailor reads one."""
    folder = LOGS / "jd"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


# --- what is waiting for you ---------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def unanswered_questions(path: Path = ANSWERS) -> List[Tuple[int, List[str]]]:
    """(line of the empty ``A:``, the questions it answers) for each question waiting for you."""
    waiting = []  # type: List[Tuple[int, List[str]]]
    questions = []  # type: List[str]
    for number, line in enumerate(_read(path).splitlines(), 1):
        text = line.strip()
        if text.startswith("Q:"):
            questions.append(text[2:].strip())
        elif text.startswith("A:"):
            if not text[2:].strip():
                waiting.append((number, questions))
            questions = []
    return waiting


_BLANK_VALUES = {"", "null", "~", '""', "''"}


def blank_facts(path: Path = PROFILE) -> List[Tuple[int, str]]:
    """(line, key) for each FILL fact in profile.yaml that is still empty."""
    blank = []  # type: List[Tuple[int, str]]
    for number, line in enumerate(_read(path).splitlines(), 1):
        body, _, comment = line.partition("#")
        if "FILL" not in comment or ":" not in body:
            continue
        key, _, value = body.partition(":")
        if key.strip() and value.strip() in _BLANK_VALUES:
            blank.append((number, key.strip()))
    return blank


def company_sites(path: Path = COMPANY_SITES) -> List[Dict[str, str]]:
    """Each company-site application that still needs you: its heading parts and its "- Key: value" lines."""
    entries = []  # type: List[Dict[str, str]]
    for line in _read(path).splitlines():
        if line.startswith("## "):
            parts = [p.strip() for p in line[3:].split("|")]
            if len(parts) > 2:
                entry = {"when": parts[0], "company": parts[1], "title": " · ".join(parts[2:])}
            else:
                entry = {"when": "", "company": "", "title": line[3:].strip()}
            entry["name"] = " · ".join(p for p in (entry["company"], entry["title"]) if p)
            entries.append(entry)
        elif entries and line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            entries[-1][key.strip().lower()] = value.strip()
    return entries


def waiting_company_sites(path: Path = COMPANY_SITES) -> List[str]:
    """'Company · Title' for each company-site application that still needs you."""
    return [entry["name"] for entry in company_sites(path)]


_FACT_LITERAL = re.compile(r"-?\d+(\.\d+)?|true|false", re.IGNORECASE)


def _check_line(lines: List[str], line: int, name: str) -> str:
    if not 1 <= line <= len(lines):
        raise ValueError(f"{name} changed since you opened it; reload and try again")
    return lines[line - 1]


def save_answer(line: int, answer: str, path: Path = ANSWERS) -> None:
    """Write your answer on the empty ``A:`` line the question is waiting on."""
    answer = " ".join(answer.split())
    if not answer:
        raise ValueError("write an answer first")
    lines = _read(path).splitlines(keepends=True)
    text = _check_line(lines, line, path.name)
    if not text.strip().startswith("A:") or text.strip()[2:].strip():
        raise ValueError(f"{path.name} changed since you opened it; reload and try again")
    indent = text[: len(text) - len(text.lstrip())]
    lines[line - 1] = f"{indent}A: {answer}\n"
    path.write_text("".join(lines), encoding="utf-8")


def save_fact(line: int, value: str, path: Path = PROFILE) -> None:
    """Fill one blank FILL fact in profile.yaml, keeping its comment."""
    value = " ".join(value.split())
    if not value:
        raise ValueError("write a value first")
    lines = _read(path).splitlines(keepends=True)
    text = _check_line(lines, line, path.name)
    if (line, text.partition(":")[0].strip()) not in blank_facts(path):
        raise ValueError(f"{path.name} changed since you opened it; reload and try again")
    body, _, comment = text.rstrip("\n").partition("#")
    key = body.partition(":")[0]
    shown = value.lower() if _FACT_LITERAL.fullmatch(value) else json.dumps(value, ensure_ascii=False)
    filled = f"{key}: {shown}"
    lines[line - 1] = f"{filled.ljust(len(body) - 1)} #{comment}\n"
    path.write_text("".join(lines), encoding="utf-8")


def report_path(day: Optional[dt.date] = None) -> Path:
    return REPORTS / (day or dt.date.today()).isoformat() / "report.md"


def report_days() -> List[str]:
    if not REPORTS.is_dir():
        return []
    return sorted((p.parent.name for p in REPORTS.glob("*/report.md")), reverse=True)


def report_html(day: dt.date) -> str:
    """The day's report as HTML, its own links pointing at the files saved next to it."""
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    tokens = md.parse(_read(report_path(day)))
    base = f"/reports/{day.isoformat()}/"
    for token in tokens:
        for child in [token, *(token.children or [])]:
            for attr in ("href", "src"):
                target = child.attrGet(attr)
                if not isinstance(target, str):
                    continue
                if "://" in target or target.startswith(("mailto:", "#", "/")):
                    if child.type == "link_open" and "://" in target:
                        child.attrSet("target", "_blank")
                        child.attrSet("rel", "noopener")
                else:
                    child.attrSet(attr, base + target)
    return md.renderer.render(tokens, md.options, {})


# --- the course -------------------------------------------------------------------

_SIDEBAR_TRACK = re.compile(r"^\s*-\s*\*\*(.+?)\*\*\s*$")
_SIDEBAR_LINK = re.compile(r"^(\s*)-\s*\[([^\]]+)\]\(([^)]+\.md)\)")


@dataclass(frozen=True)
class Module:
    track: str
    title: str
    path: str
    file: Path

    @property
    def route(self) -> str:
        """Where the course site shows this page: README.md is its folder's page."""
        route = self.path[: -len(".md")] if self.path.endswith(".md") else self.path
        return route[: -len("README")] if route.endswith("README") else route


def course_modules(course: Path = COURSE) -> List[Module]:
    """Every page of the course sidebar that reads well here, in sidebar order."""
    modules = []
    track = START_HERE
    for line in _read(course / "_sidebar.md").splitlines():
        heading = _SIDEBAR_TRACK.match(line)
        if heading:
            track = heading.group(1).strip()
            continue
        link = _SIDEBAR_LINK.match(line)
        if not link:
            continue
        indent, title, path = link.groups()
        file = (course / path).resolve()
        if path in BROWSER_ONLY or not file.is_file():
            continue
        modules.append(Module(track if indent else START_HERE, title.strip(), path, file))
    return modules


@dataclass(frozen=True)
class PlanDay:
    module: Module
    number: int
    total: int
    revising: bool
    tomorrow: Module


def _setting(key: str) -> str:
    """A value from the environment, else from apply/.env, the way the bots read it."""
    if os.environ.get(key):
        return os.environ[key]
    value = ""
    for line in _read(APPLY / ".env").splitlines():
        if line.startswith(key + "="):
            value = line.partition("=")[2].split(" #")[0].strip().strip("\"'")
    return value


def plan_start(today: dt.date) -> dt.date:
    """The first day of the study plan, as the daily report counts it."""
    try:
        saved = json.loads(_read(REPORTS / "learning.json") or "{}").get("start")
    except (ValueError, AttributeError):
        saved = None
    for text in (_setting("COURSE_START_DATE"), saved):
        try:
            return dt.date.fromisoformat(str(text))
        except ValueError:
            continue
    return today


def todays_module(
    modules: List[Module], today: Optional[dt.date] = None, course: Path = COURSE
) -> Optional[PlanDay]:
    """The module the daily report sets for today: one a day, in the 8-week plan's order."""
    today = today or dt.date.today()
    by_path = {m.path: m for m in modules}
    plan = [by_path[path] for _, path in plan_order(course) if path in by_path]
    index = (today - plan_start(today)).days
    if not plan or index < 0:
        return None
    return PlanDay(
        module=plan[index % len(plan)],
        number=index % len(plan) + 1,
        total=len(plan),
        revising=index >= len(plan),
        tomorrow=plan[(index + 1) % len(plan)],
    )


def studied(path: Optional[Path] = None) -> Set[str]:
    """Course paths you marked as read."""
    try:
        data = json.loads(_read(path or STUDIED) or "[]")
    except ValueError:
        return set()
    return {p for p in data if isinstance(p, str)} if isinstance(data, list) else set()


def mark_studied(module_path: str, done: bool = True, path: Optional[Path] = None) -> Set[str]:
    path = path or STUDIED
    read = studied(path)
    if done:
        read.add(module_path)
    else:
        read.discard(module_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(read), indent=2) + "\n", encoding="utf-8")
    return read


def first_name(path: Path = PROFILE) -> str:
    for line in _read(path).splitlines():
        if line.startswith("first_name:"):
            return line.partition(":")[2].partition("#")[0].strip().strip("\"'")
    return ""


def greeting(now: Optional[dt.datetime] = None) -> str:
    hour = (now or dt.datetime.now()).hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

