"""Counts are run-scoped metadata; no actual browser or agent is launched."""
import json
import threading
from types import SimpleNamespace

from web import browser_preview
from web.runner import Run, Runner
from web.state import Command


def add_run(runner, identifier, *, code=None, finished=False, containers=False, registry=True):
    run = Run(Command(identifier.title(), ("synthetic", "--containers") if containers else ("synthetic",)),
              "synthetic", "", frozenset(), id=identifier)
    run.proc = SimpleNamespace(poll=lambda: code)
    if registry:
        run.preview_store = SimpleNamespace(name="private-" + identifier)
    if finished:
        run.result = {"status": "completed"}
    runner.runs[identifier] = run
    return run


def test_counts_read_only_current_runs_and_return_no_browser_or_tab_details(monkeypatch):
    runner, calls = Runner(), []
    add_run(runner, "first")
    add_run(runner, "second")
    add_run(runner, "completed", finished=True)
    add_run(runner, "exited-before-drain", code=7)
    add_run(runner, "container", containers=True)
    add_run(runner, "opening", registry=False)

    def read(directories):
        calls.append(directories)
        return {"first": dict(open_browser_count=2, count_status="ready", tabs=["private-tab"]),
                "second": dict(open_browser_count=1, count_status="unavailable", endpoint="private-address")}

    monkeypatch.setattr(browser_preview, "count_many", read)
    result = runner.browser_counts()
    assert calls == [{"first": "private-first", "second": "private-second"}]
    assert result == {"runs": [
        dict(id="first", running=True, open_browser_count=2, count_status="ready"),
        dict(id="second", running=True, open_browser_count=1, count_status="unavailable"),
        dict(id="container", running=True, open_browser_count=0, count_status="unavailable"),
        dict(id="opening", running=True, open_browser_count=0, count_status="checking"),
    ]}
    assert "private" not in json.dumps(result)


def test_counting_never_blocks_logs_or_overlaps_inventory_requests(monkeypatch):
    runner, entered, release, result = Runner(), threading.Event(), threading.Event(), {}
    add_run(runner, "active")
    calls = []

    def read(directories):
        calls.append(directories)
        entered.set()
        assert release.wait(2)
        return {"active": dict(open_browser_count=2, count_status="ready")}

    monkeypatch.setattr(browser_preview, "count_many", read)
    worker = threading.Thread(target=lambda: result.update(runner.browser_counts()))
    worker.start()
    try:
        assert entered.wait(1)
        busy = runner.browser_counts()["runs"][0]
        assert busy["count_status"] == "checking" and busy["open_browser_count"] == 0
        runner.say("Still applying", "active")
        assert runner.snapshot(after=0)["lines"][-1][1] == "Still applying"
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and result["runs"][0]["open_browser_count"] == 2


def test_run_exit_during_count_drops_the_result(monkeypatch):
    runner = Runner()
    run = add_run(runner, "active")

    def read(directories):
        run.proc = SimpleNamespace(poll=lambda: 3)
        return {"active": dict(open_browser_count=1, count_status="ready")}

    monkeypatch.setattr(browser_preview, "count_many", read)
    assert runner.browser_counts() == {"runs": []}


def test_closed_workspace_cannot_read_or_return_any_browser_counts(monkeypatch):
    runner = Runner()
    add_run(runner, "active")
    runner.closed = True
    monkeypatch.setattr(browser_preview, "count_many", lambda directories: (_ for _ in ()).throw(AssertionError("Unexpected read")))
    assert runner.browser_counts() == {"runs": []}


def test_count_failure_is_unknown_and_does_not_leak_or_stop_an_agent(monkeypatch):
    runner = Runner()
    run = add_run(runner, "active")

    def fail(directories):
        raise RuntimeError("private-debugger-url")

    monkeypatch.setattr(browser_preview, "count_many", fail)
    result = runner.browser_counts()
    assert result == {"runs": [dict(id="active", running=True, open_browser_count=0, count_status="unavailable")]}
    assert run.result is None and "private" not in json.dumps(result)
