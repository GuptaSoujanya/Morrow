"""Metadata discovery uses fake registries/DevTools; no agents or real browsers."""
import json
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from test_browser_preview import devtools, register
from test_browser_preview_api import get, site
from web import browser_preview as preview, server
from web.runner import Run, Runner
from web.state import Command


def test_inventory_lists_every_browser_and_tab_without_capturing_or_controlling(tmp_path, monkeypatch, devtools):
    first, second = devtools(), devtools()
    first.targets += [dict(type="page", targetId="tab-two", title="https://jobs.example/?token=secret", url="https://jobs.example/?token=secret"),
                      dict(type="service_worker", targetId="worker", title="Hidden worker", url="https://jobs.example/worker"),
                      dict(type="page", targetId="internal", title="Settings", url="chrome://settings")]
    _, chrome, _ = register(tmp_path, monkeypatch, first)
    _, edge, _ = register(tmp_path, monkeypatch, second, "msedge")
    result = preview.inventory(tmp_path)
    browsers = {browser["id"]: browser for browser in result["browsers"]}
    assert result["state"] == "ready" and set(browsers) == {chrome["id"], edge["id"]}
    assert browsers[chrome["id"]]["tabs"] == [
        dict(id="tab-one", title="Example application", site="jobs.example"),
        dict(id="tab-two", title="jobs.example", site="jobs.example")]
    assert browsers[edge["id"]]["label"] == "Edge"
    assert all(browser["state"] == "ready" for browser in browsers.values())
    encoded = json.dumps(result)
    assert not any(private in encoded for private in ("token", "secret", "image", "endpoint", "127.0.0.1", "webSocket"))
    assert [command["method"] for command in first.commands + second.commands] == ["Target.getTargets", "Target.getTargets"]


def test_reused_browser_identity_does_not_hide_other_browser(tmp_path, monkeypatch, devtools):
    stale, healthy = devtools(), devtools()
    _, old, _ = register(tmp_path, monkeypatch, stale)
    _, current, _ = register(tmp_path, monkeypatch, healthy)
    stale.instance = str(uuid.uuid4())
    result = preview.inventory(tmp_path)
    browsers = {browser["id"]: browser for browser in result["browsers"]}
    assert result["state"] == "ready"
    assert browsers[old["id"]]["state"] == "unavailable" and browsers[old["id"]]["tabs"] == []
    assert browsers[current["id"]]["state"] == "ready"
    assert stale.commands == []


def test_browser_identity_change_during_lookup_never_lists_replacement_tabs(tmp_path, monkeypatch, devtools):
    browser = devtools()
    register(tmp_path, monkeypatch, browser)
    browser.swap_after_version = True
    result = preview.inventory(tmp_path)
    assert result["state"] == "unavailable"
    assert result["browsers"][0]["tabs"] == [] and browser.commands == []


def test_waiting_and_unavailable_inventories_are_distinct(tmp_path, monkeypatch, devtools):
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    browser_dir = tmp_path / "browser"
    browser_dir.mkdir(mode=0o700)
    browser = devtools()
    browser.targets = []
    register(browser_dir, monkeypatch, browser)
    result = preview.inventory_many({"empty": empty, "new": browser_dir, "gone": tmp_path / "gone"})
    assert result["empty"]["state"] == "waiting" and result["empty"]["browsers"] == []
    assert result["new"]["state"] == "waiting"
    assert result["new"]["browsers"][0]["state"] == "waiting"
    assert result["gone"]["state"] == "unavailable"


def test_inventory_shares_deadline_and_four_workers_across_runs(monkeypatch):
    entries = [{"id": str(index), "label": "Chrome"} for index in range(8)]
    monkeypatch.setattr(preview, "_manifests", lambda directory: entries)
    lock, release, saturated = threading.Lock(), threading.Event(), threading.Event()
    active, maximum, deadlines = 0, 0, []

    def read(entry, deadline):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            deadlines.append(deadline)
            if active == 4:
                saturated.set()
        assert release.wait(2)
        with lock:
            active -= 1
        return dict(id=entry["id"], label="Chrome", state="ready", tabs=[], message="")

    monkeypatch.setattr(preview, "_browser_inventory", read)
    result = {}
    worker = threading.Thread(target=lambda: result.update(preview.inventory_many({"one": "one", "two": "two"})))
    worker.start()
    try:
        assert saturated.wait(1)
        assert maximum == 4
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(deadlines) == 16 and len(set(deadlines)) == 1
    assert maximum == 4 and all(len(run["browsers"]) == 8 for run in result.values())


def test_slow_run_cannot_starve_another_run_or_extend_response_budget(monkeypatch):
    stale = [{"id": f"stale-{index}", "label": "Chrome"} for index in range(12)]
    healthy = [{"id": "healthy", "label": "Chrome"}]
    monkeypatch.setattr(preview, "_manifests", lambda directory: stale if directory == "stale" else healthy)
    monkeypatch.setattr(preview, "TOTAL_TIMEOUT", .2)
    release, finished = threading.Event(), threading.Event()
    calls = []

    def read(entry, deadline):
        calls.append(entry["id"])
        if entry["id"].startswith("stale"):
            assert release.wait(2)
            finished.set()
        return dict(id=entry["id"], label="Chrome", state="ready", tabs=[], message="")

    monkeypatch.setattr(preview, "_browser_inventory", read)
    started = time.monotonic()
    try:
        result = preview.inventory_many({"one": "stale", "two": "healthy"})
        assert time.monotonic() - started < 1
        assert result["two"]["state"] == "ready"
        assert "healthy" in calls[:4]
        assert result["one"]["state"] == "waiting" and len(result["one"]["browsers"]) == 12
        saved = json.dumps(result)
    finally:
        release.set()
    assert finished.wait(1)
    assert json.dumps(result) == saved, "Late worker results must not mutate a returned response"


def test_inventory_api_is_private_uncached_and_accepts_no_registry_path(site, monkeypatch):
    calls = []
    payload = {"runs": [{"id": "current", "browsers": []}]}
    monkeypatch.setattr(site.runner, "browser_inventory", lambda: calls.append(True) or payload)
    status, headers, body = get(site, "/api/run/browsers?directory=/private/arbitrary&browser=unknown")
    assert status == 200 and body == payload and calls == [True]
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("headers", [{"Origin": "https://elsewhere.test"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "elsewhere.test"}])
def test_foreign_pages_cannot_read_browser_inventory(site, monkeypatch, headers):
    calls = []
    monkeypatch.setattr(site.runner, "browser_inventory", lambda: calls.append(True) or {"runs": []})
    status, headers, _ = get(site, "/api/run/browsers", headers)
    assert status == 403 and calls == []
    assert headers["Cache-Control"] == "no-store"


def test_inventory_checks_access_before_and_after_reading_tab_metadata(site, monkeypatch):
    calls = []
    monkeypatch.setattr(site.runner, "browser_inventory", lambda: calls.append(True) or {"runs": [{"title": "Private tab"}]})
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda handler: False)
    assert get(site, "/api/run/browsers")[0] == 401 and calls == []
    access = iter([True, False])
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda handler: next(access))
    status, headers, body = get(site, "/api/run/browsers")
    assert status == 401 and calls == [True] and "Private tab" not in json.dumps(body)
    assert headers["Cache-Control"] == "no-store"


def add_run(runner, run_id, *, containers=False, finished=False, directory=True):
    run = Run(Command(run_id.title(), ("synthetic", "--containers") if containers else ("synthetic",)),
              "synthetic", "", frozenset(), id=run_id)
    if directory:
        run.preview_store = SimpleNamespace(name="private-" + run_id)
    if finished:
        run.result = {"status": "finished"}
    runner.runs[run_id] = run
    return run


def test_runner_inventories_only_active_local_runs_and_guides_container_viewing(monkeypatch):
    runner, calls = Runner(), []
    add_run(runner, "active")
    add_run(runner, "completed", finished=True)
    add_run(runner, "container", containers=True)
    add_run(runner, "waiting", directory=False)
    def read(directories):
        calls.append(directories)
        return {"active": dict(state="ready", message="", browsers=[dict(id="browser", label="Chrome", state="ready", tabs=[])])}
    monkeypatch.setattr(preview, "inventory_many", read)
    runs = {run["id"]: run for run in runner.browser_inventory()["runs"]}
    assert set(runs) == {"active", "container", "waiting"}
    assert calls == [{"active": "private-active"}]
    assert runs["active"]["browser_state"] == "ready" and runs["active"]["running"] is True
    assert runs["container"]["browser_state"] == "unavailable" and "Flows" in runs["container"]["message"]
    assert runs["waiting"]["browser_state"] == "waiting"
    assert set(runs["active"]) == {"id", "label", "action", "running", "stopping", "status", "seconds", "browser_state", "message", "browsers"}


def test_inventory_does_not_block_run_logs_or_overlap_reads(monkeypatch):
    runner = Runner()
    add_run(runner, "active")
    entered, release = threading.Event(), threading.Event()
    calls = []
    def read(directories):
        calls.append(directories)
        entered.set()
        assert release.wait(3)
        return {"active": dict(state="ready", message="", browsers=[])}
    monkeypatch.setattr(preview, "inventory_many", read)
    result = {}
    worker = threading.Thread(target=lambda: result.update(runner.browser_inventory()))
    worker.start()
    try:
        assert entered.wait(1)
        busy = runner.browser_inventory()["runs"][0]
        assert busy["browser_state"] == "waiting" and "refreshing" in busy["message"]
        assert len(calls) == 1
        runner.say("Still working", "active")
        assert runner.snapshot(after=0)["lines"][-1][1] == "Still working"
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and result["runs"][0]["browser_state"] == "ready"


def test_inventory_drops_runs_that_finish_during_lookup(monkeypatch):
    runner = Runner()
    run = add_run(runner, "active")
    def read(directories):
        with runner.lock:
            run.result = {"status": "finished"}
        return {"active": dict(state="ready", message="", browsers=[{"title": "Stale private tab"}])}
    monkeypatch.setattr(preview, "inventory_many", read)
    assert runner.browser_inventory() == {"runs": []}


def test_failed_inventory_never_leaks_diagnostics_or_stops_run(monkeypatch):
    runner = Runner()
    run = add_run(runner, "active")
    def fail(directories):
        raise RuntimeError("private-debugger-url-and-token")
    monkeypatch.setattr(preview, "inventory_many", fail)
    result = runner.browser_inventory()
    assert result["runs"][0]["browser_state"] == "unavailable"
    assert "private-debugger" not in json.dumps(result) and run.result is None
