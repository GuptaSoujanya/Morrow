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
import sqlite3
import sys
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar

from common.models import ApplyStatus, Settings
from common.report import OUTCOMES, course_modules as plan_order

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
    env: Tuple[Tuple[str, str], ...] = ()

    @property
    def shown(self) -> str:
        """The command as you would type it in apply/."""
        args = list(self.argv)
        if args and args[0] == PYTHON:
            args[0] = "venv/bin/python"
        environment = [f"{name}={shlex.quote(value)}" for name, value in self.env]
        return " ".join([*environment, *(shlex.quote(a) for a in args)])


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
    # Two tabs can submit in the same second, including a request rejected by the
    # runner afterwards. Never overwrite the input an existing run is reading.
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, suffix=".txt",
                                     prefix=f"{dt.datetime.now():%Y-%m-%d_%H%M%S}-",
                                     encoding="utf-8", delete=False) as output:
        output.write(text.strip() + "\n")
        return Path(output.name)


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


T = TypeVar("T")

_EDITS = threading.Lock()


def _serialised(edit: Callable[..., T]) -> Callable[..., T]:
    """One edit at a time: each handler thread reads, changes one line, and writes back."""

    def locked(*args: Any, **kwargs: Any) -> T:
        with _EDITS:
            return edit(*args, **kwargs)

    locked.__doc__ = edit.__doc__
    locked.__name__ = edit.__name__
    return locked


def _replace(path: Path, text: str) -> None:
    """Write a whole file at once, so a bot reading it never sees it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@_serialised
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
    _replace(path, "".join(lines))


@_serialised
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
    _replace(path, "".join(lines))


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
    if path is None:
        from common import learning_memory
        return {key for key, value in learning_memory.transact(APPLY, studied=STUDIED)["course"].items() if value["done"]}
    try:
        data = json.loads(_read(path or STUDIED) or "[]")
    except ValueError:
        return set()
    return {p for p in data if isinstance(p, str)} if isinstance(data, list) else set()


@_serialised
def mark_studied(module_path: str, done: bool = True, path: Optional[Path] = None) -> Set[str]:
    if path is None:
        from common import learning_memory
        title = next((m.title for m in course_modules(COURSE) if m.path == module_path), module_path)
        data = learning_memory.set_course(APPLY, module_path, done, title, studied=STUDIED)
        return {key for key, value in data["course"].items() if value["done"]}
    path = path or STUDIED
    read = studied(path)
    if done:
        read.add(module_path)
    else:
        read.discard(module_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, json.dumps(sorted(read), indent=2) + "\n")
    return read


def first_name(path: Path = PROFILE) -> str:
    for line in _read(path).splitlines():
        if line.startswith("first_name:"):
            return line.partition(":")[2].partition("#")[0].strip().strip("\"'")
    return ""


def greeting(now: Optional[dt.datetime] = None) -> str:
    hour = (now or dt.datetime.now()).hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"



# --- the overview -------------------------------------------------------------

#: How the Overview groups ledger outcomes; anything not listed (refusals, limits, sign-outs, errors) failed.
_KINDS = {
    ApplyStatus.APPLIED: "sent",
    ApplyStatus.APPLIED_PLATFORM: "sent",
    ApplyStatus.APPLIED_EXTERNAL: "sent",
    ApplyStatus.EXTERNAL_MANUAL: "waiting",
    ApplyStatus.ABSTAINED: "waiting",
    ApplyStatus.ALREADY_APPLIED: "skipped",
    ApplyStatus.EXTERNAL_SKIPPED: "skipped",
    ApplyStatus.NO_APPLY_BUTTON: "skipped",
}
_CHANNELS = {
    ApplyStatus.APPLIED: "naukri",
    ApplyStatus.APPLIED_PLATFORM: "boards",
    ApplyStatus.APPLIED_EXTERNAL: "company",
}
#: Naukri's own job sources carry no board prefix ("search:AI Engineer", "recommended:profile").
_NAUKRI_SOURCES = {"search", "recommended"}
_RUN_FIELDS = (
    "collected", "too_old", "not_ranked", "ranked", "below_score", "already_applied", "held_back",
    "eligible", "attempted", "applied", "applied_external", "external_manual", "skipped_abstained", "errors",
)


def database() -> Path:
    """The bots' ledger: DB_PATH from .env, else the bots' own default."""
    path = Path(_setting("DB_PATH") or Settings.db_path).expanduser()
    return path if path.is_absolute() else APPLY / path


def _setting_number(key: str, default: float) -> float:
    try:
        return float(_setting(key))
    except ValueError:
        return default


def _query(path: Path, sql: str) -> List[Dict[str, Any]]:
    """Rows from the ledger, opened read-only so the site never changes it while a bot writes."""
    if not path.is_file():
        return []
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql)]
    finally:
        connection.close()


def _moment(stamp: Any) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(stamp)).astimezone()
    except ValueError:
        return None


def board_name(key: str) -> str:
    return "Naukri" if key == "naukri" else key.capitalize()


def _board_of_job(job_id: Any) -> str:
    """Job boards prefix their ids ("hirist:1677523"); Naukri's ids are bare numbers."""
    text = str(job_id or "")
    return text.split(":", 1)[0] if ":" in text else "naukri"


def source_parts(source: str) -> Tuple[str, str]:
    """('hirist', 'AI Engineer') for 'hirist:search:AI Engineer': the board and the search that found the job."""
    parts = (source or "").split(":")
    board = "naukri" if len(parts) < 2 or parts[0] in _NAUKRI_SOURCES else parts.pop(0)
    kind, rest = parts[0], ":".join(parts[1:]).strip()
    if kind == "search" and rest:
        return board, rest
    if kind == "recommended":
        return board, f"Recommended: {rest.replace('_', ' ')}".rstrip(": ")
    return board, f"{board_name(board)} {kind.replace('_', ' ')}".strip()


def _funnel(totals: Counter, runs: int) -> Dict[str, Any]:
    """One group of real runs: how many jobs each step kept, and why the rest dropped out."""
    def counts(pairs: Tuple[Tuple[str, int], ...]) -> List[Dict[str, Any]]:
        return [{"label": label, "count": count} for label, count in pairs if count]

    return {
        "runs": runs,
        "steps": [
            {"key": "found", "label": "Found", "count": totals["collected"]},
            {"key": "scored", "label": "Scored", "count": totals["ranked"]},
            {"key": "eligible", "label": "Eligible", "count": totals["eligible"]},
            {"key": "tried", "label": "Tried", "count": totals["attempted"]},
            {"key": "sent", "label": "Sent", "count": totals["applied"] + totals["applied_external"]},
        ],
        "dropped": counts((
            ("Too old", totals["too_old"]),
            ("Not scored", totals["not_ranked"]),
            ("Under the minimum score", totals["below_score"]),
            ("Applied before", totals["already_applied"]),
            ("Held for your answers", totals["held_back"]),
        )),
        "unsent": counts((
            ("Left for you on a company site", totals["external_manual"]),
            ("A question had no answer", totals["skipped_abstained"]),
            ("Errors", totals["errors"]),
        )),
    }


def overview(
    days: int = 14,
    today: Optional[dt.date] = None,
    now: Optional[dt.datetime] = None,
    db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Everything the Overview draws, for the last `days` days counting today (0 means since the first run)."""
    if days < 0:
        raise ValueError("days can't be negative")
    today = today or dt.date.today()
    now = now or dt.datetime.now(dt.timezone.utc)
    db = db or database()
    min_score = _setting_number("MIN_SCORE", Settings.min_score)

    applications = _query(db, "SELECT job_id, status, quota_consumed, at FROM applications ORDER BY at, id")
    seen = _query(db, "SELECT source, first_seen, score FROM jobs_seen")
    runs = _query(db, "SELECT id, started_at, finished_at, summary_json FROM runs ORDER BY started_at, id")
    for rows, column in ((applications, "at"), (seen, "first_seen"), (runs, "started_at")):
        for row in rows:
            moment = _moment(row[column])
            row["moment"], row["day"] = moment, (moment.date() if moment else None)

    known = [row["day"] for row in applications + seen + runs if row["day"]]
    first = min(known) if known else None
    start = min(first or today, today) if days == 0 else today - dt.timedelta(days=days - 1)
    # The period before is compared only when the ledger covers all of it.
    before = start - dt.timedelta(days=days) if days and first and first <= start - dt.timedelta(days=days) else None

    def within(day: Optional[dt.date]) -> bool:
        return day is not None and start <= day <= today

    def earlier(day: Optional[dt.date]) -> bool:
        return before is not None and day is not None and before <= day < start

    daily = {
        start + dt.timedelta(days=n): {"day": (start + dt.timedelta(days=n)).isoformat(), "naukri": 0, "boards": 0,
                                       "company": 0, "waiting": 0, "skipped": 0, "failed": 0}
        for n in range((today - start).days + 1)
    }
    outcomes, sent_by_board, sent = Counter(), Counter(), Counter()
    for row in applications:
        kind = _KINDS.get(row["status"], "failed")
        if within(row["day"]):
            daily[row["day"]][_CHANNELS.get(row["status"], kind)] += 1
            outcomes[row["status"]] += 1
            if kind == "sent":
                sent[_CHANNELS[row["status"]]] += 1
                sent_by_board[_board_of_job(row["job_id"])] += 1
        elif earlier(row["day"]) and kind == "sent":
            sent["before"] += 1

    bins, found = [0] * 20, Counter()
    boards: Dict[str, Counter] = {}
    searches: Dict[str, Dict[str, Any]] = {}
    for row in seen:
        if earlier(row["day"]):
            found["before"] += 1
        if not within(row["day"]):
            continue
        board, search = source_parts(row["source"])
        entry = searches.setdefault(search, {"tally": Counter(), "boards": set()})
        entry["boards"].add(board)
        score = row["score"]
        for tally in (found, boards.setdefault(board, Counter()), entry["tally"]):
            tally["found"] += 1
            if score is not None:
                tally["scored"] += 1
                tally["points"] += score
                tally["over"] += score >= min_score
        if score is None:
            found["unscored"] += 1
        else:
            bins[min(19, max(0, int(score // 5)))] += 1

    def averaged(tally: Counter) -> Dict[str, Any]:
        return {
            "found": tally["found"],
            "over": tally["over"],
            "average": round(tally["points"] / tally["scored"], 1) if tally["scored"] else None,
        }

    funnels = {"naukri": Counter(), "boards": Counter()}
    counted_runs = Counter()
    left_out = Counter()
    recent = []
    for row in runs:
        if not within(row["day"]):
            continue
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except ValueError:
            summary = {}
        finished = _moment(row["finished_at"])
        recent.append({
            "id": row["id"],
            "day": row["day"].isoformat(),
            "time": row["moment"].strftime("%H:%M"),
            "bot": board_name(summary.get("board") or "naukri"),
            "practice": bool(summary.get("dry_run")),
            "finished": finished is not None,
            "seconds": round((finished - row["moment"]).total_seconds()) if finished else None,
            "found": summary.get("collected"),
            "eligible": summary.get("eligible"),
            "tried": summary.get("attempted"),
            "sent": (summary.get("applied") or 0) + (summary.get("applied_external") or 0) if summary else None,
        })
        if finished is None:
            left_out["unfinished"] += 1
        elif summary.get("dry_run"):
            left_out["practice"] += 1
        elif "eligible" not in summary:
            left_out["older"] += 1
        else:
            group = "boards" if summary.get("board") else "naukri"
            counted_runs[group] += 1
            funnels[group].update({key: int(summary.get(key) or 0) for key in _RUN_FIELDS})

    cutoff = now - dt.timedelta(hours=24)
    return {
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "first": first.isoformat() if first else None,
        "min_score": min_score,
        "daily": list(daily.values()),
        "sent": {
            "total": sent["naukri"] + sent["boards"] + sent["company"],
            "naukri": sent["naukri"],
            "boards": sent["boards"],
            "company": sent["company"],
            "before": sent["before"] if before else None,
        },
        "found": {
            "total": found["found"],
            "over": found["over"],
            "unscored": found["unscored"],
            "before": found["before"] if before else None,
        },
        "quota": {
            "used": sum(1 for row in applications if row["quota_consumed"] and row["moment"] and row["moment"] >= cutoff),
            "limit": int(_setting_number("DAILY_QUOTA", Settings.daily_quota)),
        },
        "attempts": sum(outcomes.values()),
        "outcomes": [
            {"status": status, "label": OUTCOMES.get(status, status.replace("_", " ").capitalize()),
             "kind": _KINDS.get(status, "failed"), "count": count}
            for status, count in outcomes.most_common()
        ],
        # Five-point buckets, from inclusive and to exclusive except the last, which ends at 100.
        "scores": [{"from": n * 5, "to": n * 5 + 5, "count": count} for n, count in enumerate(bins)],
        "boards": sorted(
            ({"key": key, "name": board_name(key), "sent": sent_by_board[key], **averaged(boards.get(key, Counter()))}
             for key in set(boards) | set(sent_by_board)),
            key=lambda b: (-b["found"], -b["sent"], b["name"]),
        ),
        "searches": sorted(
            ({"search": search, "boards": sorted(board_name(b) for b in entry["boards"]), **averaged(entry["tally"])}
             for search, entry in searches.items()),
            key=lambda s: (-s["over"], -s["found"], s["search"]),
        ),
        "funnel": {
            "naukri": _funnel(funnels["naukri"], counted_runs["naukri"]),
            "boards": _funnel(funnels["boards"], counted_runs["boards"]),
            "all": _funnel(funnels["naukri"] + funnels["boards"], counted_runs["naukri"] + counted_runs["boards"]),
            "left_out": {"practice": left_out["practice"], "older": left_out["older"], "unfinished": left_out["unfinished"]},
        },
        "runs": recent[::-1][:12],
    }
