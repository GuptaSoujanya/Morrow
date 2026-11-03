"""Runtime paths are isolated without mutating saved configuration or inputs."""
import sys

import pytest

from common import browser_lanes
from web import run_isolation
from web.runner import conflicts, resources_for
from web.state import Command


@pytest.mark.parametrize("args", [
    ("status",), ("check",), ("learn",),
    ("continue", "--only", "learn"),
    ("continue", "--only", "research:resume"),
    ("continue", "--only", "brief"),
    ("continue", "--only", "profile:linkedin"),
])
def test_nonbrowser_pipeline_commands_never_prepare_profiles(tmp_path, monkeypatch, args):
    monkeypatch.setattr(browser_lanes, "prepare_all", lambda *args: pytest.fail("Unexpected profile preparation"))
    command = Command("Pipeline", (sys.executable, "-m", "pipeline", *args))
    run_isolation.prepare(tmp_path, command, "pipeline", "example", {}, resources_for(command, "pipeline"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("selection", [(), ("--only", "apply"), ("--only", "apply:startups")])
def test_pipeline_startup_selection_reserves_its_stage_and_shared_browser(selection):
    command = Command("Pipeline", (sys.executable, "-m", "pipeline", "continue", *selection))
    selected = resources_for(command, "pipeline")
    direct = resources_for(Command("Startups", (sys.executable, "-m", "startup_bot")), "startups")
    assert {"stage:apply:startups", "browser:lane:startups"} <= selected
    assert conflicts(selected, direct)


@pytest.mark.parametrize("selection", [
    ("--skip", "apply:startups"), ("--skip", "apply"),
    ("--only", "apply", "--skip", "apply:startups"),
    ("--only", "apply:cutshort"),
])
def test_pipeline_without_startups_does_not_block_a_direct_startup_run(selection):
    command = Command("Pipeline", (sys.executable, "-m", "pipeline", "continue", *selection))
    selected = resources_for(command, "pipeline")
    direct = resources_for(Command("Startups", (sys.executable, "-m", "startup_bot")), "startups")
    assert "stage:apply:startups" not in selected
    assert "browser:lane:startups" not in selected
    assert not conflicts(selected, direct)


def test_private_paths_take_effect_without_changing_saved_profile_or_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(tmp_path / "main"))
    monkeypatch.setenv("RESUME_OUT_DIR", str(tmp_path / "resumes"))
    monkeypatch.setenv("SCREENSHOT_DIR", str(tmp_path / "screenshots"))
    command = Command("Hirist", ("synthetic", "--site", "hirist"))
    source = {"PROFILE_PATH": str(tmp_path / "saved-profile.yaml"), "RESUME_PATH": str(tmp_path / "original.pdf")}
    first = run_isolation.prepare(tmp_path, command, "boards", "first", source, resources_for(command, "boards"))
    second = run_isolation.prepare(tmp_path, command, "boards", "second", source, resources_for(command, "boards"))
    assert first["BROWSER_PROFILE_DIR"] == second["BROWSER_PROFILE_DIR"] == str(tmp_path / "lanes/hirist")
    for key in ("RESUME_OUT_DIR", "SCREENSHOT_DIR"):
        assert first[key] != second[key]
    assert first["MORROW_RESUME_LIBRARY_DIR"] == second["MORROW_RESUME_LIBRARY_DIR"] == str(tmp_path / "resumes")
    assert all(first[key] == second[key] == value for key, value in source.items())
    assert set(source) == {"PROFILE_PATH", "RESUME_PATH"}
