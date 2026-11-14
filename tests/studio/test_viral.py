"""The viral scout learns how winning openings in the niche are built, and every new reel uses it."""

import importlib.util
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


viral = _load("test_viral_module", ROOT / "studio" / "reels" / "viral.py")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MORROW_STUDIO_VIRAL", str(tmp_path / "viral"))
    return tmp_path / "viral"


def _done(stdout="", stderr="", rc=0):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def _row(i, views, channel="c1", outlier=None):
    row = {"id": f"v{i}", "title": f"Phone myth {i}", "views": views, "duration_s": 30.0, "channel": channel,
           "channel_page": f"https://www.youtube.com/@{channel}", "url": f"https://www.youtube.com/shorts/v{i}",
           "found_on": "x"}
    if outlier is not None:
        row.update(outlier=outlier, baseline="channel")
    return row


FINDINGS = {"videos": [{"id": "v1", "spoken_hook": "Your phone is not listening", "on_screen_hook": "NOT LISTENING",
                        "visual_hook": "A phone falls into frame at 0 s", "audio_hook": "Word at 0.2 s over a hit",
                        "punchline": "It is the apps, not the mic", "formula": "Myth Buster", "hook_type": "myth-bust",
                        "why": "Names the belief first"}],
            "patterns": [{"name": "Device first", "what": "The device fills the frame", "seen_in": ["#1"]}],
            "rules": ["The device fills half the frame on frame 0", "First word by 0.3 s"], "avoid": ["Logo openings"]}


def test_collect_keeps_shorts_with_views_and_drops_long_videos():
    pages = {"ytsearch": [{"id": "a", "view_count": 900, "duration": 40, "channel_url": "https://www.youtube.com/@x", "title": "A"},
                          {"id": "b", "view_count": 5000, "duration": 600, "title": "long"},
                          {"id": "c", "title": "no views"}],
             "hashtag": [{"id": "d", "view_count": 70_000}, {"id": "a", "view_count": 900, "duration": 40}]}

    def run(cmd, **kw):
        page = cmd[-1]
        return _done(json.dumps({"entries": pages["ytsearch" if page.startswith("ytsearch") else "hashtag"]}))

    rows = viral.collect(["phone myths"], run=run, tags=["techmyths"])
    assert [r["id"] for r in rows] == ["d", "a"]
    assert rows[1]["channel_page"] == "https://www.youtube.com/@x"


def test_outliers_beat_their_own_channel_not_raw_views():
    rows = [_row(1, 1_000_000, "big"), _row(2, 200_000, "small"), _row(3, 5_000, "small")]
    viral.outliers(rows, {"https://www.youtube.com/@big": 2_000_000, "https://www.youtube.com/@small": 10_000})
    assert rows[0]["outlier"] == 0.5 and rows[1]["outlier"] == 20
    picked = viral.pick(rows)
    assert [r["id"] for r in picked] == ["v2"]  # the big channel's million views is below its usual; 5K is too few views


def test_pick_keeps_at_most_two_videos_per_channel():
    rows = [_row(i, 100_000, "same", outlier=10) for i in range(5)] + [_row(9, 100_000, "other", outlier=3)]
    assert [r["channel"] for r in viral.pick(rows)] == ["same", "same", "other"]


def test_tags_skip_words_too_generic_to_stay_in_the_niche():
    tags = viral.tags_for("Evidence-based tech myth-busting", "phone battery myths")
    assert "tech" not in tags and "myth" not in tags and "phonebattery" in tags


def test_captions_give_word_timings():
    data = {"events": [{"tStartMs": 200, "segs": [{"utf8": "Your"}, {"utf8": " phone", "tOffsetMs": 300}]},
                       {"tStartMs": 4000, "segs": [{"utf8": "\n"}]}]}

    class P:
        pass
    path = Path(viral.home()) / "c.json3"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))
    assert viral._captions(path) == [(0.2, "Your"), (0.5, "phone")]


def test_relevance_filter_drops_what_the_model_rejects_and_keeps_nothing_on_an_empty_answer():
    rows = [_row(1, 10), _row(2, 10)]
    assert [r["id"] for r in viral.relevant(rows, "tech", ask=lambda p: {"keep": ["v2"]})] == ["v2"]
    assert viral.relevant(rows, "tech", ask=lambda p: {}) == []


def test_scout_measures_names_and_stores_the_openings(home, tmp_path, monkeypatch):
    rows = [_row(i, 100_000 * (9 - i), f"c{i}") for i in range(1, 8)]

    def fake_decode(row, folder, run=None):
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 60), "red").save(folder / "sheet.jpg")
        row.update(sheet=str(folder / "sheet.jpg"), first_word_s=0.2, opening_words="Your phone", ending_words="It is the apps",
                   audio={"mean_db": -14.0, "first_sound_s": 0.0})
        return row

    seen = {}

    def run_bridge(bridge, prompt, folder, mode, images=None):
        seen.update(prompt=prompt, images=images, mode=mode)
        return FINDINGS

    monkeypatch.setattr(viral, "collect", lambda q, c, run, tags: [dict(r) for r in rows])
    monkeypatch.setattr(viral, "details", lambda r, run=None: r)
    monkeypatch.setattr(viral, "baselines", lambda r, run=None: {row["channel_page"]: 10_000 for row in r})
    monkeypatch.setattr(viral, "decode", fake_decode)
    record = viral.scout("tech myths", "phone mic", run_bridge=run_bridge, say=lambda m: None, ask=lambda p: {"keep": [r["id"] for r in rows]})
    assert record["state"] == "done" and record["chosen"] == 7
    assert seen["mode"] == "plan" and len(seen["images"]) == 7 and "Your phone" in seen["prompt"]
    library = json.loads((home / "hooks.json").read_text())
    first = next(e for e in library["entries"] if e["id"] == "v1")
    assert first["visual_hook"].startswith("A phone falls") and first["punchline"] == "It is the apps, not the mic"
    assert library["rules"] == FINDINGS["rules"]
    assert viral.latest("tech myths", "phone mic")["state"] == "done"


def test_scout_refuses_when_too_few_openings_beat_their_channel(monkeypatch):
    monkeypatch.setattr(viral, "collect", lambda q, c, run, tags: [_row(i, 30_000, f"c{i}") for i in range(8)])
    monkeypatch.setattr(viral, "details", lambda r, run=None: r)
    monkeypatch.setattr(viral, "baselines", lambda r, run=None: {row["channel_page"]: 30_000 for row in r})
    with pytest.raises(viral.ViralError, match="beat their channel"):
        viral.scout("tech", fresh=True, say=lambda m: None, ask=lambda p: {"keep": [f"v{i}" for i in range(8)]})


def test_brief_and_frame0_contract_carry_the_measured_rules(home):
    viral.merge([dict(_row(1, 900_000, outlier=30), audio={}, opening_words="", ending_words="")], FINDINGS, "tech", "phone")
    text = viral.brief("phone microphone")
    assert "VIRAL HOOK EVIDENCE" in text and "The device fills half the frame" in text and "It is the apps" in text
    contract = viral.frame0_contract({"creative_spec": {"visual_hook": "A mic icon cracks"}, "punchline": "Apps, not mics"})
    assert "Frame 0 is already moving" in contract and "A mic icon cracks" in contract and "Apps, not mics" in contract
    assert "Measured in this niche: The device fills half" in contract


def test_brief_is_empty_before_any_scout():
    assert viral.brief("anything") == ""


def test_choose_hook_keeps_the_most_specific_option():
    item = {"hook": "Incognito does not hide you.",
            "hook_options": ["Incognito does not hide you.", "Your ISP saw 47 sites you opened in incognito last night."]}
    viral.choose_hook(item)
    assert item["hook"].startswith("Your ISP saw 47")
    assert {row["hook"] for row in item["hook_scores"]} == set(item["hook_options"])


def test_choose_hook_leaves_the_hook_alone_without_the_scorer(monkeypatch):
    monkeypatch.setattr(viral, "HOOKSCORE", Path("/nonexistent/hookscore.py"))
    item = {"hook": "Keep me", "hook_options": ["Other one"]}
    assert viral.choose_hook(item)["hook"] == "Keep me"


def test_planner_asks_for_three_hooks_and_a_punchline_and_keeps_them():
    planner = _load("test_viral_planner", ROOT / "studio" / "reels" / "planner.py")
    assert "hook_options" in planner.CALENDAR_SCHEMA and "punchline" in planner.CALENDAR_SCHEMA
    reply = {"items": [{"day": 1, "title": "T", "hook": "Incognito does not hide you.", "angle": "A", "caption": "C",
                        "beats": ["b"], "hook_options": ["Incognito does not hide you.", "Your ISP saw 47 sites you opened last night."],
                        "punchline": "Private from your family, not your ISP."}]}
    items = planner.normalise_items(reply, 1, [])
    assert items[0]["punchline"] == "Private from your family, not your ISP."
    assert items[0]["hook"].startswith("Your ISP saw 47")
    same = {"items": [dict(reply["items"][0], hook_options=["Same", "same "])]}
    assert any("not one repeated" in p for p in planner._calendar_problems(same, 1, []))


def test_every_render_brief_carries_the_first_three_seconds_rules():
    studio = _load("test_viral_studio", ROOT / "studio" / "reels" / "studio.py")
    assert "planner.viral.frame0_contract(item)" in (ROOT / "studio" / "reels" / "studio.py").read_text()
    assert "Frame 0 is already moving" in studio.planner.viral.frame0_contract({})
