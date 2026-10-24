"""HTTP and runner input boundaries; no browser or agent is launched."""
import http.client
import json
import tempfile

import pytest

from test_browser_preview_api import site
from web import browser_preview, server
from web.runner import Run
from web.state import Command


def body():
    return dict(id="agent", browser="browser", tab="tab", frame_id="frame", viewport={"width": 800, "height": 600},
                action="click", x=20, y=30)


def post(site, data=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=3)
    supplied = {"Content-Type": "application/json", **(headers or {})}
    connection.request("POST", "/api/run/browser/input", json.dumps(data if data is not None else body()), supplied)
    reply = connection.getresponse()
    result = reply.status, dict(reply.getheaders()), json.loads(reply.read())
    connection.close()
    return result


def test_input_uses_selected_run_and_existing_owner_check_and_is_not_cached(site, monkeypatch):
    calls = []
    def operate(run_id, data, authorized):
        assert authorized()
        calls.append((run_id, data))
        return {"ok": True}
    monkeypatch.setattr(site.runner, "browser_input", operate)
    status, headers, result = post(site)
    assert status == 200 and result == {"ok": True}
    assert calls == [("agent", body())] and headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("headers", [{"Origin": "https://other.example"}, {"Host": "other.example"},
                                      {"Sec-Fetch-Site": "cross-site"}, {"Content-Type": "text/plain"}])
def test_foreign_pages_cannot_send_browser_input(site, monkeypatch, headers):
    calls = []
    monkeypatch.setattr(site.runner, "browser_input", lambda *args, **kwargs: calls.append(args))
    assert post(site, headers=headers)[0] == 403 and calls == []


def test_account_mode_requires_matching_csrf_cookie_and_header(site, monkeypatch):
    site.account_bridge = object()
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda self: True)
    calls = []
    monkeypatch.setattr(site.runner, "browser_input", lambda *args, **kwargs: calls.append(args) or {"ok": True})
    for headers in ({}, {"X-CSRF-Token": "only-header"}, {"Cookie": "morrow_csrf=only-cookie"},
                    {"Cookie": "morrow_csrf=expected", "X-CSRF-Token": "wrong"}):
        assert post(site, headers=headers)[0] == 403
    assert calls == []
    assert post(site, headers={"Cookie": "morrow_csrf=expected", "X-CSRF-Token": "expected"})[0] == 200
    assert len(calls) == 1


def test_lost_owner_access_never_reaches_browser_and_is_checked_after_input(site, monkeypatch):
    calls = []
    monkeypatch.setattr(site.runner, "browser_input", lambda *args, **kwargs: calls.append(args) or {"ok": True})
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda self: False)
    assert post(site)[0] == 401 and calls == []
    allowed = iter([True, False])
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda self: next(allowed))
    assert post(site)[0] == 401 and len(calls) == 1


def test_invalid_payload_and_unknown_runs_cannot_select_a_registry_path(site):
    assert post(site, {**body(), "directory": "/private/other-profile"})[0] == 400
    assert post(site, {**body(), "id": "../../private"})[0] == 404


@pytest.fixture
def synthetic_run(site, tmp_path):
    run = Run(Command("Synthetic", ("never-executed",)), "naukri", "", frozenset())
    run.preview_store = tempfile.TemporaryDirectory(dir=tmp_path)
    site.runner.runs[run.id] = run
    yield run
    run.result = {"status": "completed", "running": False}


def test_runner_serializes_input_with_capture_and_does_not_stop_the_agent(site, synthetic_run, monkeypatch):
    run = synthetic_run
    data = {**body(), "id": run.id}
    calls = []
    def operate(directory, payload, ensure_allowed):
        ensure_allowed()
        assert run.preview_lock.locked()
        site.runner.say("Progress still works", run.id)
        calls.append((directory, payload))
        return {"ok": True}
    monkeypatch.setattr(browser_preview, "control", operate)
    with run.preview_lock:
        with pytest.raises(browser_preview.BrowserInputError) as caught:
            site.runner.browser_input(run.id, data)
        assert caught.value.status == 409
    assert site.runner.browser_input(run.id, data) == {"ok": True}
    assert calls == [(run.preview_store.name, data)]
    assert run.result is None and not run.stopping and not run.preview_lock.locked()


@pytest.mark.parametrize("condition", ["stopping", "finished", "closed", "access-lost"])
def test_input_cannot_reach_stopped_runs_or_a_revoked_account(site, synthetic_run, monkeypatch, condition):
    run = synthetic_run
    if condition == "stopping": run.stopping = True
    if condition == "finished": run.result = {"running": False, "status": "failed"}
    if condition == "closed": site.runner.closed = True
    calls = []
    monkeypatch.setattr(browser_preview, "control", lambda *args: calls.append(args))
    with pytest.raises(browser_preview.BrowserInputError) as caught:
        site.runner.browser_input(run.id, {**body(), "id": run.id}, authorized=lambda: condition != "access-lost")
    assert caught.value.status == (401 if condition == "access-lost" else 409) and calls == []


def test_run_stopping_during_connection_setup_is_rechecked_before_dispatch(site, synthetic_run, monkeypatch):
    def operate(directory, payload, ensure_allowed):
        synthetic_run.stopping = True
        ensure_allowed()
        pytest.fail("Stopped run reached input dispatch")
    monkeypatch.setattr(browser_preview, "control", operate)
    with pytest.raises(browser_preview.BrowserInputError) as caught:
        site.runner.browser_input(synthetic_run.id, {**body(), "id": synthetic_run.id})
    assert caught.value.status == 409 and not synthetic_run.preview_lock.locked()
