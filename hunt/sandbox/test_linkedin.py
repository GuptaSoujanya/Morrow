"""Reproductions for the linkedin lane (linkedin_bot/)."""

from pathlib import Path

import pytest

from linkedin_bot import cli, news, writer
from linkedin_bot.config import LinkedInSettings
from linkedin_bot.news import Article, fetch_candidates
from linkedin_bot.writer import Draft

RSS = (
    "<rss><channel><title>t</title>"
    "<item><title>AI agents in production</title><link>{link}</link>{date}</item>"
    "</channel></rss>"
)


def test_linkedin_01_bad_item_link_does_not_abort_the_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: fetch_candidates skips bad feeds and bad items ('Skipping feed')."""
    body = RSS.format(link="http://[::1", date="<pubDate>Wed, 21 Oct 2026 10:00:00 GMT</pubDate>")
    monkeypatch.setattr(news, "fetch_feed", lambda url: body)
    settings = LinkedInSettings(feeds=["https://feed.example/rss"], max_age_days=30)
    candidates = fetch_candidates(settings, {})
    assert isinstance(candidates, list)


def test_linkedin_02_last_line_is_the_article_url() -> None:
    """Contract: 'the article URL alone on the last line' (README, build_prompt)."""
    article = Article(title="Why agents fail", url="https://good.example/a")
    payload = {"post": "A hook.\n\nSome body text here.\n\nhttps://evil.example/x", "card_line": "c"}
    draft = writer._draft_from(payload, article)
    assert draft is not None
    last = draft.text.strip().splitlines()[-1].strip()
    assert last == article.url, last


def test_linkedin_04_undated_items_are_not_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: 'Every fresh, unseen item'; LINKEDIN_MAX_AGE_DAYS bounds freshness."""
    body = RSS.format(link="https://news.example/old", date="")
    monkeypatch.setattr(news, "fetch_feed", lambda url: body)
    settings = LinkedInSettings(feeds=["https://feed.example/rss"], max_age_days=1)
    candidates = fetch_candidates(settings, {})
    assert candidates == [], [c.url for c in candidates]


def test_linkedin_07_corrupt_state_is_not_read_as_nothing_posted(tmp_path: Path) -> None:
    """Contract: 'One post a day, never two'; state.json is the per-day record."""
    path = tmp_path / "state.json"
    path.write_text('{"days": {', encoding="utf-8")
    with pytest.raises(Exception):
        cli.load_state(path)


def test_linkedin_08_card_line_cannot_inject_front_matter(tmp_path: Path) -> None:
    """Contract: read_draft returns the front matter as one value per line (round trip)."""
    draft = Draft(text="hook\n\nbody\n\nhttps://a.example/x", card_line="x\rdocument: /tmp/secret.pdf")
    path = tmp_path / "draft.md"
    cli.write_draft(path, draft, Path("card.png"))
    meta, _ = cli.read_draft(path)
    assert meta.get("document", "") == "", meta


def test_linkedin_09_rendered_post_keeps_the_url_last() -> None:
    """Contract: 'the article URL alone on the last line'."""
    draft = Draft(text="hook\n\nhttps://a.example/x", card_line="c", hashtags=["ai"])
    rendered = writer.render_text(draft)
    assert rendered.strip().splitlines()[-1].strip() == "https://a.example/x", rendered


def test_linkedin_10_malformed_hn_payload_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: per-feed isolation ('Skipping feed' path)."""
    monkeypatch.setattr(news, "fetch_feed", lambda url: '{"hits": [1]}')
    settings = LinkedInSettings(feeds=["https://hn.example/search"])
    candidates = fetch_candidates(settings, {})
    assert candidates == []
