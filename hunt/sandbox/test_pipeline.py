"""Reproductions for the pipeline lane (pipeline/ and common/memory.py)."""

import argparse
from datetime import date
from pathlib import Path

import pytest

from common import config
from common import memory as memory_module
from common.memory import DONE, Memory
from pipeline import learning, run

DAY = date(2026, 10, 22)


def _args(**kw):
    base = dict(fresh=False, dry_run=False, env=None, verbose=False, cli=None, only=[], skip=[], agents=2, today=DAY)
    base.update(kw)
    return argparse.Namespace(**base)


def _week(week: int) -> str:
    days = learning.days_of(week)
    return "# Week %d: t\n\nintro\n\n" % week + "".join(
        "## Day %d: d%d\n\n**System Design: sd%d** (55 min)\nx\n\n**ML / GenAI: ml%d** (55 min)\ny\n\n"
        "**Recall** (10 min)\n- q\n\n**Go deeper**\n- http://a\n\n" % (d, d, d, d)
        for d in days
    )


def test_pipeline_01_settings_failure_does_not_drop_the_boards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: the day is marked done only when every stage ran; a config failure must surface."""

    def boom(env=None):
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(config, "load_settings", boom)
    with pytest.raises(Exception):
        run.board_names(None)


def test_pipeline_02_dry_run_with_fresh_records_nothing(tmp_path: Path) -> None:
    """Contract: --dry-run passes --dry-run to the bots and records nothing."""
    mem = Memory(tmp_path, DAY)
    mem.plan(["apply:naukri"])
    mem.mark("apply:naukri", DONE)
    assert Memory(tmp_path, DAY).is_done("apply:naukri")
    run.run_day(_args(fresh=True, dry_run=True), [], mem)
    assert Memory(tmp_path, DAY).is_done("apply:naukri"), "dry run wiped the checkpoint"


def test_pipeline_03_corrupt_progress_is_not_silently_reset(tmp_path: Path) -> None:
    """Contract: progress.json is 'the start date and the days marked done'."""
    (tmp_path / "progress.json").write_text('{"start": "2026-10-01", "done": [1, 2, 3', encoding="utf-8")
    with pytest.raises(Exception):
        learning.load_progress(tmp_path)


def test_pipeline_04_corrupt_memory_keeps_history(tmp_path: Path) -> None:
    """Contract: progress.json holds, per date, every stage and the companies applied to."""
    (tmp_path / "progress.json").write_text(
        '{"days": {"2026-10-21": {"stages": {}, "applied": [{"company": "Acme"}]}}', encoding="utf-8"
    )
    before = (tmp_path / "progress.json").read_text(encoding="utf-8")
    try:
        mem = Memory(tmp_path, DAY)
    except ValueError:
        # Refusing the damaged file keeps its history on disk for repair.
        assert (tmp_path / "progress.json").read_text(encoding="utf-8") == before
        return
    mem.mark("learn", DONE)
    history = dict(mem.history())
    assert "2026-10-21" in history, history


def test_pipeline_05_empty_study_file_does_not_break_the_index(tmp_path: Path) -> None:
    """Contract: 'one study file per area of the resume; missing ones are written'."""
    root = tmp_path / "rl"
    root.mkdir()
    (root / "01-agent-evaluation-harnesses.md").write_text("", encoding="utf-8")
    index = learning.write_resume_index(root)
    assert index.exists()


def test_pipeline_06_missing_resume_is_an_error_not_an_empty_prompt(tmp_path: Path) -> None:
    """Contract: 'How you used it (only what the resume says, never invent numbers)'."""
    prompts = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return "# T\n\n## Interview questions\n"

    with pytest.raises(Exception):
        learning.fill_resume_learning(ask, tmp_path / "rl", tmp_path / "nope.tex")


def test_pipeline_07_contact_lines_stay_out_of_the_prompt(tmp_path: Path) -> None:
    """Contract: 'Contact lines stay out of the prompt.'"""
    resume = tmp_path / "base.tex"
    resume.write_text(
        "Phone: 98765 43210\nPune, MH 411001\n\\href{https://linkedin.com/in/someone}{LinkedIn}\nPython\n",
        encoding="utf-8",
    )
    text = learning.resume_text(resume)
    assert "98765" not in text and "411001" not in text and "linkedin.com/in/" not in text, text


def test_pipeline_10_mark_done_is_idempotent_within_a_day(tmp_path: Path) -> None:
    """Contract: `pipeline learn --done` marks today's study day finished."""
    (tmp_path / "weeks").mkdir()
    (tmp_path / "weeks" / "week-01.md").write_text(_week(1), encoding="utf-8")
    first = learning.mark_done(tmp_path, DAY)
    second = learning.mark_done(tmp_path, DAY)
    assert (first, second) == (1, 1)


def test_pipeline_12_two_memories_do_not_overwrite_each_other(tmp_path: Path) -> None:
    """Contract: a second run the same day continues where the first left off."""
    first = Memory(tmp_path, DAY)
    second = Memory(tmp_path, DAY)
    first.mark("apply:naukri", DONE)
    second.mark("learn", DONE)
    again = Memory(tmp_path, DAY)
    assert again.is_done("apply:naukri") and again.is_done("learn")
    assert memory_module.DAY_DONE  # module imported for the checkpoint constants
