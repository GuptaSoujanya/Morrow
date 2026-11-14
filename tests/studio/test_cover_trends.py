"""The cover scout learns from the most-watched Shorts covers before a reel cover is designed."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


trends = _load("test_cover_trends_module", ROOT / "studio" / "reels" / "cover_trends.py")

FINDINGS = {"summary": "Strong covers freeze one action.", "patterns": [{"name": "Action", "what": "Someone mid-reaction", "seen_in": ["TOP 1"]}] * 3,
            "rules": ["Mascot 40 % of the height", "Two-word headline", "One prop", "Real frame behind"],
            "avoid": ["Flat background", "Small type"], "headline": "Two words, white, black outline",
            "character": "He leans toward the phone", "colour": "Navy and yellow", "production": "Depth and shadows"}


def _page(*entries):
    return SimpleNamespace(returncode=0, stdout=json.dumps({"entries": list(entries)}), stderr="")


def _entry(video_id, views, vertical=True):
    size = (405, 720) if vertical else (720, 404)
    return {"id": video_id, "title": f"Short {video_id}", "view_count": views,
            "thumbnails": [{"url": f"https://i.ytimg.com/vi/{video_id}/oar2.jpg", "width": size[0], "height": size[1]}]}


def _webp():
    buffer = io.BytesIO()
    Image.new("RGB", (405, 720), (200, 40, 40)).save(buffer, "WEBP")
    return buffer.getvalue()


class _Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit):
        return self.data[:limit]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MORROW_COVER_TRENDS", str(tmp_path / "trends"))
    return tmp_path / "trends"


def test_tags_come_from_the_reel_and_its_topic():
    tags = trends.tags_for("Is Your Phone Listening for Ads?", "Evidence-Based Tech Myth Busting")
    assert tags[:4] == ["phonelistening", "listeningads", "techmyth", "techmyths"]
    assert "your" not in tags and len(tags) <= 8
    assert trends.tags_for("x", extra=["#Cyber Security"])[0] == "cybersecurity"


def test_only_vertical_covers_with_views_are_kept_best_first():
    pages = {"a": _page(_entry("v1", 50), _entry("wide", 9_000, vertical=False), {"id": "noviews", "thumbnails": []}),
             "b": _page(_entry("v2", 900), _entry("v1", 50))}
    run = lambda command, **kw: pages["a" if command[-1].endswith("a/shorts") else "b"]
    rows = trends.collect(["a", "b"], run=run)
    assert [r["id"] for r in rows] == ["v2", "v1"]
    assert rows[0]["url"] == "https://www.youtube.com/shorts/v2"


def test_the_sheet_holds_the_strongest_and_a_few_of_the_weakest():
    rows = [{"id": str(i), "views": 100 - i} for i in range(20)]
    chosen = trends.pick(rows)
    assert [r["rank"] for r in chosen][:2] == ["TOP 1", "TOP 2"] and chosen[-1]["rank"] == "LOW 3"
    assert chosen[-1]["id"] == "19" and len(chosen) == trends.TOP + trends.WEAK
    assert trends.pick(rows[:3]) == []


def test_scout_downloads_sheets_analyses_and_caches(home):
    entries = [_entry(f"id{i}", 10_000 - i) for i in range(20)]
    calls = []
    run = lambda command, **kw: _page(*entries)
    opener = lambda request, timeout: _Response(_webp())

    def bridge(name, prompt, folder, mode, images):
        calls.append((mode, prompt, images))
        assert json.loads((folder / "schema.json").read_text())["required"]
        return dict(FINDINGS)

    record = trends.scout("Tech myths", "Is your phone listening?", run=run, opener=opener, run_bridge=bridge, say=lambda _: None)
    folder = Path(record["folder"])
    assert (folder / "sheet.jpg").is_file() and len(list((folder / "refs").glob("*.jpg"))) == 12
    with Image.open(folder / "refs" / "id0.jpg") as picture:
        assert picture.format == "JPEG"  # the WebP answer was kept as a plain JPEG
    mode, prompt, images = calls[0]
    assert mode == "plan" and images == [folder / "sheet.jpg"]
    assert "FIXED" in prompt and "red zip hoodie" in prompt and "TOP 1" in prompt
    again = trends.scout("Tech myths", "Is your phone listening?", run=lambda *a, **k: pytest.fail("cache ignored"),
                         run_bridge=bridge, say=lambda _: None)
    assert again["folder"] == record["folder"] and len(calls) == 1
    text = trends.brief(record)
    assert "TRENDING COVER ANALYSIS" in text and "Mascot 40 % of the height" in text and "Flat background" in text


def test_too_few_covers_is_a_clear_error(home):
    run = lambda command, **kw: _page(_entry("a", 5), _entry("b", 4))
    with pytest.raises(trends.TrendError, match="at least"):
        trends.scout("x", "y", run=run, run_bridge=lambda *a, **k: FINDINGS, say=lambda _: None)


def test_a_failing_bridge_hands_over_and_a_bad_reply_is_refused(home, tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    with pytest.raises(trends.TrendError, match="did not match"):
        trends.analyse([{"rank": "TOP 1", "views": 5, "title": "t"}], folder, "x", "y", run_bridge=lambda *a, **k: {"summary": "only"})


def test_a_cover_is_designed_with_the_trends_and_survives_without_them(monkeypatch, tmp_path):
    artwork = _load("test_cover_trends_artwork", ROOT / "studio" / "reels" / "artwork.py")
    sheet = tmp_path / "sheet.jpg"
    Image.new("RGB", (40, 40)).save(sheet, "JPEG")
    record = {"at": "now", "folder": str(tmp_path), "covers": [{"rank": "TOP 1", "views": 7}], "findings": FINDINGS}
    fake = SimpleNamespace(for_reel=lambda plan_id, day, say: record, brief=trends.brief, sheet_path=lambda r: sheet)
    monkeypatch.setattr(artwork, "_trend_module", lambda: fake)
    reel, job = {"title": "T"}, {}
    found = artwork._cover_trends("cover", "plan", 1, reel, job)
    assert found["sheet"] == sheet and "Two-word headline" in reel["trends"] and job["trend_brief"] == reel["trends"]
    assert "TRENDING COVER ANALYSIS" in artwork._reel_brief(reel)
    assert artwork._cover_trends("avatar", "plan", 1, {"title": "T"}, {}) is None

    def broken(plan_id, day, say):
        raise trends.TrendError("offline")
    monkeypatch.setattr(artwork, "_trend_module", lambda: SimpleNamespace(for_reel=broken))
    job = {}
    assert artwork._cover_trends("cover", "plan", 1, {"title": "T"}, job)["summary"] == {"error": "offline"}
    assert job["trend_error"] == "offline"


def test_the_wide_thumbnail_is_no_longer_offered():
    artwork = sys.modules.get("test_cover_trends_artwork") or _load("test_cover_trends_artwork", ROOT / "studio" / "reels" / "artwork.py")
    assert artwork.OFFERED_KINDS == ("avatar", "cover")
    agent = _load("test_cover_trends_agent", ROOT / "studio" / "reels" / "social_agent.py")
    assert agent.REEL_ARTWORK == ("cover",) and "thumbnail" not in agent.ARTWORK_KINDS
