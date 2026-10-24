"""Run-scoped previews use synthetic frames and processes, never real browsers."""
import http.client
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from web import server, state
from web.state import Command


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'APPLY', tmp_path)
    httpd = server.ControlServer(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.runner.shutdown()
    httpd.shutdown()
    httpd.server_close()


def get(site, path, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', site.server_port, timeout=10)
    connection.request('GET', path, headers=headers or {})
    reply = connection.getresponse()
    result = reply.status, dict(reply.getheaders()), json.loads(reply.read())
    connection.close()
    return result


def test_preview_forwards_only_selected_run_browser_and_tab_and_is_not_cached(site, monkeypatch):
    calls = []
    frame = {'state': 'ready', 'image': 'data:image/jpeg;base64,dGVzdA=='}
    monkeypatch.setattr(site.runner, 'browser_snapshot', lambda *args: calls.append(args) or frame)
    status, headers, data = get(site, '/api/run/browser?id=first&browser=chrome&tab=page')
    assert status == 200 and data == frame
    assert calls == [('first', 'chrome', 'page')]
    assert headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('headers', [{'Origin': 'https://elsewhere.test'}, {'Sec-Fetch-Site': 'cross-site'}, {'Host': 'elsewhere.test'}])
def test_foreign_pages_cannot_capture_browser_frames(site, monkeypatch, headers):
    def forbidden(*args):
        raise AssertionError('No screenshot should be captured')
    monkeypatch.setattr(site.runner, 'browser_snapshot', forbidden)
    assert get(site, '/api/run/browser?id=first', headers)[0] == 403


def test_invalid_or_unknown_run_cannot_choose_a_registry_directory(site):
    assert get(site, '/api/run/browser')[0] == 400
    assert get(site, '/api/run/browser?id=../../private')[0] == 404
    assert get(site, '/api/run/browser?id=' + 'x' * 129)[0] == 400


def test_access_is_checked_again_before_delivering_a_captured_frame(site, monkeypatch):
    access = iter([True, False])
    monkeypatch.setattr(server.Handler, 'stream_authorized', lambda handler: next(access))
    monkeypatch.setattr(site.runner, 'browser_snapshot', lambda *args: {'state': 'ready', 'image': 'private-frame'})
    status, _, body = get(site, '/api/run/browser?id=first')
    assert status == 401 and 'private-frame' not in json.dumps(body)


def start_synthetic(site):
    return site.runner.start(Command('Synthetic browser worker', (sys.executable, '-c',
        'import os,time; print(os.environ["MORROW_BROWSER_PREVIEW_DIR"],flush=True); time.sleep(30)')), 'synthetic')


def test_runner_creates_private_registry_and_cleans_it_after_stop(site):
    run_id = start_synthetic(site)
    folder = Path(site.runner.runs[run_id].preview_store.name)
    assert folder.is_dir() and folder.stat().st_mode & 0o077 == 0
    site.runner.stop(run_id)
    deadline = time.monotonic() + 5
    while folder.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert not folder.exists()
    assert site.runner.browser_snapshot(run_id)['state'] == 'finished'


def test_browser_frames_do_not_block_agent_output_or_overlap(site, monkeypatch):
    from web import browser_preview
    run_id = start_synthetic(site)
    entered, release = threading.Event(), threading.Event()
    def capture(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {'state': 'ready', 'image': 'synthetic'}
    monkeypatch.setattr(browser_preview, 'snapshot', capture)
    thread = threading.Thread(target=lambda: site.runner.browser_snapshot(run_id))
    thread.start()
    try:
        assert entered.wait(2)
        assert site.runner.browser_snapshot(run_id)['state'] == 'waiting'
        site.runner.say('Agent output still works', run_id)
        assert site.runner.snapshot(after=0)['lines'][-1][1] == 'Agent output still works'
    finally:
        release.set()
        thread.join(3)


def test_frames_captured_after_a_run_finishes_are_discarded(site, monkeypatch):
    from web import browser_preview
    run_id = start_synthetic(site)
    def capture(*args, **kwargs):
        with site.runner.lock:
            site.runner.closed = True
        return {'state': 'ready', 'image': 'stale-frame'}
    monkeypatch.setattr(browser_preview, 'snapshot', capture)
    result = site.runner.browser_snapshot(run_id)
    assert result['state'] == 'finished' and 'image' not in result


def test_failed_preview_does_not_expose_debug_addresses_or_stop_the_agent(site, monkeypatch):
    from web import browser_preview
    run_id = start_synthetic(site)
    def capture(*args, **kwargs):
        raise RuntimeError('private-debug-address-and-token')
    monkeypatch.setattr(browser_preview, 'snapshot', capture)
    result = site.runner.browser_snapshot(run_id)
    assert result['state'] == 'unavailable' and 'private-debug' not in json.dumps(result)
    assert site.runner.runs[run_id].result is None


def test_process_start_failure_does_not_leave_a_registry_directory(site, monkeypatch):
    folders = []
    factory = tempfile.TemporaryDirectory
    def temporary(*args, **kwargs):
        result = factory(*args, **kwargs)
        folders.append(Path(result.name))
        return result
    def fail(*args, **kwargs):
        raise OSError('Synthetic start failure')
    monkeypatch.setattr(tempfile, 'TemporaryDirectory', temporary)
    monkeypatch.setattr(subprocess, 'Popen', fail)
    with pytest.raises(RuntimeError, match='Could not start'):
        start_synthetic(site)
    assert folders and all(not folder.exists() for folder in folders)
