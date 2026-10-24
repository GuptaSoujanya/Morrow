"""Remote input uses only synthetic DevTools and private temporary leases."""
import fcntl
import json
import os
import threading
import time
import uuid

import pytest

from test_browser_preview import devtools, register
from web import browser_preview as preview


def ready(tmp_path, monkeypatch, devtools):
    server = devtools()
    driver, manifest, _ = register(tmp_path, monkeypatch, server)
    lease = tmp_path / (manifest["id"] + ".assist")
    lease.write_text(json.dumps(dict(version=1, provider="naukri", expires_at=time.time() + 60,
                                    browser_instance=manifest["browser_instance"])))
    lease.chmod(0o600)
    frame = preview.snapshot(tmp_path)
    assert frame["state"] == "ready" and frame["control"]["enabled"]
    assert frame["viewport"] == {"width": 1920, "height": 1080}
    data = dict(id="synthetic-run", browser=frame["browser_id"], tab=frame["tab_id"],
                frame_id=frame["frame_id"], viewport=frame["viewport"], action="click", x=1500, y=30)
    server.commands.clear()
    return server, driver, lease, data


def mutations(server):
    return [command for command in server.commands if command["method"].startswith("Input.")
            or command["method"] in ("Page.navigate", "Page.reload")]


@pytest.mark.parametrize("action,fields,methods", [
    ("click", {"x": 1500, "y": 30}, ["Input.dispatchMouseEvent", "Input.dispatchMouseEvent"]),
    ("type", {"text": "synthetic@example.test"}, ["Input.insertText"]),
    ("key", {"key": "Tab", "shift": True}, ["Input.dispatchKeyEvent", "Input.dispatchKeyEvent"]),
    ("scroll", {"x": 100, "y": 40, "deltaX": 0, "deltaY": 400}, ["Input.dispatchMouseEvent"]),
    ("reload", {}, ["Page.reload"]),
    ("sign-in", {}, ["Page.navigate"]),
])
def test_only_explicit_allowlisted_input_reaches_the_selected_session(tmp_path, monkeypatch, devtools, action, fields, methods):
    server, driver, _, data = ready(tmp_path, monkeypatch, devtools)
    data.pop("x"); data.pop("y")
    data.update(action=action, **fields)
    assert preview.control(tmp_path, data) == {"ok": True}
    sent = mutations(server)
    assert [item["method"] for item in sent] == methods
    assert all(item["sessionId"] == "synthetic-session" for item in sent)
    assert server.commands[1]["params"] == {"targetId": "tab-one", "flatten": True}
    assert server.commands[-1]["method"] == "Target.detachFromTarget"
    assert driver.quit_count == 0
    assert not any(item["method"] in ("Browser.close", "Target.closeTarget", "Page.bringToFront") for item in server.commands)
    if action == "click":
        assert sent[0]["params"]["x"] == 1500 and sent[0]["params"]["y"] == 30
        assert [item["params"]["type"] for item in sent] == ["mousePressed", "mouseReleased"]
    if action == "key":
        assert sent[0]["params"]["modifiers"] == 8
    if action == "sign-in":
        assert sent[0]["params"] == {"url": "https://www.naukri.com/nlogin/login"}


@pytest.mark.parametrize("change", [
    {"action": "Runtime.evaluate", "expression": "window.secret"},
    {"url": "https://arbitrary.example"}, {"method": "Browser.close"}, {"file": "/private/file"},
    {"x": -1}, {"x": 1920}, {"y": 1080}, {"x": True}, {"x": float("nan")},
    {"viewport": {"width": 10 ** 1000, "height": 1080}},
    {"action": "key", "key": "F12"}, {"action": "key", "key": "Tab", "shift": "true"},
    {"action": "type", "text": "x" * 4097}, {"action": "type", "text": "\x00"},
    {"action": "scroll", "deltaX": 0, "deltaY": 1201},
])
def test_malformed_or_arbitrary_commands_fail_before_any_browser_connection(change):
    data = dict(id="run", browser="browser", tab="tab", frame_id="frame", viewport={"width": 1920, "height": 1080},
                action="click", x=10, y=10)
    data.update(change)
    with pytest.raises(preview.BrowserInputError) as caught:
        preview.validate_input(data)
    assert caught.value.status == 400


@pytest.mark.parametrize("kind", ["missing", "expired", "wrong-instance", "wrong-provider", "public", "symlink"])
def test_screenshots_are_view_only_without_a_valid_private_assistance_lease(tmp_path, monkeypatch, devtools, kind):
    server = devtools()
    _, manifest, _ = register(tmp_path, monkeypatch, server)
    path = tmp_path / (manifest["id"] + ".assist")
    value = dict(version=1, provider="naukri", expires_at=time.time() + 60, browser_instance=manifest["browser_instance"])
    if kind == "expired": value["expires_at"] = time.time() - 1
    if kind == "wrong-instance": value["browser_instance"] = str(uuid.uuid4())
    if kind == "wrong-provider": value["provider"] = "arbitrary"
    if kind != "missing":
        path.write_text(json.dumps(value)); path.chmod(0o644 if kind == "public" else 0o600)
    if kind == "symlink":
        target = tmp_path / "lease-target"
        path.rename(target); path.symlink_to(target)
    result = preview.snapshot(tmp_path)
    assert result["state"] == "ready" and result["control"]["enabled"] is False and result["frame_id"] == ""
    assert mutations(server) == []


@pytest.mark.parametrize("kind", ["frame", "browser", "tab", "dimensions", "expired", "different-run"])
def test_frame_receipt_is_bound_to_run_browser_tab_dimensions_and_age(tmp_path, monkeypatch, devtools, kind):
    server, _, _, data = ready(tmp_path, monkeypatch, devtools)
    directory = tmp_path
    if kind == "frame": data["frame_id"] = "unknown"
    if kind == "browser": data["browser"] = "another-browser"
    if kind == "tab": data["tab"] = "another-tab"
    if kind == "dimensions": data["viewport"] = {"width": 2000, "height": 1080}
    if kind == "expired":
        future = time.monotonic() + preview.FRAME_TTL + 1
        monkeypatch.setattr(preview.time, "monotonic", lambda: future)
    if kind == "different-run":
        directory = tmp_path / "other-run"; directory.mkdir(mode=0o700)
    with pytest.raises(preview.BrowserInputError) as caught:
        preview.control(directory, data)
    assert caught.value.status == 409 and server.commands == []


@pytest.mark.parametrize("kind", ["navigation", "internal-page", "closed-tab", "resize", "scroll", "reused-port", "lease-removed", "new-lease"])
def test_a_changed_browser_page_or_lease_cannot_receive_stale_input(tmp_path, monkeypatch, devtools, kind):
    server, _, lease, data = ready(tmp_path, monkeypatch, devtools)
    if kind == "navigation": server.targets[0]["url"] = "https://different.example"
    if kind == "internal-page": server.targets[0]["url"] = "chrome://settings"
    if kind == "closed-tab": server.targets = []
    if kind == "resize": server.viewport["clientWidth"] = 1800
    if kind == "scroll": server.viewport["pageY"] += 200
    if kind == "reused-port": server.instance = str(uuid.uuid4())
    if kind == "lease-removed": lease.unlink()
    if kind == "new-lease":
        value = json.loads(lease.read_text()); value["expires_at"] += 1; lease.write_text(json.dumps(value))
    with pytest.raises(preview.BrowserInputError) as caught:
        preview.control(tmp_path, data)
    assert caught.value.status == 409 and mutations(server) == []


def test_access_is_rechecked_immediately_before_input_and_diagnostics_do_not_leak(tmp_path, monkeypatch, devtools):
    server, _, _, data = ready(tmp_path, monkeypatch, devtools)
    calls = []
    def authorized():
        calls.append(True)
        if len(calls) == 3:
            raise preview.BrowserInputError(401, "Sign in again.")
    with pytest.raises(preview.BrowserInputError) as caught:
        preview.control(tmp_path, data, authorized)
    assert caught.value.status == 401 and mutations(server) == []
    server.fail_method = "Input.dispatchMouseEvent"
    with pytest.raises(preview.BrowserInputError) as caught:
        preview.control(tmp_path, data)
    assert "private" not in str(caught.value) and "127.0.0.1" not in str(caught.value)


def test_auth_cannot_resume_until_inflight_input_releases_the_lease(tmp_path, monkeypatch, devtools):
    server, _, lease, data = ready(tmp_path, monkeypatch, devtools)
    data.pop("x"); data.pop("y"); data.update(action="type", text="synthetic")
    entered, finish_input, resumed = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def hold(request):
        if request["method"] == "Input.insertText":
            entered.set(); assert finish_input.wait(1)
    server.on_command = hold
    def operate():
        try: preview.control(tmp_path, data)
        except Exception as error: errors.append(error)
    def teardown():
        with lease.open() as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            lease.unlink(); resumed.set()
    worker = threading.Thread(target=operate); worker.start()
    assert entered.wait(1)
    waiter = threading.Thread(target=teardown); waiter.start()
    assert not resumed.wait(.1)
    finish_input.set(); worker.join(2); waiter.join(2)
    assert resumed.is_set() and not errors and not worker.is_alive() and not waiter.is_alive()


def test_navigation_between_attach_and_dispatch_is_rechecked(tmp_path, monkeypatch, devtools):
    server, _, _, data = ready(tmp_path, monkeypatch, devtools)
    def navigate(request):
        if request["method"] == "Page.getLayoutMetrics":
            server.targets[0]["url"] = "https://changed.example"
    server.on_command = navigate
    with pytest.raises(preview.BrowserInputError): preview.control(tmp_path, data)
    assert mutations(server) == []
