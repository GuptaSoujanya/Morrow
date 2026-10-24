"""Parallel pipeline writers publish complete indexes from the latest checkpoint."""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from common.memory import DONE, Memory
from pipeline import briefing, run


DAY = date(2026, 10, 22)
ROOT = Path(__file__).resolve().parents[1]


def test_late_index_writer_reloads_completed_stages_without_changing_checkpoint(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory", DAY)
    memory.plan(["brief:papers", "brief:tech-news"])
    stale = Memory(memory.folder, DAY)
    memory.mark("brief:papers", DONE)
    memory.mark("brief:tech-news", DONE)
    checkpoint = memory.path.read_bytes()
    daily = tmp_path / "research" / "daily"
    original = briefing.write_index
    monkeypatch.setattr(briefing, "write_index", lambda day, stages, history, applied:
                        original(day, stages, history, applied, daily, tmp_path / "learning"))

    run.write_index(stale)

    index = (daily / DAY.isoformat() / "README.md").read_text()
    assert "| papers | done |" in index
    assert "| tech-news | done |" in index
    assert memory.path.read_bytes() == checkpoint


def _wait_for(path, child, seconds=5):
    deadline = time.monotonic() + seconds
    while not path.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), "worker did not reach the expected checkpoint"


def test_separate_processes_publish_indexes_one_at_a_time(tmp_path):
    memory = Memory(tmp_path / "memory", DAY)
    memory.plan(["brief:papers", "brief:tech-news"])
    worker = r'''
from datetime import date
import json, os, sys, time
from pathlib import Path
from common.memory import Memory
from pipeline import run
root, label = Path(sys.argv[1]), sys.argv[2]
memory = Memory(root / "memory", date(2026, 10, 22))
def publish(day, stages, history, applied):
    marker = root / "writer-active"
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError("two processes entered index publication together")
    os.close(descriptor)
    try:
        (root / (label + "-entered")).touch()
        if label == "first":
            deadline = time.monotonic() + 5
            while not (root / "release").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("first publisher was not released")
                time.sleep(0.01)
        (root / (label + "-published.json")).write_text(json.dumps(stages))
    finally:
        marker.unlink()
run.briefing.write_index = publish
(root / (label + "-ready")).touch()
run.write_index(memory)
'''
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    children = []
    try:
        first = subprocess.Popen([sys.executable, "-c", worker, str(tmp_path), "first"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        children.append(first)
        _wait_for(tmp_path / "first-entered", first)
        second = subprocess.Popen([sys.executable, "-c", worker, str(tmp_path), "second"],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        children.append(second)
        _wait_for(tmp_path / "second-ready", second)
        # The second process has reached publication, but the first holds the
        # shared lock. It must neither enter nor fail on the exclusive marker.
        time.sleep(0.15)
        assert second.poll() is None
        assert not (tmp_path / "second-entered").exists()
        (tmp_path / "release").touch()
        for child in children:
            _, errors = child.communicate(timeout=5)
            assert child.returncode == 0, errors.decode()
        for label in ("first", "second"):
            assert set(json.loads((tmp_path / (label + "-published.json")).read_text())) == {
                "brief:papers", "brief:tech-news"}
    finally:
        (tmp_path / "release").touch()
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)


@pytest.mark.parametrize("target_name", ["README.md", "TODAY.md"])
def test_failed_index_replacement_keeps_previous_complete_file(tmp_path, monkeypatch, target_name):
    daily = tmp_path / "research" / "daily"
    learning = tmp_path / "learning"
    briefing.write_index(DAY, {}, [], [], daily, learning)
    target = daily / DAY.isoformat() / target_name if target_name == "README.md" else daily.parent / target_name
    previous = target.read_bytes()
    replace = os.replace

    def fail_replacement(source, destination):
        if Path(destination) == target:
            assert target.read_bytes() == previous
            assert Path(source).read_text().startswith("# ")
            raise OSError("replacement interrupted")
        replace(source, destination)

    monkeypatch.setattr(briefing.os, "replace", fail_replacement)
    with pytest.raises(OSError, match="replacement interrupted"):
        briefing.write_index(DAY, {"brief:papers": {"status": DONE}}, [], [], daily, learning)
    assert target.read_bytes() == previous
    assert not list(daily.parent.rglob("*.tmp"))
