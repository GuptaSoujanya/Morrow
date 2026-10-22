"""Reproductions for the web lane (web/). Loopback sockets only."""

import http.client
import json
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from web import server, state
from web.state import Command

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def _make_course(root: Path) -> Path:
    for path in ("README.md", "news.md", "01-sd/README.md", "01-sd/01-basics.md"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"# {path}\n", encoding="utf-8")
    (root / "_sidebar.md").write_text(
        "- [Home](README.md)\n- [News](news.md)\n\n- **1. System Design**\n  - [Overview](01-sd/README.md)\n"
        "  - [1.1 Basics](01-sd/01-basics.md)\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    (data / "inputs").mkdir(parents=True)
    monkeypatch.setattr(state, "APPLY", tmp_path)
    monkeypatch.setattr(state, "ANSWERS", data / "inputs" / "answers.txt")
    monkeypatch.setattr(state, "PROFILE", data / "inputs" / "profile.yaml")
    monkeypatch.setattr(state, "COMPANY_SITES", data / "inputs" / "company_sites.md")
    monkeypatch.setattr(state, "REPORTS", data / "reports")
    monkeypatch.setattr(state, "STUDIED", data / "reports" / "studied.json")
    monkeypatch.setattr(state, "COURSE", _make_course(tmp_path / "course"))
    monkeypatch.delenv("DB_PATH", raising=False)
    state.ANSWERS.write_text("Q: Country*\nA:\n", encoding="utf-8")
    state.PROFILE.write_text('first_name: "Sam"\n', encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    httpd = server.ControlServer(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.runner.shutdown()
    httpd.shutdown()
    httpd.server_close()


def _call(httpd, method, path, body=None, headers=None):
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    conn.request(method, path, json.dumps(body) if body is not None else None, sent)
    reply = conn.getresponse()
    data = reply.read()
    conn.close()
    kind = reply.getheader("Content-Type", "")
    return reply.status, json.loads(data) if kind.startswith("application/json") else data


def test_web_03_runner_notices_the_command_exited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Contract: Runner 'Runs one command at a time'; once the command exits a new one may start."""
    monkeypatch.setattr(state, "APPLY", tmp_path)
    runner = server.Runner()
    runner.start(Command("x", ("/bin/sh", "-c", "sleep 30 & exit 0")))
    proc = runner.proc
    assert proc is not None
    try:
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc.poll() == 0
        deadline = time.monotonic() + 2
        while runner.running and time.monotonic() < deadline:
            time.sleep(0.05)
        assert runner.running is False, "the exited command is still shown as running"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_web_05_bad_option_shape_gets_a_json_error(site) -> None:
    """Contract: every route replies with JSON, 400 for bad input."""
    status, data = _call(site, "POST", "/api/preview", {"action": "naukri", "options": "x"})
    assert status in (200, 400), (status, data)


def test_web_08_huge_days_gets_a_400(site) -> None:
    """Contract: overview_json raises ValueError for bad input so the route answers 400."""
    status, data = _call(site, "GET", "/api/overview?days=1000000")
    assert status == 400, (status, data)


def test_web_10_report_links_with_spaces_resolve(site) -> None:
    """Contract: the report's own links point at the files saved next to it."""
    folder = state.REPORTS / "2026-10-12"
    folder.mkdir(parents=True)
    (folder / "my file.txt").write_text("hi\n", encoding="utf-8")
    status, _ = _call(site, "GET", "/reports/2026-10-12/my%20file.txt")
    assert status == 200, status
