"""The social manager's bookkeeping, with the browser agent, claude and ffprobe replaced by fakes."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "studio" / "reels" / "social.py"

pytestmark = pytest.mark.skipif(not SOCIAL.exists(), reason="the private studio folder is not checked out")


@pytest.fixture
def social(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("studio_reels_social_test", SOCIAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "social"
    for name, value in (("HOME", home), ("CONFIG", home / "config.json"), ("STATE", home / "state.json"),
                        ("DB", home / "posts.sqlite"), ("RESEARCH", home / "research"), ("RUNS", home / "runs"),
                        ("LEARNINGS", home / "learnings.md")):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module.planner, "PLANS", tmp_path / "plans")
    monkeypatch.setattr(module.planner, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "profile_root", lambda account: tmp_path / "browser" / "main")
    module.save_config({"niche": "Python tips", "accounts": ["instagram", "youtube"]})
    return module


def _plan_with_prompts(social, days=2):
    plan = social.planner.new_plan("Python tips", days=days)
    reply = {"pillars": ["Tips"], "series_note": "", "items": [
        {"day": d, "title": f"Reel {d}", "hook": f"Hook {d}", "angle": "Angle", "skill": "hyperframes", "why_skill": "fits",
         "duration_s": 20, "beats": ["one", "two"], "on_screen_text": [], "cta": "Follow", "caption": f"Caption {d}",
         "hashtags": ["python"], "pillar": "Tips"} for d in range(1, days + 1)]}
    social.planner.make_calendar(plan, ask=lambda p, s, t: reply)
    script = ["Your print statements are lying to you about one thing",
              "Put an equals sign inside the braces and see the name",
              "Follow for one more Python tip like this one tomorrow"]
    social.planner.write_prompts(plan, ask=lambda p, s, t: {"prompts": [
        {"day": d, "prompt": " ".join(["w"] * 130), "script": script} for d in range(1, days + 1)]})
    state = social.load_state()
    state["current_plan"] = plan["id"]
    social.save_state(state)
    return social.planner.load_plan(plan["id"])


def test_config_is_validated_and_kept(social):
    config = social.save_config({"post_time": "19:15", "reference_channels": ["@fireship", " mkbhd "], "accounts": ["instagram", "tiktok"], "bogus": 1})
    assert config["post_time"] == "19:15" and config["reference_channels"] == ["fireship", "mkbhd"]
    assert config["accounts"] == ["instagram"] and "bogus" not in config
    with pytest.raises(ValueError):
        social.save_config({"post_time": "7pm"})


def test_outliers_score_against_their_own_source_median(social):
    items = [{"title": "a", "views": 100, "source": "s1"}, {"title": "b", "views": 400, "source": "s1"},
             {"title": "c", "views": 100, "source": "s1"}, {"title": "d", "views": 10, "source": "s2"}, {"title": "e", "views": 0, "source": "s2"}]
    ranked = social.outliers(items)
    assert ranked[0]["title"] == "b" and ranked[0]["score"] == 4.0
    assert {i["title"]: i["score"] for i in ranked}["d"] == 1.0


def test_next_item_skips_made_and_posted_reels(social):
    plan = _plan_with_prompts(social, days=3)
    picked = social.next_item()
    assert picked[1]["day"] == 1
    state = social.load_state()
    state["made"][f"{plan['id']}:1"] = {"status": "ok"}
    social.save_state(state)
    assert social.next_item()[1]["day"] == 1, "a rendered but unposted reel is posted before anything new is rendered"
    with social.db() as conn:
        conn.execute("INSERT INTO posts (plan_id, day, title, platform, url, posted_at, status) VALUES (?,?,?,?,?,?,?)",
                     (plan["id"], 1, "Reel 1", "instagram", "https://www.instagram.com/reel/x/", "2026-11-10T18:30:00", "posted"))
    assert social.next_item()[1]["day"] == 2, "once the rendered reel is posted the next unrendered day follows"
    state = social.load_state()
    state["made"][f"{plan['id']}:3"] = {"status": "ok"}
    social.save_state(state)
    assert social.next_item()[1]["day"] == 3, "a ready reel jumps the queue even when an earlier day is unrendered"


def test_verify_reports_every_mismatch(social, monkeypatch):
    monkeypatch.setattr(social, "probe", lambda video: {"exists": True, "width": 1920, "height": 1080, "duration_s": 31.0, "audio": False, "codec": "h264"})
    problems = social.verify(Path("reel.mp4"), 20)
    assert len(problems) == 3 and any("1920x1080" in p for p in problems) and any("no audio" in p for p in problems)
    monkeypatch.setattr(social, "probe", lambda video: {"exists": True, "width": 1080, "height": 1920, "duration_s": 21.5, "audio": True, "codec": "h264"})
    assert social.verify(Path("reel.mp4"), 20) == []


def test_post_records_a_row_per_platform_and_ticks_the_day(social, monkeypatch):
    plan = _plan_with_prompts(social, days=1)
    folder = social.planner.day_dir(plan, 1)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "reel.mp4").write_bytes(b"x")
    monkeypatch.setattr(social, "verify", lambda video, planned: [])
    state = social.load_state()
    state["accounts"] = {"instagram": {"logged_in": True, "account": "dev",
                                        "browser_profile": str(social.profile_root("instagram"))},
                         "youtube": {"logged_in": False}}
    social.save_state(state)
    seen = {}

    def fake_task(account, task, schema, label, files=()):
        seen[account] = (task, files)
        return {"posted": True, "url": "https://www.instagram.com/reel/abc/"}

    monkeypatch.setattr(social, "run_browser_task", fake_task)
    results = social.post(plan["id"], 1)
    assert [r["platform"] for r in results] == ["instagram", "youtube"]
    assert results[0]["posted"] and "not connected" in results[1]["problem"]
    assert "Caption 1" in seen["instagram"][0] and "#python" in seen["instagram"][0] and seen["instagram"][1][0].name == "reel.mp4"
    with social.db() as conn:
        rows = conn.execute("SELECT platform, status, url FROM posts ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("instagram", "posted", "https://www.instagram.com/reel/abc/")]
    assert social.planner.load_plan(plan["id"])["items"][0]["done"] is True
    assert social.post(plan["id"], 1, ["instagram"])[0]["problem"] == "already posted"


def test_measure_stores_numbers_only_for_posts_that_are_due(social, monkeypatch):
    plan = _plan_with_prompts(social, days=1)
    state = social.load_state()
    state["accounts"] = {"instagram": {"logged_in": True,
                                        "browser_profile": str(social.profile_root("instagram"))}}
    social.save_state(state)
    with social.db() as conn:
        conn.execute("INSERT INTO posts (plan_id, day, title, platform, url, posted_at, status) VALUES (?,?,?,?,?,?,?)",
                     (plan["id"], 1, "Reel 1", "instagram", "https://www.instagram.com/reel/abc/", "2026-11-01T18:30:00", "posted"))
        conn.execute("INSERT INTO posts (plan_id, day, title, platform, url, posted_at, status) VALUES (?,?,?,?,?,?,?)",
                     (plan["id"], 1, "Reel 1", "instagram", "https://www.instagram.com/reel/new/", "2999-01-01T00:00:00", "posted"))
    monkeypatch.setattr(social, "run_browser_task", lambda account, task, schema, label, files=(): {
        "posts": [{"id": 1, "views": "1.2K", "likes": 40, "comments": "3", "saves": 7, "avg_watch_s": 9.5}, {"id": 2, "views": 5}]})
    saved = social.measure()
    assert saved == [{"post_id": 1, "platform": "instagram", "views": 1200, "likes": 40}]
    assert social.posts_with_metrics()[1]["metrics"]["saves"] == 7
    assert social.due_posts(social.load_config()) == [], "measured posts are not due again for 20 hours"


def test_learn_writes_learnings_and_moves_the_posting_time(social, monkeypatch):
    plan = _plan_with_prompts(social, days=1)
    with social.db() as conn:
        conn.execute("INSERT INTO posts (plan_id, day, title, platform, url, posted_at, status) VALUES (?,?,?,?,?,?,?)",
                     (plan["id"], 1, "Reel 1", "instagram", "https://www.instagram.com/reel/abc/", "2026-11-01T18:30:00", "posted"))
        conn.execute("INSERT INTO metrics (post_id, measured_at, views, likes, comments, saves, shares, reach, avg_watch_s, retention_pct, raw) "
                     "VALUES (1, '2026-11-02T19:00:00', 1200, 40, 3, 7, 1, 900, 9.5, 61.0, '{}')")
    reply = {"summary": "Short code-card reels win.", "keep": ["20 s length"], "change": ["post at 20:00"],
             "next_topics": ["f-strings"], "best_post_time": "20:00", "best_format": "hyperframes", "best_length_s": 20}
    learnings = social.learn(ask=lambda p, s, t: reply)
    assert learnings["best_post_time"] == "20:00" and social.load_config()["post_time"] == "20:00"
    assert "Short code-card reels win." in social.LEARNINGS.read_text()
    assert social.load_state()["learnings"]["keep"] == ["20 s length"]


def test_research_without_browser_ranks_with_claude(social, monkeypatch):
    monkeypatch.setattr(social, "_ytdlp", lambda url, end: [
        {"title": "Walrus operator", "channel": "c", "views": 900, "url": "u1", "duration_s": 30, "source": url},
        {"title": "List comps", "channel": "c", "views": 100, "url": "u2", "duration_s": 30, "source": url}])
    asked = {}

    def fake_ask(prompt, schema, timeout):
        asked["prompt"] = prompt
        return {"trends": [{"topic": "Walrus", "why_now": "9x", "evidence": ["Walrus operator (9.0)"], "hook_idea": "h", "format": "code card", "score": 90}],
                "avoid": ["basics"], "summary": "Go niche."}

    found = social.research(use_browser=False, ask=fake_ask)
    assert found["trends"][0]["topic"] == "Walrus" and found["candidates"][0]["score"] == 1.8
    assert "Walrus operator" in asked["prompt"] and "Python tips" in asked["prompt"]
    assert social.latest_research()["summary"] == "Go niche."
    assert social.load_state()["last_research"].endswith(".json")


def test_cycle_stops_cleanly_when_nothing_is_signed_in(social, monkeypatch):
    _plan_with_prompts(social, days=1)
    monkeypatch.setattr(social, "check_login", lambda account: {"logged_in": False, "checked": "2026-11-12T10:00:00"})
    monkeypatch.setattr(social, "make", lambda plan_id, day, notes="", attempts=2: {"status": "ok"})
    record = social.cycle(no_post=True)
    assert record["result"] == "made, not posted (posting off)"
    assert any("NOT signed in" in s for s in record["steps"]) and any("next reel: day 1" in s for s in record["steps"])
    assert social.load_state()["last_cycle"]["result"] == record["result"]


def test_int_reads_counts_the_way_the_pages_show_them(social):
    assert [social._int(v) for v in ("1.2K", "3,400", "2M", "", None, "abc")] == [1200, 3400, 2000000, None, None, None]
