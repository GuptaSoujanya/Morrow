"""The daily workflow must not mix saved previews with live bot stages."""
from datetime import date

import pytest

from common import onboard
from common.memory import FAILED, Memory
from pipeline import run


DAY = date(2026, 11, 3)


@pytest.fixture
def configured_pipeline(tmp_path, monkeypatch):
    env = tmp_path / "pipeline.env"
    env.write_text("DRY_RUN=true\n")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("RESUME_PATH", "")
    monkeypatch.setenv("DAILY_QUOTA", "0")
    monkeypatch.setattr(run, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(run, "board_names", lambda _: ["hirist", "cutshort", "wellfound"])
    monkeypatch.setattr(run, "_startup_jobs_on", lambda _: True)
    monkeypatch.setattr(onboard, "needs_onboarding", lambda: False)
    return env


@pytest.mark.parametrize("environment,explicit_preview,expected", [
    (None, False, True),
    ("false", False, False),
    ("false", True, True),
    ("true", False, True),
    ("not-a-boolean", False, True),
])
def test_every_bot_uses_one_effective_mode(configured_pipeline, monkeypatch,
                                         environment, explicit_preview, expected):
    if environment is not None:
        monkeypatch.setenv("DRY_RUN", environment)
    observed = []

    def capture(args, stages, memory, catalogue):
        observed.append(args.dry_run)
        bots = [stage for stage in stages if stage.command]
        assert {stage.name for stage in bots} >= {
            "profile:naukri", "profile:linkedin", "profile:cutshort", "profile:wellfound",
            "apply:naukri", "apply:cutshort", "apply:wellfound", "apply:startups",
        }
        assert all(("--dry-run" in stage.command) == expected for stage in bots)
        return 0

    monkeypatch.setattr(run, "run_day", capture)
    argv = ["run", "--env", str(configured_pipeline)]
    if explicit_preview:
        argv.append("--dry-run")
    assert run.main(argv, today=DAY) == 0
    assert observed == [expected]


def test_saved_preview_runs_callbacks_without_changing_checkpoint(configured_pipeline, monkeypatch):
    memory = Memory(run.MEMORY_DIR, DAY)
    memory.plan(["apply:naukri", "apply:cutshort"])
    memory.mark("apply:naukri", FAILED, "Previous sign-in expired", exit_code=2)
    before = {path.name: path.read_bytes() for path in run.MEMORY_DIR.iterdir() if path.is_file()}
    calls = []
    monkeypatch.setattr(run, "_naukri_apply", lambda flags: calls.append(("naukri", flags)) or 0)
    monkeypatch.setattr(run, "_board_bot", lambda name, tool, flags: calls.append((name, flags)) or 0)
    monkeypatch.setattr(run, "_startup_bot", lambda flags: calls.append(("startups", flags)) or 0)
    assert run.main(["continue", "--env", str(configured_pipeline), "--only", "apply",
                     "--bots", "1", "--fresh", "--redo"], today=DAY) == 0
    assert {name for name, _ in calls} == {"naukri", "hirist", "cutshort", "wellfound", "startups"}
    assert all("--dry-run" in flags for _, flags in calls)
    assert {path.name: path.read_bytes() for path in run.MEMORY_DIR.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("selection", [
    ["study"],
    ["run", "--only", "learn", "--only", "brief"],
    ["run", "--skip", "profile", "--skip", "apply"],
])
def test_study_and_research_can_save_progress_with_applications_in_preview(
        configured_pipeline, monkeypatch, selection):
    observed = []

    def capture(args, stages, memory, catalogue):
        observed.append(args.dry_run)
        assert not any(stage.command for stage in stages)
        assert any(stage.name == "learn" for stage in stages)
        return 0

    monkeypatch.setattr(run, "run_day", capture)
    assert run.main([*selection, "--env", str(configured_pipeline)], today=DAY) == 0
    assert observed == [False]
