"""Read the whole article with a web-enabled CLI, so the post can use its real specifics.

A feed only gives a headline and a snippet; posts written from that come out generic.
"""

import logging

from common import ai_cli

from .news import Article

logger = logging.getLogger(__name__)

NOTES_MAX_CHARS = 4000

_PROMPT = """Open and read this article in full: %s
(Title: %s, from %s.)

Write plain-text research notes for someone who will react to it in a short post.
Give, as short plain lines:
- what is actually new, in one or two sentences
- every concrete number, name, benchmark, model, company or date it states
- the strongest claim, and any limitation or caveat it admits
- one point where people working on AI agents or evaluation might disagree

Only what the article (or a source it links) says. Mark anything you are unsure of
with "(unsure)". If the page cannot be opened, say so in one line and stop.
No preamble, no markdown headings."""


def research(article: Article, cli: str, timeout_s: int) -> str:
    """Notes on the full article, or "" when no CLI could read it."""
    logger.info("Reading the full article with %s...", cli)
    try:
        answer = ai_cli.ask(_PROMPT % (article.url, article.title, article.source), cli, timeout_s)
    except ai_cli.AIError as exc:
        logger.warning("Could not research the article (%s); writing from the feed text", exc)
        return ""
    return answer.strip()[:NOTES_MAX_CHARS]
