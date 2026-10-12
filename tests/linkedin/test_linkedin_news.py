"""Feed parsing and article selection for the LinkedIn poster, without network."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from linkedin_bot import news
from linkedin_bot.config import LinkedInSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example Wire</title>
<item><title>New LLM benchmarks for agents</title><link>https://example.com/a?utm_source=rss&amp;id=1#top</link>
<pubDate>Sat, 10 Oct 2026 09:00:00 GMT</pubDate><description><![CDATA[<p>Multi-agent systems get a new <b>evaluation</b> suite.</p>]]></description></item>
<item><title>Old news</title><link>https://example.com/old</link>
<pubDate>Mon, 01 Sep 2026 09:00:00 GMT</pubDate><description>Nothing on topic</description></item>
<item><title>No link here</title><description>skip</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Blog</title>
<entry><title>Shipping a Next.js dashboard</title>
<link rel="alternate" href="https://blog.example.org/nextjs"/>
<published>2026-10-09T20:00:00Z</published><summary>Notes on Next.js and LangChain.</summary></entry>
<entry><title>Weekend links</title>
<link rel="alternate" href="https://blog.example.org/links"/>
<updated>2026-10-08T08:00:00Z</updated><content type="html">&lt;p&gt;Assorted&lt;/p&gt;</content></entry>
</feed>"""

HN = {
    "hits": [
        {"title": "LangChain 1.0 released", "url": "https://langchain.example/1", "created_at": "2026-10-10T10:00:00Z", "points": 240},
        {"title": "Ask HN: no url", "url": None, "created_at": "2026-10-10T10:00:00Z", "points": 50},
    ]
}


def _settings(**overrides):
    values = dict(
        topics=["AI agent evaluation", "LLM benchmarks", "multi-agent systems", "LangChain", "Next.js"],
        feeds=["rss", "atom", "hn", "broken"],
        max_age_days=3,
    )
    values.update(overrides)
    return LinkedInSettings(**values)


def _fake_fetch(url):
    bodies = {"rss": RSS, "atom": ATOM, "hn": '{"hits": %s}' % __import__("json").dumps(HN["hits"])}
    if url not in bodies:
        raise news.requests.RequestException("boom")
    return bodies[url]


def test_rss_items_are_parsed_with_source_and_clean_summary():
    items = news.parse_rss(RSS)
    assert [a.title for a in items] == ["New LLM benchmarks for agents", "Old news"]
    assert items[0].source == "Example Wire"
    assert items[0].summary == "Multi-agent systems get a new evaluation suite."
    assert items[0].published == datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def test_atom_entries_use_the_alternate_link_and_updated_as_fallback():
    items = news.parse_atom(ATOM)
    assert [a.url for a in items] == ["https://blog.example.org/nextjs", "https://blog.example.org/links"]
    assert items[1].published == datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    assert items[1].summary == "Assorted"


def test_hn_hits_without_a_url_are_skipped():
    items = news.parse_hn(HN)
    assert len(items) == 1
    assert items[0].points == 240


def test_parse_feed_sniffs_json_atom_and_rss():
    assert news.parse_feed('{"hits": []}') == []
    assert news.parse_feed(ATOM)[0].source == "Atom Blog"
    assert news.parse_feed(RSS)[0].source == "Example Wire"


def test_utm_parameters_and_fragments_are_stripped():
    assert news.normalise_url("https://Example.com/a?utm_source=rss&id=1#top") == "https://example.com/a?id=1"
    assert news.normalise_url("https://example.com/a/") == "https://example.com/a"


def test_candidates_are_scored_fresh_deduped_and_sorted(monkeypatch):
    monkeypatch.setattr(news, "fetch_feed", _fake_fetch)
    state = {"posted": [{"url": "https://blog.example.org/nextjs"}], "skipped": []}

    candidates = news.fetch_candidates(_settings(), state, now=NOW)

    urls = [a.url for a in candidates]
    assert "https://example.com/old" not in urls, "older than max_age_days"
    assert "https://blog.example.org/nextjs" not in urls, "already posted"
    assert urls[0] == "https://example.com/a?id=1", "two topic phrases, fresh: scores highest"
    assert urls[1] == "https://langchain.example/1", "one topic, fresh, 100+ points"
    assert candidates[0].score > candidates[1].score > candidates[-1].score


def test_scoring_weights_phrases_words_recency_and_points():
    fresh = news.Article(title="LLM benchmarks for multi-agent systems", url="u", published=NOW - timedelta(hours=1))
    stale = news.Article(title="LLM benchmarks for multi-agent systems", url="u", published=NOW - timedelta(hours=30))
    popular = news.Article(title="Nothing related", url="u", published=NOW - timedelta(days=5), points=150)
    topics = ["LLM benchmarks", "multi-agent systems"]
    assert news.score_article(fresh, topics, NOW) == 3 + 2 + 3 + 2 + 2
    assert news.score_article(stale, topics, NOW) == 3 + 2 + 3 + 2 + 1
    assert news.score_article(popular, topics, NOW) == 1


def test_pick_article_skips_pages_with_too_little_text(monkeypatch):
    short = news.Article(title="short", url="https://a.example/short", score=9)
    good = news.Article(title="good", url="https://a.example/good", score=5)
    bodies = {short.url: ("too short", "A"), good.url: ("x" * 700, "Good Site")}
    monkeypatch.setattr(news, "fetch_article_text", lambda url: bodies[url])

    picked = news.pick_article(_settings(), {}, candidates=[short, good])

    assert picked is good
    assert picked.text == "x" * 700
    assert picked.source == "Good Site"


def test_pick_article_returns_none_when_nothing_is_readable(monkeypatch):
    monkeypatch.setattr(news, "fetch_article_text", lambda url: ("", ""))
    only = news.Article(title="t", url="https://a.example/t")
    assert news.pick_article(_settings(), {}, candidates=[only]) is None
