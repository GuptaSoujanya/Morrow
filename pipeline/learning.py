"""The day's study material in .research/, written with the claude or kiro CLI.

- learning/weeks/week-NN.md: the 90-day plan, one file per week. A week file that
  is missing (or short of days) is written by the CLI when that week comes up.
- learning/today.md and learning/daily/<date>.md: today's day, cut from its week.
- .memory/learning.json: shared durable progress (imports learning/progress.json once).
- resume-learning/NN-*.md: one study file per area of the resume; missing ones are written.
- daily/<date>/: the day's briefing, written by the agents in pipeline/briefing.py.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from common import ai_cli

from . import course, links

logger = logging.getLogger(__name__)

RESEARCH = Path(".research")
LEARNING = RESEARCH / "learning"
RESUME_LEARNING = RESEARCH / "resume-learning"
RESUME_TEX = Path("data/resume/base.tex")
LAST_DAY = 90
_DAY = re.compile(r"^## Day (\d+)\b", re.M)

Ask = Callable[[str], str]

#: One study file per area of the resume, by number; the file name is free after "NN-".
RESUME_AREAS = (
    ("01", "agent-evaluation-harnesses", "Agent evaluation harnesses (WildClawBench on OpenClaw, drift injection over 101 FastAPI mock services, bounded multi-agent, persona task packs)"),
    ("02", "llm-as-judge", "LLM-as-judge and the three-judge council, pytest grading"),
    ("03", "inference-gateways-litellm", "Inference gateways: the LiteLLM sidecar, Bedrock extended thinking, OpenRouter, prompt caching, cost tracking"),
    ("04", "langchain-and-rag", "LangChain benchmarking pipelines, RAG, EvalAgentFlow's 8-agent LangChain design"),
    ("05", "metrics-and-dataset-quality", "Evaluation metrics and dataset quality: taxonomy, entropy, inter-rater reliability"),
    ("06", "fine-tuning-and-prompting-llama", "Prompting and rubrics for LLaMA 4 Maverick, fine-tuning basics"),
    ("07", "python-fastapi-pytest", "Python, FastAPI and pytest"),
    ("08", "docker-ci-ec2-gitlfs", "Docker sandboxes, offline vendoring, CI, EC2 and Git LFS"),
    ("09", "react-nextjs-frontend", "React, Next.js, Tailwind, shadcn/ui, Redux Toolkit, TanStack Query"),
    ("10", "node-express-websockets-redis-mongo", "Node, Express, WebSockets, Redis, MongoDB and geospatial queries (RideMate)"),
    ("11", "sql-javascript-typescript-cpp", "SQL (MySQL, SQLite), JavaScript, TypeScript and C++"),
    ("12", "whisper-and-aws", "Whisper audio transcription, multimodal trajectories and the AWS services and certifications"),
)


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


def load_progress(root: Path = LEARNING) -> Dict:
    """The saved progress, {} before the first day; a damaged file is an error, not a fresh start."""
    if root.resolve().name == "learning" and root.resolve().parent.name == ".research":
        from common import learning_memory
        return learning_memory.transact(root.resolve().parent.parent)["plan"]
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
    if root.resolve().name == "learning" and root.resolve().parent.name == ".research":
        from common import learning_memory
        # Generation only establishes the start date. Completion belongs to locked
        # transactions, so a slow generator cannot overwrite a newer dashboard save.
        def update(data):
            for key, value in progress.items():
                if key not in ("done", "marked"):
                    data["plan"].setdefault(key, value)
        learning_memory.transact(root.resolve().parent.parent, update)
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
    if root.resolve().name == "learning" and root.resolve().parent.name == ".research":
        from common import learning_memory
        return learning_memory.finish_plan_day(root.resolve().parent.parent, (today or date.today()).isoformat())
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
    return "\n\n".join([
        "Write week %d of a 90-day study plan for a software engineer (about 2 years of experience, "
        "working on LLM evaluation) who studies 2 hours a day to reach senior interview level in "
        "High-Level System Design and in ML / Generative AI." % week,
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
    tail = ("Also today: the briefing in `.research/daily/%s/` and one file from "
            "`.research/resume-learning/`.\n" % today.isoformat())
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


def resume_text(path: Path = RESUME_TEX) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    # Contact lines stay out of the prompt.
    return "\n".join(line for line in text.splitlines() if not _CONTACT_LINE.search(line))


def missing_resume_areas(root: Path = RESUME_LEARNING) -> List[Tuple[str, str, str]]:
    have = {path.name[:2] for path in root.glob("[0-9][0-9]-*.md")}
    return [area for area in RESUME_AREAS if area[0] not in have]


def resume_prompt(area: str, resume: str) -> str:
    return "\n\n".join([
        "Write a study file for a software engineer preparing interviews on one area of their own "
        "resume: %s." % area,
        "Their resume (LaTeX source):\n" + resume[:8000],
        "Search the web for accurate, current material and link real pages.",
        "Output markdown only. Start with '# <area title>', then these sections in order: "
        "## What it is, ## How you used it (only what the resume says, never invent numbers), "
        "## Core concepts, ## Interview questions and answers (8 to 12), ## Hands-on exercise, "
        "## Read next. No contact details, no emojis.",
    ])


def fill_resume_learning(ask: Ask, root: Path = RESUME_LEARNING, resume_path: Path = RESUME_TEX) -> List[Path]:
    """Write every missing resume study file, then the index; the files written."""
    resume = resume_text(resume_path)
    if not resume.strip():
        # Without the resume the model would invent "how you used it".
        raise ai_cli.AIError("could not read the resume at %s" % resume_path)
    written = []
    for number, slug, area in missing_resume_areas(root):
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
