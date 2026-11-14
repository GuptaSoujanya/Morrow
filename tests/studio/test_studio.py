"""The video studio with the bridge, ffprobe, ffmpeg and the critic replaced by fakes."""
import importlib.util
import json
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio" / "reels" / "studio.py"

pytestmark = pytest.mark.skipif(not STUDIO.exists(), reason="the private studio folder is not checked out")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("studio_reels_studio_test", STUDIO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.planner, "PLANS", tmp_path / "plans")
    monkeypatch.setattr(module.planner, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "check_bridge", lambda bridge: bridge)
    monkeypatch.setattr(module, "probe", lambda video: {"exists": True, "width": 1080, "height": 1920, "duration_s": 20.0,
                                                         "audio": True, "codec": "h264", "size_mb": 1.0} if video.is_file() else {"exists": False})

    def fake_snapshots(folder, video):
        shots = []
        for pct in module.SNAP_POINTS:
            (folder / f"snap-{pct}.png").write_bytes(b"png")
            shots.append(folder / f"snap-{pct}.png")
        return shots
    monkeypatch.setattr(module, "snapshots", fake_snapshots)
    module.calls = []
    module.verdicts = []

    def fake_run(bridge, prompt, folder, timeout_s, log):
        module.calls.append({"bridge": bridge, "prompt": prompt, "folder": folder, "timeout": timeout_s})
        (folder / "index.html").write_text(f"<html>render {len(module.calls)}</html>")
        (folder / "reel.mp4").write_bytes(b"mp4" + str(len(module.calls)).encode())
        log.write_text("fake log")
        return {"bridge": bridge, "seconds": 3, "rc": 0, "log": str(log), "cost_usd": 0.5, "turns": 7, "tokens": None, "reply": {"done": True}}
    monkeypatch.setattr(module, "run_bridge", fake_run)
    monkeypatch.setattr(module, "critic", lambda folder, item, shots: module.verdicts.pop(0) if module.verdicts
                        else {"ok": True, "problems": [], "fix": "", "missing_text": [], "hook_ok": True})
    module.voiced = []

    def fake_voice(plan, item, folder, force=False):
        module.voiced.append({"day": item["day"], "force": force})
        (folder / "voice.wav").write_bytes(b"wav")
        record = {"engine": "edge", "voice": "en-US-AndrewMultilingualNeural", "duration_s": 17.5,
                  "lines": [{"i": 0, "text": "hook", "start": 0.25, "end": 3.0}], "words": [],
                  "pace": {"words": 30, "wpm": 120, "ok": True}}
        (folder / "words.json").write_text(json.dumps(record))
        item["voice"] = {"engine": "edge", "voice": record["voice"], "duration_s": 17.5, "wpm": 120, "words": 30}
        return record
    monkeypatch.setattr(module, "prepare_voice", fake_voice)
    module.mixed = []
    monkeypatch.setattr(module, "finalize_audio", lambda folder: module.mixed.append(folder) or {"lufs": -14.2, "true_peak_db": -1.3, "sfx": []})
    monkeypatch.setattr(module, "audio_problems", lambda folder, video: [])
    return module


def _plan(studio, days=1):
    plan = studio.planner.new_plan("Python tips", days=days)
    reply = {"pillars": ["Tips"], "series_note": "", "items": [
        {"day": d, "title": f"Reel {d}", "hook": f"Hook {d}", "angle": "Angle", "skill": "hyperframes", "why_skill": "fits",
         "duration_s": 20, "beats": ["open on the bug", "show the fix"], "on_screen_text": ["f'{x=}'", "Python 3.8+"],
         "cta": "Follow", "caption": f"Caption {d}", "hashtags": ["python"], "pillar": "Tips"} for d in range(1, days + 1)]}
    studio.planner.make_calendar(plan, ask=lambda p, s, t: reply)
    script = ["Your print statements are lying to you about one thing",
              "Put an equals sign inside the braces and see the name",
              "Follow for one more Python tip like this one tomorrow"]
    studio.planner.write_prompts(plan, ask=lambda p, s, t: {"prompts": [
        {"day": d, "prompt": "Use the skill hyperframes " + " ".join(["w"] * 130), "script": script} for d in range(1, days + 1)]})
    return studio.planner.load_plan(plan["id"])


def test_make_wraps_the_brief_in_the_delivery_spec(studio):
    plan = _plan(studio)
    result = studio.make(plan["id"], 1, bridge="claude")
    prompt = studio.calls[0]["prompt"]
    assert prompt.startswith("Use the skill hyperframes")
    for must in ("plan.md", "snap-10.png", "snap-90.png", "f'{x=}'", "Python 3.8+", "open on the bug -> show the fix", "top 250 px", '"done": true'):
        assert must in prompt
    assert result["status"] == "ok" and result["video"].endswith("day-01/reel.mp4")
    folder = studio.planner.day_dir(plan, 1)
    assert (folder / "make.json").is_file() and (folder / "make-1.prompt.md").is_file()
    assert studio.record_for(folder)["snaps"] == [f"snap-{p}.png" for p in studio.SNAP_POINTS]
    assert studio.versions(folder) == []


def test_failed_review_comes_back_as_a_fix_pass_on_the_sources(studio):
    plan = _plan(studio)
    studio.verdicts.append({"ok": False, "problems": ["title cut off at the right edge"], "missing_text": ["Python 3.8+"],
                            "fix": "Shrink the title to 72 px."})
    result = studio.make(plan["id"], 1, attempts=3)
    assert len(result["attempts"]) == 2 and result["status"] == "ok"
    assert result["attempts"][0]["problems"][0].startswith("critic: title cut off")
    second = studio.calls[1]["prompt"]
    assert "Do NOT start over" in second and "index.html" in second
    assert "title cut off at the right edge" in second and "'Python 3.8+' never appears" in second and "Shrink the title" in second
    assert studio.calls[1]["timeout"] == studio.EDIT_TIMEOUT_S


def test_giving_up_marks_the_reel_failed(studio):
    plan = _plan(studio)
    studio.verdicts += [{"ok": False, "problems": ["black frame at 50%"], "missing_text": [], "fix": ""}] * 2
    with pytest.raises(studio.StudioError, match="black frame"):
        studio.make(plan["id"], 1, attempts=2)
    folder = studio.planner.day_dir(plan, 1)
    record = studio.record_for(folder)
    assert record["status"] == "failed" and record["problems"] == ["critic: black frame at 50%"] and record["has_video"]


def test_second_make_keeps_the_first_as_a_version(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.make(plan["id"], 1, notes="warmer colours")
    folder = studio.planner.day_dir(plan, 1)
    kept = studio.versions(folder)
    assert [v["n"] for v in kept] == [1] and kept[0]["label"].startswith("before make") and kept[0]["has_video"]
    assert (folder / "versions" / "v1" / "reel.mp4").read_bytes() == b"mp41"
    assert (folder / "versions" / "v1" / "index.html").is_file(), "sources travel with the version"
    assert (folder / "reel.mp4").read_bytes() == b"mp42"
    assert "Extra direction from the editor: warmer colours" in studio.calls[1]["prompt"]


def test_edit_changes_in_place_and_refuses_before_a_render(studio):
    plan = _plan(studio)
    with pytest.raises(studio.StudioError, match="never been rendered"):
        studio.edit(plan["id"], 1, "move the title down")
    studio.make(plan["id"], 1)
    result = studio.edit(plan["id"], 1, "move the title down 60 px", bridge="codex")
    prompt = studio.calls[1]["prompt"]
    assert "Requested changes: move the title down 60 px" in prompt and "Do NOT start over" in prompt and "index.html" in prompt
    assert studio.calls[1]["bridge"] == "codex" and result["mode"] == "edit"
    assert len(studio.versions(studio.planner.day_dir(plan, 1))) == 1
    with pytest.raises(studio.StudioError):
        studio.edit(plan["id"], 1, "   ")


def test_edit_correction_retains_current_direction_prior_brief_and_minor_scope(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.verdicts.append({"ok": False, "problems": ["Supporting label overlaps the caption"],
                           "missing_text": [], "fix": "Move only the supporting label."})
    notes = "Keep the approved mascot and colours. Increase the headline margin only. Read continuity.json and source-review.json."
    studio.edit(plan["id"], 1, notes, attempts=2)
    edit, correction = [call["prompt"] for call in studio.calls[1:]]
    for prompt in (edit, correction):
        assert notes in prompt and plan["items"][0]["prompt"].strip() in prompt
        assert prompt.rsplit("\n\n", 1)[-1].startswith("FINAL CONTINUITY RULE:")
        assert "Default to minor adjustments" in prompt
        assert "scene order, mascot identity and rig, visual style, palette, fonts and motion language" in prompt
        assert "Never revert newer accepted styling to an older brief" in prompt
        assert "Only an explicit current creator request can expand that scope" in prompt
    assert "Supporting label overlaps the caption" in correction
    assert "do not repeat completed edits" in correction


def test_restore_brings_a_version_back_and_keeps_the_current_one(studio):
    plan = _plan(studio)
    studio.make(plan["id"], 1)
    studio.make(plan["id"], 1)
    folder = studio.planner.day_dir(plan, 1)
    record = studio.restore(plan["id"], 1, 1)
    assert (folder / "reel.mp4").read_bytes() == b"mp41" and record["mode"] == "restore"
    assert [v["n"] for v in studio.versions(folder)] == [1, 2] and studio.versions(folder)[1]["label"] == "before restoring v1"
    with pytest.raises(studio.StudioError):
        studio.restore(plan["id"], 1, 9)


def test_direct_reel_is_a_one_day_plan_with_a_prompt_file(studio):
    plan = studio.direct("Three list tricks", "Use the skill hyperframes to make a 25 s reel about " + " ".join(["slicing"] * 20),
                         duration_s=25, skill="bang-motion")
    item = plan["items"][0]
    assert plan["days"] == 1 and plan["status"] == "done" and item["skill"] == "bang-motion" and item["duration_s"] == 25
    assert (studio.planner.day_dir(plan, 1) / "PROMPT.md").read_text().startswith("Use the skill hyperframes")
    assert studio.planner.load_plan(plan["id"])["items"][0]["prompt_path"].endswith("day-01/PROMPT.md")
    with pytest.raises(studio.StudioError, match="too short"):
        studio.direct("Short", "too short", 20)
    with pytest.raises(studio.StudioError):
        studio.direct("Long", " ".join(["w"] * 30), 200)


def test_set_prompt_rewrites_the_prompt_file(studio):
    plan = _plan(studio)
    item = studio.set_prompt(plan["id"], 1, "Use the skill bang-motion instead " + " ".join(["x"] * 25))
    assert item["prompt"].startswith("Use the skill bang-motion")
    assert (studio.planner.day_dir(plan, 1) / "PROMPT.md").read_text().startswith("Use the skill bang-motion")
    with pytest.raises(studio.StudioError):
        studio.set_prompt(plan["id"], 1, "tiny")
    with pytest.raises(studio.StudioError):
        studio.set_prompt(plan["id"], 9, " ".join(["x"] * 30))


def test_codex_gets_the_prompt_on_stdin_and_its_last_message_is_read(studio, tmp_path):
    argv, stdin = studio.bridge_argv("codex", "make it", tmp_path)
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "-" and stdin == "make it"
    assert "--dangerously-bypass-approvals-and-sandbox" in argv and str(tmp_path) in argv
    argv, stdin = studio.bridge_argv("claude", "make it", tmp_path)
    assert argv[:3] == ["claude", "-p", "make it"] and stdin is None
    (tmp_path / "last-message.txt").write_text('Done. {"done": true, "video": "reel.mp4"}')
    out = "\n".join([json.dumps({"type": "item.completed", "item": {}}), json.dumps({"type": "item.completed", "item": {}}),
                     json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}})])
    parsed = studio.parse_run("codex", out, tmp_path)
    assert parsed["turns"] == 2 and parsed["tokens"] == 120 and parsed["reply"] == {"done": True, "video": "reel.mp4"}
    parsed = studio.parse_run("claude", json.dumps({"total_cost_usd": 1.5, "num_turns": 9, "result": 'ok {"done": true}'}), tmp_path)
    assert parsed["cost_usd"] == 1.5 and parsed["turns"] == 9 and parsed["reply"] == {"done": True}


def test_videos_and_detail_list_rendered_days_only(studio):
    plan = _plan(studio, days=2)
    studio.make(plan["id"], 2)
    rows = studio.videos()
    assert [(r["day"], r["status"]) for r in rows] == [(2, "ok")]
    info = studio.detail(plan["id"], 2)
    assert info["item"]["title"] == "Reel 2" and info["record"]["has_video"] and info["sources"] == ["index.html", "plan.md"] or "index.html" in info["sources"]
    assert info["log_tail"] == "fake log" and len(info["attempts"]) == 1 and info["bridges"][0]["id"] == "claude"
    with pytest.raises(studio.StudioError):
        studio.detail(plan["id"], 7)


def test_the_style_and_the_mascot_are_written_into_the_brief(studio, tmp_path):
    item = {"day": 1, "title": "T", "hook": "H", "style": "paper", "skill": "paper-cutout", "duration_s": 20,
            "beats": ["one"], "on_screen_text": ["x"]}
    text = studio.spec(item, tmp_path)
    assert "THE LOOK is paper cut-out" in text and "Layered paper" in text
    files = studio.planner.mascot_files()
    assert set(files) == {"sheet", "cutout", "sprite", "source"}, f"the mascot assets are missing: {files}"
    assert "THE MASCOT is the one explaining" in text and "MASCOT.md" in text
    assert "sprite-1080.png" in text
    assert "red zip hoodie" in studio.mascot_check()
    assert "paper-cutout" in studio.motion_rules("paper-cutout")


def test_start_fresh_archives_the_previous_mascot_reversibly():
    path = ROOT / "studio" / "reels" / "archive.py"
    spec = importlib.util.spec_from_file_location("studio_reels_archive_test", path)
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    assert "mascot" in archive.WORK_PATHS, "start fresh must archive the previous channel identity with its manifest"


def test_every_style_names_an_installed_skill(studio):
    for name in studio.planner.STYLES:
        look = studio.planner.style(name)
        assert look["label"] and look["look"] and look["motion"]
        assert look["skill"], f"{name} has no installed skill: {look['missing']}"
    with pytest.raises(ValueError):
        studio.planner.style("watercolour-dreams")


def test_a_direct_reel_takes_the_looks_skill_unless_one_is_named(studio):
    plan = studio.direct("Clay one", "Explain the thing " + " ".join(["w"] * 25), 20, style_name="clay")
    assert plan["style"] == "clay" and plan["items"][0]["style"] == "clay"
    assert plan["items"][0]["skill"] == studio.planner.style("clay")["skill"]
    named = studio.direct("Mine", "Explain the thing " + " ".join(["w"] * 25), 20, skill="hyperframes", style_name="pencil")
    assert named["items"][0]["skill"] == "hyperframes" and named["items"][0]["style"] == "pencil"
    with pytest.raises(ValueError):
        studio.direct("Bad", "Explain the thing " + " ".join(["w"] * 25), 20, style_name="nope")


def test_the_render_record_keeps_the_look(studio):
    plan = studio.direct("Clay two", "Explain the thing " + " ".join(["w"] * 25), 20, style_name="sticker")
    studio.make(plan["id"], 1)
    assert studio.detail(plan["id"], 1)["record"]["style"] == "sticker"


@pytest.fixture
def local_tools(studio, tmp_path, monkeypatch):
    root, home = tmp_path / "workspace", tmp_path / "home"
    project = root / "reels" / "a reel with spaces ' $(no-execution)"
    project.mkdir(parents=True)
    home.mkdir()
    binaries, skills, lookups = {}, {}, []
    monkeypatch.setattr(studio, "ROOT", root)
    monkeypatch.setattr(studio.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(studio.shutil, "which", lambda name: lookups.append(name) or binaries.get(name))
    monkeypatch.setattr(studio.planner, "skill_path", lambda name: skills.get(name))
    monkeypatch.setattr(studio.planner, "companions", lambda skill: ["motion-doctrine", "hyperframes-core"])
    return {"root": root, "home": home, "project": project, "binaries": binaries, "skills": skills, "lookups": lookups}


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_hyperframes_prefers_project_local_command_without_searching_cache(studio, local_tools, monkeypatch):
    local = executable(local_tools["project"] / "node_modules" / ".bin" / "hyperframes")
    local_tools["binaries"]["hyperframes"] = str(executable(local_tools["home"] / "bin" / "hyperframes"))
    monkeypatch.setattr(studio.Path, "glob", lambda *args: pytest.fail("Local discovery must not inspect an npm cache or home tree."))
    assert studio._hyperframes_command(local_tools["project"]) == [str(local)]
    assert "hyperframes" not in local_tools["lookups"]


def test_hyperframes_reuses_repository_local_mjs_through_node(studio, local_tools, monkeypatch):
    script = executable(local_tools["root"] / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs")
    link = local_tools["root"] / "node_modules" / ".bin" / "hyperframes"
    link.parent.mkdir(parents=True)
    link.symlink_to(script)
    node = executable(local_tools["home"] / "Node tools" / "node")
    local_tools["binaries"]["node"] = str(node)
    monkeypatch.setattr(studio.Path, "glob", lambda *args: pytest.fail("A repository-local CLI must avoid cache discovery."))
    assert studio._hyperframes_command(local_tools["project"]) == [str(node), str(script)]
    assert local_tools["lookups"] == ["node"]


def test_hyperframes_path_command_and_project_inspection_are_shell_quoted(studio, local_tools, monkeypatch):
    installed = executable(local_tools["home"] / "tools with spaces ' $(no-execution)" / "hyperframes")
    local_tools["binaries"]["hyperframes"] = str(installed)
    monkeypatch.setattr(studio.Path, "glob", lambda *args: pytest.fail("An installed CLI must not trigger cache discovery."))
    hints = studio.local_tool_contract({"skill": "hyperframes"}, local_tools["project"])
    assert f"`{shlex.quote(str(installed))}`" in hints
    assert f"-- {shlex.quote(str(local_tools['project']))}`" in hints
    assert "reuse its package.json scripts or saved render scripts" in hints
    assert "Never run `find /`" in hints and "recursive search through the home directory" in hints
    assert "rg --files" in hints and "no package download or installation is needed" in hints


def test_npx_fallback_checks_only_the_known_package_path_and_uses_node(studio, local_tools, monkeypatch):
    cache = local_tools["home"] / ".npm" / "_npx"
    script = cache / "installed-hash" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("// Cached fixture; never executed.")
    older = cache / "zz-older-hash" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    older.parent.mkdir(parents=True)
    older.write_text("// An older installed version should not win by its hash name.")
    studio.os.utime(older, (1, 1))
    node = executable(local_tools["home"] / "node-bin" / "node")
    local_tools["binaries"]["node"] = str(node)
    unrelated = executable(local_tools["home"] / "unrelated-project" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs")
    real_glob, searched = studio.Path.glob, []
    def bounded_glob(path, pattern):
        searched.append((path, pattern))
        assert path == cache and pattern == "*/node_modules/hyperframes/bin/hyperframes.mjs"
        return real_glob(path, pattern)
    monkeypatch.setattr(studio.Path, "glob", bounded_glob)
    assert studio._hyperframes_command(local_tools["project"]) == [str(node), str(script)]
    assert searched == [(cache, "*/node_modules/hyperframes/bin/hyperframes.mjs")]
    assert unrelated.is_file(), "The unrelated install exists but must never be discovered by a whole-home walk."


def test_hyperframes_missing_tool_reports_bounded_fallback_without_install_or_broad_search(studio, local_tools):
    hints = studio.local_tool_contract({"skill": "hyperframes"}, local_tools["project"])
    assert studio._hyperframes_command(local_tools["project"]) is None
    assert "No usable local HyperFrames command was found" in hints
    assert "existing working project render script" in hints and "report the missing tool" in hints
    assert "No installed skill file was resolved for:" in hints
    assert "available local command is" not in hints


def test_cached_mjs_without_node_does_not_claim_a_working_command(studio, local_tools):
    script = local_tools["home"] / ".npm" / "_npx" / "cache" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("// Requires Node; never executed.")
    assert studio._hyperframes_command(local_tools["project"]) is None
    assert "No usable local HyperFrames command" in studio.local_tool_contract({"skill": "hyperframes"}, local_tools["project"])


@pytest.mark.parametrize("mode", ["make", "edit", "fix"])
def test_generation_prompts_resolve_exact_skill_files_and_keep_existing_renderer(studio, local_tools, monkeypatch, mode):
    for name in ("hyperframes", "hyperframes-cli", "motion-doctrine", "hyperframes-core"):
        path = local_tools["home"] / "skill library ' $(no-execution)" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("Fixture instructions.")
        local_tools["skills"][name] = path
    (local_tools["project"] / "render-existing.mjs").write_text("// Reuse this source project's renderer.")
    monkeypatch.setattr(studio, "spec", lambda *args: "Delivery constraints unchanged.")
    item = {"title": "An existing reel", "prompt": "Original creative direction.", "skill": "hyperframes"}
    prompt = studio.build_prompt(item, local_tools["project"], mode, notes="Make the title easier to read.")
    for name, path in local_tools["skills"].items():
        assert f"{name}: {json.dumps(str(path))}" in prompt
    assert "Keep this project's existing renderer" in prompt
    assert "Delivery constraints unchanged." in prompt
    assert "Never run `find /`" in prompt and "rg --files" in prompt
    if mode == "make":
        assert prompt.startswith(item["prompt"])
    else:
        assert "Do NOT start over" in prompt and item["prompt"] in prompt
