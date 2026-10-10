"""Find something worth reacting to: RSS, Atom and Hacker News, scored by topic."""

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .config import LinkedInSettings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FEED_TIMEOUT_S = 15
ARTICLE_TIMEOUT_S = 20
MAX_TEXT_CHARS = 6000
MIN_TEXT_CHARS = 600
MAX_FETCHES = 5

_ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Article:
    title: str
    url: str
    source: str = ""
    published: Optional[datetime] = None
    summary: str = ""
    text: str = ""
    score: float = 0.0
    points: int = 0


def normalise_url(url: str) -> str:
    parts = urlparse(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    cleaned = parts._replace(
        scheme=parts.scheme.lower() or "https",
        netloc=parts.netloc.lower(),
        query=urlencode(query),
        fragment="",
    )
    return urlunparse(cleaned).rstrip("/")


def _parse_date(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _strip_html(value: str) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _text(node: Optional[ET.Element]) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_rss(body: str) -> List[Article]:
    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        return []
    source = _text(channel.find("title"))
    articles = []  # type: List[Article]
    for item in channel.findall("item"):
        url = _text(item.find("link"))
        title = _text(item.find("title"))
        if not url or not title:
            continue
        articles.append(
            Article(
                title=title,
                url=url,
                source=source,
                published=_parse_date(_text(item.find("pubDate"))),
                summary=_strip_html(_text(item.find("description")))[:600],
            )
        )
    return articles


def parse_atom(body: str) -> List[Article]:
    root = ET.fromstring(body)
    source = _text(root.find(_ATOM + "title"))
    articles = []  # type: List[Article]
    for entry in root.findall(_ATOM + "entry"):
        url = ""
        for link in entry.findall(_ATOM + "link"):
            rel = link.get("rel", "alternate")
            if rel == "alternate" and link.get("href"):
                url = link.get("href", "")
                break
        title = _text(entry.find(_ATOM + "title"))
        if not url or not title:
            continue
        when = _text(entry.find(_ATOM + "published")) or _text(entry.find(_ATOM + "updated"))
        summary = _text(entry.find(_ATOM + "summary")) or _text(entry.find(_ATOM + "content"))
        articles.append(
            Article(
                title=title,
                url=url,
                source=source,
                published=_parse_date(when),
                summary=_strip_html(summary)[:600],
            )
        )
    return articles


def parse_hn(payload: Dict[str, Any]) -> List[Article]:
    articles = []  # type: List[Article]
    for hit in payload.get("hits", []):
        url = (hit.get("url") or "").strip()
        title = (hit.get("title") or "").strip()
        if not url or not title:
            continue
        articles.append(
            Article(
                title=title,
                url=url,
                source="",
                published=_parse_date(hit.get("created_at") or ""),
                points=int(hit.get("points") or 0),
            )
        )
    return articles


def parse_feed(body: str) -> List[Article]:
    stripped = body.lstrip()
    if stripped.startswith("{"):
        return parse_hn(json.loads(stripped))
    root = ET.fromstring(stripped)
    if root.tag == _ATOM + "feed":
        return parse_atom(stripped)
    return parse_rss(stripped)


def fetch_feed(url: str) -> str:
    response = requests.get(
        url, timeout=FEED_TIMEOUT_S, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    return response.text


def _topic_words(topics: List[str]) -> List[Tuple[str, List[str]]]:
    result = []
    for topic in topics:
        phrase = topic.strip().lower()
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9.+#-]*", phrase) if len(w) > 2]
        result.append((phrase, words))
    return result


def score_article(article: Article, topics: List[str], now: datetime) -> float:
    haystack = ("%s %s" % (article.title, article.summary)).lower()
    score = 0.0
    for phrase, words in _topic_words(topics):
        if phrase and re.search(r"\b%s\b" % re.escape(phrase), haystack):
            score += 3
        for word in words:
            if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word), haystack):
                score += 1
    if article.published is not None:
        age = now - article.published
        if age < timedelta(hours=24):
            score += 2
        elif age < timedelta(hours=48):
            score += 1
    if article.points >= 100:
        score += 1
    return score


def _seen_urls(state: Dict[str, Any]) -> set:
    seen = set()
    for key in ("posted", "skipped"):
        for entry in state.get(key, []):
            url = entry.get("url") if isinstance(entry, dict) else entry
            if url:
                seen.add(normalise_url(url))
    return seen


def fetch_candidates(
    settings: LinkedInSettings,
    state: Dict[str, Any],
    now: Optional[datetime] = None,
) -> List[Article]:
    """Every fresh, unseen item across the feeds, best match first."""
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(days=settings.max_age_days)
    seen = _seen_urls(state)
    candidates = []  # type: List[Article]
    for feed_url in settings.feeds:
        try:
            items = parse_feed(fetch_feed(feed_url))
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            logger.warning("Skipping feed %s (%s): %s", feed_url, type(exc).__name__, exc)
            continue
        for article in items:
            key = normalise_url(article.url)
            if not key or key in seen:
                continue
            if article.published is not None and article.published < oldest:
                continue
            seen.add(key)
            article.url = key
            article.score = score_article(article, settings.topics, now)
            candidates.append(article)
    candidates.sort(key=lambda a: (a.score, a.published or oldest), reverse=True)
    return candidates


def fetch_article_text(url: str) -> Tuple[str, str]:
    """(body text, site name); ("", "") when the page cannot be read."""
    try:
        response = requests.get(
            url, timeout=ARTICLE_TIMEOUT_S, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not read %s (%s): %s", url, type(exc).__name__, exc)
        return "", ""

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()

    container = soup.find("article")
    if container is None:
        best_len = 0
        for parent in soup.find_all(["div", "section", "main", "body"]):
            length = sum(len(p.get_text(" ", strip=True)) for p in parent.find_all("p", recursive=False))
            if length > best_len:
                best_len, container = length, parent
    if container is None:
        return "", ""

    paragraphs = [
        re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        for p in container.find_all("p")
    ]
    text = "\n\n".join(p for p in paragraphs if len(p) > 40)[:MAX_TEXT_CHARS]

    site = ""
    meta = soup.find("meta", attrs={"property": "og:site_name"})
    if meta is not None and meta.get("content"):
        site = meta["content"].strip()
    elif soup.title is not None and soup.title.string:
        site = soup.title.string.strip()
    return text, site


def pick_article(
    settings: LinkedInSettings,
    state: Dict[str, Any],
    candidates: Optional[List[Article]] = None,
) -> Optional[Article]:
    """Best-scored candidate with enough readable body text to react to."""
    if candidates is None:
        candidates = fetch_candidates(settings, state)
    for article in candidates[:MAX_FETCHES]:
        text, site = fetch_article_text(article.url)
        if len(text) < MIN_TEXT_CHARS:
            logger.info("Not enough text at %s; trying the next one", article.url)
            continue
        article.text = text
        if not article.source:
            article.source = site or urlparse(article.url).netloc
        return article
    return None
