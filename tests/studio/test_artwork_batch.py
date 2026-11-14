"""One round of artwork feedback becomes one generate command per marked piece."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "studio" / "reels" / "artwork_batch.py"
pytestmark = pytest.mark.skipif(not BATCH.exists(), reason="the private studio folder is not checked out")


@pytest.fixture(scope="module")
def batch():
    spec = importlib.util.spec_from_file_location("studio_artwork_batch", BATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_piece_gets_its_own_command_with_its_own_brief(batch, tmp_path):
    steps = batch.commands({"items": [
        {"kind": "cover", "prompt": "Bigger headline", "parent_id": "art-c", "plan_id": "p", "day": 1},
        {"kind": "banner", "prompt": "Brighter red", "parent_id": "art-b"}]}, tmp_path)
    assert [kind for kind, _ in steps] == ["cover", "banner"]
    cover, banner = steps[0][1], steps[1][1]
    assert cover[cover.index("--parent-id") + 1] == "art-c" and cover[cover.index("--day") + 1] == "1"
    assert "--plan-id" not in banner
    assert Path(cover[cover.index("--prompt-file") + 1]).read_text() == "Bigger headline"


def test_one_failed_piece_does_not_stop_the_others(batch, tmp_path, monkeypatch, capsys):
    calls = []
    class Done:
        def __init__(self, ok):
            self.returncode, self.stdout, self.stderr = (0, json.dumps({"id": "art-new"}), "") if ok else (1, "", "bridge down")
    monkeypatch.setattr(batch.subprocess, "run", lambda command, **kw: calls.append(command) or Done(len(calls) != 1))
    file = tmp_path / "b.json"
    file.write_text(json.dumps({"items": [{"kind": "cover", "prompt": "a change", "parent_id": "x"},
                                          {"kind": "thumbnail", "prompt": "a change", "parent_id": "y"}]}))
    assert batch.main([str(file)]) == 1 and len(calls) == 2
    out = capsys.readouterr().out
    assert "cover: could not be redesigned - bridge down" in out and "thumbnail: new version art-new" in out
    assert "1 of 2 redesigned; failed: cover" in out


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("MORROW_STUDIO_JOBS", str(tmp_path / "jobs"))
    spec = importlib.util.spec_from_file_location("studio_api_for_changes", ROOT / "studio" / "api" / "studio_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Handler:
    def __init__(self):
        self.sent = None
    def json(self, payload, status=200):
        self.sent = (int(status), payload)


def test_one_round_of_changes_starts_exactly_one_job(api, monkeypatch, tmp_path):
    started, saved = [], []
    pieces = {"cover": {"id": "art-c"}, "thumbnail": {"id": "art-t"}, "avatar": {"id": "art-a", "source": "photo"}, "banner": {"id": "art-b"}}
    monkeypatch.setattr(api.social_agent, "review", lambda target, decision, note, plan_id, day: saved.append((target, decision, note))
                        or {"plan_id": "p", "day": 1, "pieces": pieces})
    monkeypatch.setattr(api, "_start_job", lambda action, name, group, argv=None, kind="": started.append((action, name, kind, argv))
                        or {"id": "1", "state": "running", "argv": argv})
    monkeypatch.setattr(api.artwork, "HOME", tmp_path)
    monkeypatch.setattr(api, "_job_view", lambda job: job)
    handler = Handler()
    api._post_review_changes(handler, {"target": "artwork", "plan_id": "p", "day": 1, "general": "Brighter red",
                                       "pieces": {"cover": "Bigger headline"}})
    assert handler.sent[0] == 202 and len(started) == 1
    action, name, kind, argv = started[0]
    assert (action, kind) == ("redesign", "artwork") and name == "cover, thumbnail, banner", "a supplied photo is left alone"
    batch = json.loads(Path(argv[-1]).read_text())
    assert [item["kind"] for item in batch["items"]] == ["cover", "thumbnail", "banner"]
    assert batch["items"][0]["plan_id"] == "p" and "plan_id" not in batch["items"][2]
    assert saved == [("artwork", "changes", "Reel / Shorts cover: Bigger headline; whole set: Brighter red")]

    started.clear()
    monkeypatch.setattr(api.social, "load_config", lambda: {"bridge": "codex"})
    api._post_review_changes(handler, {"target": "video", "plan_id": "p", "day": 1,
                                       "notes": [{"text": "Hold the hook", "at": 2}, {"text": "Louder"}]})
    action, name, kind, argv = started[0]
    assert (action, kind, name) == ("edit", "make", "p:1") and argv[argv.index("--bridge") + 1] == "codex"
    notes = argv[argv.index("--notes") + 1]
    assert "1. At 0:02: Hold the hook" in notes and "2. Louder" in notes


def test_changes_wait_while_something_is_being_made(api, monkeypatch):
    monkeypatch.setattr(api, "_running", lambda kind: kind == "make")
    monkeypatch.setattr(api.social_agent, "review", lambda *a: pytest.fail("nothing may be saved while a cut is being made"))
    handler = Handler()
    api._post_review_changes(handler, {"target": "video", "plan_id": "p", "day": 1, "notes": [{"text": "Louder"}]})
    assert handler.sent[0] == 409 and "notes are kept" in handler.sent[1]["error"]


def test_a_reel_render_only_holds_up_that_reels_own_cover_and_thumbnail(api, monkeypatch):
    render = {"kind": "make", "action": "make", "name": "p:1", "state": "running"}
    monkeypatch.setattr(api, "_running", lambda kind: render if kind == "make" else None)
    sources = {"other-reel": {"kind": "thumbnail", "plan_id": "p", "day": 2},
               "this-reel": {"kind": "thumbnail", "plan_id": "p", "day": 1},
               "channel": {"kind": "avatar", "plan_id": "", "day": None}}
    monkeypatch.setattr(api.artwork, "load", lambda identity: sources[identity])
    prepared = []
    monkeypatch.setattr(api.review_refinement, "prepare", lambda kind, body: prepared.append(body["artwork_id"]) or
                        {"id": "r1", "artwork_kind": "thumbnail", "plan_id": "p", "day": 1})
    monkeypatch.setattr(api, "_start_job", lambda *a, **k: {"id": "2", "state": "running"})
    monkeypatch.setattr(api, "_job_view", lambda job: job)
    for identity, status in (("other-reel", 202), ("channel", 202), ("this-reel", 409)):
        handler = Handler()
        api._post_refinement(handler, "artwork", {"run_id": "x", "artwork_id": identity})
        assert handler.sent[0] == status, identity
    assert prepared == ["other-reel", "channel"]
    assert "a reel render (make, p:1)" in handler.sent[1]["error"] and "made from that reel's frames" in handler.sent[1]["error"]
    handler = Handler()
    api._post_refinement(handler, "video", {"run_id": "x", "plan_id": "p", "day": 1})
    assert handler.sent[0] == 409
