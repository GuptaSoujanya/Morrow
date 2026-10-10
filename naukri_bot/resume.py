"""Tailor the LaTeX resume to one job, compile it, and put it on the Naukri profile.

The resume at RESUME_PATH (resume/base.tex) is the copy the user edits by
hand; the bot never writes to it. For one job, three parts are adjusted: the
one-line subtitle under the name, the Summary paragraph, and the order of the
items inside each Skills category. Nothing else changes, and nothing is
added: every technology, employer or number in a tailored part must already
appear somewhere in the base resume, or the proposal is dropped and the base
text is used instead. A recruiter reading the tailored PDF therefore reads
the user's own claims, in the user's own words, in a different order.

    python3 -m naukri_bot.resume                     # compile the base resume
    python3 -m naukri_bot.resume --tailor jd.txt \\
        --title "Backend Engineer" --company Acme    # tailor to a pasted posting

The apply run tailors and uploads before each application when TAILOR_RESUME
is on, and the profile updater re-uploads the base PDF when
UPLOAD_RESUME_DAILY is on or the compiled PDF changed.
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from selenium.common.exceptions import (
    ElementNotInteractableException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .browser import human_pause, safe_get
from .llm import LLMClient
from .models import JobPosting, Settings
from .profile import extract_resume_text

logger = logging.getLogger(__name__)

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
#: Naukri rejects larger files ("Supported Formats: doc, docx, rtf, pdf, upto 2 MB").
NAUKRI_MAX_BYTES = 2 * 1024 * 1024

_RESUME_CARD = "#lazyAttachCV"
_RESUME_INPUT = "input#attachCV"
_RESUME_NAME = ".resume-name-inline"
_RESUME_PREVIEW = ".cvPreview"
_RESUME_MESSAGE = "#attachCVMsgBox"
#: Naukri shows "Resume has been successfully uploaded." within a second and clears it after ~5 s.
UPLOAD_WAIT_S = 60

# The three tailored parts, located by the structure of resume/base.tex.
_SUBTITLE = re.compile(
    r"(\{\\normalsize\\color\{muted\}\s*)(?P<subtitle>[^\n}]*?)(\s*\}\\\\\[\d+pt\])"
)
_SUMMARY = re.compile(r"(\\section\{Summary\}[ \t]*\n)(?P<summary>.+?)(\n[ \t]*\n)", re.S)
_SKILLS_BLOCK = re.compile(r"(\\section\{Skills\}[ \t]*\n)(?P<block>.+?)(\n[ \t]*\n)", re.S)
_SKILL_LINE = re.compile(
    r"^\{\\bfseries (?P<category>[^}]+?):\}[ \t]*(?P<items>.*?)"
    r"(?P<tail>\\par\\vspace\{\d+pt\})?[ \t]*$"
)
_ITEMIZE = re.compile(r"(\\begin\{itemize\}[^\n]*\n)(?P<body>.*?)(\n[ \t]*\\end\{itemize\})", re.S)
_HEADER_NAME = re.compile(
    r"\\LARGE(?:\\[A-Za-z]+(?:\{[^}]*\})?)*\s+"
    r"(?P<name>[A-Z][A-Z'.-]*(?:\s+[A-Z][A-Z'.-]*)+)\s*\}"
)

_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.'/-]*")
_ALLOWED_COMMANDS = {"&", "%", "#", "_", ";", ",", "cdot", "textbf", "emph", "textit"}
_PRONOUNS = {"i", "i'm", "i've", "i'd", "i'll"}
# Words that mark text as machine-written or salesy; the resume is the user's
# own voice and these are not in it.
_BANNED_WORDS = (
    "passionate",
    "results-driven",
    "results driven",
    "leverage",
    "leveraging",
    "synergy",
    "cutting-edge",
    "cutting edge",
    "delve",
    "seamless",
    "seamlessly",
    "spearheaded",
    "dynamic",
    "innovative",
    "proven track record",
    "guru",
    "ninja",
    "rockstar",
    "thought leader",
    "excited",
    "thrilled",
    "visionary",
    "world-class",
    "best-in-class",
    "game-changing",
)


class ResumeError(RuntimeError):
    """The resume could not be parsed, compiled, or put on the profile."""


@dataclass
class ResumeSections:
    subtitle: str
    summary: str
    skills: List[Tuple[str, List[str]]]
    # The \item lines of each itemize block, verbatim, in the order they print.
    bullets: List[List[str]] = field(default_factory=list)


@dataclass
class BaseResume:
    path: Path
    tex: str
    sections: ResumeSections
    plain_text: str
    terms: set


@dataclass
class ResumeUpload:
    file_name: str
    shown: str
    uploaded: bool


# --- parsing and rendering --------------------------------------------------------


def _split_items(text: str) -> List[str]:
    items = []  # type: List[str]
    current = []  # type: List[str]
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        if character == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    items.append("".join(current).strip())
    return [item for item in items if item]


def _bullet_items(body: str) -> List[str]:
    items = []  # type: List[str]
    for line in body.split("\n"):
        if line.lstrip().startswith("\\item") or not items:
            items.append(line)
        else:
            items[-1] += "\n" + line
    return items


def _plain(latex: str) -> str:
    text = re.sub(r"^\s*\\item\s*", "", latex)
    text = text.replace("$\\cdot$", "-")
    text = re.sub(r"\\([&%#_])", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?", " ", text).replace("{", " ").replace("}", " ")
    return " ".join(text.split())


def bullet_headings(tex: str) -> List[str]:
    """What each itemize block sits under: the role or sub-role line just above it."""
    headings = []  # type: List[str]
    for match in _ITEMIZE.finditer(tex):
        before = [line for line in tex[: match.start()].splitlines() if line.strip() and not line.lstrip().startswith("%")]
        headings.append(_plain(before[-1])[:120] if before else "")
    return headings


def parse_sections(tex: str) -> ResumeSections:
    subtitle = _SUBTITLE.search(tex)
    if subtitle is None:
        raise ResumeError("could not find the subtitle line under the name")
    summary = _SUMMARY.search(tex)
    if summary is None:
        raise ResumeError("could not find the Summary paragraph")
    block = _SKILLS_BLOCK.search(tex)
    if block is None:
        raise ResumeError("could not find the Skills section")
    skills = []  # type: List[Tuple[str, List[str]]]
    for line in block.group("block").splitlines():
        match = _SKILL_LINE.match(line)
        if match is not None:
            skills.append((match.group("category"), _split_items(match.group("items"))))
    if not skills:
        raise ResumeError("the Skills section has no '{\\bfseries Category:} items' lines")
    return ResumeSections(
        subtitle=subtitle.group("subtitle").strip(),
        summary=summary.group("summary").strip(),
        skills=skills,
        bullets=[_bullet_items(match.group("body")) for match in _ITEMIZE.finditer(tex)],
    )


def _render_skills_block(block: str, skills: List[Tuple[str, List[str]]]) -> str:
    rendered = []
    index = 0
    for line in block.splitlines():
        match = _SKILL_LINE.match(line)
        if match is None or index >= len(skills):
            rendered.append(line)
            continue
        category, items = skills[index]
        index += 1
        rendered.append(
            "{\\bfseries %s:} %s%s" % (category, ", ".join(items), match.group("tail") or "")
        )
    return "\n".join(rendered)


def render(tex: str, sections: ResumeSections) -> str:
    tex = _SUBTITLE.sub(lambda m: m.group(1) + sections.subtitle + m.group(3), tex, count=1)
    tex = _SUMMARY.sub(lambda m: m.group(1) + sections.summary + m.group(3), tex, count=1)
    if sections.bullets:
        blocks = iter(sections.bullets)

        def _block(m: "re.Match[str]") -> str:
            items = next(blocks, None)
            return m.group(0) if items is None else m.group(1) + "\n".join(items) + m.group(3)

        tex = _ITEMIZE.sub(_block, tex)
    return _SKILLS_BLOCK.sub(
        lambda m: m.group(1) + _render_skills_block(m.group("block"), sections.skills) + m.group(3),
        tex,
        count=1,
    )


def _terms(text: str) -> set:
    return {term.lower().strip(".'") for term in _TERM.findall(text)}


def load_base(path: str) -> BaseResume:
    resume_path = Path(path)
    try:
        tex = resume_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResumeError("could not read %s: %s" % (path, exc)) from exc
    if resume_path.suffix.lower() != ".tex":
        raise ResumeError("RESUME_PATH must be the LaTeX source (.tex), not %s" % path)
    plain = extract_resume_text(str(resume_path))
    return BaseResume(
        path=resume_path,
        tex=tex,
        sections=parse_sections(tex),
        plain_text=plain,
        terms=_terms(plain),
    )


def pdf_file_name(base: BaseResume, override: str = "") -> str:
    if override.strip():
        name = override.strip()
        return name if name.lower().endswith(".pdf") else name + ".pdf"
    match = _HEADER_NAME.search(base.tex)
    if match is None:
        return "Resume.pdf"
    words = [word.strip(".'-").title() for word in match.group("name").split()]
    return "_".join(word for word in words if word) + "_Resume.pdf"


# --- validation of a proposal -----------------------------------------------------


def _escape_latex(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "`")
    text = text.replace("\u201c", "``").replace("\u201d", "''")
    return re.sub(r"(?<!\\)([&%#_])", r"\\\1", text)


def _unescape(text: str) -> str:
    return re.sub(r"\\([&%#_])", r"\1", text)


def _at_sentence_start(text: str, position: int) -> bool:
    before = text[:position].rstrip()
    return not before or before[-1] in ".!?:"


def _claim_like(term: str, sentence_start: bool) -> bool:
    if any(character.isdigit() for character in term):
        return True
    if any(character in term for character in "+#/"):
        return True
    if "." in term.strip("."):
        return True
    return any(character.isupper() for character in term) and not sentence_start


def ungrounded_terms(text: str, base: BaseResume, known: frozenset = frozenset()) -> List[str]:
    """Technologies, names and numbers in `text` that neither the resume nor `known` mention."""
    missing = []  # type: List[str]
    for match in _TERM.finditer(text):
        term = match.group(0)
        if not _claim_like(term, _at_sentence_start(text, match.start())):
            continue
        lowered = term.lower().strip(".'")
        if lowered in _PRONOUNS:
            continue
        candidates = {lowered, lowered.rstrip("s")}
        if lowered.endswith("'s"):
            candidates.add(lowered[:-2])
        if not candidates & base.terms and not candidates & known and term not in missing:
            missing.append(term)
    return missing


def _lint(text: str, label: str) -> List[str]:
    problems = []  # type: List[str]
    if "\u2014" in text or "\u2013" in text:
        problems.append("%s uses an em or en dash" % label)
    if "!" in text:
        problems.append("%s uses an exclamation mark" % label)
    if any(ord(character) > 0x2600 for character in text):
        problems.append("%s contains a symbol or emoji" % label)
    lowered = text.lower()
    for word in _BANNED_WORDS:
        if re.search(r"(?<![a-z-])%s(?![a-z-])" % re.escape(word), lowered):
            problems.append("%s uses the word %r" % (label, word))
    for command in re.findall(r"\\([A-Za-z]+|[&%#_;,])", text):
        if command not in _ALLOWED_COMMANDS:
            problems.append("%s uses the LaTeX command \\%s" % (label, command))
    return problems


def _normalise(value: str) -> str:
    return " ".join(value.split()).casefold()


def _accept_skills(
    base: List[Tuple[str, List[str]]], proposed: Any
) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
    """Keep a category's new order only when it is a pure reordering."""
    notes = []  # type: List[str]
    accepted = []  # type: List[Tuple[str, List[str]]]
    for category, items in base:
        new_items = proposed.get(category) if isinstance(proposed, dict) else None
        if not isinstance(new_items, list) or not all(isinstance(i, str) for i in new_items):
            accepted.append((category, items))
            continue
        by_key = {_normalise(item): item for item in items}
        keys = [_normalise(item) for item in new_items]
        if sorted(keys) != sorted(by_key) or len(set(keys)) != len(keys):
            notes.append("skills %s: proposal added or dropped items; kept the base order" % _unescape(category))
            accepted.append((category, items))
            continue
        reordered = [by_key[key] for key in keys]
        if reordered != items:
            notes.append("skills %s: reordered to lead with %s" % (_unescape(category), _unescape(reordered[0])))
        accepted.append((category, reordered))
    return accepted, notes


def _accept_bullets(
    base: List[List[str]], headings: List[str], proposed: Any
) -> Tuple[List[List[str]], List[str]]:
    """Keep a block's new bullet order only when it is a permutation of its own bullets."""
    notes = []  # type: List[str]
    accepted = []  # type: List[List[str]]
    for index, items in enumerate(base):
        order = proposed[index] if isinstance(proposed, list) and index < len(proposed) else None
        if not isinstance(order, list) or sorted(order) != list(range(len(items))):
            if order is not None and order != list(range(len(items))):
                notes.append("bullets under %s: proposal was not a reordering; kept the base order" % (headings[index] or "a role"))
            accepted.append(items)
            continue
        reordered = [items[position] for position in order]
        if reordered != items:
            notes.append(
                "bullets under %s: now lead with \"%s\""
                % (headings[index] or "a role", " ".join(_plain(reordered[0]).split()[:8]))
            )
        accepted.append(reordered)
    return accepted, notes


def _accept_text(
    base: BaseResume,
    label: str,
    proposed: Any,
    current: str,
    words: Tuple[int, int],
    known: frozenset = frozenset(),
) -> Tuple[str, List[str]]:
    if not isinstance(proposed, str) or not proposed.strip():
        return current, []
    text = _escape_latex(" ".join(proposed.split()))
    if _normalise(text) == _normalise(current):
        return current, []
    problems = _lint(text, label)
    count = len(text.split())
    if not words[0] <= count <= words[1]:
        problems.append("%s has %d words; expected %d to %d" % (label, count, words[0], words[1]))
    missing = ungrounded_terms(text, base, known)
    if missing:
        problems.append("%s mentions things not in the resume: %s" % (label, ", ".join(missing)))
    if problems:
        return current, ["%s proposal rejected (%s); kept the base text" % (label, "; ".join(problems))]
    return text, ["%s rewritten" % label]


def summary_bounds(summary: str) -> Tuple[int, int]:
    """Word counts a rewritten summary may have: a little shorter, barely longer."""
    words = len(summary.split())
    return max(30, words - 20), words + 10


_TAILOR_SCHEMA = (
    '{"subtitle": "...", "summary": "...", "skills": {"<category exactly as given>": ["..."]}, '
    '"bullets": [[0, 1, 2]], "notes": "..."}'
)


def tailor(client: LLMClient, base: BaseResume, job: JobPosting) -> Tuple[ResumeSections, List[str]]:
    """Return sections adjusted for `job`, plus notes on what changed or was refused."""
    sections = base.sections
    if not client.available():
        return sections, ["LLM unavailable; resume left as is"]

    target_words = len(sections.summary.split())
    prompt = (
        "You are editing a software engineer's own resume for one job posting. "
        "The resume text below is the ONLY source of facts. Three things may change:\n"
        "1. subtitle: the one-line role description under the name. Reword it toward "
        "the posting's role, using only areas the resume already shows. Keep the "
        "LaTeX separators exactly as in the current subtitle (the \\;$\\cdot$\\; "
        "between parts) and under 90 characters.\n"
        "2. summary: rewrite the paragraph so the experience most relevant to this "
        "posting comes first. Keep the first-person, plain voice of the current "
        "summary and reuse its own sentences and phrases wherever possible; about "
        "%d words and never more than %d, because the resume must stay on one page; "
        "no new tools, employers, numbers or claims that the resume "
        "does not contain; no buzzwords (passionate, leverage, cutting-edge, "
        "seamless, dynamic, innovative, results-driven); no em dashes; no "
        "exclamation marks. Write & as \\& and %% as \\%%.\n"
        "3. skills: for each category, return the SAME items reordered so the ones "
        "the posting asks for come first. Never add, drop, rename or merge an item; "
        "copy each item exactly as given, including any parentheses.\n"
        "4. bullets: a list with one entry per bullet block, in block order. Each "
        "entry lists that block's bullet numbers in the order they should print, the "
        "bullet most relevant to the posting first; every number exactly once. The "
        "bullets' words never change. Always return this list, even when no order "
        "changes.\n"
        "If a part is already right for the posting, return it unchanged. "
        "notes: one sentence on what you changed and why.\n"
        "Posting: %s\nCurrent subtitle: %s\nCurrent summary: %s\nCurrent skills: %s\n"
        "Bullet blocks: %s\nResume text: %s"
    ) % (
        target_words,
        target_words + 10,
        json.dumps(
            {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "experience": job.experience,
                "tags": job.tags,
                "description": job.description[:3500],
            },
            ensure_ascii=True,
        ),
        sections.subtitle,
        sections.summary,
        json.dumps({category: items for category, items in sections.skills}, ensure_ascii=True),
        json.dumps(
            [
                {"block": index, "under": heading, "bullets": ["%d: %s" % (n, _plain(item)) for n, item in enumerate(items)]}
                for index, (heading, items) in enumerate(zip(bullet_headings(base.tex), sections.bullets))
            ],
            ensure_ascii=True,
        ),
        base.plain_text[:5000],
    )
    response = client.complete_json(prompt, _TAILOR_SCHEMA)
    if response is None:
        return sections, ["LLM gave no usable proposal; resume left as is"]

    notes = []  # type: List[str]
    # The subtitle is the one line meant to echo the posting's role, so the
    # words of the job title count as grounded there and nowhere else.
    subtitle, subtitle_notes = _accept_text(
        base,
        "subtitle",
        response.get("subtitle"),
        sections.subtitle,
        (2, 16),
        frozenset(_terms(job.title or "")),
    )
    summary, summary_notes = _accept_text(
        base, "summary", response.get("summary"), sections.summary, summary_bounds(sections.summary)
    )
    skills, skill_notes = _accept_skills(sections.skills, response.get("skills"))
    bullets, bullet_notes = _accept_bullets(sections.bullets, bullet_headings(base.tex), response.get("bullets"))
    notes.extend(subtitle_notes + summary_notes + skill_notes + bullet_notes)
    if isinstance(response.get("notes"), str) and response["notes"].strip():
        notes.append("model: %s" % " ".join(response["notes"].split())[:300])
    return ResumeSections(subtitle=subtitle, summary=summary, skills=skills, bullets=bullets), notes


# --- compiling --------------------------------------------------------------------


def find_compiler(preferred: str = "") -> Optional[Tuple[str, str]]:
    """(name, path) of the first LaTeX compiler on PATH, or None."""
    names = [preferred.strip()] if preferred.strip() else ["tectonic", "pdflatex", "xelatex", "lualatex"]
    for name in names:
        found = shutil.which(name)
        if found:
            return name, found
    return None


def compile_pdf(tex_path: Path, out_dir: Path, compiler: str = "", timeout_s: int = 240) -> Path:
    found = find_compiler(compiler)
    if found is None:
        raise ResumeError(
            "no LaTeX compiler found; install one with `brew install tectonic` "
            "(or set TEX_COMPILER to pdflatex/xelatex)"
        )
    name, path = found
    # The compiler runs inside the .tex directory (so \input and images resolve),
    # which would misplace a relative out_dir.
    tex_path = tex_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if name == "tectonic":
        command = [path, "--outdir", str(out_dir), str(tex_path)]
    else:
        command = [
            path,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory=%s" % out_dir,
            str(tex_path),
        ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(tex_path.parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResumeError("%s took longer than %d seconds" % (name, timeout_s)) from exc
    except OSError as exc:
        raise ResumeError("could not run %s: %s" % (name, exc)) from exc

    pdf = out_dir / (tex_path.stem + ".pdf")
    if completed.returncode != 0 or not pdf.exists():
        output = (completed.stdout or "") + (completed.stderr or "")
        tail = "\n".join(output.strip().splitlines()[-15:])
        raise ResumeError("%s failed on %s:\n%s" % (name, tex_path.name, tail))
    size = pdf.stat().st_size
    if size == 0:
        raise ResumeError("%s wrote an empty PDF" % name)
    if size > NAUKRI_MAX_BYTES:
        raise ResumeError(
            "the PDF is %d bytes; Naukri accepts at most %d" % (size, NAUKRI_MAX_BYTES)
        )
    return pdf


_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?!s)")
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def pdf_page_count(path: Path) -> int:
    """Pages in a PDF; tectonic keeps page objects inside compressed object streams."""
    data = Path(path).read_bytes()
    count = len(_PAGE_OBJECT.findall(data))
    for match in _STREAM.finditer(data):
        try:
            count += len(_PAGE_OBJECT.findall(zlib.decompress(match.group(1))))
        except zlib.error:
            continue
    return count


def _slug(value: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:limit].strip("-") or "job"


def _is_fresh(pdf: Path, *sources: Path) -> bool:
    if not pdf.exists():
        return False
    built = pdf.stat().st_mtime
    return all(source.stat().st_mtime <= built for source in sources if source.exists())


def _publish(pdf: Path, file_name: str) -> Path:
    target = pdf.with_name(file_name)
    if target != pdf:
        shutil.copyfile(str(pdf), str(target))
    return target


def _compile_sections(tex_path: Path, base: BaseResume, sections: ResumeSections, settings: Settings) -> Path:
    tex_path.write_text(render(base.tex, sections), encoding="utf-8")
    return compile_pdf(tex_path, tex_path.parent, settings.tex_compiler)


def build_base_pdf(settings: Settings) -> Path:
    """Compile RESUME_PATH into RESUME_OUT_DIR/base/<file name>, reusing a fresh build."""
    base = load_base(settings.resume_path)
    out_dir = Path(settings.resume_out_dir) / "base"
    target = out_dir / pdf_file_name(base, settings.resume_file_name)
    if _is_fresh(target, base.path):
        return target
    pdf = compile_pdf(base.path, out_dir, settings.tex_compiler)
    logger.info("Compiled %s -> %s (%d KB)", base.path.name, target, pdf.stat().st_size // 1024)
    return _publish(pdf, target.name)


def _folder_name(value: str, limit: int = 60) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 .&()+-]+", " ", value)
    return " ".join(cleaned.split()).strip(" .")[:limit].strip(" .")


def _recorded(record: Path) -> dict:
    try:
        loaded = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def tailored_dir(settings: Settings, job: JobPosting) -> Path:
    """RESUME_OUT_DIR/tailored/<Company - Title>/: one folder per posting, named for it."""
    company = _folder_name(job.company or "") or "Unknown company"
    title = _folder_name(job.title or "") or "Role"
    root = Path(settings.resume_out_dir) / "tailored"
    folder = root / ("%s - %s" % (company, title))
    recorded_id = _recorded(folder / "tailoring.json").get("job_id")
    if recorded_id and recorded_id != job.job_id:
        folder = root / ("%s - %s (%s)" % (company, title, _slug(job.job_id, 16)))
    return folder


def _write_posting(path: Path, job: JobPosting) -> None:
    lines = [
        "Title: %s" % (job.title or ""),
        "Company: %s" % (job.company or ""),
        "Location: %s" % (job.location or ""),
        "Experience: %s" % (job.experience or ""),
        "Salary: %s" % (job.salary or ""),
        "Posted: %s" % (job.posted_label or ""),
        "URL: %s" % (job.url or ""),
        "Saved: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        job.description or "",
    ]
    try:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)


def _write_record(record: Path, job: JobPosting, pdf: Path, notes: List[str]) -> None:
    try:
        record.write_text(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "url": job.url,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "resume": str(pdf),
                    "notes": notes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not write %s: %s", record, exc)


def build_tailored_pdf(
    settings: Settings, client: LLMClient, job: JobPosting
) -> Tuple[Path, List[str]]:
    """The PDF to apply with for `job`: tailored when possible, else the base.

    Every posting gets its own folder, RESUME_OUT_DIR/tailored/<Company - Title>/,
    holding posting.txt, the tailored .tex, the PDF that was sent (under the
    recruiter-visible file name) and a tailoring.json that records what changed,
    so a submitted resume can always be read back.
    """
    base = load_base(settings.resume_path)
    file_name = pdf_file_name(base, settings.resume_file_name)
    out_dir = tailored_dir(settings, job)
    target = out_dir / file_name
    record = out_dir / "tailoring.json"
    if _is_fresh(target, base.path):
        notes = list(_recorded(record).get("notes") or [])
        return target, ["reused the tailored resume built earlier"] + notes

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_posting(out_dir / "posting.txt", job)
    sections, notes = tailor(client, base, job)
    base_pdf = build_base_pdf(settings)
    base_pages = pdf_page_count(base_pdf)
    tailored_tex = out_dir / "tailored.tex"
    result = None  # type: Optional[Path]
    try:
        pdf = _compile_sections(tailored_tex, base, sections, settings)
        if pdf_page_count(pdf) > base_pages and sections.summary != base.sections.summary:
            notes.append("the rewritten summary ran past page %d; kept the base summary" % base_pages)
            sections = ResumeSections(sections.subtitle, base.sections.summary, sections.skills)
            pdf = _compile_sections(tailored_tex, base, sections, settings)
        if pdf_page_count(pdf) > base_pages:
            notes.append("tailored resume ran past page %d; used the base resume" % base_pages)
        else:
            result = _publish(pdf, file_name)
    except ResumeError as exc:
        logger.warning("Tailored resume did not compile (%s); applying with the base resume", exc)
        notes.append("tailoring failed to compile; used the base resume")
    if result is None:
        result = base_pdf
    _write_record(record, job, result, notes)
    return result, notes


# --- the Naukri profile -----------------------------------------------------------


def _wait(driver: Any, condition: Callable[[Any], Any], timeout: float, what: str) -> Any:
    try:
        return WebDriverWait(driver, timeout).until(condition)
    except TimeoutException as exc:
        raise ResumeError("timed out waiting for %s" % what) from exc


def _visible(driver: Any, selector: str) -> Optional[Any]:
    try:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            if element.is_displayed():
                return element
    except (StaleElementReferenceException, WebDriverException):
        return None
    return None


def shown_resume(driver: Any) -> Tuple[str, str]:
    """(file name, preview text such as 'Uploaded on Oct 10, 2026') from the profile."""
    name = _visible(driver, _RESUME_NAME)
    preview = _visible(driver, _RESUME_PREVIEW)
    return (
        " ".join(name.text.split()) if name is not None else "",
        " ".join(preview.text.split()) if preview is not None else "",
    )


def _today_labels() -> List[str]:
    now = datetime.now()
    labels = [now.strftime("%b %d, %Y")]
    labels.append("%s %d, %d" % (now.strftime("%b"), now.day, now.year))
    return labels


def _shows_upload(driver: Any, file_name: str) -> bool:
    name, preview = shown_resume(driver)
    return name == file_name and any(label in preview for label in _today_labels())


def _upload_message(driver: Any) -> str:
    box = _visible(driver, _RESUME_MESSAGE)
    return " ".join(box.text.split()) if box is not None else ""


def _upload_error(driver: Any) -> str:
    text = _upload_message(driver)
    return "" if not text or "success" in text.lower() else text


def upload_resume(driver: Any, pdf_path: Path, dry_run: bool = False) -> ResumeUpload:
    """Put `pdf_path` on the profile and verify it is shown, before and after a reload."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise ResumeError("resume PDF not found: %s" % pdf_path)
    if not safe_get(driver, PROFILE_URL):
        raise ResumeError("could not open the profile page")
    _wait(driver, lambda d: _visible(d, _RESUME_CARD), 20, "the resume card")
    before_name, before_preview = shown_resume(driver)
    logger.info("Profile resume now: %s (%s)", before_name or "none", before_preview or "-")
    if dry_run:
        logger.info("Dry run: would upload %s. Nothing was changed.", pdf_path.name)
        return ResumeUpload(file_name=before_name, shown=before_preview, uploaded=False)
    # Every upload of the same file name on the same day leaves the card exactly as
    # it was, so then only Naukri's own success message proves the new file landed.
    card_already_matches = _shows_upload(driver, pdf_path.name)

    try:
        control = driver.find_element(By.CSS_SELECTOR, _RESUME_INPUT)
    except WebDriverException as exc:
        raise ResumeError("the resume upload control is missing (%s)" % type(exc).__name__) from exc
    try:
        control.send_keys(str(pdf_path))
    except ElementNotInteractableException:
        # Naukri hides the file input behind a styled button; a hidden input
        # still accepts a path once it is displayed.
        driver.execute_script(
            "arguments[0].style.display='block'; arguments[0].style.visibility='visible';",
            control,
        )
        control.send_keys(str(pdf_path))

    def _done(d: Any) -> bool:
        if _upload_message(d):
            return True
        return not card_already_matches and _shows_upload(d, pdf_path.name)

    _wait(driver, _done, UPLOAD_WAIT_S, "Naukri to confirm the upload")
    error = _upload_error(driver)
    if error:
        raise ResumeError("Naukri refused the upload: %s" % error)
    message = _upload_message(driver)
    if message:
        logger.info("Naukri says: %s", message)
    human_pause(2.0, 4.0)

    if not safe_get(driver, PROFILE_URL):
        raise ResumeError("could not reload the profile page to verify the upload")
    _wait(driver, lambda d: _visible(d, _RESUME_CARD), 20, "the resume card after reload")
    if not _shows_upload(driver, pdf_path.name):
        name, preview = shown_resume(driver)
        raise ResumeError(
            "after reload the profile shows %r (%s), not today's %s"
            % (name, preview, pdf_path.name)
        )
    name, preview = shown_resume(driver)
    logger.info("Profile resume is now %s (%s)", name, preview)
    return ResumeUpload(file_name=name, shown=preview, uploaded=True)


def file_digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- command line -----------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m naukri_bot.resume",
        description="Compile the LaTeX resume, or tailor it to a pasted job posting.",
    )
    parser.add_argument("--tailor", metavar="JD_FILE", help="text file with the job description")
    parser.add_argument("--title", default="", help="job title (with --tailor)")
    parser.add_argument("--company", default="", help="company name (with --tailor)")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="also put the compiled PDF on the Naukri profile and verify it is shown",
    )
    parser.add_argument("--headless", action="store_true", help="run the browser without a window")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from .cli import EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, configure_logging, keep_log
    from . import config, llm

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env, {"headless": True} if args.headless else {})
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    keep_log(settings, "resume")
    if args.upload:
        problems = settings.validate()
        if problems:
            for problem in problems:
                logger.error("Config: %s", problem)
            return EXIT_CONFIG

    try:
        if args.tailor:
            description = Path(args.tailor).read_text(encoding="utf-8")
            job = JobPosting(
                job_id="manual-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"),
                url="",
                title=args.title,
                company=args.company,
                description=description,
            )
            pdf, notes = build_tailored_pdf(settings, llm.build_client(settings), job)
            for note in notes:
                logger.info("  - %s", note)
        else:
            pdf = build_base_pdf(settings)
    except (ResumeError, OSError) as exc:
        logger.error("%s", exc)
        return EXIT_FAILED
    logger.info("Resume PDF: %s (%d KB)", pdf, pdf.stat().st_size // 1024)
    if not args.upload:
        return EXIT_OK

    from . import update_profile

    try:
        result = update_profile.with_session(settings, lambda driver: upload_resume(driver, pdf))
    except update_profile._NeedsHuman as exc:
        logger.error("Login needs a human: %s", exc)
        return EXIT_LOGIN
    except (ResumeError, update_profile.ProfileUpdateError) as exc:
        logger.error("%s", exc)
        return EXIT_FAILED
    update_profile.mark_resume(Path(settings.profile_update_state_path), pdf)
    logger.info("Profile shows %s (%s).", result.file_name, result.shown)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
