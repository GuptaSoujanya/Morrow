"""Count registered live Chrome instances without viewing or controlling pages."""
import json
import threading
import time
import uuid

import pytest

from test_browser_preview import devtools, register
from test_browser_preview_api import get, site
from web import browser_preview as preview, server


def test_counts_distinct_browser_instances_without_reading_tabs(tmp_path, monkeypatch, devtools):
    first, second = devtools(), devtools()
    first.targets += [dict(type="page", targetId="second-tab", title="Private title", url="https://example.test/?token=private")]
    register(tmp_path, monkeypatch, first)
    register(tmp_path, monkeypatch, first)  # Duplicate registration is one browser.
    register(tmp_path, monkeypatch, second, "msedge")
    assert preview.count_many({"run": tmp_path}) == {
        "run": {"open_browser_count": 2, "count_status": "ready"}}
    assert first.commands == second.commands == [], "Counts must not attach, inspect targets, or capture images"


def test_reused_port_does_not_count_a_replacement_browser(tmp_path, monkeypatch, devtools):
    stale, current = devtools(), devtools()
    register(tmp_path, monkeypatch, stale)
    register(tmp_path, monkeypatch, current)
    stale.instance = str(uuid.uuid4())
    assert preview.count_many({"run": tmp_path})["run"] == {
        "open_browser_count": 1, "count_status": "ready"}
    assert stale.commands == current.commands == []


def test_empty_and_missing_registries_have_different_count_status(tmp_path):
    tmp_path.chmod(0o700)
    assert preview.count_many({"empty": tmp_path, "missing": tmp_path / "missing"}) == {
        "empty": {"open_browser_count": 0, "count_status": "ready"},
        "missing": {"open_browser_count": 0, "count_status": "unavailable"},
    }


def test_unverified_registration_is_unknown_without_reading_endpoint(monkeypatch):
    monkeypatch.setattr(preview, "_manifests", lambda directory: [{"id": "unknown", "browser_instance": ""}])
    monkeypatch.setattr(preview, "request_json", lambda *args: pytest.fail("Unverified registrations cannot be queried"))
    assert preview.count_many({"run": "private"})["run"] == {
        "open_browser_count": 0, "count_status": "unavailable"}


@pytest.mark.parametrize("error,status", [(ConnectionRefusedError(), "ready"), (TimeoutError(), "unavailable"), (ValueError("Private URL"), "unavailable")])
def test_closed_and_unreachable_instances_are_not_claimed_open(monkeypatch, error, status):
    entry = {"browser_instance": str(uuid.uuid4()), "endpoint": "http://127.0.0.1:9234"}
    monkeypatch.setattr(preview, "_manifests", lambda directory: [entry])
    def fail(*args):
        raise error
    monkeypatch.setattr(preview, "request_json", fail)
    result = preview.count_many({"run": "private"})
    assert result == {"run": {"open_browser_count": 0, "count_status": status}}
    assert "Private URL" not in json.dumps(result)


def test_count_deadline_is_shared_and_each_run_gets_a_turn(monkeypatch):
    entries = [{"browser_instance": str(uuid.uuid4()), "label": f"stale-{index}"} for index in range(12)]
    healthy = [{"browser_instance": str(uuid.uuid4()), "label": "healthy"}]
    monkeypatch.setattr(preview, "_manifests", lambda directory: entries if directory == "slow" else healthy)
    monkeypatch.setattr(preview, "TOTAL_TIMEOUT", .2)
    release, finished = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls, deadlines = [], []
    active, maximum = 0, 0
    def read(entry, deadline):
        nonlocal active, maximum
        with lock:
            calls.append(entry["label"])
            deadlines.append(deadline)
            active += 1
            maximum = max(maximum, active)
        if entry["label"] != "healthy":
            assert release.wait(2)
            finished.set()
        with lock:
            active -= 1
        return "open"
    monkeypatch.setattr(preview, "_browser_open", read)
    started = time.monotonic()
    try:
        result = preview.count_many({"one": "slow", "two": "healthy"})
        assert time.monotonic() - started < 1
        assert result["one"] == {"open_browser_count": 0, "count_status": "checking"}
        assert result["two"] == {"open_browser_count": 1, "count_status": "ready"}
        assert "healthy" in calls[:4] and maximum == 4 and len(set(deadlines)) == 1
        saved = json.dumps(result)
    finally:
        release.set()
    assert finished.wait(1)
    assert json.dumps(result) == saved, "Late reads cannot change an already returned count"


def test_counts_api_is_private_uncached_and_cannot_accept_registry_paths(site, monkeypatch):
    calls = []
    payload = {"runs": [{"id": "active", "running": True, "open_browser_count": 2, "count_status": "ready"}]}
    monkeypatch.setattr(site.runner, "browser_counts", lambda: calls.append(True) or payload)
    monkeypatch.setattr(site.runner, "browser_inventory", lambda: pytest.fail("Count requests must not read page metadata"))
    status, headers, body = get(site, "/api/run/browsers?counts=1&directory=/private/arbitrary")
    assert status == 200 and body == payload and calls == [True]
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("headers", [{"Origin": "https://elsewhere.test"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "elsewhere.test"}])
def test_foreign_pages_cannot_read_browser_counts(site, monkeypatch, headers):
    calls = []
    monkeypatch.setattr(site.runner, "browser_counts", lambda: calls.append(True) or {"runs": []})
    assert get(site, "/api/run/browsers?counts=1", headers)[0] == 403
    assert calls == []


def test_counts_api_rechecks_access_after_read(site, monkeypatch):
    calls = []
    monkeypatch.setattr(site.runner, "browser_counts", lambda: calls.append(True) or {"runs": [{"id": "private-run"}]})
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda handler: False)
    assert get(site, "/api/run/browsers?counts=1")[0] == 401 and calls == []
    access = iter([True, False])
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda handler: next(access))
    status, _, body = get(site, "/api/run/browsers?counts=1")
    assert status == 401 and calls == [True] and "private-run" not in json.dumps(body)
