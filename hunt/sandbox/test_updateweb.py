"""Cross-endpoint edit isolation, using direct handlers and temporary files only."""

import importlib.util
import sys
import threading
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import server, state


@pytest.fixture
def dashboard(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    original_path = sys.path[:]
    spec = importlib.util.spec_from_file_location(
        "hound_updateweb_dashboard", root / "froned-dashbord/server.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = original_path


def _handler(dashboard, app, path, payload, replies):
    handler = object.__new__(dashboard.DashboardHandler)
    handler.server = app
    handler.path = path
    handler.host_ok = lambda: True
    handler.change_ok = lambda: True
    handler.body = lambda: payload
    handler.json = lambda value, status=HTTPStatus.OK: replies.append((int(status), value))
    handler.error = lambda status, message: replies.append((int(status), {"error": message}))
    return handler


def _exercise(dashboard, tmp_path, monkeypatch, kind, shared_lock=False):
    """A successful fact or answer save must survive an overlapping file save."""
    monkeypatch.setattr(state, "APPLY", tmp_path)
    if kind == "fact":
        name = "profile"
        path = tmp_path / "profile.yaml"
        original = "first_name: Ada\nphone: null # FILL\n"
        replacement = original.replace("Ada", "Grace")
        detail = {"line": 2, "value": "5550100"}
        expected = "5550100"
        monkeypatch.setattr(state, "PROFILE", path)
    else:
        name = "answers"
        path = tmp_path / "answers.txt"
        original = "Q: City?\nA:\nQ: Experience?\nA: Two years\n"
        replacement = original.replace("Two years", "Three years")
        detail = {"line": 2, "answer": "Pune"}
        expected = "Pune"
        monkeypatch.setattr(state, "ANSWERS", path)
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(server, "files", lambda: {name: path})
    app = SimpleNamespace(file_lock=state._EDITS if shared_lock else threading.Lock(), runner=None)
    whole_replies, detail_replies, errors = [], [], []
    whole = _handler(dashboard, app, "/api/file", {
        "name": name, "text": replacement, "revision": dashboard.revision(original)
    }, whole_replies)
    partial = _handler(dashboard, app, "/api/" + kind, detail, detail_replies)
    checked = threading.Event()
    release = threading.Event()
    detail_done = threading.Event()
    original_temporary = dashboard.tempfile.NamedTemporaryFile

    def pause_after_revision(*args, **kwargs):
        checked.set()
        if not release.wait(5):
            raise AssertionError("the controlled edit interleaving timed out")
        return original_temporary(*args, **kwargs)

    monkeypatch.setattr(dashboard.tempfile, "NamedTemporaryFile", pause_after_revision)

    def run(handler, finished=None):
        try:
            handler.do_POST()
        except BaseException as exc:
            errors.append(exc)
        finally:
            if finished is not None:
                finished.set()

    whole_thread = threading.Thread(target=run, args=(whole,))
    detail_thread = threading.Thread(target=run, args=(partial, detail_done))
    whole_thread.start()
    try:
        assert checked.wait(5), "whole-file route did not reach its post-revision write"
        detail_thread.start()
        # An independent edit lock lets the detail commit here. A shared lock
        # correctly delays that commit until the whole-file save has finished.
        detail_done.wait(0.5)
    finally:
        release.set()
        whole_thread.join(5)
        if detail_thread.ident is not None:
            detail_thread.join(5)
    assert not whole_thread.is_alive() and not detail_thread.is_alive()
    assert not errors, errors
    assert detail_replies == [(200, {"ok": True})], detail_replies
    assert whole_replies[0][0] in (200, 409), whole_replies
    final = path.read_text(encoding="utf-8")
    if whole_replies[0][0] == 200:
        assert ("Grace" if kind == "fact" else "Three years") in final
    assert expected in final, {
        "whole_reply": whole_replies, "detail_reply": detail_replies,
        "committed_detail": expected, "final_file": final,
    }


@pytest.mark.parametrize("kind", ["fact", "answer"])
def test_updateweb_01_concurrent_edits_are_preserved(dashboard, tmp_path, monkeypatch, kind):
    _exercise(dashboard, tmp_path, monkeypatch, kind)


@pytest.mark.parametrize("kind", ["fact", "answer"])
def test_shared_lock_control_preserves_concurrent_edits(dashboard, tmp_path, monkeypatch, kind):
    """The identical schedule preserves both saves when writers share a lock."""
    _exercise(dashboard, tmp_path, monkeypatch, kind, shared_lock=True)
