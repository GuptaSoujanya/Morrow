"""The day's study material in user/research/, written with the claude or kiro CLI.

- learning/weeks/week-NN.md: the 90-day plan, one file per week. A week file that
  is missing (or short of days) is written by the CLI when that week comes up.
- learning/today.md and learning/daily/<date>.md: today's day, cut from its week.
- user/memory/learning.json: shared durable progress (imports learning/progress.json once).
- resume-learning/NN-*.md: one study file per area of the resume; missing ones are written.
- daily/<date>/: the day's briefing, written by the agents in pipeline/briefing.py.
"""

import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from common import ai_cli
from common import persona as persona_module
from common.profile import ProfileError, extract_resume_text

from . import course, links
from common import paths

logger = logging.getLogger(__name__)

RESEARCH = paths.research_dir()
LEARNING = RESEARCH / "learning"
RESUME_LEARNING = RESEARCH / "resume-learning"
RESUME_TEX = paths.user_dir() / "resume" / "base.tex"
LAST_DAY = 90
_DAY = re.compile(r"^## Day (\d+)\b", re.M)
#: What the plan is for when the persona does not say.
DEFAULT_GOAL = "senior interview level in High-Level System Design and in ML / Generative AI"

Ask = Callable[[str], str]

#: A "{\bfseries Category:} items" line of the resume's Skills section: the fallback study areas.
_SKILL_LINE = re.compile(r"^\{\\bfseries (?P<category>[^}]+?):\}[ \t]*(?P<items>.*?)(?:\\par\\vspace\{\d+pt\})?[ \t]*$", re.M)


def resume_areas(resume_path: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    """One study file per area of the resume: (number, slug, title).

    The areas come from user/inputs/persona.yaml (study_areas, written by the first
    run from the resume). Without them, each category line of the resume's Skills
    section is one area, so the stage still writes something for a person who
    skipped onboarding; the file name is free after "NN-".
    """
    areas = [(area.slug, area.title) for area in persona_module.load_persona().study_areas]
    if not areas:
        for match in _SKILL_LINE.finditer(resume_text(resume_path)):
            category, items = match.group("category").strip(), " ".join(match.group("items").split())
            if category and items:
                areas.append((persona_module.slugify(category), "%s: %s" % (category, _plain_tex(items))))
    return [("%02d" % number, slug, title) for number, (slug, title) in enumerate(areas[:99], start=1)]


def _plain_tex(text: str) -> str:
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+", " ", text).replace("{", "").replace("}", "")
    return " ".join(text.replace("$", "").replace("\\", "").split())


def ask_cli(cli: Optional[str] = None) -> Ask:
    return lambda prompt: ai_cli.ask(prompt, cli)


def researchers(cli: Optional[str] = None) -> Dict[str, Ask]:
    """One ask per CLI in the team (claude and kiro by default); the first one also merges."""
    names = ai_cli.team(cli) or ["claude"]  # no CLI at all: asking fails later with a clear error
    return {name: ask_cli(name) for name in names}


# ---------------------------------------------------------------------------
# The 90-day plan
# ---------------------------------------------------------------------------


def week_of(day: int) -> int:
    return min((day - 1) // 7 + 1, 13)


def days_of(week: int) -> List[int]:
    first = (week - 1) * 7 + 1
    return list(range(first, min(first + 7, LAST_DAY + 1)))


def week_path(week: int, root: Path = LEARNING) -> Path:
    return root / "weeks" / ("week-%02d.md" % week)


def split_days(text: str) -> Dict[int, str]:
    """Each '## Day N:' section of a week file, heading included."""
    marks = list(_DAY.finditer(text))
    sections = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        sections[int(mark.group(1))] = text[mark.start():end].strip() + "\n"
    return sections


def syllabus_row(week: int, root: Path = LEARNING) -> str:
    """The week's row of the syllabus table in learning/README.md."""
    try:
        text = (root / "README.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r"^\| %d \| [^\n]+$" % week, text, re.M)
    return found.group(0) if found else ""


def _shared(root: Path) -> bool:
    """True for the user's own learning folder, whose progress lives in user/memory/learning.json."""
    resolved = root.resolve()
    if resolved == LEARNING.resolve():
        return True
    parts = resolved.parts[-3:]
    return len(parts) == 3 and parts == (paths.user_dir().name, "research", "learning")


def _repo(root: Path) -> Path:
    """The folder learning_memory resolves user/ against: three above user/research/learning."""
    return root.resolve().parent.parent.parent


def load_progress(root: Path = LEARNING) -> Dict:
    """The saved progress, {} before the first day; a damaged file is an error, not a fresh start."""
    if _shared(root):
        from common import learning_memory
        return learning_memory.transact(_repo(root))["plan"]
    path = root / "progress.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        progress = json.loads(text)
    except ValueError as exc:
        raise ValueError("%s is not valid JSON (%s); fix or remove it" % (path, exc)) from exc
    if not isinstance(progress, dict):
        raise ValueError("%s does not hold a JSON object" % path)
    return progress


def save_progress(progress: Dict, root: Path = LEARNING) -> None:
    if _shared(root):
        from common import learning_memory
        # Generation only establishes the start date. Completion belongs to locked
        # transactions, so a slow generator cannot overwrite a newer dashboard save.
        def update(data):
            for key, value in progress.items():
                if key not in ("done", "marked"):
                    data["plan"].setdefault(key, value)
        learning_memory.transact(_repo(root), update)
        return
    root.mkdir(parents=True, exist_ok=True)
    (root / "progress.json").write_text(json.dumps(progress, indent=1), encoding="utf-8")


def current_day(progress: Dict) -> int:
    """The first day not marked done."""
    done = set(progress.get("done") or [])
    day = 1
    while day in done and day < LAST_DAY:
        day += 1
    return day


def mark_done(root: Path = LEARNING, today: Optional[date] = None) -> int:
    if _shared(root):
        from common import learning_memory
        return learning_memory.finish_plan_day(_repo(root), (today or date.today()).isoformat())
    progress = load_progress(root)
    stamp = (today or date.today()).isoformat()
    progress.setdefault("start", stamp)
    marked = progress.setdefault("marked", {})
    if stamp in marked:
        # A second --done the same day does not skip a study day.
        return int(marked[stamp])
    day = current_day(progress)
    progress["done"] = sorted(set(progress.get("done") or []) | {day})
    marked[stamp] = day
    save_progress(progress, root)
    return day


def week_prompt(week: int, root: Path = LEARNING) -> str:
    days = days_of(week)
    who = persona_module.load_persona()
    return "\n\n".join([
        "Write week %d of a 90-day study plan for %s who studies 2 hours a day to reach %s."
        % (week, who.learner_line(), who.goal or DEFAULT_GOAL),
        "This week's syllabus row (| week | days | system design | ML / GenAI |):\n" + syllabus_row(week, root),
        "Search the web for current, accurate material and link real pages (official docs, papers, "
        "well-known engineering blogs). Prefer sources from the last two years for GenAI topics.",
        "Output markdown only, nothing before or after it. Start with '# Week %d: <title>' and one "
        "paragraph. Then exactly %d day sections, Day %d to Day %d, each in this exact shape and with "
        "no other '## ' headings anywhere:\n\n"
        "## Day N: <short title>\n\n**System Design: <topic>** (55 min)\n<teaching notes, a mermaid "
        "diagram, a back-of-envelope estimate>\n\n**ML / GenAI: <topic>** (55 min)\n<teaching notes and "
        "a small Python exercise>\n\n**Recall** (10 min)\n- 3 to 5 self-check questions\n\n**Go deeper**\n"
        "- 2 to 4 links" % (week, len(days), days[0], days[-1]),
        "Day %d is a revision and mini-project day for the week. No emojis." % days[-1]
        if len(days) == 7 else "The last day is a final mock interview and wrap-up. No emojis.",
    ])


def ensure_week(week: int, ask: Ask, root: Path = LEARNING) -> Path:
    """The week file, written by the CLI first when it is missing or short of days."""
    path = week_path(week, root)
    wanted = set(days_of(week))
    try:
        if wanted <= set(split_days(path.read_text(encoding="utf-8"))):
            return path
    except OSError:
        pass
    logger.info("Writing %s with the AI CLI.", path)
    text = links.linkify(ai_cli.markdown_from(ask(week_prompt(week, root)), "# Week"))
    missing = wanted - set(split_days(text))
    if missing:
        raise ai_cli.AIError("the week it wrote has no section for day(s) %s" % sorted(missing))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_today(ask: Ask, root: Path = LEARNING, today: Optional[date] = None) -> Tuple[int, Path]:
    """Write today.md and daily/<date>.md for the first day not yet done."""
    today = today or date.today()
    progress = load_progress(root)
    if "start" not in progress:
        progress["start"] = today.isoformat()
        save_progress(progress, root)
    day = current_day(progress)
    week = week_of(day)
    week_file = ensure_week(week, ask, root)
    section = split_days(week_file.read_text(encoding="utf-8"))[day]
    head = "\n".join([
        "# %s: Day %d of %d (week %d)" % (today.isoformat(), day, LAST_DAY, week),
        "",
        "2 hours: 55 min system design, 55 min ML / GenAI, 10 min recall. "
        "When finished: `python3 -m pipeline learn --done`.",
        "",
    ])
    tail = ("Also today: the briefing in `user/research/daily/%s/` and one file from "
            "`user/research/resume-learning/`.\n" % today.isoformat())
    daily = root / "daily" / ("%s.md" % today.isoformat())
    daily.parent.mkdir(parents=True, exist_ok=True)
    for path in (daily, root / "today.md"):
        # The week's links are relative to weeks/; move them for each copy.
        body = links.relink(section, week_file.parent, path.parent)
        quoted = course.reading(day, section, week_file.parent, path.parent, root)
        path.write_text("\n".join([head, body, quoted, tail]), encoding="utf-8")
    return day, daily


# ---------------------------------------------------------------------------
# Resume study files
# ---------------------------------------------------------------------------


# Email, phone, address and profile links: any line holding one is dropped.
_CONTACT_LINE = re.compile(
    r"@|\+\d|\\href\{(?:mailto|tel)|\b(?i:phone|mobile|tel|address)\b"
    r"|\b\d{5}[ -]?\d{5}\b|\b\d{3}[ -]\d{3}[ -]\d{4}\b|\b[A-Z]{2},?\s+\d{6}\b"
    r"|(?i:linkedin\.com/in/|github\.com/)"
)


def selected_resume_path(path: Optional[Path] = None) -> Path:
    """Explicit callers win; the runner's selected input wins over legacy data."""
    return Path(path) if path is not None else Path(os.getenv("RESUME_PATH") or RESUME_TEX)


def resume_text(path: Optional[Path] = None) -> str:
    path = selected_resume_path(path)
    try:
        # Keep LaTeX lines intact: redaction and existing briefing skill
        # selectors depend on their original structure. PDFs need extraction.
        text = extract_resume_text(str(path)) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    except ProfileError as exc:
        raise ai_cli.AIError(str(exc)) from exc
    except (OSError, UnicodeError):
        return ""
    # Contact lines stay out of the prompt.
    return "\n".join(line for line in text.splitlines() if not _CONTACT_LINE.search(line))


def missing_resume_areas(root: Path = RESUME_LEARNING, resume_path: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    have = {path.name[:2] for path in root.glob("[0-9][0-9]-*.md")}
    return [area for area in resume_areas(resume_path) if area[0] not in have]


def resume_prompt(area: str, resume: str) -> str:
    return "\n\n".join([
        "Write a study file for a software engineer preparing interviews on one area of their own "
        "resume: %s." % area,
        "Their resume:\n" + resume[:8000],
        "Search the web for accurate, current material and link real pages.",
        "Output markdown only. Start with '# <area title>', then these sections in order: "
        "## What it is, ## How you used it (only what the resume says, never invent numbers), "
        "## Core concepts, ## Interview questions and answers (8 to 12), ## Hands-on exercise, "
        "## Read next. No contact details, no emojis.",
    ])


def fill_resume_learning(ask: Ask, root: Path = RESUME_LEARNING, resume_path: Optional[Path] = None) -> List[Path]:
    """Write every missing resume study file, then the index; the files written."""
    resume_path = selected_resume_path(resume_path)
    resume = resume_text(resume_path)
    if not resume.strip():
        # Without the resume the model would invent "how you used it".
        raise ai_cli.AIError("could not read the resume at %s" % resume_path)
    written = []
    for number, slug, area in missing_resume_areas(root, resume_path):
        logger.info("Writing resume study file %s-%s with the AI CLI.", number, slug)
        text = links.linkify(ai_cli.markdown_from(ask(resume_prompt(area, resume)), "# "))
        if "## Interview questions" not in text:
            raise ai_cli.AIError("the %s file it wrote has no interview questions section" % slug)
        path = root / ("%s-%s.md" % (number, slug))
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    write_resume_index(root)
    return written


def write_resume_index(root: Path = RESUME_LEARNING) -> Path:
    lines = ["# Resume learning", "", "One file per area of the resume: what it is, how you used it, "
             "core concepts, interview Q&A, a hands-on exercise, what to read next.", ""]
    for path in sorted(root.glob("[0-9][0-9]-*.md")):
        content = path.read_text(encoding="utf-8").splitlines()
        title = (content[0].lstrip("# ").strip() if content else "") or path.stem
        lines.append("- [%s](%s)" % (title, path.name))
    index = root / "README.md"
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index


def today_topics(root: Path = LEARNING) -> str:
    """The two topic lines of today's study day, for the briefing agents."""
    try:
        text = (root / "today.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return "; ".join(re.findall(r"^\*\*((?:System Design|ML / GenAI): [^*]+)\*\*", text, re.M))
