"""Saved-answer events and file review use private, genuine run state only."""
import http.client
import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_browser_preview_api import site, get
from web import answer_notifications, runner as runtime, server, state
from web.state import Command


def event(expected_token, identity="1" * 32, **overrides):
    return {"version": 1, "id": identity, "kind": "answer_saved", "question": "Notice period?",
            "answer": "30 days", "source": "profile", "token": expected_token, **overrides}


def feed(instance, run, lines):
    run.proc = SimpleNamespace(stdout=io.BytesIO(("\n".join(lines) + "\n").encode()))
    instance._read(run)


def test_saved_answer_wakes_snapshot_without_exposing_protocol_or_token_in_logs():
    instance = runtime.Runner()
    run = runtime.Run(Command("Hirist apply", ("synthetic",)), "boards", "", frozenset())
    value = event(run.answer_event_token)
    line = answer_notifications.PREFIX + json.dumps(value)
    feed(instance, run, ["Applying to a role", line, line])
    snapshot = instance.snapshot(after=0)
    assert snapshot["revision"] == 2 and snapshot["next"] == 1
    assert len(snapshot["notifications"]) == 1
    saved = snapshot["notifications"][0]
    assert saved["run_id"] == run.id and saved["label"] == "Hirist apply" and saved["answer"] == "30 days"
    assert "token" not in saved and run.answer_event_token not in json.dumps(snapshot)
    assert [line[1] for line in snapshot["lines"]] == ["Applying to a role"]
    assert instance.snapshot(after=1)["notifications"] == snapshot["notifications"]


@pytest.mark.parametrize("overrides", [{"token": "wrong"}, {"token": "\ud800"}, {"version": True},
                                      {"extra": "x"}, {"question": ""}, {"answer": "x" * 8001},
                                      {"id": "invalid"}, {"kind": "ordinary_log"}])
def test_forged_or_invalid_events_cannot_create_answer_notifications(overrides):
    instance = runtime.Runner()
    run = runtime.Run(Command("Agent", ("synthetic",)), "test", "", frozenset())
    feed(instance, run, [answer_notifications.PREFIX + json.dumps(event(run.answer_event_token, **overrides))])
    assert instance.snapshot()["notifications"] == []


def test_ordinary_logs_are_not_interpreted_as_saved_answers_and_retention_is_bounded():
    instance = runtime.Runner()
    instance.MAX_NOTIFICATIONS = 2
    run = runtime.Run(Command("Agent", ("synthetic",)), "test", "", frozenset())
    lines = ["INFO " + answer_notifications.PREFIX + json.dumps(event(run.answer_event_token))]
    lines += [answer_notifications.PREFIX + json.dumps(event(run.answer_event_token, identity=str(index) * 32)) for index in (2, 3, 4)]
    feed(instance, run, lines)
    assert [item["id"] for item in instance.snapshot()["notifications"]] == ["3" * 32, "4" * 32]
    assert instance.count == 1


def test_an_oversized_reserved_record_is_discarded_in_full_without_leaking_its_token():
    instance = runtime.Runner()
    run = runtime.Run(Command("Agent", ("synthetic",)), "test", "", frozenset())
    oversized = answer_notifications.PREFIX + json.dumps(event(run.answer_event_token, answer="x" * 100000))
    feed(instance, run, [oversized, "Normal progress remains visible"])
    snapshot = instance.snapshot(after=0)
    assert snapshot["notifications"] == []
    assert [line[1] for line in snapshot["lines"]] == ["Normal progress remains visible"]
    assert run.answer_event_token not in json.dumps(snapshot)


def test_real_child_emitter_reaches_runner_notifications_without_using_any_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "APPLY", tmp_path)
    instance = runtime.Runner()
    command = Command("Synthetic answer save", (sys.executable, "-c",
        "from common.answer_events import answer_saved; answer_saved('Notice period?', '30 days', 'profile')"),
        (("PYTHONPATH", str(Path(__file__).resolve().parents[2])),))
    try:
        run_id = instance.start(command, "synthetic-answer-test")
        deadline = time.monotonic() + 5
        while instance.running and time.monotonic() < deadline:
            time.sleep(.01)
        snapshot = instance.snapshot(after=0)
        assert not snapshot["running"]
        assert len(snapshot["notifications"]) == 1
        assert snapshot["notifications"][0]["run_id"] == run_id
        assert snapshot["notifications"][0]["answer"] == "30 days"
        assert not any(answer_notifications.PREFIX in line[1] for line in snapshot["lines"])
    finally:
        instance.shutdown()


def post(site, body, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=5)
    connection.request("POST", "/api/run/answers", json.dumps(body), {"Content-Type": "application/json", **(headers or {})})
    reply = connection.getresponse()
    result = reply.status, dict(reply.getheaders()), json.loads(reply.read())
    connection.close()
    return result


def test_review_reads_configured_sheet_and_rejects_stale_edits_without_losing_new_answers(site, tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    (tmp_path / ".env").write_text("DATA_DIR=agent-inputs\n")
    path = tmp_path / "agent-inputs" / "answers.txt"
    path.parent.mkdir()
    path.write_text("Q: Notice period?\nA: 30 days\n")
    code, headers, sheet = get(site, "/api/run/answers")
    assert code == 200 and headers["Cache-Control"] == "no-store" and sheet["text"] == path.read_text()
    assert sheet["scope"] == "automation"
    path.write_text(path.read_text() + "\nQ: Location?\nA: Indore\n")
    assert post(site, {"text": "old draft", "revision": sheet["revision"]})[0] == 409
    assert "Indore" in path.read_text()
    fresh = get(site, "/api/run/answers")[2]
    assert post(site, {"text": fresh["text"] + "\n# Reviewed\n", "revision": fresh["revision"]})[0] == 200
    assert "Indore" in path.read_text() and "Reviewed" in path.read_text()
    assert len(list((path.parent / "backups").glob("*.bak"))) == 1


def test_sheet_uses_server_runtime_path_and_never_accepts_caller_paths(site, tmp_path):
    folder = tmp_path / "private-runtime"
    folder.mkdir()
    (folder / "answers.txt").write_text("Runtime answers")
    site.runner.environment_provider = lambda command, action: {"DATA_DIR": str(folder)}
    assert get(site, "/api/run/answers?path=/other/account/answers.txt")[2]["text"] == "Runtime answers"
    assert post(site, {"path": "/other/account/answers.txt", "text": "x", "revision": "x"})[0] == 400


@pytest.mark.parametrize("headers", [{"Origin": "https://other.test"}, {"Host": "other.test"}, {"Sec-Fetch-Site": "cross-site"}])
def test_foreign_pages_cannot_read_or_write_answers(site, headers):
    assert get(site, "/api/run/answers", headers)[0] == 403
    assert post(site, {"text": "x", "revision": "x"}, headers)[0] == 403


def test_sheet_rechecks_owner_access_and_requires_csrf_for_account_writes(site, monkeypatch):
    site.account_bridge = object()
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda self: True)
    sheet = get(site, "/api/run/answers")[2]
    payload = {"text": "saved", "revision": sheet["revision"]}
    assert post(site, payload)[0] == 403
    assert post(site, payload, {"Cookie": "morrow_csrf=expected", "X-CSRF-Token": "wrong"})[0] == 403
    assert post(site, payload, {"Cookie": "morrow_csrf=expected", "X-CSRF-Token": "expected"})[0] == 200
    access = iter([True, False])
    monkeypatch.setattr(server.Handler, "stream_authorized", lambda self: next(access))
    code, _, body = get(site, "/api/run/answers")
    assert code == 401 and "saved" not in json.dumps(body)
