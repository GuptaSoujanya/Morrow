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
HOOK_MAX_CHARS = 110
MIN_SLIDES = 4
MAX_SLIDES = 7
SLIDE_TITLE_MAX = 60
SLIDE_BODY_MAX = 240
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
    slides: List[Dict[str, str]] = field(default_factory=list)
    question: str = ""
    subtitle: str = ""


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
    if not tags:
        return text
    lines = text.splitlines()
    if lines and _URL_LINE.match(lines[-1].strip()):
        # Hashtags go above the link so the article URL stays on the last line.
        body = "\n".join(lines[:-1]).rstrip()
        return "%s\n\n%s\n\n%s" % (body, " ".join(tags), lines[-1].strip())
    return "%s\n\n%s" % (text, " ".join(tags))


_SCHEMA = (
    '{"post": "string", "card_line": "string", "hashtags": ["string"], '
    '"subtitle": "string", "slides": [{"title": "string", "body": "string"}], '
    '"question": "string"}'
)


def build_prompt(
    article: Article, voice: str, feedback: Optional[List[str]] = None, notes: str = ""
) -> str:
    rules = """Write a LinkedIn post reacting to the article below, as the author described
under VOICE. Return JSON only: %s

Rules:
- First person, 3 to 5 short paragraphs, %d to %d characters in total.
- The FIRST line is a hook on its own: one sentence under %d characters that
  makes a scrolling reader stop. Use a surprising number, a concrete problem or
  a claim from the article that cuts against the usual view. No question here.
- Keep paragraphs to one to three sentences so the post reads well on a phone.
- Include ONE concrete detail from the article: a number, a name or a specific
  claim, paraphrased in your own words. No invented quotes, no made-up numbers.
- Connect it to ONE thing from the author's own work, using only the VOICE
  facts. Claim nothing else about the author.
- One short sentence tells readers the slides walk through the details.
- End with ONE direct question that asks readers about their own experience,
  specific enough that they can answer it in a comment. Same text as "question".
- The last line is the article URL on its own, with nothing else on that line.
- "card_line": one sentence under 90 characters, in the author's words, that
  could stand alone on an image. Not the article headline.
- "hashtags": 0 to 3, lowercase, no spaces, without the # sign.
- "slides": %d to %d slides for a swipeable carousel that explains the idea step
  by step. Each "title" is a short, punchy sentence under %d characters in
  sentence case; each "body" is one or two plain sentences under %d characters
  that make one point. Facts only from the article and VOICE.
- "subtitle": one line under 90 characters for the carousel cover.
- "question": the closing question, under 120 characters.
- Do not open by restating the headline.

Never use: emojis; em dashes or en dashes; exclamation marks; bullet or
numbered lists; headlines in Title Case; the words or phrases excited, thrilled,
honored, humbled, game-changer, delve, dive deep, deep dive, unlock, leverage,
revolutionize, seamless, cutting-edge, in today's fast-paced, journey, synergy,
empower, elevate, landscape, testament, tapestry; "it's not X, it's Y" or
"this isn't about X" constructions; rhetorical triplets; "Let that sink in";
"Thoughts?"; "Agree?"; "I'm excited to share"; "I'm proud to"; anything
addressed to "LinkedIn fam"; advice lists.
""" % (_SCHEMA, MIN_CHARS, PROMPT_MAX_CHARS, HOOK_MAX_CHARS,
       MIN_SLIDES, MAX_SLIDES, SLIDE_TITLE_MAX, SLIDE_BODY_MAX)
    parts = [rules, "VOICE:\n" + voice.strip()]
    if feedback:
        parts.append("Rewrite; fix these problems:\n- " + "\n- ".join(feedback))
    if notes:
        parts.append(
            "RESEARCH NOTES (from reading the full article; take the concrete detail "
            "from here, and skip anything marked unsure)\n" + notes.strip()
        )
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
    lines = post.strip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _URL_LINE.match(lines[-1].strip()):
        # The model's link is replaced: only the article's own URL is posted.
        lines.pop()
    text = "%s\n\n%s" % ("\n".join(lines).strip(), article.url)
    return Draft(
        text=text,
        card_line=card_line.strip(),
        hashtags=[t for t in hashtags if t],
        source_url=article.url,
        source_title=article.title,
        slides=_slides_from(payload.get("slides")),
        question=_clean_str(payload.get("question")),
        subtitle=_clean_str(payload.get("subtitle")),
    )


def _clean_str(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _slides_from(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    slides = []  # type: List[Dict[str, str]]
    for item in value:
        if isinstance(item, dict):
            slides.append({"title": _clean_str(item.get("title")), "body": _clean_str(item.get("body"))})
    return slides


def _bad_symbols(text: str) -> bool:
    return any(ord(ch) > 0x2600 for ch in text) or any(d in text for d in _DASHES)


def check_visuals(draft: Draft) -> List[str]:
    """Problems with the carousel fields; an empty list means it can be drawn."""
    problems = []  # type: List[str]
    if not MIN_SLIDES <= len(draft.slides) <= MAX_SLIDES:
        problems.append("give %d to %d slides, not %d" % (MIN_SLIDES, MAX_SLIDES, len(draft.slides)))
    for number, slide in enumerate(draft.slides, start=1):
        if not slide["title"] or not slide["body"]:
            problems.append("slide %d needs both a title and a body" % number)
        elif len(slide["title"]) > SLIDE_TITLE_MAX:
            problems.append("slide %d title is over %d characters" % (number, SLIDE_TITLE_MAX))
        elif len(slide["body"]) > SLIDE_BODY_MAX:
            problems.append("slide %d body is over %d characters" % (number, SLIDE_BODY_MAX))
        elif _bad_symbols(slide["title"] + slide["body"]):
            problems.append("slide %d contains an emoji or a dash" % number)
        elif any(p in (slide["title"] + " " + slide["body"]).lower() for p in BANNED_PHRASES):
            problems.append("slide %d uses a banned phrase" % number)
    if not draft.question.endswith("?") or len(draft.question) > 120:
        problems.append("'question' must be one question under 120 characters ending in '?'")
    elif _bad_symbols(draft.question):
        problems.append("'question' contains an emoji or a dash")
    if len(draft.subtitle) > 90 or _bad_symbols(draft.subtitle):
        problems.append("'subtitle' must be under 90 characters with no emoji or dash")
    return problems


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
    first = next((line.strip() for line in draft.text.splitlines() if line.strip()), "")
    if len(first) > HOOK_MAX_CHARS:
        problems.append("the first line (the hook) must be one sentence under %d characters" % HOOK_MAX_CHARS)
    if draft.question and draft.question.lower().rstrip("?") not in draft.text.lower():
        problems.append("the post must end with the same question as 'question'")
    return problems


_REVIEW_SCHEMA = '{"verdict": "publish or revise", "problems": ["string"]}'
REVIEW_MAX_PROBLEMS = 4

_REVIEW_PROMPT = """You are a strict editor for a software engineer's LinkedIn posts.
Judge the draft below against the article, the research notes and the author facts.

Ask "revise" only for real problems, each one a concrete fix of one sentence:
- a fact, number or name that the article or notes do not support
- a claim about the author beyond the AUTHOR FACTS
- a hook that a scrolling reader would skip, or one that restates the headline
- vague filler where the article gives a specific detail
- a sentence that sounds like a press release or an AI assistant
- slides that repeat the post instead of explaining the idea step by step
At most %d problems. If the draft is good enough to publish, verdict "publish" and no problems.

AUTHOR FACTS
%s

ARTICLE
Title: %s
URL: %s
%s

RESEARCH NOTES
%s

DRAFT POST
%s

CARD LINE: %s
SLIDES
%s"""


def review(critic: Any, article: Article, draft: Draft, notes: str = "", voice: str = VOICE) -> List[str]:
    """A second model's fixes for a draft that already passes the checks; [] means publish."""
    slides = "\n".join("%s: %s" % (s["title"], s["body"]) for s in draft.slides) or "(none)"
    prompt = _REVIEW_PROMPT % (
        REVIEW_MAX_PROBLEMS, voice.strip(), article.title, article.url, article.text[:3000],
        notes.strip() or "(none)", draft.text, draft.card_line, slides,
    )
    payload = critic.complete_json(prompt, _REVIEW_SCHEMA)
    if not payload:
        logger.warning("The reviewer returned nothing usable; keeping the draft")
        return []
    problems = payload.get("problems")
    if str(payload.get("verdict", "")).strip().lower() != "revise" or not isinstance(problems, list):
        return []
    return [_clean_str(p) for p in problems if _clean_str(p)][:REVIEW_MAX_PROBLEMS]


def write_post(
    client: Any, article: Article, voice: str = VOICE, notes: str = "", critic: Any = None
) -> Optional[Draft]:
    """Up to three attempts; lint findings go back to the model between them.

    With a critic, the first draft that passes the checks goes to it once; its fixes
    become the next attempt's feedback, and that draft is kept if the rewrite fails.
    """
    feedback = None  # type: Optional[List[str]]
    text_only = None  # type: Optional[Draft]
    reviewed = None  # type: Optional[Draft]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        payload = client.complete_json(build_prompt(article, voice, feedback, notes), _SCHEMA)
        if not payload:
            logger.warning("Attempt %d: the model returned nothing usable", attempt)
            feedback = ["return the JSON object described above"]
            continue
        draft = _draft_from(payload, article)
        if draft is None:
            feedback = ["return 'post' and 'card_line' as strings"]
            continue
        problems = check_draft(draft, article)
        visual = check_visuals(draft)
        if not problems and not visual:
            if critic is None or reviewed is not None or attempt == MAX_ATTEMPTS:
                return draft
            fixes = review(critic, article, draft, notes, voice)
            if not fixes:
                logger.info("Attempt %d: the reviewer passed the draft", attempt)
                return draft
            logger.info("Attempt %d: the reviewer asked for: %s", attempt, "; ".join(fixes))
            reviewed = draft
            feedback = fixes
            continue
        if not problems:
            logger.info("Attempt %d: the post is fine, the carousel is not: %s", attempt, "; ".join(visual))
            draft.slides = []
            text_only = draft
        problems += visual
        logger.info("Attempt %d rejected: %s", attempt, "; ".join(problems))
        feedback = problems
    if reviewed is not None:
        logger.warning("The rewrite did not pass the checks; keeping the draft the reviewer saw")
        return reviewed
    if text_only is not None:
        logger.warning("No usable carousel; posting the text with the image card only")
    return text_only
