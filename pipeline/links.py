"""Markdown links in the study material: bare URLs made clickable, relative links moved, broken ones found."""

import os
import re
from pathlib import Path
from typing import List

_FENCE = re.compile(r"```.*?```", re.S)
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_BARE_ITEM = re.compile(r"^([ \t]*- )(.+?)(?:[ \t]+(?:—|–|-)|:)[ \t]+((?:https?://|(?:\.\./)+)\S+?)\.?[ \t]*$", re.M)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_BARE = re.compile(r"(?<![(\[<`\w/.])((?:https?://|(?:\.\./)+)[^\s)>\]]+[^\s)>\].,;])")


def prose(text: str) -> str:
    """The text without fenced code blocks, where link-like strings are code, not links."""
    return _FENCE.sub("", text)


def _outside_code(text: str, fix) -> str:
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    return "".join(part if part.startswith("```") else fix(part) for part in parts)


def linkify(text: str) -> str:
    """Turn bare URLs and course paths into markdown links ("- label: url" becomes "- [label](url)")."""
    def fix(part: str) -> str:
        part = _BARE_ITEM.sub(lambda m: "%s[%s](%s)" % (m.group(1), m.group(2).strip(), m.group(3)), part)
        return _BARE.sub(lambda m: "[%s](%s)" % (m.group(1), m.group(1)), part)
    return _outside_code(text, fix)


def relink(text: str, src: Path, dst: Path) -> str:
    """Rewrite relative links written for a file in folder `src` so they work from folder `dst`."""
    src, dst = Path(src).resolve(), Path(dst).resolve()

    def move(match: "re.Match") -> str:
        target = match.group(1)
        if re.match(r"[a-z]+:|#|/", target):
            return match.group(0)
        path, _, anchor = target.partition("#")
        moved = Path(_relative(src / path, dst))
        return "](%s%s)" % (moved.as_posix(), "#" + anchor if anchor else "")

    return _outside_code(text, lambda part: MD_LINK.sub(move, part))


def _relative(path: Path, start: Path) -> str:
    return os.path.relpath(os.path.normpath(str(path)), str(start))


def slug(heading: str) -> str:
    """A heading's anchor, the way the course site (docsify) and GitHub make it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def headings(text: str) -> List[tuple]:
    """(level, title, start offset) of every heading outside code blocks."""
    found = []
    for match in HEADING.finditer(text):
        if text.count("```", 0, match.start()) % 2:
            continue  # inside a fenced block
        found.append((len(match.group(1)), match.group(2), match.start()))
    return found


def link_problems(path: Path) -> List[str]:
    """Relative links in a markdown file that point at nothing, or at a heading that is not there."""
    text = prose(path.read_text(encoding="utf-8"))
    problems = []
    for target in MD_LINK.findall(text):
        if re.match(r"[a-z]+:|#", target):
            continue
        file, _, anchor = target.partition("#")
        linked = path.parent / file
        if not linked.exists():
            problems.append("%s: broken link %s" % (path, target))
        elif anchor and linked.suffix == ".md" and anchor not in {
                slug(title) for _, title, _ in headings(linked.read_text(encoding="utf-8"))}:
            problems.append("%s: link %s points at no heading" % (path, target))
    return problems
