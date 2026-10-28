"""Run completion with isolated Python children, never real agents or browsers."""
import signal
import sys
import threading
import time

import pytest

from web import runner as runtime, state
from web.state import Command


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "APPLY", tmp_path)
    monkeypatch.setattr(runtime, "READ_GRACE_S", .04)
    instance = runtime.Runner()
    yield instance
    instance.shutdown()


def launch(runner, script, action="synthetic"):
    return runner.start(Command(action.title(), (sys.executable, "-c", script)), action)


def wait_for(runner, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = runner.snapshot(after=0)
        if predicate(result):
            return result
        time.sleep(.01)
    pytest.fail("The synthetic run did not reach its expected lifecycle state")


def test_quiet_crash_wakes_event_waiters_and_marks_only_that_agent_finished(runner):
    other = launch(runner, "import time; time.sleep(30)", "other")
    crashed = launch(runner, "import os,time; time.sleep(.15); os._exit(9)", "crashed")
    initial = runner.snapshot(after=0)
    assert initial["active_count"] == 2
    changed = runner.wait_snapshot(initial["revision"], initial["next"], initial["epoch"], timeout=2)
    rows = {run["id"]: run for run in changed["runs"]}
    assert changed["revision"] > initial["revision"]
    assert not rows[crashed]["running"] and rows[crashed]["status"] == "failed" and rows[crashed]["exit"] == 9
    assert rows[other]["running"] and changed["active_count"] == 1
    assert changed["last"]["id"] == crashed
    assert any("failed (exit 9)" in line[1] and line[2] == crashed for line in changed["lines"])


def test_force_stop_updates_terminal_state_without_stopping_another_agent(runner):
    other = launch(runner, "import time; time.sleep(30)", "other")
    stopped = launch(runner, "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('ready',flush=True); time.sleep(30)", "stopped")
    wait_for(runner, lambda result: any(line[1] == "ready" and line[2] == stopped for line in result["lines"]))
    assert runner.stop(stopped)[0]
    assert next(row for row in runner.snapshot()["runs"] if row["id"] == stopped)["status"] == "stopping"
    assert runner.stop(stopped)[0]
    result = wait_for(runner, lambda result: any(row["id"] == stopped and not row["running"] for row in result["runs"]))
    rows = {run["id"]: run for run in result["runs"]}
    assert rows[stopped]["status"] == "stopped" and rows[stopped]["exit"] == -signal.SIGKILL
    assert rows[other]["running"] and result["active_count"] == 1


def test_dashboard_never_inherits_remote_browser_assistance(runner, monkeypatch):
    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "true")
    runner.environment_provider = lambda command, action: {"MORROW_BROWSER_INTERACTIVE": "true"}
    run_id = runner.start(Command("Browser policy", (sys.executable, "-c",
        "import os; print('interactive=' + os.environ.get('MORROW_BROWSER_INTERACTIVE', 'missing'))"),
        env=(("MORROW_BROWSER_INTERACTIVE", "true"),)), "synthetic")
    result = wait_for(runner, lambda result: not result["running"])
    assert result["runs"][0]["status"] == "completed"
    assert any(line[1] == "interactive=false" and line[2] == run_id for line in result["lines"])


def inherited_pipe_script():
    return ("import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('last agent output',flush=True); sys.exit(7)")


def test_crash_with_inherited_stdout_does_not_remain_active(runner):
    run_id = launch(runner, inherited_pipe_script())
    result = wait_for(runner, lambda result: not result["running"])
    assert result["active_count"] == 0
    assert result["runs"][0]["status"] == "failed" and result["runs"][0]["exit"] == 7
    assert any(line[1] == "last agent output" and line[2] == run_id for line in result["lines"])


@pytest.mark.parametrize("ignore_term", [False, True], ids=["graceful-child", "force-stopped-child"])
def test_crash_closes_only_owned_children_even_when_they_detach_output(runner, tmp_path, ignore_term):
    ready, closed = tmp_path / "child-ready", tmp_path / "child-closed"
    child = (
        "import os,signal,time\nfrom pathlib import Path\n"
        f"closed = Path({str(closed)!r})\n"
        "def finish(*args):\n    closed.write_text('closed cleanly')\n    os._exit(0)\n"
        f"signal.signal(signal.SIGTERM, {'signal.SIG_IGN' if ignore_term else 'finish'})\n"
        f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    parent = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"ready = Path({str(ready)!r})\n"
        "while not ready.exists(): time.sleep(.01)\n"
        "sys.exit(7)\n"
    )
    other = launch(runner, "import time; time.sleep(30)", "independent")
    run_id = launch(runner, parent, "crashed-with-child")
    run = runner.runs[run_id]
    try:
        result = wait_for(runner, lambda result: any(row["id"] == run_id and not row["running"] for row in result["runs"]))
        rows = {row["id"]: row for row in result["runs"]}
        assert rows[run_id]["status"] == "failed" and rows[run_id]["exit"] == 7
        assert rows[other]["running"] and runner.runs[other].proc.poll() is None
        deadline = time.monotonic() + 2
        while runner._group_alive(run) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not runner._group_alive(run), "The exited agent left its own child process alive"
        assert closed.exists() is not ignore_term
    finally:
        runner._signal(run, signal.SIGKILL, include_children=True)


@pytest.mark.parametrize("failures", [1, 2], ids=["term-fails", "all-cleanup-signals-fail"])
def test_descendant_cleanup_error_cannot_leave_exited_process_marked_running(runner, monkeypatch, failures):
    original = runner._signal
    calls, thread_errors = [], []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_value))

    def signal_children(run, sig, include_children=False):
        if include_children:
            calls.append(sig)
            if len(calls) <= failures:
                raise OSError("Synthetic cleanup failure")
        return original(run, sig, include_children)

    monkeypatch.setattr(runner, "_signal", signal_children)
    run_id = launch(runner, inherited_pipe_script())
    run = runner.runs[run_id]
    try:
        result = wait_for(runner, lambda result: not result["running"])
        assert run.proc.poll() == 7
        assert result["active_count"] == 0 and result["runs"][0]["status"] == "failed"
        assert result["last"]["id"] == run_id and not thread_errors
        assert calls[:2] == [signal.SIGTERM, signal.SIGKILL]
    finally:
        # Even when cleanup signals were deliberately rejected, this test owns
        # and closes only its synthetic process group.
        monkeypatch.setattr(runner, "_signal", original)
        original(run, signal.SIGKILL, include_children=True)


def test_a_run_reads_the_settings_file_as_it_is_now_not_the_dashboards_startup_copy(runner, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("MIN_SCORE=40\nKEPT_ELSEWHERE=1\n")
    monkeypatch.setenv("MIN_SCORE", "50")
    monkeypatch.setenv("NOT_IN_FILE", "stays")
    run_id = launch(runner, "import os; print('MIN_SCORE', os.environ.get('MIN_SCORE'), 'NOT_IN_FILE', os.environ.get('NOT_IN_FILE'), flush=True)")
    seen = wait_for(runner, lambda result: any(line[1].startswith("MIN_SCORE") and line[2] == run_id for line in result["lines"]))
    assert any("MIN_SCORE None NOT_IN_FILE stays" in line[1] for line in seen["lines"])
