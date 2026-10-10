"""Turn an article into a short post that reads like the author wrote it."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .news import Article

logger = logging.getLogger(__name__)

VOICE = """Facts about the author (the only facts a post may use):
- Soujanya Gupta, software engineer at Ethara AI in Gurugram.
- Works on evaluating AI agents and large language models.
- Grew the open-source WildClawBench benchmark on the OpenClaw harness into a
  multi-provider evaluation platform: three-judge council grading, drift
  injection across 100+ mock services, bounded multi-agent orchestration, and
  cost tracking for Claude on AWS Bedrock, GPT-5.5 and OpenRouter.
- Builds Next.js front-ends and LangChain pipelines.
- Wrote prompts and rubrics for a LLaMA 4 Maverick fine-tuning program.
- Site: soujanyalab.in

How she writes: first person, plain words, short paragraphs, concrete, a little
dry, never salesy. For register, the opening of her resume summary: "I'm a
software engineer who works on evaluating AI agents and large language models.
Most of my time goes into growing the open-source WildClawBench benchmark on
the OpenClaw harness into a full multi-provider evaluation platform."
"""

MIN_CHARS = 450
MAX_CHARS = 1300
PROMPT_MAX_CHARS = 1100
MAX_HASHTAGS = 3
MAX_ATTEMPTS = 3
PARROT_WORDS = 12
PARROT_OVERLAP = 0.6

BANNED_PHRASES = (
    "excited",
    "thrilled",
    "honored",
    "honoured",
    "humbled",
    "game-changer",
    "game changer",
    "delve",
    "dive deep",
    "deep dive",
    "unlock",
    "leverage",
    "revolutioni",
    "seamless",
    "cutting-edge",
    "cutting edge",
    "in today's fast-paced",
    "journey",
    "synergy",
    "empower",
    "elevate",
    "landscape",
    "testament",
    "tapestry",
    "let that sink in",
    "thoughts?",
    "agree?",
    "i'm excited to share",
    "i am excited to share",
    "i'm proud to",
    "i am proud to",
    "linkedin fam",
    "as an ai",
)

_CONSTRUCTIONS = (
    re.compile(r"\bit'?s not (about )?[^.,;]{1,60},? it'?s\b", re.IGNORECASE),
    re.compile(r"\bthis isn'?t about\b", re.IGNORECASE),
)
_DASHES = ("\u2014", "\u2013")
_LIST_LINE = re.compile(r"^\s*(?:[-*\u2022]|\d+\.)\s")
_URL_LINE = re.compile(r"^https?://\S+$")
_ALLOWED_HIGH = set("\u2018\u2019\u201c\u201d\u2026\u00a0\u00e9\u00e8\u00fc\u00f6\u00e4\u00e1\u00ed\u00f3\u00fa\u00f1")


@dataclass
class Draft:
    text: str
    card_line: str
    hashtags: List[str] = field(default_factory=list)
    source_url: str = ""
    source_title: str = ""


def lint(text: str) -> List[str]:
    """Every reason this text does not pass as a plain human post."""
    problems = []  # type: List[str]
    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            problems.append("contains the banned phrase %r" % phrase)
    for pattern in _CONSTRUCTIONS:
        if pattern.search(text):
            problems.append("uses an 'it's not X, it's Y' style construction")
    for dash in _DASHES:
        if dash in text:
            problems.append("contains an em dash or en dash; use a comma or a full stop")
            break
    if any(ord(ch) > 0x2600 for ch in text):
        problems.append("contains an emoji or symbol")
    elif any(ord(ch) > 0x2000 and ch not in _ALLOWED_HIGH for ch in text):
        problems.append("contains an unusual symbol")
    if text.count("!") > 1:
        problems.append("more than one exclamation mark")
    if len(re.findall(r"(?<!\w)#\w+", text)) > MAX_HASHTAGS:
        problems.append("more than %d hashtags" % MAX_HASHTAGS)
    lines = [line for line in text.splitlines()]
    if any(_LIST_LINE.match(line) for line in lines):
        problems.append("contains a bullet or numbered list")
    body = [line for line in lines if line.strip() and not _URL_LINE.match(line.strip())]
    for line in body:
        words = line.split()
        if len(words) <= 8 and len(words) >= 3 and _looks_title_case(words):
            problems.append("has a Title Case headline: %r" % line.strip())
            break
    length = len(text.strip())
    if length < MIN_CHARS:
        problems.append("too short: %d characters, needs at least %d" % (length, MIN_CHARS))
    if length > MAX_CHARS:
        problems.append("too long: %d characters, at most %d" % (length, MAX_CHARS))
    stripped = [line.strip() for line in lines if line.strip()]
    if not stripped or not _URL_LINE.match(stripped[-1]):
        problems.append("the article URL must be the last line, on its own")
    return problems


def _looks_title_case(words: List[str]) -> bool:
    small = {"a", "an", "the", "of", "and", "or", "to", "in", "on", "for", "with", "vs"}
    capitalised = [w for w in words if w[0].isupper() and w.lower() not in small]
    if any(w.endswith((".", "?", ":")) for w in words):
        return False
    return len(capitalised) >= max(3, len(words) - len(small & {w.lower() for w in words}))


def parrots_headline(text: str, title: str) -> bool:
    """True when the post opens by restating the article headline."""
    head = re.findall(r"[a-z0-9']+", text.lower())[:PARROT_WORDS]
    title_words = set(re.findall(r"[a-z0-9']+", title.lower()))
    if not head or not title_words:
        return False
    shared = sum(1 for w in head if w in title_words)
    return shared / float(len(head)) > PARROT_OVERLAP


def render_text(draft: Draft) -> str:
    text = draft.text.strip()
    tags = [t if t.startswith("#") else "#" + t for t in draft.hashtags if t.strip()]
    if tags:
        text = "%s\n\n%s" % (text, " ".join(tags))
    return text


_SCHEMA = '{"post": "string", "card_line": "string", "hashtags": ["string"]}'


def build_prompt(article: Article, voice: str, feedback: Optional[List[str]] = None) -> str:
    rules = """Write a LinkedIn post reacting to the article below, as the author described
under VOICE. Return JSON only: %s

Rules:
- First person, 2 to 4 short paragraphs, %d to %d characters in total.
- Include ONE concrete detail from the article: a number, a name or a specific
  claim, paraphrased in your own words. No invented quotes, no made-up numbers.
- Connect it to ONE thing from the author's own work, using only the VOICE
  facts. Claim nothing else about the author.
- End with either a plain question to readers or a one-line takeaway, not both.
- The last line is the article URL on its own, with nothing else on that line.
- "card_line": one sentence under 90 characters, in the author's words, that
  could stand alone on an image. Not the article headline.
- "hashtags": 0 to 3, lowercase, no spaces, without the # sign.
- Do not open by restating the headline.

Never use: emojis; em dashes or en dashes; exclamation marks; bullet or
numbered lists; headlines in Title Case; the words or phrases excited, thrilled,
honored, humbled, game-changer, delve, dive deep, deep dive, unlock, leverage,
revolutionize, seamless, cutting-edge, in today's fast-paced, journey, synergy,
empower, elevate, landscape, testament, tapestry; "it's not X, it's Y" or
"this isn't about X" constructions; rhetorical triplets; "Let that sink in";
"Thoughts?"; "Agree?"; "I'm excited to share"; "I'm proud to"; anything
addressed to "LinkedIn fam"; advice lists.
""" % (_SCHEMA, MIN_CHARS, PROMPT_MAX_CHARS)
    parts = [rules, "VOICE:\n" + voice.strip()]
    if feedback:
        parts.append("Rewrite; fix these problems:\n- " + "\n- ".join(feedback))
    parts.append(
        "ARTICLE\nTitle: %s\nSource: %s\nURL: %s\n\n%s"
        % (article.title, article.source, article.url, article.text[:6000])
    )
    return "\n\n".join(parts)


def _draft_from(payload: Dict[str, Any], article: Article) -> Optional[Draft]:
    post = payload.get("post")
    card_line = payload.get("card_line")
    if not isinstance(post, str) or not isinstance(card_line, str):
        return None
    tags = payload.get("hashtags") or []
    if not isinstance(tags, list):
        tags = []
    hashtags = [
        re.sub(r"[^a-z0-9]", "", str(tag).lower().lstrip("#")) for tag in tags
    ][:MAX_HASHTAGS]
    text = post.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not _URL_LINE.match(lines[-1]):
        text = "%s\n\n%s" % (text, article.url)
    return Draft(
        text=text,
        card_line=card_line.strip(),
        hashtags=[t for t in hashtags if t],
        source_url=article.url,
        source_title=article.title,
    )


def check_draft(draft: Draft, article: Article) -> List[str]:
    problems = lint(draft.text)
    if parrots_headline(draft.text, article.title):
        problems.append("the opening restates the article headline; start somewhere else")
    if not draft.card_line:
        problems.append("card_line is empty")
    elif len(draft.card_line) >= 90:
        problems.append("card_line must be under 90 characters")
    elif any(ord(ch) > 0x2600 for ch in draft.card_line) or any(
        d in draft.card_line for d in _DASHES
    ):
        problems.append("card_line contains an emoji or a dash")
    return problems


def write_post(client: Any, article: Article, voice: str = VOICE) -> Optional[Draft]:
    """Up to three attempts; lint findings go back to the model between them."""
    feedback = None  # type: Optional[List[str]]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        payload = client.complete_json(build_prompt(article, voice, feedback), _SCHEMA)
        if not payload:
            logger.warning("Attempt %d: the model returned nothing usable", attempt)
            feedback = ["return the JSON object described above"]
            continue
        draft = _draft_from(payload, article)
        if draft is None:
            feedback = ["return 'post' and 'card_line' as strings"]
            continue
        problems = check_draft(draft, article)
        if not problems:
            return draft
        logger.info("Attempt %d rejected: %s", attempt, "; ".join(problems))
        feedback = problems
    return None
