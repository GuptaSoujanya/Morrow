"""The day's study material in user/research/, written with the claude or kiro CLI.

- learning/weeks/week-NN.md: the 90-day plan, one file per week. A week file that
  is missing (or short of days) is written by the CLI when that week comes up.
- learning/today.md and learning/daily/<date>.md: today's day, cut from its week.
- user/memory/learning.json: shared durable progress (imports learning/progress.json once).
- resume-learning/NN-*.md: one study file per area of the resume; missing ones are written.
- daily/<date>/: the day's briefing, written by the agents in pipeline/briefing.py.
"""

import json
import hashlib
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

    Current resume evidence wins over saved onboarding areas, which may belong
    to a previous upload. LaTeX categories and recognizable PDF/text skills work
    without another AI call; unknown stacks use the resume's projects directly.
    """
    resume = resume_text(resume_path)
    areas = []
    for match in _SKILL_LINE.finditer(resume):
        category, items = match.group("category").strip(), " ".join(match.group("items").split())
        if category and items:
            areas.append((persona_module.slugify(category), "%s: %s" % (category, _plain_tex(items))))
    if not areas and resume.strip():
        # Uploaded PDFs do not contain the old LaTeX skill macros. Derive areas
        # from the selected resume, never blindly reuse a previous persona.
        for category, vocabulary in (
            ("Languages", ("Python", "JavaScript", "TypeScript", "Java", "Go", "Rust", "C++", "SQL")),
            ("Full-stack engineering", ("React", "Next.js", "Vue", "Angular", "Node.js", "FastAPI", "Django", "Spring")),
            ("AI and machine learning", ("PyTorch", "TensorFlow", "LLM", "RAG", "LangChain", "Transformers", "machine learning", "AI agents")),
            ("Data and distributed systems", ("PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "Spark", "Elasticsearch")),
            ("Cloud and delivery", ("AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD")),
        ):
            found = [skill for skill in vocabulary if re.search(r"(?<![\w])" + re.escape(skill) + r"(?![\w])", resume, re.I)]
            if found:
                areas.append((persona_module.slugify(category), "%s: %s" % (category, ", ".join(found))))
        if not areas:
            areas = [("resume-projects", "Projects and experience evidenced by this resume")]
    if not resume.strip():
        areas = [(area.slug, area.title) for area in persona_module.load_persona().study_areas]
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
    resume = resume_text()
    return "\n\n".join([
        "Write week %d of a 90-day study plan for %s who studies 2 hours a day to reach %s."
        % (week, "the engineer described by the current resume" if resume.strip() else who.learner_line(), who.goal or DEFAULT_GOAL),
        "Resume evidence (contact details removed; authoritative for experience):\n" + (resume[:8000] or "No resume is available. Label this as a general curriculum; do not invent experience."),
        "Personalize prerequisites, examples and skill gaps to this resume and target roles. Cover "
        "system design, full-stack engineering (frontend, backend, databases and deployment), and AI agents "
        "(tool use, retrieval, evaluation and reliability). Include full-stack implementation within the "
        "System Design block and agent projects within ML / GenAI, with one practical deliverable each week. "
        "Separate skills demonstrated by the resume from skills the learner still needs to develop.",
        "This week's existing syllabus is a suggested sequence, not evidence of the learner's skills. Adapt it to the current resume (| week | days | system design | ML / GenAI |):\n" + syllabus_row(week, root),
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
    """Refresh unfinished days for the selected resume, preserving completed work."""
    path = week_path(week, root)
    wanted = set(days_of(week))
    fingerprint = resume_fingerprint()
    evidence = resume_text()  # Fail clearly if an explicitly selected resume cannot be read.
    if fingerprint and not evidence.strip():
        raise ai_cli.AIError("the selected resume has no readable experience or skills")
    metadata = _read_metadata(path)
    previous = ""
    try:
        previous = path.read_text(encoding="utf-8")
        if wanted <= set(split_days(previous)) and (not fingerprint or metadata.get("resume_sha256") == fingerprint):
            return path
    except OSError:
        pass
    completed = set(load_progress(root).get("done") or [])
    old_sections = split_days(previous)
    if wanted <= completed and wanted <= set(old_sections):
        return path
    logger.info("Writing %s with the AI CLI.", path)
    text = links.linkify(ai_cli.markdown_from(ask(week_prompt(week, root)), "# Week"))
    missing = wanted - set(split_days(text))
    if missing:
        raise ai_cli.AIError("the week it wrote has no section for day(s) %s" % sorted(missing))
    if resume_fingerprint() != fingerprint:
        raise ai_cli.AIError("the selected resume changed during generation; retry with the current resume")
    completed = set(load_progress(root).get("done") or [])
    # The model may produce a new whole week, but completed lessons retain their
    # exact source. Their provenance remains old/unknown, never relabelled.
    new_sections = split_days(text)
    text = text[:_DAY.search(text).start()] + "\n".join(
        old_sections[d] if d in completed and d in old_sections else new_sections[d]
        for d in days_of(week)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if previous:
        _archive(path, previous)
    path.write_text(text, encoding="utf-8")
    old_sources = metadata.get("day_resume_sha256", {})
    if not isinstance(old_sources, dict):
        old_sources = {}
    _write_metadata(path, {"resume_sha256": fingerprint, "day_resume_sha256": {
        str(d): old_sources.get(str(d), metadata.get("resume_sha256", ""))
        if d in completed and d in old_sections else fingerprint for d in days_of(week)
    }})
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
    sources = _read_metadata(week_file).get("day_resume_sha256", {})
    source = sources.get(str(day), "") if isinstance(sources, dict) else ""
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
        content = "\n".join([head, body, quoted, tail])
        if path == daily and path.exists():
            previous = path.read_text(encoding="utf-8")
            if previous != content:
                _archive(path, previous)
        path.write_text(content, encoding="utf-8")
        _write_metadata(path, {"resume_sha256": source, "plan_day": day, "week": week})
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
    if path is not None:
        return Path(path).expanduser()
    selected = os.getenv("RESUME_PATH", "").strip()
    return paths.resolve(selected, Path.cwd()) if selected else RESUME_TEX.expanduser()


def resume_fingerprint(path: Optional[Path] = None) -> str:
    """Public provenance contract: SHA256 of the selected resume's raw bytes."""
    try:
        return hashlib.sha256(selected_resume_path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _read_metadata(path: Path) -> Dict:
    try:
        data = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_metadata(path: Path, data: Dict) -> None:
    path.with_suffix(".meta.json").write_text(json.dumps({"schema_version": 1, **data}, indent=2) + "\n", encoding="utf-8")


def _archive(path: Path, text: str) -> None:
    """A content-addressed copy keeps previous lessons and provenance reviewable."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    archived = path.parent / "archive" / path.stem / (digest + ".md")
    archived.parent.mkdir(parents=True, exist_ok=True)
    if not archived.exists():
        archived.write_text(links.relink(text, path.parent, archived.parent), encoding="utf-8")
        _write_metadata(archived, _read_metadata(path))


def resume_text(path: Optional[Path] = None) -> str:
    path = selected_resume_path(path)
    try:
        # Keep LaTeX lines intact: redaction and existing briefing skill
        # selectors depend on their original structure. PDFs need extraction.
        text = extract_resume_text(str(path)) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    except ProfileError as exc:
        raise ai_cli.AIError(str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        if os.getenv("RESUME_PATH") or path != RESUME_TEX:
            raise ai_cli.AIError("could not read the selected resume at %s" % path) from exc
        return ""
    # Contact lines stay out of the prompt.
    return "\n".join(line for line in text.splitlines() if not _CONTACT_LINE.search(line))


def missing_resume_areas(root: Path = RESUME_LEARNING, resume_path: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    return [area for area in resume_areas(resume_path)
            if current_resume_area(area[0], area[1], root, resume_path) is None]


def current_resume_area(number: str, slug: str, root: Path = RESUME_LEARNING,
                        resume_path: Optional[Path] = None) -> Optional[Path]:
    fingerprint = resume_fingerprint(resume_path)
    for path in sorted(root.glob("%s-%s*.md" % (number, slug))):
        metadata = _read_metadata(path)
        if metadata.get("resume_sha256") == fingerprint and metadata.get("area_slug") == slug:
            return path
    return None


def _resume_area_path(root: Path, number: str, slug: str, fingerprint: str) -> Path:
    path = root / ("%s-%s.md" % (number, slug))
    if path.exists():
        # Preserve original paths: bookmarks and completion refer to them.
        path = root / ("%s-%s-%s.md" % (number, slug, fingerprint[:12]))
        revision = 2
        while path.exists():
            path = root / ("%s-%s-%s-%d.md" % (number, slug, fingerprint[:12], revision))
            revision += 1
    return path


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
    fingerprint = resume_fingerprint(resume_path)
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
        if resume_fingerprint(resume_path) != fingerprint:
            raise ai_cli.AIError("the selected resume changed during generation; retry with the current resume")
        path = _resume_area_path(root, number, slug, fingerprint)
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _write_metadata(path, {"resume_sha256": fingerprint, "area_slug": slug})
        written.append(path)
    write_resume_index(root, fingerprint)
    return written


def write_resume_index(root: Path = RESUME_LEARNING, fingerprint: str = "") -> Path:
    lines = ["# Resume learning", "", "One file per area of the resume: what it is, how you used it, "
             "core concepts, interview Q&A, a hands-on exercise, what to read next.", ""]
    for path in sorted(root.glob("[0-9][0-9]-*.md")):
        content = path.read_text(encoding="utf-8").splitlines()
        title = (content[0].lstrip("# ").strip() if content else "") or path.stem
        source = _read_metadata(path).get("resume_sha256", "")
        label = "" if source and source == fingerprint else " — previous resume" if source else " — source resume untracked"
        lines.append("- [%s](%s)%s" % (title, path.name, label))
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
