"""Checkpoint recovery uses synthetic stages only; no bot or provider runs."""

import argparse
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from common.memory import DONE, FAILED, RUNNING, Memory
from common.pipeline_diagnostics import MAX_DETAIL, sanitize_detail
from pipeline import lanes, run


DAY = date(2026, 10, 22)


def args(**changes):
    options = dict(fresh=False, dry_run=False, redo=False, env=None,
                   cli="kiro", agents=2, bots=1, containers=False)
    options.update(changes)
    return argparse.Namespace(**options)


@pytest.fixture(autouse=True)
def no_derived_files(monkeypatch):
    monkeypatch.setattr(run, "write_index", lambda memory: None)
    monkeypatch.setattr(run, "check_day", lambda memory, stages: None)
    monkeypatch.setattr(run, "sync_applied", lambda memory, env: None)


def test_resume_keeps_completed_outputs_date_and_last_error_until_success(tmp_path):
    memory = Memory(tmp_path / "checkpoint", DAY)
    artifact = tmp_path / "saved.md"
    calls = []

    def complete():
        calls.append("complete")
        artifact.write_text("saved output")
        return 0

    def fail():
        calls.append("failed")
        logging.getLogger("synthetic").error("Kiro session expired. Sign in to Kiro and retry.")
        return 2

    stages = [run.Stage("profile:synthetic", complete, outputs=(artifact,)),
              run.Stage("research:synthetic", fail)]
    assert run.run_day(args(), stages, memory) == run.EXIT_FAILED
    failed = Memory(memory.folder, DAY).stage("research:synthetic")
    assert failed["last_error"]["message"] == "Kiro session expired. Sign in to Kiro and retry."
    assert failed["last_error"]["exit_code"] == 2
    assert failed["started_at"] and failed["finished_at"]
    assert "owner_pid" not in failed
    completed = dict(memory.stage("profile:synthetic"))

    def fixed():
        live = Memory(memory.folder, DAY).stage("research:synthetic")
        assert live["status"] == RUNNING and live["owner_pid"] == os.getpid()
        assert "finished_at" not in live
        assert live["last_error"] == failed["last_error"]
        calls.append("fixed")
        return 0

    stages[1] = run.Stage("research:synthetic", fixed)
    assert run.run_day(args(), stages, Memory(memory.folder, DAY)) == 0
    recovered = Memory(memory.folder, DAY)
    assert recovered.stage("profile:synthetic") == completed
    assert artifact.read_text() == "saved output"
    assert calls == ["complete", "failed", "fixed"]
    assert recovered.stage("research:synthetic")["last_error"]["resolved_at"]
    assert recovered.stage("research:synthetic")["attempts"] == 2
    assert recovered.day_status() == "done"
    assert list(recovered.data["days"]) == [DAY.isoformat()]


def test_parallel_stages_record_only_their_own_failure(tmp_path):
    gate = threading.Barrier(2, timeout=5)

    def fail(label):
        gate.wait()
        logging.getLogger("synthetic").error("%s login expired", label)
        gate.wait()
        return 2

    memory = Memory(tmp_path, DAY)
    stages = [run.Stage(name, lambda name=name: fail(name), parallel=True)
              for name in ("research:alpha", "research:beta")]
    assert run.run_day(args(), stages, memory) == run.EXIT_FAILED
    for name in ("research:alpha", "research:beta"):
        assert memory.stage(name)["last_error"]["message"] == name + " login expired"


def test_subprocess_lane_output_is_attributed_without_redirecting_global_streams(monkeypatch):
    gate = threading.Barrier(2, timeout=5)

    class Child:
        def __init__(self, argv, **_):
            self.label = argv[-1]

        @property
        def stdout(self):
            gate.wait()
            yield "INFO starting %s\n" % self.label
            yield "ERROR %s browser session expired\n" % self.label
            gate.wait()

        def wait(self):
            return 2

    monkeypatch.setattr(lanes.subprocess, "Popen", Child)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run._run, label,
                               lambda label=label: lanes.run_isolated(label, (label,), {}))
                   for label in ("alpha", "beta")]
        results = [future.result() for future in futures]
    assert results == [(2, "ERROR alpha browser session expired"),
                       (2, "ERROR beta browser session expired")]


def test_checkpoint_redacts_secrets_and_bounds_failure_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_API_KEY", "example-environment-value")
    secret_message = (
        "Authentication failed: example-environment-value\n"
        'password="example password" access_token=query-secret\n'
        "Authorization: Bearer bearer-secret-value\n"
        "https://username:password-value@example.com/callback?token=url-secret&X-Amz-Signature=signed-secret\n"
        "session_id=session-secret\n"
        "-----BEGIN PRIVATE KEY-----\nprivate-key-content\n-----END PRIVATE KEY-----"
    )
    memory = Memory(tmp_path, DAY)

    def fail():
        raise RuntimeError(secret_message)

    assert run.run_day(args(), [run.Stage("research:synthetic", fail)], memory) == 3
    persisted = memory.path.read_text() + (tmp_path / (DAY.isoformat() + ".md")).read_text()
    for secret in ("example-environment-value", "example password", "query-secret", "bearer-secret-value",
                   "password-value", "url-secret", "signed-secret", "session-secret", "private-key-content"):
        assert secret not in persisted
    assert "Authentication failed" in persisted
    assert len(sanitize_detail("x" * 5000)) == MAX_DETAIL
    # Legacy detail read by the dashboard can use the same public sanitizer.
    assert "url-secret" not in sanitize_detail(secret_message)


def test_retry_of_interrupted_attempt_explains_previous_stop(tmp_path, monkeypatch):
    memory = Memory(tmp_path, DAY)
    memory.mark("profile:synthetic", RUNNING)
    original = memory.stage("profile:synthetic")["at"]
    monkeypatch.setattr("common.memory.process_alive", lambda pid: False)
    memory.mark("profile:synthetic", RUNNING)
    entry = Memory(tmp_path, DAY).stage("profile:synthetic")
    assert "stopped before recording completion" in entry["last_error"]["message"]
    assert entry["last_error"]["at"] == original
    assert "resolved_at" not in entry["last_error"]
    memory.mark("profile:synthetic", DONE)
    assert memory.stage("profile:synthetic")["last_error"]["resolved_at"]


def test_retry_preserves_legacy_failure_detail(tmp_path):
    (tmp_path / "progress.json").write_text(json.dumps({"days": {DAY.isoformat(): {
        "stages": {"profile:synthetic": {"status": "failed", "attempts": 1,
            "at": "2026-10-22T09:00:00", "detail": "Sign-in expired; token=old-secret"}}, "applied": []}}}))
    memory = Memory(tmp_path, DAY)
    memory.mark("profile:synthetic", RUNNING)
    error = memory.stage("profile:synthetic")["last_error"]
    assert error == {"message": "Sign-in expired; token=[redacted]", "at": "2026-10-22T09:00:00"}
    assert "old-secret" not in memory.path.read_text()


def test_partial_retry_preserves_whole_workflow_options_and_safe_stage_choices(tmp_path):
    memory = Memory(tmp_path, DAY)
    plan = ["research:alpha", "research:beta"]
    original = {"cli": "claude", "agents": 3, "bots": 1, "containers": False}
    memory.plan(plan, {**original, "env": "private.env", "api_key": "never-save-this"})
    assert run.run_day(args(command="continue"), [run.Stage("research:alpha", lambda: 0)], memory, plan) == 0
    assert memory.today["run_options"] == original
    assert memory.stage("research:alpha")["run_options"] == {
        "cli": "kiro", "agents": 2, "bots": 1, "containers": False}
    assert "private.env" not in memory.path.read_text()
    assert "never-save-this" not in memory.path.read_text()


def test_continue_preserves_historical_plan_without_adding_new_catalogue_stages(tmp_path):
    memory = Memory(tmp_path, DAY)
    original = {"cli": "claude", "agents": 3, "bots": 1, "containers": False}
    memory.plan(["learn", "profile:naukri"], original)
    memory.mark("learn", DONE)
    memory.mark("profile:naukri", FAILED, "Session expired")
    assert run.run_day(args(command="continue"), [run.Stage("profile:naukri", lambda: 0)], memory,
                       ["learn", "profile:naukri", "research:resume", "brief:goal"]) == 0
    assert memory.planned() == ["learn", "profile:naukri"]
    assert memory.today["run_options"] == original
    assert memory.day_status() == "done"
    assert "brief:goal" not in memory.today["stages"]


def test_first_partial_workflow_records_only_selected_steps_for_future_resume(tmp_path):
    memory = Memory(tmp_path, DAY)
    catalogue = ["learn", "profile:naukri", "apply:naukri", "research:resume", "brief:goal"]
    assert run.run_day(args(command="run"), [run.Stage("learn", lambda: 3)], memory, catalogue) == 3
    reloaded = Memory(tmp_path, DAY)
    assert reloaded.planned() == ["learn"]
    assert reloaded.left() == ["learn"]
    assert set(reloaded.today["stages"]) == {"learn"}
    assert run.run_day(args(command="continue"), [run.Stage("learn", lambda: 0)], reloaded, catalogue) == 0
    assert reloaded.day_status() == "done"
    assert set(reloaded.today["stages"]) == {"learn"}


def test_dry_run_does_not_replace_checkpoint_or_failure_history(tmp_path):
    memory = Memory(tmp_path, DAY)
    memory.plan(["research:synthetic"])
    memory.mark("research:synthetic", FAILED, "Existing failure", exit_code=3)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    calls = []
    assert run.run_day(args(dry_run=True, fresh=True, redo=True),
                       [run.Stage("research:synthetic", lambda: calls.append(1) or 0)], memory) == 0
    assert calls == [1]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before


def test_separate_memory_writers_keep_each_others_stage_failures(tmp_path):
    first, second = Memory(tmp_path, DAY), Memory(tmp_path, DAY)
    first.plan(["research:alpha", "research:beta"])
    gate = threading.Barrier(2, timeout=5)

    def record(memory, name):
        gate.wait()
        memory.mark(name, RUNNING)
        memory.mark(name, FAILED, name + " failed", exit_code=3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(record, first, "research:alpha"), pool.submit(record, second, "research:beta")]
        for future in futures:
            future.result()
    data = json.loads(first.path.read_text())["days"][DAY.isoformat()]
    assert set(data["stages"]) == {"research:alpha", "research:beta"}
    for name, stage in data["stages"].items():
        assert stage["last_error"]["message"] == name + " failed"


def test_unlogged_failure_and_string_system_exit_provide_actionable_reason():
    code, detail = run._run("synthetic", lambda: 2)
    assert code == 2 and "Sign in" in detail

    def exit_message():
        raise SystemExit("Missing browser executable. Install Chromium and retry.")

    code, detail = run._run("synthetic", exit_message)
    assert code == 3 and "Install Chromium" in detail
