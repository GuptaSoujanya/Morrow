"""The course site in course/ as reading material for the 90-day plan.

The week files link course sections (`course/<track>/<chapter>.md#<heading>`);
the day's study notes quote those sections, so the day's reading is in one
file, and point at one chapter the plan never links, so over the 90 days every
chapter of the course comes up once.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import links
from common import paths

COURSE = paths.course_dir()
#: LEARNING and LAST_DAY (learning imports this module, so not imported here).
LEARNING = paths.research_dir() / "learning"
LAST_DAY = 90
SIDEBAR = "_sidebar.md"
#: Tracks the plan is built on: every chapter of these must be linked by some week.
PLAN_TRACKS = ("01-system-design", "04-ml-genai-agents")
#: Quoted course lines per day, so a day stays a 2-hour read.
MAX_QUOTED_LINES = 400


def chapters(root: Path = COURSE) -> List[Path]:
    """The course chapters in the site's order (the sidebar), track overviews and home page left out."""
    try:
        sidebar = (root / SIDEBAR).read_text(encoding="utf-8")
    except OSError:
        return []
    found = []
    for target in links.MD_LINK.findall(sidebar):
        path = root / target.split("#")[0]
        if path.name != "README.md" and path.parent != root and path not in found:
            found.append(path)
    return found


def course_links(text: str, src: Path, root: Path = COURSE) -> List[Tuple[Path, str]]:
    """(chapter, anchor) of every course link in `text`, whose links are relative to folder `src`."""
    return [(path, anchor) for path, anchor, _ in _course_links(text, src, root)]


def _course_links(text: str, src: Path, root: Path) -> List[Tuple[Path, str, int]]:
    course = root.resolve()
    found = []  # type: List[Tuple[Path, str, int]]
    for match in links.MD_LINK.finditer(links.prose(text)):
        target = match.group(1)
        if re.match(r"[a-z]+:|#|/", target):
            continue
        file, _, anchor = target.partition("#")
        path = (Path(src) / file).resolve()
        if course in path.parents and path.suffix == ".md" and all(
                (path, anchor) != (seen, mark) for seen, mark, _ in found):
            found.append((path, anchor, match.start()))
    return found


def section(path: Path, anchor: str) -> Optional[str]:
    """The text under the heading `anchor` in `path`, down to the next heading of its level or above."""
    text = path.read_text(encoding="utf-8")
    marks = links.headings(text)
    for index, (level, title, start) in enumerate(marks):
        if links.slug(title) != anchor:
            continue
        end = next((s for lvl, _, s in marks[index + 1:] if lvl <= level), len(text))
        return text[start:end].strip()
    return None


_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_COMMON = {"with", "from", "that", "this", "what", "your", "into", "chapter", "course", "design", "system",
           "systems", "about", "when", "they", "them", "deep", "dive", "minutes", "hour", "hours", "and", "the",
           "for", "how", "why", "day", "part", "min", "its", "are", "not", "one", "two", "vs"}


def _words(text: str) -> set:
    return {word.rstrip("s") for word in _WORD.findall(text.lower()) if word not in _COMMON}


_PART = re.compile(r"^\*\*(System Design|ML / GenAI|Recall|Go deeper)\b:?\s*(.*?)\*\*", re.M)


def topics_of(day_text: str) -> List[Tuple[int, str]]:
    """(offset, topic) for each part of the day: a part's own title with the day's heading;
    Recall and Go deeper take every title, since they cover the whole day."""
    first = day_text.splitlines()[0] if day_text else ""
    marks = list(_PART.finditer(day_text))
    titles = " ".join(mark.group(2) for mark in marks)
    found = [(0, " ".join([first, titles]))]
    for mark in marks:
        own = mark.group(2) if mark.group(1) in ("System Design", "ML / GenAI") else titles
        found.append((mark.start(), " ".join([first, own])))
    return found


def _topic_at(topics: List[Tuple[int, str]], offset: int) -> str:
    return [topic for start, topic in topics if start <= offset][-1]


#: A whole-chapter link quotes a section only when the section shares this many words with the topic.
MIN_SHARED_WORDS = 2


def best_section(path: Path, topic: str) -> str:
    """The anchor of the chapter's '##' section (title and sub-headings) sharing most words with `topic`.

    "" when none shares MIN_SHARED_WORDS, so a chapter that does not fit the day is linked, not quoted.
    """
    wanted = _words(topic)
    sections = []  # type: List[List[str]]
    for level, title, _ in links.headings(path.read_text(encoding="utf-8")):
        if level == 2:
            sections.append([title])
        elif level > 2 and sections:
            sections[-1].append(title)
    best, score = "", MIN_SHARED_WORDS - 1
    for titles in sections:
        shared = len(wanted & _words(" ".join(titles)))
        if shared > score:
            best, score = links.slug(titles[0]), shared
    return best


def linked_by_plan(learning_root: Path = LEARNING, root: Path = COURSE) -> Dict[Path, int]:
    """How many links each course chapter gets from the week files."""
    counts = {}  # type: Dict[Path, int]
    for week in sorted((learning_root / "weeks").glob("week-*.md")):
        for path, _ in course_links(week.read_text(encoding="utf-8"), week.parent, root):
            counts[path] = counts.get(path, 0) + 1
    return counts


def extra_chapter(day: int, learning_root: Path = LEARNING, root: Path = COURSE) -> Optional[Path]:
    """The chapter the plan never links that belongs to `day`, spread evenly over the 90 days."""
    linked = linked_by_plan(learning_root, root)
    rest = [path for path in chapters(root) if path.resolve() not in linked]
    if not rest:
        return None
    return rest[(max(1, day) - 1) * len(rest) // LAST_DAY]


def _demote(text: str, to: int) -> str:
    """Shift headings so the quote's top heading sits at level `to`."""
    marks = links.headings(text)
    if not marks:
        return text
    shift = to - marks[0][0]

    def move(match: "re.Match") -> str:
        level = min(6, max(1, len(match.group(1)) + shift))
        return "%s %s" % ("#" * level, match.group(2))

    parts = re.split(r"(```.*?```)", text, flags=re.S)
    return "".join(part if part.startswith("```") else links.HEADING.sub(move, part)
                   for part in parts)


def reading(day: int, day_text: str, src: Path, dst: Path,
            learning_root: Path = LEARNING, root: Path = COURSE) -> str:
    """The 'From the course' part of the day's notes: quoted sections, then the day's extra chapter.

    `day_text` has links relative to `src`; the result has links relative to `dst`.
    """
    dst = Path(dst).resolve()
    lines = ["## From the course", "",
             "The course sections this day links, quoted so today's reading is all here. "
             "The site version: `python3 course/serve.py`, then http://localhost:8000.", ""]
    quoted = 0
    topics = topics_of(links.prose(day_text))
    chosen = []  # type: List[Tuple[Path, str]]
    for path, anchor, offset in _course_links(day_text, src, root):
        # A link to a whole chapter quotes its section closest to the topic of the part it sits in.
        anchor = anchor or best_section(path, _topic_at(topics, offset))
        if anchor and (path, anchor) not in chosen:
            chosen.append((path, anchor))
    for path, anchor in chosen:
        text = section(path, anchor)
        if text is None:
            continue
        size = len(text.splitlines())
        if quoted + size > MAX_QUOTED_LINES:
            lines += ["Also linked: [%s](%s#%s)" % (anchor.replace("-", " "),
                                                    links._relative(path, dst), anchor), ""]
            continue
        quoted += size
        source = "[%s](%s#%s)" % (path.stem, links._relative(path, dst), anchor)
        lines += [links.relink(_demote(text, 3), path.parent, dst), "", "*From %s.*" % source, ""]
    extra = extra_chapter(day, learning_root, root)
    if extra is not None:
        lines += ["**Extra from the course** (optional, outside the 2 hours): [%s](%s). "
                  "The plan's days do not link this chapter; it comes up here for a few days." % (
                      _title(extra), links._relative(extra, dst)), ""]
    return "\n".join(lines)


def _title(path: Path) -> str:
    marks = links.headings(path.read_text(encoding="utf-8"))
    return marks[0][1] if marks else path.stem


def problems(root: Path = COURSE, learning_root: Path = LEARNING) -> List[str]:
    """The course site is whole: sidebar and files agree, links work, the plan uses its tracks."""
    if not (root / SIDEBAR).exists():
        return ["%s: missing" % (root / SIDEBAR)]
    found = []  # type: List[str]
    pages = sorted(path for path in root.rglob("*.md"))
    listed = {(root / target.split("#")[0]).resolve()
              for target in links.MD_LINK.findall((root / SIDEBAR).read_text(encoding="utf-8"))}
    for path in pages:
        if path.name != SIDEBAR and path.resolve() not in listed:
            found.append("%s: not in the sidebar, so the site never shows it" % path)
        text = path.read_text(encoding="utf-8")
        if path.name not in (SIDEBAR,) and not links.headings(text):
            found.append("%s: has no heading" % path)
        found += links.link_problems(path)
    for target in listed:
        if not target.exists():
            found.append("%s: lists %s, which is not there" % (root / SIDEBAR, target))
    linked = linked_by_plan(learning_root, root)
    for path in chapters(root):
        if path.parent.name in PLAN_TRACKS and path.resolve() not in linked:
            found.append("%s: no week of the plan links it" % path)
    return found
