"""A synthetic DevTools endpoint; no Chrome, agent, real page, or account."""
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import struct
import sys
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import browser_preview as registration
from web import browser_preview as preview

JPEG = base64.b64encode(b"\xff\xd8synthetic\xff\xd9").decode()


class DevToolsHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def json(self, value):
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(raw)
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _frame(self, value):
        data = json.dumps(value).encode()
        header = bytes([0x81, len(data)]) if len(data) < 126 else bytes([0x81, 126]) + struct.pack("!H", len(data))
        self.wfile.write(header + data)
        self.wfile.flush()

    def do_GET(self):
        authority = f"127.0.0.1:{self.server.server_port}"
        if self.path == "/json/version":
            self.server.version_reads += 1
            value = {"webSocketDebuggerUrl": f"ws://{authority}/devtools/browser/{self.server.instance}"}
            if self.server.metadata_too_large:
                value["excess"] = "x" * 70000
            if self.server.swap_after_version:
                self.server.instance = str(uuid.uuid4())
            return self.json(value)
        if self.path != "/devtools/browser/" + self.server.instance:
            self.send_error(404)
            return
        key = self.headers["Sec-WebSocket-Key"]
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        try:
            while True:
                header = self.rfile.read(2)
                if len(header) != 2 or header[0] & 15 == 8:
                    return
                length = header[1] & 127
                if length == 126:
                    length = struct.unpack("!H", self.rfile.read(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self.rfile.read(8))[0]
                mask = self.rfile.read(4) if header[1] & 128 else b""
                raw = self.rfile.read(length)
                if mask:
                    raw = bytes(value ^ mask[index % 4] for index, value in enumerate(raw))
                request = json.loads(raw)
                self.server.commands.append(request)
                if self.server.oversized_frame:
                    self.wfile.write(bytes([0x81, 127]) + struct.pack("!Q", preview.MAX_MESSAGE + 1))
                    self.wfile.flush()
                    return
                method = request["method"]
                if method == self.server.fail_method:
                    self._frame({"id": request["id"], "error": {"message": "Sensitive backend detail http://127.0.0.1:9222/?token=secret"}})
                    continue
                result = {
                    "Target.getTargets": {"targetInfos": self.server.targets},
                    "Target.attachToTarget": {"sessionId": "synthetic-session"},
                    "Page.getLayoutMetrics": {"cssVisualViewport": self.server.viewport},
                    "Page.captureScreenshot": {"data": self.server.image},
                    "Target.detachFromTarget": {},
                }.get(method)
                assert result is not None, "A preview attempted an unexpected browser command"
                self._frame({"id": request["id"], "result": result})
        except (OSError, ValueError):
            return


@pytest.fixture
def devtools():
    servers = []

    def create():
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), DevToolsHandler)
        server.instance = str(uuid.uuid4())
        server.targets = [dict(type="page", targetId="tab-one", title="Example application", url="https://jobs.example/apply?token=private#secret")]
        server.viewport = dict(clientWidth=1920, clientHeight=1080, pageX=0, pageY=430)
        server.commands = []
        server.image = JPEG
        server.fail_method = ""
        server.version_reads = 0
        server.oversized_frame = False
        server.swap_after_version = False
        server.metadata_too_large = False
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server

    yield create
    for server in servers:
        server.shutdown()
        server.server_close()


class Driver:
    def __init__(self, server, browser_name="chrome"):
        self.capabilities = {"browserName": browser_name,
                             "goog:chromeOptions": {"debuggerAddress": f"127.0.0.1:{server.server_port}"}}
        self.quit_count = 0

    def quit(self):
        self.quit_count += 1
        return "closed"


def register(tmp_path, monkeypatch, server, browser_name="chrome"):
    tmp_path.chmod(0o700)
    monkeypatch.setenv(registration.ENV_NAME, str(tmp_path))
    driver = Driver(server, browser_name)
    registration.register(driver)
    entries = list(tmp_path.glob("*.json"))
    newest = max(entries, key=lambda path: path.stat().st_mtime_ns)
    return driver, json.loads(newest.read_text()), newest


def test_registry_is_private_and_successful_quit_unregisters(tmp_path, monkeypatch, devtools):
    driver, manifest, path = register(tmp_path, monkeypatch, devtools())
    assert path.stat().st_mode & 0o777 == 0o600
    assert manifest["id"] == path.stem and manifest["label"] == "Chrome"
    assert manifest["browser_instance"]
    assert driver.quit() == "closed" and driver.quit_count == 1
    assert not path.exists()


def test_failed_identity_registration_is_unavailable_and_cannot_adopt_later_browser(tmp_path, monkeypatch, devtools):
    server = devtools()
    monkeypatch.setattr(registration, "request_json", lambda *args: {})
    _, manifest, _ = register(tmp_path, monkeypatch, server)
    assert manifest["browser_instance"] == ""
    result = preview.snapshot(tmp_path)
    assert result["state"] == "unavailable"
    assert server.version_reads == 0 and server.commands == []


def test_registry_prunes_old_known_manifests_without_touching_other_files(tmp_path, monkeypatch, devtools):
    server = devtools()
    monkeypatch.setattr(registration, "MAX_MANIFESTS", 2)
    _, _, first = register(tmp_path, monkeypatch, server)
    os.utime(first, (1, 1))
    other = tmp_path / "unrelated.txt"
    other.write_text("Keep this file")
    register(tmp_path, monkeypatch, server)
    register(tmp_path, monkeypatch, server)
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert not first.exists() and other.read_text() == "Keep this file"


def test_capture_uses_only_read_commands_and_omits_sensitive_addresses(tmp_path, monkeypatch, devtools):
    server = devtools()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    register(tmp_path, monkeypatch, server)
    result = preview.snapshot(tmp_path)
    assert result["state"] == "ready"
    assert result["image"] == "data:image/jpeg;base64," + JPEG
    assert result["site"] == "jobs.example" and result["tab_id"] == "tab-one"
    assert result["captured_at"]
    text = json.dumps(result)
    assert "token" not in text and "secret" not in text and "127.0.0.1" not in text
    assert "endpoint" not in text and "webSocketDebuggerUrl" not in text
    assert [command["method"] for command in server.commands] == [
        "Target.getTargets", "Target.attachToTarget", "Page.getLayoutMetrics", "Page.captureScreenshot", "Target.detachFromTarget"]
    capture = server.commands[3]
    assert capture["sessionId"] == "synthetic-session"
    assert capture["params"]["captureBeyondViewport"] is False
    clip = capture["params"]["clip"]
    assert clip["width"] * clip["scale"] <= 1280 and clip["scale"] <= .7
    assert clip["y"] == 430
    assert [path.suffix for path in tmp_path.iterdir()] == [".json"], "Snapshots must not be recorded to disk"


def test_tab_selection_is_read_only_and_closed_selection_does_not_show_another_tab(tmp_path, monkeypatch, devtools):
    server = devtools()
    server.targets += [dict(type="page", targetId="tab-two", title="Second tab", url="https://other.example/?auth=private")]
    register(tmp_path, monkeypatch, server)
    result = preview.snapshot(tmp_path, tab_id="tab-two")
    assert result["state"] == "ready" and result["tab_id"] == "tab-two"
    assert server.commands[1]["params"]["targetId"] == "tab-two"
    server.commands.clear()
    closed = preview.snapshot(tmp_path, tab_id="already-closed")
    assert closed["state"] == "waiting" and "closed" in closed["message"]
    assert "image" not in closed
    assert [command["method"] for command in server.commands] == ["Target.getTargets"]


def test_changed_browser_identity_and_port_reuse_never_attach(tmp_path, monkeypatch, devtools):
    server = devtools()
    register(tmp_path, monkeypatch, server)
    server.instance = str(uuid.uuid4())
    result = preview.snapshot(tmp_path)
    assert result["state"] == "unavailable" and "image" not in result
    assert server.commands == []


def test_identity_change_between_metadata_and_socket_cannot_capture_other_browser(tmp_path, monkeypatch, devtools):
    server = devtools()
    register(tmp_path, monkeypatch, server)
    server.swap_after_version = True
    result = preview.snapshot(tmp_path)
    assert result["state"] == "unavailable" and server.commands == []


def test_default_browser_is_newest_and_explicit_browser_is_respected(tmp_path, monkeypatch, devtools):
    first, second = devtools(), devtools()
    _, old, old_path = register(tmp_path, monkeypatch, first)
    _, new, _ = register(tmp_path, monkeypatch, second, "msedge")
    os.utime(old_path, (1, 1))
    result = preview.snapshot(tmp_path)
    assert result["browser_id"] == new["id"] and result["browsers"][0]["label"] == "Edge"
    assert first.commands == []
    result = preview.snapshot(tmp_path, browser_id=old["id"])
    assert result["browser_id"] == old["id"] and result["state"] == "ready"


def test_default_skips_a_closed_newer_browser(tmp_path, monkeypatch, devtools):
    first, second = devtools(), devtools()
    _, old, old_path = register(tmp_path, monkeypatch, first)
    register(tmp_path, monkeypatch, second)
    os.utime(old_path, (1, 1))
    second.instance = str(uuid.uuid4())
    result = preview.snapshot(tmp_path)
    assert result["state"] == "ready" and result["browser_id"] == old["id"]


@pytest.mark.parametrize("failure", ["Page.captureScreenshot", "Target.attachToTarget", "Page.getLayoutMetrics"])
def test_closed_page_or_capture_error_is_honest_and_does_not_leak_backend_error(tmp_path, monkeypatch, devtools, failure):
    server = devtools()
    register(tmp_path, monkeypatch, server)
    server.fail_method = failure
    result = preview.snapshot(tmp_path)
    assert result["state"] == "unavailable" and "image" not in result
    assert "Sensitive" not in json.dumps(result) and "token" not in json.dumps(result)
    if failure != "Target.attachToTarget":
        assert server.commands[-1]["method"] == "Target.detachFromTarget"


@pytest.mark.parametrize("kind", ["frame", "metadata", "image"])
def test_oversized_or_invalid_payload_is_rejected(tmp_path, monkeypatch, devtools, kind):
    server = devtools()
    register(tmp_path, monkeypatch, server)
    server.oversized_frame = kind == "frame"
    server.metadata_too_large = kind == "metadata"
    if kind == "image":
        server.image = "This is not a jpeg"
    result = preview.snapshot(tmp_path)
    assert result["state"] == "unavailable" and "image" not in result


def test_registry_rejects_public_files_symlinks_and_public_directories(tmp_path, monkeypatch, devtools):
    server = devtools()
    _, manifest, path = register(tmp_path, monkeypatch, server)
    path.chmod(0o644)
    assert preview.snapshot(tmp_path)["state"] == "waiting"
    path.chmod(0o600)
    elsewhere = tmp_path / "elsewhere"
    path.rename(elsewhere)
    path.symlink_to(elsewhere)
    assert preview.snapshot(tmp_path)["state"] == "waiting"
    tmp_path.chmod(0o755)
    assert preview.snapshot(tmp_path)["state"] == "unavailable"
    assert server.commands == []


def test_unknown_browser_and_unregistered_directory_do_not_connect(tmp_path, monkeypatch, devtools):
    assert preview.snapshot(tmp_path)["state"] == "waiting"
    server = devtools()
    register(tmp_path, monkeypatch, server)
    reads = server.version_reads
    result = preview.snapshot(tmp_path, browser_id="unknown")
    assert result["state"] == "unavailable" and server.version_reads == reads


def test_metadata_includes_only_safe_pages_and_sanitizes_url_titles():
    assert preview._tab(dict(type="service_worker", targetId="worker", url="https://private.example")) is None
    assert preview._tab(dict(type="page", targetId="internal", url="chrome://settings")) is None
    assert preview._tab(dict(type="page", targetId="file", url="file:///private/doc.txt")) is None
    tab = preview._tab(dict(type="page", targetId="tab", url="https://user:password@example.test/?token=secret",
                            title="https://user:password@example.test/?token=secret#code"))
    assert tab == {"id": "tab", "title": "example.test", "site": "example.test"}


def test_total_budget_stops_scanning_stale_browsers(tmp_path, monkeypatch, devtools):
    first, second = devtools(), devtools()
    register(tmp_path, monkeypatch, first)
    register(tmp_path, monkeypatch, second)
    clock = [100.0]
    monkeypatch.setattr(preview.time, "monotonic", lambda: clock[0])
    calls = []

    def timeout(*args):
        calls.append(args)
        clock[0] += preview.TOTAL_TIMEOUT
        raise TimeoutError()

    monkeypatch.setattr(preview, "request_json", timeout)
    assert preview.snapshot(tmp_path)["state"] == "unavailable"
    assert len(calls) == 1


@pytest.mark.parametrize("address", ["example.com:9222", "192.168.1.1:9222", "http://127.0.0.1:9222/?secret=1",
    "http://user:password@127.0.0.1:9222", "https://127.0.0.1:9222", "127.0.0.1", "127.0.0.1:99999"])
def test_nonlocal_or_ambiguous_debugger_addresses_are_rejected(address):
    with pytest.raises((ValueError, TypeError)):
        registration.endpoint_parts(address)
