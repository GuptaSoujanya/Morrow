"""An image card designed by Claude or Kiro as HTML, drawn to PNG by headless Chrome.

Nothing is fetched: the page may not load scripts, fonts or images, and Chrome
renders a local file. Any failure returns None so the caller can draw the
Pillow card from card.py instead.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from PIL import Image, ImageStat

from common import ai_cli
from common import persona as persona_module

from .news import Article
from .writer import Draft

logger = logging.getLogger(__name__)

CARD_W, CARD_H = 1200, 627
SCALE = 2
MAX_DESIGNS = 2
CHROME_TIMEOUT_S = 90
MIN_CONTRAST = 12.0

_CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

_PROMPT = """Design a LinkedIn image card as ONE self-contained HTML document.

The card goes with the post below by %(author)s (%(about)s). Readers see it at
phone size in a busy feed.

Hard rules:
- The page is exactly %(w)dpx wide and %(h)dpx tall: set html and body to that
  size, margin 0, overflow hidden. Keep every piece of text at least 56px from
  the edges and make sure nothing overlaps or is cut off.
- Inline <style> only. No <script>, no external fonts, images, links or URLs of
  any kind. Use the font stack -apple-system, "Avenir Next", "Helvetica Neue",
  Arial, sans-serif, and "SF Mono", Menlo, monospace for code-like labels.
- Visuals from HTML and CSS (or inline <svg>) only: shapes, a simple diagram,
  a bar or number comparison, a code-window frame. No emoji.
- The headline is this line, word for word: %(card_line)s
- Headline at least 54px and bold; at most 30 words of text on the whole card.
- Add one supporting visual built from a concrete detail in the post (a number,
  a before/after, a small flow of steps). Use only facts from the post.
- Small footer: "%(author)s"%(footer_site)s, plus "via %(source)s".
- Palette: ink #0B1220, body #334155, muted #64748B, page #F7F7F5, accent #4F46E5,
  soft accent #E0E7FF. A dark variant (#0B1220 page, #A5B4FC accent) is fine.
  Strong contrast, generous whitespace, one clear focal point.
%(feedback)s
POST
%(post)s

Reply with the HTML document only, starting with <!DOCTYPE html>."""

_CHECK_SCHEMA = '{"ok": true, "problems": ["string"]}'
_CHECK_PROMPT = (
    "This is a %dx%d LinkedIn image card. The headline should read: %s\n"
    "Check it as a designer would. List real problems only: text cut off, clipped or "
    "overlapping; text running off the edge; a misspelt or different headline; poor "
    "contrast; an empty or broken layout; anything unreadable at phone size. "
    'Answer {"ok": true, "problems": []} when it is ready to post.'
)

_FORBIDDEN = re.compile(r"<script|<iframe|<link|<img|@import|javascript:|https?://(?!www\.w3\.org/)|url\(\s*['\"]?(?!#)", re.I)


def find_chrome() -> Optional[str]:
    configured = os.getenv("LINKEDIN_CHROME", "").strip()
    if configured:
        return configured if os.path.exists(configured) else None
    for path in _CHROME_PATHS:
        if os.path.exists(path):
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_from(answer: str) -> Optional[str]:
    """The HTML document in the answer, without fences or chatter around it."""
    match = re.search(r"(<!DOCTYPE html.*?</html>|<html.*?</html>)", answer, re.I | re.S)
    return match.group(1).strip() if match else None


def unsafe_reason(html: str) -> str:
    """Why this page may not be rendered, or "" when it is self-contained."""
    found = _FORBIDDEN.search(html)
    if found:
        return "the page uses %r; it must not load scripts, files or URLs" % found.group(0)
    return ""


def render_html(html_path: Path, out_path: Path, chrome: str) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with tempfile.TemporaryDirectory(prefix="linkedin-card-") as profile:
        command = [
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--user-data-dir=%s" % profile,
            "--window-size=%d,%d" % (CARD_W, CARD_H),
            "--force-device-scale-factor=%d" % SCALE,
            "--screenshot=%s" % out_path,
            html_path.resolve().as_uri(),
        ]
        try:
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=CHROME_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Headless Chrome could not draw the card: %s", exc)
            return False
    return out_path.is_file()


def image_problem(path: Path) -> str:
    """Why the PNG is not a usable card, or "" when it is."""
    with Image.open(path) as image:
        if image.size != (CARD_W * SCALE, CARD_H * SCALE):
            return "the image is %dx%d, not %dx%d" % (image.size + (CARD_W * SCALE, CARD_H * SCALE))
        spread = ImageStat.Stat(image.convert("L")).stddev[0]
    if spread < MIN_CONTRAST:
        return "the image is nearly one flat colour"
    return ""


def _looked_at(reviewer: Any, png: Path, card_line: str) -> List[str]:
    check = getattr(reviewer, "complete_json_with_image", None)
    if check is None:
        return []
    payload = check(_CHECK_PROMPT % (CARD_W, CARD_H, card_line), _CHECK_SCHEMA, png)
    if not payload or payload.get("ok") is True:
        return []
    problems = payload.get("problems")
    return [str(p).strip() for p in problems if str(p).strip()][:4] if isinstance(problems, list) else []


def design_card(
    draft: Draft, article: Article, out_path: Path, cli: str, timeout_s: int, reviewer: Any = None
) -> Optional[Path]:
    """A designed PNG card at out_path, or None when no good one could be made."""
    chrome = find_chrome()
    if chrome is None:
        logger.warning("No Chrome found for the designed card (set LINKEDIN_CHROME); using the drawn card")
        return None
    html_path = out_path.with_suffix(".html")
    if out_path.exists():
        out_path.unlink()
    feedback = []  # type: List[str]
    who = persona_module.load_persona()
    author = who.name or "the author"
    about = "; ".join(part for part in [who.headline, "site " + who.site if who.site else ""] if part) or "the author"
    for attempt in range(1, MAX_DESIGNS + 1):
        note = ""
        if feedback:
            note = "- The last version had these problems; fix them:\n  " + "\n  ".join(feedback) + "\n"
        prompt = _PROMPT % {
            "w": CARD_W, "h": CARD_H, "card_line": draft.card_line, "source": article.source,
            "feedback": note, "post": draft.text, "author": author, "about": about,
            "footer_site": ' and "%s"' % who.site if who.site else "",
        }
        logger.info("Asking %s to design the card (attempt %d)...", cli, attempt)
        try:
            answer = ai_cli.ask(prompt, cli, timeout_s, web=False)
        except ai_cli.AIError as exc:
            logger.warning("Card design failed: %s", exc)
            return None
        html = html_from(answer)
        problem = "the reply held no HTML document" if html is None else unsafe_reason(html)
        if not problem:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html or "", encoding="utf-8")
            if not render_html(html_path, out_path, chrome):
                return None
            problem = image_problem(out_path)
        feedback = [problem] if problem else (_looked_at(reviewer, out_path, draft.card_line) if reviewer else [])
        if not feedback:
            logger.info("Designed card saved to %s", out_path)
            return out_path
        logger.info("Design attempt %d rejected: %s", attempt, "; ".join(feedback))
    if out_path.exists() and not image_problem(out_path):
        logger.warning("Keeping the last designed card despite: %s", "; ".join(feedback))
        return out_path
    return None
