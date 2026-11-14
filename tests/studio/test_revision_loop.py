"""The revision loop: scoped rounds, the feedback list, the prompt preview, every round kept, and one change sent to several reels."""
import json

import pytest

from tests.studio.test_studio import _plan, studio  # noqa: F401  (the fixture)


def test_a_scoped_round_unlocks_only_what_was_ticked(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.edit(plan["id"], 1, "Give the mascot a pointing pose beside the code", scopes=["mascot", "visuals"])
    prompt = studio.calls[-1]["prompt"]
    tail = prompt.rsplit("\n\n", 1)[-1]
    assert tail.startswith("CHANGE SCOPE FOR THIS ROUND")
    assert "You MAY change: Visuals and layout" in tail and "Mascot (" in tail
    kept = tail.split("Keep exactly as they are in the current cut: ", 1)[1].split(".", 1)[0]
    assert "Script" in kept and "Voice" in kept and "Mascot" not in kept
    assert "same character" in tail and "FINAL CONTINUITY RULE" not in prompt
    record = json.loads((studio.planner.day_dir(plan, 1) / "make.json").read_text())
    assert record["scopes"] == ["visuals", "mascot"]


def test_a_round_without_a_scope_keeps_the_minor_fix_rule(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.edit(plan["id"], 1, "Nudge the title down a little")
    assert "FINAL CONTINUITY RULE" in studio.calls[-1]["prompt"]


def test_unknown_scope_is_refused(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    with pytest.raises(studio.StudioError, match="Unknown change scope"):
        studio.edit(plan["id"], 1, "anything at all here", scopes=["everything"])


def test_voice_and_script_rounds_record_the_narration_again(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.edit(plan["id"], 1, "A warmer delivery please", scopes=["voice"])
    assert studio.voiced[-1]["force"] is True
    new_lines = ["Stop guessing what your variable holds", "One equals sign prints the name too", "Follow for more"]
    studio.edit(plan["id"], 1, "Tighter wording", scopes=["script"], script=new_lines)
    assert studio.voiced[-1]["force"] is True
    assert studio.planner.load_plan(plan["id"])["items"][0]["script"] == new_lines
    assert "retime every scene and caption" in studio.calls[-1]["prompt"]


def test_a_script_round_without_lines_rewrites_them_from_the_feedback(studio, monkeypatch):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    asked = []
    lines = ["Your print calls hide the variable name", "Add an equals sign inside the braces", "Follow for a tip tomorrow"]
    monkeypatch.setattr(studio.planner, "ask_checked", lambda prompt, schema, check, timeout: asked.append(prompt) or {"script": lines})
    studio.edit(plan["id"], 1, "Make the hook sharper", scopes=["script"])
    assert "Make the hook sharper" in asked[0]
    assert studio.planner.load_plan(plan["id"])["items"][0]["script"] == lines


def test_feedback_is_one_numbered_list_with_moments(studio):
    text = studio.feedback_text([{"text": "Bigger title", "at": 3.4}, {"text": "  "}, {"text": "Calmer music", "at": None},
                                 {"text": "Hold the end card", "at": 75}], "Keep it bright")
    assert text == "1. At 0:03: Bigger title\n2. Calmer music\n3. At 1:15: Hold the end card\n\nFor the whole reel: Keep it bright"
    with pytest.raises(studio.StudioError, match="4,000"):
        studio.feedback_text([{"text": "x" * 4100}])


def test_preview_is_the_exact_prompt_and_changes_nothing(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    before = len(studio.calls)
    shown = studio.preview(plan["id"], 1, "1. Bigger title", ["text", "mascot"])
    assert len(studio.calls) == before and studio.voiced and len(studio.versions(studio.planner.day_dir(plan, 1))) == 0
    assert "Requested changes: 1. Bigger title" in shown["prompt"] and "CHANGE SCOPE FOR THIS ROUND" in shown["prompt"]
    assert shown["scopes"] == ["text", "mascot"] and "Voice" in shown["kept"] and shown["revoice"] is False
    assert studio.preview(plan["id"], 1, "x", ["script"])["script_rewrite"] is True


def test_every_round_is_listed_with_the_feedback_that_made_it(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.edit(plan["id"], 1, "Bigger title", scopes=["text"])
    studio.edit(plan["id"], 1, "New mascot pose", scopes=["mascot"])
    rows = studio.rounds(studio.planner.day_dir(plan, 1))
    assert [r["round"] for r in rows] == [1, 2, 3]
    assert [r["mode"] for r in rows] == ["make", "edit", "edit"]
    assert rows[1]["notes"] == "Bigger title" and rows[1]["scopes"] == ["text"] and rows[1]["version"] == 2
    assert rows[2]["current"] and rows[2]["notes"] == "New mascot pose" and rows[2]["version"] is None
    detail = studio.detail(plan["id"], 1)
    assert detail["rounds"] == rows and {s["id"] for s in detail["scopes"]} >= {"mascot", "script", "voice"}


def test_one_change_reaches_several_reels_and_a_failure_does_not_stop_the_rest(studio):
    plan = _plan(studio, days=3)
    studio.make(plan["id"], 1)
    studio.make(plan["id"], 3)
    results = studio.revise_many([{"plan_id": plan["id"], "day": 1}, {"plan_id": plan["id"], "day": 2},
                                  {"plan_id": plan["id"], "day": 3}], "Mascot waves at the end", scopes=["mascot"])
    assert [r["status"] for r in results] == ["ok", "failed", "ok"]
    assert "never been rendered" in results[1]["error"]
    for day in (1, 3):
        assert json.loads((studio.planner.day_dir(plan, day) / "make.json").read_text())["notes"] == "Mascot waves at the end"


# --- the dashboard routes ---------------------------------------------------------------------------

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

API = Path(__file__).resolve().parents[2] / "studio" / "api" / "studio_api.py"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("MORROW_STUDIO_JOBS", str(tmp_path / "jobs"))
    spec = importlib.util.spec_from_file_location("studio_api_for_loop", API)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.started = []
    monkeypatch.setattr(module, "_start_job", lambda action, name, group, argv=None, kind="", **kw:
                        module.started.append((action, name, kind, argv)) or {"id": "1", "state": "running"})
    monkeypatch.setattr(module, "_job_view", lambda job: job)
    monkeypatch.setattr(module, "_running", lambda kind: None)
    return module


class Handler:
    sent = None

    def json(self, payload, status=200):
        self.sent = (int(status), payload)


def _rendered(api, tmp_path, monkeypatch, days=(1, 2)):
    plans = {"p": {"id": "p", "items": [{"day": d, "prompt": "x"} for d in days]}}
    monkeypatch.setattr(api.planner, "load_plan", lambda plan_id: plans[plan_id] if plan_id in plans else (_ for _ in ()).throw(FileNotFoundError(plan_id)))
    monkeypatch.setattr(api.planner, "day_dir", lambda plan, day: tmp_path / f"day-{day}")
    for d in days:
        (tmp_path / f"day-{d}").mkdir(exist_ok=True)
        (tmp_path / f"day-{d}" / "reel.mp4").write_bytes(b"mp4")
    return plans["p"]


def test_a_round_for_several_reels_is_one_job_with_its_request_on_disk(api, tmp_path, monkeypatch):
    _rendered(api, tmp_path, monkeypatch)
    handler = Handler()
    api._post_revise(handler, {"targets": [{"plan_id": "p", "day": 1}, {"plan_id": "p", "day": 2}, {"plan_id": "p", "day": 1}],
                               "notes": [{"text": "Mascot waves goodbye", "at": 19}], "scopes": ["mascot"], "bridge": "codex"})
    assert handler.sent[0] == 202 and len(api.started) == 1
    action, name, kind, argv = api.started[0]
    assert (action, name, kind) == ("revise", "2 reels", "make") and argv[-2] == "revise"
    request = json.loads(Path(argv[-1]).read_text())
    assert request == {"targets": [{"plan_id": "p", "day": 1}, {"plan_id": "p", "day": 2}],
                       "notes": "1. At 0:19: Mascot waves goodbye", "scopes": ["mascot"], "bridge": "codex"}
    assert str(tmp_path / "jobs") in argv[-1]


def test_a_round_for_several_reels_refuses_what_it_cannot_do(api, tmp_path, monkeypatch):
    _rendered(api, tmp_path, monkeypatch, days=(1,))
    cases = [({"targets": [{"plan_id": "p", "day": 1}], "notes": "short"}, "few words"),
             ({"targets": [{"plan_id": "p", "day": 1}], "notes": "rewrite every line", "scopes": ["script"]}, "one reel at a time"),
             ({"targets": [{"plan_id": "p", "day": 5}], "notes": "a proper change here"}, "not been rendered"),
             ({"targets": [], "notes": "a proper change here"}, "at least one"),
             ({"targets": [{"plan_id": "p", "day": 1}], "notes": "a proper change here", "scopes": ["all"]}, "Unknown change scope")]
    for body, message in cases:
        with pytest.raises((ValueError, api.studio.StudioError), match=message):
            api._post_revise(Handler(), body)
    assert not api.started


def test_an_edit_round_carries_its_scopes_and_new_lines_to_the_job(api, tmp_path, monkeypatch):
    plan = _rendered(api, tmp_path, monkeypatch, days=(1,))
    handler = Handler()
    api._post_render(handler, "edit", plan, {"day": 1, "notes": [{"text": "New hook line"}], "scopes": ["script", "text"],
                                             "script": ["Line one", "Line two"], "bridge": "claude"})
    assert handler.sent[0] == 202
    argv = api.started[0][3]
    assert argv[argv.index("--notes") + 1] == "1. New hook line"
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--scope"] == ["text", "script"]
    assert Path(argv[argv.index("--script-file") + 1]).read_text() == "Line one\nLine two\n"
