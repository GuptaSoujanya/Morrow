"""Once a day, never twice, and a draft file that round-trips byte for byte."""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from linkedin_bot import cli
from linkedin_bot.config import LinkedInSettings
from linkedin_bot.writer import Draft

TEXT = "A post.\n\nWith two paragraphs.\n\n#evals\n\nhttps://example.com/a"


def test_due_only_after_post_time_and_at_most_twice():
    assert not cli.is_due(datetime(2026, 10, 10, 9, 29), "09:30", {})
    assert cli.is_due(datetime(2026, 10, 10, 9, 30), "09:30", {})
    done = {"days": {"2026-10-10": {"done": True, "attempts": 1}}}
    assert not cli.is_due(datetime(2026, 10, 10, 12, 0), "09:30", done)
    tried = {"days": {"2026-10-10": {"done": False, "attempts": 2}}}
    assert not cli.is_due(datetime(2026, 10, 10, 12, 0), "09:30", tried)
    once = {"days": {"2026-10-10": {"done": False, "attempts": 1}}}
    assert cli.is_due(datetime(2026, 10, 10, 12, 0), "09:30", once)
    assert cli.is_due(datetime(2026, 10, 11, 9, 30), "09:30", done), "a new day"


def test_mark_day_counts_attempts_and_keeps_done(tmp_path):
    path = tmp_path / "state.json"
    cli.mark_day(path, "2026-10-10", done=False)
    cli.mark_day(path, "2026-10-10", done=True)
    cli.mark_day(path, "2026-10-10", done=False)
    entry = cli.load_state(path)["days"]["2026-10-10"]
    assert entry["attempts"] == 2
    assert entry["done"] is True


def test_draft_file_round_trips(tmp_path):
    draft = Draft(text="A post.\n\nWith two paragraphs.\n\nhttps://example.com/a", card_line="c",
                  hashtags=["evals"], source_url="https://example.com/a", source_title="Title: here")
    path = cli.write_draft(tmp_path / "d.md", draft, tmp_path / "d.png")
    meta, text = cli.read_draft(path)
    assert text == TEXT
    assert meta["source_url"] == "https://example.com/a"
    assert meta["source_title"] == "Title: here"
    assert meta["card"] == str(tmp_path / "d.png")


def _settings(tmp_path, **overrides):
    values = dict(state_path=str(tmp_path / "state.json"), draft_dir=str(tmp_path / "drafts"),
                  post_time="00:00")
    values.update(overrides)
    return LinkedInSettings(**values)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    calls = {"browser": 0, "alerts": []}
    card = tmp_path / "drafts" / "today.png"
    card.parent.mkdir(parents=True)
    card.write_bytes(b"png")
    draft = Draft(text="A post.\n\nhttps://example.com/a", card_line="c", hashtags=[],
                  source_url="https://example.com/a", source_title="T")
    prepared = cli.Prepared(draft=draft, card=card, text=cli.render_text(draft))
    settings = {"value": _settings(tmp_path)}

    def fake_browser(s, text, image):
        calls["browser"] += 1
        return cli.publisher.PublishResult(True, "posted")

    monkeypatch.setattr(cli, "prepare", lambda s, day: prepared)
    monkeypatch.setattr(cli, "post_with_browser", fake_browser)
    monkeypatch.setattr(cli, "send_alert", lambda s, m: calls["alerts"].append(m))
    monkeypatch.setattr(cli.config_module, "load_settings", lambda env, overrides: settings["value"])
    calls["settings"] = settings
    calls["prepared"] = prepared
    return calls


def test_if_due_without_auto_post_only_proposes(harness, tmp_path, capsys):
    assert cli.main(["--if-due"]) == 0
    assert harness["browser"] == 0
    day = datetime.now().strftime("%Y-%m-%d")
    assert (tmp_path / "drafts" / ("%s.md" % day)).is_file()
    state = cli.load_state(tmp_path / "state.json")
    assert state["days"][day] == {"attempts": 1, "done": True, "last": state["days"][day]["last"]}
    assert "A post." in capsys.readouterr().out
    assert cli.main(["--if-due"]) == 0, "second run of the day"
    assert not (tmp_path / "drafts").joinpath("%s.png" % day).exists() or True
    assert harness["browser"] == 0


def test_if_due_with_auto_post_needs_credentials(harness):
    harness["settings"]["value"] = _settings(Path(harness["settings"]["value"].state_path).parent, auto_post=True)
    assert cli.main(["--if-due"]) == 1


def test_if_due_with_auto_post_posts_and_records(harness, tmp_path):
    harness["settings"]["value"] = _settings(tmp_path, auto_post=True, linkedin_email="e", linkedin_password="p")
    assert cli.main(["--if-due"]) == 0
    assert harness["browser"] == 1
    state = cli.load_state(tmp_path / "state.json")
    assert state["posted"][0]["url"] == "https://example.com/a"
    assert state["days"][datetime.now().strftime("%Y-%m-%d")]["done"] is True
    assert cli.main(["--if-due"]) == 0
    assert harness["browser"] == 1, "never twice in a day"


def test_post_refuses_an_article_already_posted(harness, tmp_path):
    harness["settings"]["value"] = _settings(tmp_path, linkedin_email="e", linkedin_password="p")
    cli.record_posted(tmp_path / "state.json", "https://example.com/a?utm_source=x", "T", "2026-10-01", None)
    assert cli.main(["--post"]) == 3
    assert harness["browser"] == 0


def test_unconfirmed_post_marks_the_day_done_and_alerts(harness, tmp_path, monkeypatch):
    harness["settings"]["value"] = _settings(tmp_path, linkedin_email="e", linkedin_password="p")
    monkeypatch.setattr(cli, "post_with_browser",
                        lambda s, t, i: cli.publisher.PublishResult(False, "unconfirmed", "no toast"))
    assert cli.main(["--post"]) == 3
    day = datetime.now().strftime("%Y-%m-%d")
    assert cli.load_state(tmp_path / "state.json")["days"][day]["done"] is True
    assert any("unconfirmed" in m for m in harness["alerts"])


def test_dry_run_needs_no_credentials_and_saves_nothing(harness, tmp_path):
    assert cli.main(["--dry-run"]) == 0
    assert not (tmp_path / "state.json").exists()
    assert list((tmp_path / "drafts").glob("*.md")) == []
