import contextlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    name = "studio_reels_autopilot"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "studio" / "reels" / "autopilot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


auto = _load()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "STATE", tmp_path / "autopilot.json")
    monkeypatch.setattr(auto, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(auto.agent, "_lock", contextlib.nullcontext)
    monkeypatch.setattr(auto, "library", lambda: [])
    monkeypatch.setattr(auto, "_learn", lambda say: None)
    monkeypatch.setattr(auto, "_accounts", lambda say: {})
    return tmp_path


def _plan(days=3):
    return {"id": "plan-a", "topic": "Tech myths", "language": "English",
            "items": [{"day": d, "title": f"Myth {d}", "hook": "h", "prompt": "p", "script": ["a"]} for d in range(1, days + 1)]}


def test_one_run_walks_every_step_and_stops_for_your_approval(home, monkeypatch):
    plan = _plan()
    calls = []
    monkeypatch.setattr(auto, "choose", lambda say: (plan, plan["items"][0]))
    for name in ("_script", "_reel", "_artwork", "_caption"):
        monkeypatch.setattr(auto, name, (lambda n: lambda p, i, say: calls.append(n) or (p, i))(name))
    monkeypatch.setattr(auto, "_bar", lambda p, i, say: calls.append("_bar") or {"check": {"passed": True}})
    state = auto.chain()
    assert calls == ["_script", "_reel", "_artwork", "_caption", "_bar"]
    assert state["state"] == "waiting" and state["current"] == "approval"
    assert state["steps"]["approval"]["state"] == "waiting"
    assert json.loads((home / "autopilot.json").read_text())["state"] == "waiting"


def test_a_failing_step_is_named_and_nothing_after_it_runs(home, monkeypatch):
    plan = _plan()
    monkeypatch.setattr(auto, "choose", lambda say: (plan, plan["items"][0]))
    monkeypatch.setattr(auto, "_script", lambda p, i, say: (p, i))
    def broken(p, i, say):
        raise auto.AutopilotError("The reel did not pass its own checks: too many words")
    monkeypatch.setattr(auto, "_reel", broken)
    monkeypatch.setattr(auto, "_artwork", lambda *a: pytest.fail("artwork must not run after a failed reel"))
    state = auto.chain()
    assert state["state"] == "failed" and state["failed_step"] == "reel"
    assert "too many words" in state["steps"]["reel"]["detail"]


def test_choose_skips_reels_that_are_already_live_and_researches_a_new_plan_when_all_are(home, monkeypatch):
    plan = _plan(2)
    saved = {}
    monkeypatch.setattr(auto, "_selection", lambda: (plan, plan["items"][0]))
    monkeypatch.setattr(auto.agent, "save_config", lambda changes: saved.update(changes))
    live = {1}
    monkeypatch.setattr(auto, "_live_everywhere", lambda plan_id, day: day in live)
    chosen, item = auto.choose(lambda *a: None)
    assert item["day"] == 2 and saved == {"plan_id": "plan-a", "day": 2}
    live.add(2)
    fresh = {"id": "plan-b", "items": [{"day": 1, "title": "New"}]}
    monkeypatch.setattr(auto, "_new_plan", lambda say: fresh)
    chosen, item = auto.choose(lambda *a: None)
    assert chosen["id"] == "plan-b" and item["title"] == "New"


def test_a_new_plan_needs_a_niche(home, monkeypatch):
    monkeypatch.setattr(auto.agent, "load_config", lambda: {"niche": ""})
    with pytest.raises(auto.AutopilotError, match="niche"):
        auto._new_plan(lambda *a: None)


def test_approval_refuses_a_package_that_changed_and_asks_about_kids_once(home, monkeypatch):
    plan = _plan()
    monkeypatch.setattr(auto.agent, "_selection", lambda plan_id, day: (plan, plan["items"][0]))
    monkeypatch.setattr(auto, "_latest_draft", lambda: {"id": "d1", "revision": "r1"})
    monkeypatch.setattr(auto, "_platforms", lambda: ["instagram", "youtube"])
    monkeypatch.setattr(auto.agent, "load_config", lambda: {"youtube_made_for_kids": None})
    with pytest.raises(auto.AutopilotError, match="changed"):
        auto.approve("plan-a", 1, "d1", "old")
    with pytest.raises(auto.AutopilotError, match="made for kids"):
        auto.approve("plan-a", 1, "d1", "r1")


def test_approval_records_both_reviews_and_requires_the_bar(home, monkeypatch):
    plan = _plan()
    seen = []
    monkeypatch.setattr(auto.agent, "_selection", lambda plan_id, day: (plan, plan["items"][0]))
    monkeypatch.setattr(auto, "_latest_draft", lambda: {"id": "d1", "revision": "r1"})
    monkeypatch.setattr(auto, "_platforms", lambda: ["instagram"])
    monkeypatch.setattr(auto.agent, "load_config", lambda: {})
    monkeypatch.setattr(auto.agent, "review", lambda target, decision, *a: seen.append((target, decision)))
    monkeypatch.setattr(auto, "_caption", lambda p, i, say: {"id": "d2", "revision": "r2"})
    monkeypatch.setattr(auto.agent, "bar_state", lambda *a: {"current": True, "check": {"passed": False, "failing": ["hook"]}})
    with pytest.raises(auto.AutopilotError, match="bar"):
        auto.approve("plan-a", 1, "d1", "r1")
    assert seen == [("video", "approve"), ("artwork", "approve")]
    monkeypatch.setattr(auto.agent, "bar_state", lambda *a: {"current": True, "check": {"passed": True}})
    monkeypatch.setattr(auto.agent, "_approved", lambda *a: None)
    monkeypatch.setattr(auto.agent, "_require_reviews", lambda *a: None)
    assert auto.approve("plan-a", 1, "d1", "r1")["id"] == "d2"


def test_every_reel_gets_a_topic_folder_with_its_files_and_sources(tmp_path, monkeypatch):
    plan = _plan(1)
    plan["items"][0].update(search_phrase="is my phone listening", why_now="People ask",
                            evidence=[{"url": "https://example.com/q", "text": "phone listening", "metric_label": "suggestion #1"}],
                            sources=["https://doi.org/10.1/x"], caption="Caption", hashtags=["tech"])
    work = tmp_path / "out" / "day-01"
    work.mkdir(parents=True)
    (work / "reel.mp4").write_bytes(b"mp4")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    monkeypatch.setattr(auto, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(auto.planner, "list_plans", lambda: [{"id": "plan-a"}])
    monkeypatch.setattr(auto.planner, "load_plan", lambda plan_id: plan)
    monkeypatch.setattr(auto.planner, "day_dir", lambda p, d: work)
    monkeypatch.setattr(auto.social, "made_record", lambda p, d: {"status": "ok"})
    monkeypatch.setattr(auto.agent, "_active_artwork", lambda *a: {"cover": {"path": str(cover), "scope": "reel"},
                                                                   "thumbnail": {"path": str(cover), "scope": "channel"}})
    monkeypatch.setattr(auto, "posted", lambda plan_id, day: {})
    monkeypatch.setattr(auto, "_platforms", lambda: ["instagram", "youtube"])
    rows = auto.library()
    folder = tmp_path / "library" / "plan-a" / "day-01-myth-1"
    assert rows[0]["status"] == "rendered" and Path(rows[0]["folder"]) == folder
    assert (folder / "reel.mp4").resolve() == (work / "reel.mp4").resolve()
    assert (folder / "cover.png").is_symlink() and not (folder / "thumbnail.png").exists()  # a generic thumbnail is not this reel's
    bookmarks = (folder / "bookmarks.md").read_text()
    assert "is my phone listening" in bookmarks and "https://example.com/q" in bookmarks and "doi.org" in bookmarks
    assert (folder / "caption.txt").read_text().strip() == "Caption\n\n#tech"
    assert "Day 1" in (tmp_path / "library" / "plan-a" / "README.md").read_text()


def test_steps_read_the_truth_and_a_running_job_shows_its_step(monkeypatch):
    plan = _plan()
    item = plan["items"][0]
    monkeypatch.setattr(auto.social, "made_record", lambda p, d: {"status": "ok"})
    monkeypatch.setattr(auto.agent, "artwork_review", lambda *a: {"state": "pending"})
    monkeypatch.setattr(auto, "package", lambda p, i: {"posted": {}, "platforms": ["instagram", "youtube"], "draft": {"id": "d"},
                                                        "bar": {"current": True, "passed": True, "level": 1, "failing": []}})
    states = {s["key"]: s["state"] for s in auto.steps(plan, item)}
    assert states["reel"] == states["artwork"] == states["caption"] == states["bar"] == "done"
    assert states["approval"] == "waiting" and states["upload"] == "todo"
    run = {"plan_id": "plan-a", "day": 1, "current": "artwork", "steps": {"artwork": {"state": "running", "detail": "Designing"}}}
    running = {s["key"]: s for s in auto.steps(plan, item, run, job_running=True)}
    assert running["artwork"]["state"] == "running" and running["artwork"]["detail"] == "Designing"


def test_api_starts_one_autopilot_job_and_refuses_while_busy(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("studio_api_autopilot_test", ROOT / "studio" / "api" / "studio_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    started = []
    monkeypatch.setattr(api, "_reserve_social_browser", lambda handler: None)
    monkeypatch.setattr(api, "_start_job", lambda action, name, group, argv=None, kind="", on_finish=None:
                        started.append((action, kind, argv)) or {"id": "1"})
    monkeypatch.setattr(api, "_job_view", lambda job: job)
    monkeypatch.setattr(api.jobstore, "HOME", tmp_path)

    class Handler:
        sent = None
        def json(self, data, status=200):
            Handler.sent = (data, status)
    api._post_autopilot(Handler(), "run", {})
    assert started[-1][0] == "autopilot" and started[-1][1] == "social" and started[-1][2][-1] == "run"
    api._post_autopilot(Handler(), "revise", {"plan_id": "p", "day": 1, "notes": "Bigger hook", "artwork": True})
    argv = started[-1][2]
    assert started[-1][0] == "autopilot-revise" and "--video" in argv and "--artwork" in argv
    assert Path(argv[argv.index("--notes-file") + 1]).read_text() == "Bigger hook"
    with pytest.raises(ValueError):
        api._post_autopilot(Handler(), "revise", {"plan_id": "p", "day": 1, "notes": ""})
    with pytest.raises(ValueError):
        api._post_autopilot(Handler(), "approve", {"plan_id": "p", "day": 1, "draft_id": "d"})
    monkeypatch.setattr(api, "_running", lambda kind="skills": {"kind": "make", "action": "make", "name": "x"} if kind == "make" else None)
    api._post_autopilot(Handler(), "run", {})
    assert Handler.sent[1] == api.HTTPStatus.CONFLICT and len(started) == 2


def test_the_critic_keeps_minor_remarks_as_notes_and_only_problems_fail_a_cut(tmp_path, monkeypatch):
    studio = auto.studio
    reply = {"ok": False, "hook_ok": True, "mascot_ok": True,
             "problems": ["Minor: the padlock could sit higher", "the headline is cut off at the right edge"],
             "notes": ["a warmer end card"]}

    class Done:
        @property
        def stdout(self):
            return json.dumps(reply)
    seen = {}
    monkeypatch.setattr(studio.subprocess, "run", lambda argv, **kw: seen.update(prompt=argv[2]) or Done())
    shot = tmp_path / "snap-50.png"
    shot.write_bytes(b"png")
    result = studio.critic(tmp_path, {"title": "T", "hook": "H", "beats": []}, [shot])
    assert result["problems"] == ["the headline is cut off at the right edge"] and result["ok"] is False
    assert result["notes"] == ["a warmer end card", "Minor: the padlock could sit higher"]
    assert "5-word quote" in seen["prompt"] and "never ask for more text" in seen["prompt"]
    reply.update(ok=True, problems=["Minor: tighten the gap"])
    assert studio.critic(tmp_path, {"title": "T", "hook": "H", "beats": []}, [shot])["ok"] is True


def test_a_failed_cut_is_fixed_in_place_rather_than_made_again(tmp_path, monkeypatch):
    plan, item = _plan(), _plan()["items"][0]
    (tmp_path / "reel.mp4").write_bytes(b"mp4")
    monkeypatch.setattr(auto.planner, "day_dir", lambda p, d: tmp_path)
    records = iter([{"status": "failed", "problems": ["card too wordy"]}, {"status": "ok"}])
    monkeypatch.setattr(auto.social, "made_record", lambda p, d: next(records))
    monkeypatch.setattr(auto.social, "make", lambda *a, **k: pytest.fail("a failed cut must not be made from scratch"))
    monkeypatch.setattr(auto.social, "load_config", lambda: {"bridge": "codex"})
    edits = []
    monkeypatch.setattr(auto.studio, "edit", lambda plan_id, day, notes, bridge: edits.append((notes, bridge)))
    assert auto._reel(plan, item, lambda *a: None)["status"] == "ok"
    assert "card too wordy" in edits[0][0] and edits[0][1] == "codex"


def test_a_browser_upload_names_the_copies_the_upload_tool_can_read(tmp_path, monkeypatch):
    from sites_bot import browser_agent
    social = auto.social
    video = tmp_path / "elsewhere" / "reel.mp4"
    video.parent.mkdir()
    video.write_bytes(b"mp4")
    monkeypatch.setattr(social, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(social, "_settings_for", lambda account: object())
    seen = {}

    class Run:
        report, seconds, cost_usd, turns, problem = {"posted": False}, 1, 0, 1, ""

    class Browser:
        metadata = {}
        def open_account(self, account):
            pass

    monkeypatch.setattr(social.browser_session, "session", lambda settings: contextlib.nullcontext(Browser()))
    monkeypatch.setattr(browser_agent, "run_agent",
                        lambda browser, settings, prompt, workdir, files, system="": seen.update(prompt=prompt, workdir=workdir, files=files) or Run())
    social.run_browser_task("instagram", "upload", "{}", "test", files=(video,))
    staged = (seen["workdir"] / "reel.mp4").resolve()
    assert staged.is_file() and str(staged) in seen["prompt"] and str(video) not in seen["prompt"]
    assert seen["files"] == (staged,)


def _desk(monkeypatch, plans):
    monkeypatch.setattr(auto.planner, "list_plans", lambda: [{"id": p["id"]} for p in plans])
    monkeypatch.setattr(auto.planner, "load_plan", lambda plan_id: next(p for p in plans if p["id"] == plan_id))
    monkeypatch.setattr(auto.social, "made_record", lambda plan, day: {"status": "ok" if day == 1 else ""})
    monkeypatch.setattr(auto, "posted", lambda plan_id, day: {"instagram": "https://x"} if (plan_id, day) == ("plan-b", 1) else {})


def test_the_desk_lists_every_topic_with_its_days(monkeypatch):
    other = dict(_plan(2), id="plan-b", topic="Python tips")
    _desk(monkeypatch, [_plan(), other, dict(_plan(0), id="empty")])
    rows = auto.reels()
    assert [r["plan_id"] for r in rows] == ["plan-a", "plan-b"]
    assert rows[0]["days"][0] == {"day": 1, "title": "Myth 1", "made": "ok", "live": []}
    assert rows[1]["made"] == 1 and rows[1]["live"] == 1 and rows[1]["topic"] == "Python tips"


def test_choosing_a_reel_saves_it_for_social(monkeypatch):
    plan, saved = _plan(), {}
    monkeypatch.setattr(auto.agent, "_selection", lambda plan_id, day: (plan, next(i for i in plan["items"] if i["day"] == day)))
    monkeypatch.setattr(auto.agent, "save_config", saved.update)
    assert auto.select("plan-a", 2) == {"plan_id": "plan-a", "day": 2, "title": "Myth 2"}
    assert saved == {"plan_id": "plan-a", "day": 2}


def test_the_desk_offers_only_this_reels_covers_newest_first(monkeypatch):
    plan = _plan()
    versions = [{"id": "c1", "kind": "cover", "plan_id": "plan-a", "day": 1, "created_at": "2026-01-01"},
                {"id": "c2", "kind": "cover", "plan_id": "plan-a", "day": 1, "created_at": "2026-02-01"},
                {"id": "c3", "kind": "cover", "plan_id": "plan-a", "day": 2, "created_at": "2026-03-01"},
                {"id": "t1", "kind": "thumbnail", "plan_id": "other", "day": 1, "created_at": "2026-03-01"}]
    fake = type("Art", (), {"status": staticmethod(lambda plan_id, day: {"versions": versions})})
    monkeypatch.setattr(auto.agent, "_artwork_module", lambda: fake)
    out = auto._versions(plan, plan["items"][0])
    assert [v["id"] for v in out["cover"]] == ["c2", "c1"] and out["thumbnail"] == []
    assert out["cover"][0]["url"].endswith("versions/c2/artwork.png")


def test_the_profile_flow_offers_channel_art_and_reports_each_account(monkeypatch, tmp_path):
    versions = [{"id": "a1", "kind": "avatar", "created_at": "2026-01-01"},
                {"id": "a2", "kind": "avatar", "created_at": "2026-02-01"},
                {"id": "a3", "kind": "avatar", "plan_id": "plan-a", "day": 1, "created_at": "2026-03-01"},
                {"id": "b1", "kind": "banner", "created_at": "2026-01-05"}]
    fake = type("Art", (), {"status": staticmethod(lambda **kw: {"versions": versions})})
    monkeypatch.setattr(auto.agent, "_artwork_module", lambda: fake)
    monkeypatch.setattr(auto.agent, "profile_review", lambda: {"state": "approved", "at": "2026-02-02T00:00:00+00:00", "pieces": {}})
    monkeypatch.setattr(auto.agent, "HOME", tmp_path)
    monkeypatch.setattr(auto.agent, "load_config", lambda: {"platforms": ["instagram", "youtube"]})
    (tmp_path / "operations").mkdir()
    (tmp_path / "audit.json").write_text(json.dumps({"accounts": {"instagram": {"logged_in": True, "handle": "me"}}}))
    (tmp_path / "operations" / "1.json").write_text(json.dumps(
        {"action": "apply-profile", "platform": "instagram", "status": "complete", "finished_at": "2026-02-03T00:00:00+00:00"}))
    (tmp_path / "operations" / "2.json").write_text(json.dumps(
        {"id": "op2", "action": "apply-profile", "platform": "youtube", "status": "needs_verification", "error": "not read back"}))
    out = auto.profile_desk()
    assert [v["id"] for v in out["versions"]["avatar"]] == ["a2", "a1"]  # a reel's own picture is never a profile picture
    assert out["accounts"]["instagram"]["signed_in"] and not out["accounts"]["youtube"]["signed_in"]
    assert out["uploaded"] == {"instagram": "2026-02-03T00:00:00+00:00"}
    assert [row["id"] for row in out["stuck"]] == ["op2"]
