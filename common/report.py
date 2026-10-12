"""One Markdown file a day: what the bots did, where you applied, what is left.

reports/<YYYY-MM-DD>/report.md is rebuilt from the records whenever a bot
finishes (the morning run, the profile updater, the LinkedIn poster), so it
always covers the whole day so far. `python3 -m common.report` rebuilds it
by hand. Every line comes from the ledger, the state files and the data folder;
nothing in it is written by a model.
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sites_bot import browser_agent, cold_email
from .models import ApplyStatus, Settings


logger = logging.getLogger(__name__)

REPORT_NAME = "report.md"
COURSE_PORT = 8000
#: The course README's 8-week plan: DSA, then system design, full stack, ML, behavioral.
COURSE_TRACK_ORDER = ("02-", "01-", "03-", "04-", "05-")
MAX_LISTED = 40

_OUTCOMES = {
    ApplyStatus.APPLIED: "Applied on Naukri",
    ApplyStatus.APPLIED_EXTERNAL: "Applied on the company site",
    ApplyStatus.APPLIED_PLATFORM: "Applied on another job board",
    ApplyStatus.EXTERNAL_MANUAL: "Company site, needs you",
    ApplyStatus.EXTERNAL_SKIPPED: "Company site, not tried",
    ApplyStatus.ALREADY_APPLIED: "Already applied earlier",
    ApplyStatus.ABSTAINED: "Skipped, a question had no answer",
    ApplyStatus.NO_APPLY_BUTTON: "No apply button",
    ApplyStatus.CHATBOT_TIMEOUT: "Naukri's question bot stalled",
    ApplyStatus.QUOTA_EXPIRED: "Naukri's daily limit reached",
    ApplyStatus.NAUKRI_REFUSED: "Naukri refused the click (its limit for the day)",
    ApplyStatus.SESSION_EXPIRED: "Signed out mid-run",
    ApplyStatus.ERROR: "Error",
}
_SENT = (ApplyStatus.APPLIED, ApplyStatus.APPLIED_EXTERNAL, ApplyStatus.APPLIED_PLATFORM)
_SIDEBAR_LINK = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+\.md)\)")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def funnel_text(record: Dict[str, Any]) -> str:
    """Where one run's collected jobs went, as one line. Empty for older runs."""
    if "eligible" not in record:
        return ""
    steps = [
        ("too old", record.get("too_old", 0)),
        ("not ranked (LLM_RANK_TOP_N)", record.get("not_ranked", 0)),
        ("scored under %g (MIN_SCORE)" % record.get("min_score", 0), record.get("below_score", 0)),
        ("applied before", record.get("already_applied", 0)),
        ("held back for your answers", record.get("held_back", 0)),
    ]
    dropped = ", ".join("%d %s" % (count, label) for label, count in steps if count)
    line = "collected %d" % record.get("collected", 0)
    if dropped:
        line += "; dropped %s" % dropped
    line += "; %d eligible, %d tried, %d applied" % (
        record.get("eligible", 0),
        record.get("attempted", 0),
        record.get("applied", 0) + record.get("applied_external", 0),
    )
    if record.get("applied", 0) >= record.get("target", 0) > 0:
        line += " (stopped at the target of %d)" % record["target"]
    return line


def _where(row: Dict[str, Any]) -> str:
    if row.get("status") == ApplyStatus.APPLIED:
        return "Naukri"
    if row.get("status") == ApplyStatus.APPLIED_PLATFORM:
        return str(row.get("job_id", "")).split(":", 1)[0].capitalize() or "Job board"
    return "Company site"


def _cell(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value if value is not None else "").split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _day_bounds(day: date) -> Tuple[str, str]:
    """The local calendar day as a [start, end) pair of UTC ISO strings, the ledger's format."""
    start = datetime.combine(day, dtime()).astimezone()
    end = datetime.combine(date.fromordinal(day.toordinal() + 1), dtime()).astimezone()
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def _local_clock(at: str) -> str:
    try:
        return datetime.fromisoformat(at).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "-"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _from_repo(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else _repo_root() / path


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


def _ledger_rows(settings: Settings, day: date) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Today's attempts and runs; nothing when the bot has never run (no database yet)."""
    if not settings.db_path or not Path(settings.db_path).exists():
        return [], []
    from .ledger import Ledger

    start, end = _day_bounds(day)
    ledger = Ledger(settings.db_path)
    try:
        return ledger.applications_between(start, end), ledger.runs_between(start, end)
    finally:
        ledger.close()


def _blank_questions(settings: Settings) -> List[str]:
    from .answers import AnswerBook, answers_file_path

    return AnswerBook(answers_file_path(settings)).blank_questions()


def _blank_facts(settings: Settings) -> List[str]:
    """Keys in the facts file still set to nothing, nested ones as parent.child."""
    try:
        import yaml

        data = yaml.safe_load(Path(settings.profile_path).read_text(encoding="utf-8")) or {}
    except Exception as exc:  # a broken facts file must not stop the report
        logger.debug("Could not read %s: %s", settings.profile_path, exc)
        return []
    blanks = []  # type: List[str]

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, "%s.%s" % (prefix, key) if prefix else str(key))
        elif node is None or (isinstance(node, str) and not node.strip()):
            blanks.append(prefix)

    walk(data, "")
    return blanks


def _disagreements(settings: Settings) -> List[Any]:
    from .answers import AnswerBook, answers_file_path
    from .assist import disagreements
    from .profile import load_profile

    try:
        return disagreements(load_profile(settings), AnswerBook(answers_file_path(settings)))
    except Exception as exc:  # the report must not fail on a broken facts file
        logger.debug("Could not compare answers.txt and profile.yaml: %s", exc)
        return []


def _untried_company_sites() -> int:
    from naukri_bot.cli import _EXTERNAL_JOBS_FILE, _parse_external_rows

    return len(_parse_external_rows(_EXTERNAL_JOBS_FILE))


def _tailored_today(settings: Settings, day: date) -> List[Dict[str, Any]]:
    root = Path(settings.resume_out_dir or "resume/out") / "tailored"
    made = []
    for record_path in sorted(root.glob("*/tailoring.json")):
        record = _read_json(record_path)
        if str(record.get("generated_at", ""))[:10] == day.isoformat():
            record["folder"] = str(record_path.parent)
            made.append(record)
    return made


def _profile_slots(settings: Settings, day: date, now: datetime) -> Tuple[List[str], Dict[str, Any]]:
    from naukri_bot.update_profile import SLOTS

    state = _read_json(Path(settings.profile_update_state_path))
    lines = []
    for slot in SLOTS:
        label = slot.strftime("%H:%M")
        entry = state.get("%s %s" % (day.isoformat(), label)) or {}
        if entry.get("done"):
            status = "headline refreshed"
        elif entry.get("attempts"):
            status = "failed after %d attempt(s)" % entry["attempts"]
        elif day == now.date() and now.time() < slot:
            status = "later today"
        else:
            status = "did not run"
        lines.append("%s: %s" % (label, status))
    resume = state.get("resume") if isinstance(state.get("resume"), dict) else {}
    return lines, resume


def _linkedin(day: date) -> Dict[str, Any]:
    """Today's LinkedIn state, read from the poster's own files (same env keys, same defaults)."""
    import os

    state = _read_json(_from_repo(os.getenv("LINKEDIN_STATE_PATH", "linkedin/state.json")))
    drafts = _from_repo(os.getenv("LINKEDIN_DRAFT_DIR", "linkedin/drafts"))
    key = day.isoformat()
    posted = [entry for entry in state.get("posted", []) if isinstance(entry, dict) and entry.get("date") == key]
    draft = drafts / ("%s.md" % key)
    title = ""
    if draft.is_file():
        match = re.search(r"^source_title:\s*(.+)$", draft.read_text(encoding="utf-8"), re.M)
        title = match.group(1).strip() if match else ""
    return {
        "posted": posted,
        "day": (state.get("days") or {}).get(key) or {},
        "draft": draft if draft.is_file() else None,
        "draft_title": title,
        "card": drafts / ("%s.png" % key) if (drafts / ("%s.png" % key)).is_file() else None,
    }


def course_modules(course_dir: Path) -> List[Tuple[str, str]]:
    """(title, path) for every study module in the sidebar, in the 8-week plan's track order."""
    try:
        lines = (course_dir / "_sidebar.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for position, line in enumerate(lines):
        match = _SIDEBAR_LINK.match(line)
        if not match:
            continue
        title, path = match.group(1).strip(), match.group(2).strip()
        if "/" not in path or path.endswith("README.md"):
            continue
        track = next((rank for rank, prefix in enumerate(COURSE_TRACK_ORDER) if path.startswith(prefix)), len(COURSE_TRACK_ORDER))
        found.append((track, position, title, path))
    return [(title, path) for _, _, title, path in sorted(found)]


def _course_start(settings: Settings, today: date) -> date:
    if settings.course_start_date:
        try:
            return date.fromisoformat(settings.course_start_date)
        except ValueError:
            logger.warning("COURSE_START_DATE %r is not YYYY-MM-DD; counting from today", settings.course_start_date)
            return today
    path = Path(settings.report_dir or "reports") / "learning.json"
    state = _read_json(path)
    try:
        return date.fromisoformat(str(state.get("start")))
    except ValueError:
        pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"start": today.isoformat()}, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not save the course start date: %s", exc)
    return today


def learning_for(settings: Settings, day: date) -> List[str]:
    course_dir = Path(settings.course_dir) if settings.course_dir else None
    if course_dir is None or not course_dir.is_dir():
        return ["The course folder %s was not found; set COURSE_DIR in .env." % (settings.course_dir or "(unset)")]
    modules = course_modules(course_dir)
    if not modules:
        return ["No modules found in %s/_sidebar.md." % course_dir]
    start = _course_start(settings, day)
    index = (day - start).days
    if index < 0:
        return ["The plan starts on %s." % start.isoformat()]
    revising = index >= len(modules)
    title, path = modules[index % len(modules)]
    route = path[:-3] if path.endswith(".md") else path
    lines = [
        "%s: **%s** (day %d of %d)" % ("Revise" if revising else "Today", title, index % len(modules) + 1, len(modules)),
        "Read it: [%s](%s)" % (path, (course_dir / path).as_uri()),
        'On the site: `python3 "%s"`, then http://localhost:%d/#/%s'
        % (course_dir.resolve() / "serve.py", COURSE_PORT, route),
    ]
    following = modules[(index + 1) % len(modules)][0]
    lines.append("Tomorrow: %s" % following)
    return lines


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def build_report(settings: Settings, day: Optional[date] = None, now: Optional[datetime] = None) -> str:
    from sites_bot.external import pending_company_sites

    now = now or datetime.now()
    day = day or now.date()
    attempts, runs = _ledger_rows(settings, day)
    sent = [row for row in attempts if row.get("status") in _SENT]
    not_sent = [row for row in attempts if row.get("status") not in _SENT]
    sites = pending_company_sites(settings)
    questions = _blank_questions(settings)
    facts = _blank_facts(settings)
    disagreeing = _disagreements(settings)
    slots, resume = _profile_slots(settings, day, now)
    tailored = _tailored_today(settings, day)
    linkedin = _linkedin(day)
    untried = _untried_company_sites()

    naukri = sum(1 for row in sent if row.get("status") == ApplyStatus.APPLIED)
    boards = sum(1 for row in sent if row.get("status") == ApplyStatus.APPLIED_PLATFORM)
    if linkedin["posted"]:
        linkedin_line = "posted \"%s\"" % _cell(linkedin["posted"][-1].get("title"), 80)
    elif linkedin["draft"]:
        linkedin_line = "draft ready, not posted"
    else:
        linkedin_line = "nothing yet"

    out = [
        "# Daily report: %s" % day.strftime("%A, %d %B %Y"),
        "",
        "_Updated %s. Rebuild with `python3 -m common.report`._" % now.strftime("%H:%M"),
        "",
        "## At a glance",
        "",
        "- Applied: %d on Naukri, %d on other job boards, %d on company sites" % (
            naukri, boards, len(sent) - naukri - boards),
        "- Tried without applying: %d" % len(not_sent),
        "- Company-site applications waiting for you: %d" % len(sites),
        "- Questions waiting for your answer in answers.txt: %d" % len(questions),
        "- Facts still blank in profile.yaml: %d" % len(facts),
        "- Places where answers.txt and profile.yaml disagree: %d" % len(disagreeing),
        "- Naukri profile: %s" % "; ".join(slots),
        "- LinkedIn: %s" % linkedin_line,
        "",
        "## Applied today",
        "",
    ]
    if sent:
        out += ["| Time | Company | Role | Where | Link |", "|---|---|---|---|---|"]
        for row in sent:
            out.append(
                "| %s | %s | %s | %s | [job](%s) |"
                % (
                    _local_clock(row.get("at", "")),
                    _cell(row.get("company") or "-", 60),
                    _cell(row.get("title") or "-", 80),
                    _where(row),
                    row.get("url") or "",
                )
            )
    else:
        out.append("Nothing was applied to today.")

    out += ["", "## Tried but not applied", ""]
    if not_sent:
        out += ["| Time | Company | Role | Outcome | Why |", "|---|---|---|---|---|"]
        for row in not_sent:
            out.append(
                "| %s | %s | %s | %s | %s |"
                % (
                    _local_clock(row.get("at", "")),
                    _cell(row.get("company") or "-", 60),
                    _cell(row.get("title") or "-", 80),
                    _OUTCOMES.get(row.get("status"), row.get("status")),
                    _cell(row.get("detail") or "-"),
                )
            )
    else:
        out.append("None.")

    out += ["", "## Runs today", ""]
    if runs:
        out += [
            "| Started | Finished | Collected | Attempted | Applied | Company site | For you | Errors | Mode |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for run in runs:
            summary = run.get("summary") or {}
            out.append(
                "| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    _local_clock(run.get("started_at", "")),
                    _local_clock(run.get("finished_at", "")) if run.get("finished_at") else "still running",
                    summary.get("collected", run.get("collected") or 0),
                    summary.get("attempted", run.get("attempted") or 0),
                    summary.get("applied", run.get("applied") or 0),
                    summary.get("applied_external", 0),
                    summary.get("external_manual", 0),
                    summary.get("errors", 0),
                    "dry run" if summary.get("dry_run") else "real",
                )
            )
        funnels = [
            (run, funnel_text(run.get("summary") or {})) for run in runs
        ]
        funnels = [(run, line) for run, line in funnels if line]
        if funnels:
            out += ["", "### Where the collected jobs went", ""]
            for run, line in funnels:
                out.append("- %s: %s" % (_local_clock(run.get("started_at", "")), line))
    else:
        out.append("The Naukri bot did not run today.")

    out += ["", "## Left for you", "", "### Company-site applications to finish (data/company_sites.md)", ""]
    if sites:
        for entry in sites[-MAX_LISTED:]:
            out.append(
                "- **%s**, %s (%s): %s. [Open the site](%s)%s"
                % (
                    _cell(entry.get("company") or "-", 60),
                    _cell(entry.get("title") or "-", 80),
                    entry.get("when", "")[:10],
                    _cell(entry.get("why") or "-", 200),
                    entry.get("site") or entry.get("naukri") or "",
                    "; resume: `%s`" % entry["resume to send"] if entry.get("resume to send") else "",
                )
            )
        if len(sites) > MAX_LISTED:
            out.append("- ...and %d older ones in the file." % (len(sites) - MAX_LISTED))
    else:
        out.append("None.")
    out += ["", "### Questions to answer (data/answers.txt)", ""]
    if questions:
        out += ["- %s" % _cell(question, 200) for question in questions[:MAX_LISTED]]
        if len(questions) > MAX_LISTED:
            out.append("- ...and %d more in the file." % (len(questions) - MAX_LISTED))
        out.append("")
        out.append("Write each answer after its `A:` line; the next run uses it.")
    else:
        out.append("None.")
    out += ["", "### Where answers.txt and profile.yaml disagree", ""]
    if disagreeing:
        out += ["- %s: %s" % (item.topic, _cell(item.message, 220)) for item in disagreeing]
        out.append("")
        out.append("Employers get one or the other depending on how they word the question. Make them match.")
    else:
        out.append("None.")
    out += ["", "### Facts to fill (data/profile.yaml)", ""]
    out += ["- %s" % fact for fact in facts] if facts else ["None."]
    if untried:
        out += [
            "",
            "### Company-site roles nobody has tried yet",
            "",
            "`external_jobs.md` lists %d role(s). Set EXTERNAL_APPLY=true to let the bot try them, "
            "or open them by hand." % untried,
        ]

    out += ["", "## Naukri profile", ""]
    out += ["- %s" % line for line in slots]
    if resume:
        out.append("- Resume on the profile: %s, uploaded %s" % (Path(str(resume.get("file", ""))).name or "-", resume.get("date", "-")))

    out += ["", "## Resumes made for today's jobs", ""]
    if tailored:
        for record in tailored:
            notes = "; ".join(str(note) for note in record.get("notes") or []) or "no notes"
            out.append(
                "- %s, %s: `%s` (%s)"
                % (_cell(record.get("company") or "-", 60), _cell(record.get("title") or "-", 80), record["folder"], _cell(notes, 200))
            )
    else:
        out.append("None.")

    out += ["", "## LinkedIn", ""]
    if linkedin["posted"]:
        for entry in linkedin["posted"]:
            out.append("- Posted about [%s](%s)" % (_cell(entry.get("title") or "an article", 100), entry.get("url") or ""))
    elif linkedin["draft"]:
        out.append("- Draft for today: `%s`%s" % (linkedin["draft"], ", about \"%s\"" % linkedin["draft_title"] if linkedin["draft_title"] else ""))
        if linkedin["card"]:
            out.append("- Image card: `%s`" % linkedin["card"])
        out.append("- Not posted. Read it, then `python3 -m linkedin_bot --post`.")
    else:
        attempts_today = linkedin["day"].get("attempts", 0)
        out.append("- Nothing today%s." % (" (%d failed attempt(s))" % attempts_today if attempts_today else ""))

    out += ["", "## Filled in by the AI today", ""]
    from .assist import changes_on

    filled = changes_on(settings, day.isoformat())
    if filled:
        out += [
            "- %s, %s: **%s** (from your %s: \"%s\")"
            % (record.get("file"), _cell(record.get("item"), 80), _cell(record.get("value"), 60), record.get("source"), _cell(record.get("evidence"), 100))
            for record in filled
        ]
        out.append("")
        out.append("Each one is marked in the file. Change any that are wrong; your edit wins.")
    else:
        out.append("Nothing.")

    judged = changes_on(settings, day.isoformat(), kind="judged")
    if judged:
        out += ["", "### Answered by judgement", ""]
        out += [
            "- %s: **%s** (%s; %s)"
            % (
                _cell(record.get("item"), 80),
                _cell(record.get("value"), 60),
                _cell(record.get("evidence"), 100),
                "saved in answers.txt" if record.get("file") != "this application only" else "this application only",
            )
            for record in judged
        ]
        out.append("")
        out.append("No fact of yours said these outright. Check them; an answer you write in answers.txt replaces the judgement.")

    written = changes_on(settings, day.isoformat(), kind="written")
    if written:
        out += ["", "### Long answers written for company forms", ""]
        out += ["- %s: `%s`" % (_cell(record.get("item"), 80), record.get("file")) for record in written]
        out.append("")
        out.append("Written from your resume and the posting. Read them; a version you put in answers.txt is used instead next time.")

    drafts = [record for record in cold_email.read_records(settings)
              if str(record.get("drafted_at", "")).startswith(day.isoformat())]
    if drafts:
        out += ["", "## Cold emails drafted today (not sent)", ""]
        out += ["| To | Company | Role | In Gmail | Draft |", "|---|---|---|---|---|"]
        for record in drafts:
            out.append("| %s | %s | %s | %s | `%s` |" % (
                record.get("email"), _cell(record.get("company"), 40), _cell(record.get("title"), 50),
                "yes" if record.get("gmail_draft") else "no", record.get("eml")))
        out.append("")
        out.append("Read each one, then send it from Gmail's Drafts or by opening the .eml file in Mail.")

    tasks = browser_agent.records_for(settings, day.isoformat())
    if tasks:
        out += ["", "## Browser agent (Claude Code on the company sites)", ""]
        out += ["| Time | Company | Role | Outcome | Minutes | Folder |", "|---|---|---|---|---|---|"]
        for task in tasks:
            job = task.get("job") or {}
            folder = Path(task["folder"])
            out.append("| %s | %s | %s | %s | %.1f | [%s](agent/%s/) |" % (
                _local_clock(task.get("at", "")), _cell(job.get("company"), 40), _cell(job.get("title"), 50),
                _cell("%s: %s" % (task.get("status"), task.get("detail")), 160), (task.get("seconds") or 0) / 60.0,
                folder.name, folder.name.replace(" ", "%20")))
        out.append("")
        out.append("Each folder keeps the task it was given (task.md), every step it took (steps.txt, transcript.jsonl) and report.json.")

    out += ["", "## Logs", ""]
    logs = sorted((report_path(settings, day).parent / "logs").glob("*.log"))
    if logs:
        out += ["- [%s](logs/%s)" % (log.name, log.name) for log in logs]
    else:
        out.append("No run saved a log today.")

    out += ["", "## Learning today", ""]
    out += ["- %s" % line for line in learning_for(settings, day)]
    out.append("")
    return "\n".join(out)


def report_path(settings: Settings, day: date) -> Path:
    return Path(settings.report_dir or "reports") / day.isoformat() / REPORT_NAME


def write_daily_report(settings: Settings, day: Optional[date] = None, now: Optional[datetime] = None) -> Path:
    now = now or datetime.now()
    day = day or now.date()
    path = report_path(settings, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(settings, day, now), encoding="utf-8")
    return path


def update_quietly(settings: Settings) -> Optional[Path]:
    """Rebuild today's report after a bot run; a failure here never fails the run."""
    try:
        path = write_daily_report(settings)
    except Exception as exc:  # the report is a by-product; the run already happened
        logger.warning("Could not write the daily report (%s: %s)", type(exc).__name__, exc)
        return None
    logger.info("Daily report: %s", path)
    return path


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m common.report",
        description="Rebuild reports/<date>/report.md: applications, what is left for you, profile, LinkedIn, learning.",
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="the day to report on (default: today)")
    parser.add_argument("--print", action="store_true", help="also print the report")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from . import config
    from .run import EXIT_CONFIG, EXIT_OK, configure_logging

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    try:
        day = date.fromisoformat(args.date) if args.date else None
    except ValueError:
        logger.error("--date must look like 2026-10-10, not %r", args.date)
        return EXIT_CONFIG
    path = write_daily_report(settings, day)
    logger.info("Wrote %s", path)
    if args.print:
        print(path.read_text(encoding="utf-8"))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
