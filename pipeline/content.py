"""Checks on the reading material in .research/ and the course site in course/.

`python3 -m pipeline check [--date D]` prints every problem found; the pipeline
runs the same check for the day at the end of a run, so a day whose study notes
or briefing are missing or broken is reported, not silently skipped.
"""

import re
from datetime import date
from pathlib import Path
from typing import List, Optional

from . import briefing, course, learning
from .links import MD_LINK, link_problems, prose

#: Each regular study day has these four parts, in this order.
DAY_PARTS = ("**System Design:", "**ML / GenAI:", "**Recall**", "**Go deeper**")
#: Each resume study file has these sections.
RESUME_SECTIONS = ("## What it is", "## How you used it", "## Core concepts", "## Interview questions",
                   "## Hands-on", "## Read next")

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+91[\d -]{8,}")


def _hygiene(path: Path, text: str) -> List[str]:
    problems = ["%s: has emojis" % path] if _EMOJI.search(text) else []
    return problems + link_problems(path)


def week_problems(week: int, root: Path = learning.LEARNING) -> List[str]:
    path = learning.week_path(week, root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ["%s: missing (the pipeline writes it when week %d comes up)" % (path, week)]
    problems = _hygiene(path, text)
    numbers = [int(n) for n in re.findall(r"^## Day (\d+)\b", text, re.M)]
    if sorted(numbers) != learning.days_of(week):
        problems.append("%s: days %s, wanted %s" % (path, numbers, learning.days_of(week)))
    for heading in re.findall(r"^## (?!Day \d).*", prose(text), re.M):
        problems.append("%s: stray heading '%s'" % (path, heading))
    for number, section in learning.split_days(text).items():
        revision = re.search(r"revision|mock interview|wrap-up", section.splitlines()[0], re.I)
        parts = DAY_PARTS[2:] if revision else DAY_PARTS
        missing = [part.strip("*:") for part in parts if part not in section]
        if missing:
            problems.append("%s: day %d has no %s" % (path, number, ", ".join(missing)))
        deeper = section.split("**Go deeper**")[-1]
        if "**Go deeper**" in section and not MD_LINK.search(prose(deeper)):
            problems.append("%s: day %d has no link under Go deeper" % (path, number))
    return problems


def resume_problems(root: Path = learning.RESUME_LEARNING) -> List[str]:
    problems = []
    have = {path.name[:2]: path for path in root.glob("[0-9][0-9]-*.md")}
    for number, slug, _ in learning.RESUME_AREAS:
        path = have.get(number)
        if not path:
            problems.append("%s: no %s-%s.md" % (root, number, slug))
            continue
        text = path.read_text(encoding="utf-8")
        problems += _hygiene(path, text)
        if _CONTACT.search(prose(text)):
            problems.append("%s: has contact details" % path)
        missing = [section for section in RESUME_SECTIONS if section not in text]
        if missing:
            problems.append("%s: no %s" % (path, ", ".join(missing)))
        if len(re.findall(r"^(?:###|\*\*Q)", text, re.M)) < 5:
            problems.append("%s: fewer than 5 interview questions" % path)
    index = root / "README.md"
    if not index.exists():
        problems.append("%s: missing" % index)
    else:
        problems += link_problems(index)
    return problems


def day_problems(day: date, learning_root: Path = learning.LEARNING,
                 daily_root: Path = briefing.DAILY) -> List[str]:
    """What the pipeline should have written for `day`: the study notes and the briefing."""
    problems = []
    notes = learning_root / "daily" / ("%s.md" % day.isoformat())
    if not notes.exists():
        problems.append("%s: missing (stage learn)" % notes)
    else:
        text = notes.read_text(encoding="utf-8")
        if not text.startswith("# %s: Day " % day.isoformat()):
            problems.append("%s: not headed with the date" % notes)
        if not learning.split_days(text):
            problems.append("%s: has no study day" % notes)
        if "## From the course" not in text:
            problems.append("%s: has no 'From the course' part" % notes)
        problems += link_problems(notes)
    today = learning_root / "today.md"
    if today.exists():
        problems += link_problems(today)
    folder = briefing.folder_for(day, daily_root)
    for agent in briefing.AGENTS:
        path = folder / agent.filename
        if not path.exists():
            problems.append("%s: missing (stage brief:%s)" % (path, agent.key))
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith(agent.heading):
            problems.append("%s: does not start with '%s'" % (path, agent.heading))
        try:
            briefing.check(agent, text, day)
        except Exception as exc:
            problems.append("%s: %s" % (path, exc))
        problems += _hygiene(path, text)
    index = folder / "README.md"
    if not index.exists():
        problems.append("%s: missing" % index)
    else:
        problems += link_problems(index)
    return problems


def all_problems(day: Optional[date] = None, research: Path = learning.RESEARCH,
                 course_root: Path = course.COURSE) -> List[str]:
    """Every problem in the 90-day plan, the course, the resume files and the day's material."""
    day = day or date.today()
    learning_root = research / "learning"
    problems = []
    for week in range(1, learning.week_of(learning.LAST_DAY) + 1):
        problems += week_problems(week, learning_root)
    problems += course.problems(course_root, learning_root)
    problems += resume_problems(research / "resume-learning")
    problems += day_problems(day, learning_root, research / "daily")
    for name in ("tech-radar.md", "companies-to-watch.md"):
        path = research / name
        if path.exists():
            problems += _hygiene(path, path.read_text(encoding="utf-8"))
    return problems
