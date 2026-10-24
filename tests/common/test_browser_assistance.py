"""Filesystem-only tests for assistance scoped to a registered browser identity."""
import json
import os
import stat
import threading
from types import SimpleNamespace

import pytest

from common import browser_preview


IDENTIFIER = "a" * 32
INSTANCE = "00000000-0000-4000-8000-000000000001"
OTHER_INSTANCE = "00000000-0000-4000-8000-000000000002"
NOW = 1792827000.0


@pytest.fixture
def registered(tmp_path, monkeypatch):
    directory = tmp_path / "registry"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    manifest = directory / f"{IDENTIFIER}.json"
    value = {"version": 1, "id": IDENTIFIER, "label": "Chrome",
             "endpoint": "http://127.0.0.1:9222", "browser_instance": INSTANCE}
    manifest.write_text(json.dumps(value), encoding="utf-8")
    manifest.chmod(0o600)
    driver = SimpleNamespace(_morrow_browser_preview_registration={
        "directory": str(directory), "id": IDENTIFIER, "browser_instance": INSTANCE,
    })
    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "true")
    monkeypatch.setattr(browser_preview.time, "time", lambda: NOW)
    # Any accidental browser/network operation is a test failure.
    monkeypatch.setattr(browser_preview, "request_json", lambda *args, **kwargs: pytest.fail("Assistance must not contact a browser"))
    return driver, directory, manifest, value


def marker(directory):
    return directory / f"{IDENTIFIER}.assist"


def test_marker_is_exact_private_and_removed_after_assistance(registered):
    driver, directory, manifest, original = registered
    with browser_preview.assistance(driver, timeout_s=120, provider="naukri") as enabled:
        assert enabled is True
        assert json.loads(marker(directory).read_text()) == {
            "version": 1, "provider": "naukri", "expires_at": NOW + 120,
            "browser_instance": INSTANCE,
        }
        assert stat.S_IMODE(marker(directory).stat().st_mode) == 0o600
        assert sorted(path.name for path in directory.iterdir()) == [f"{IDENTIFIER}.assist", f"{IDENTIFIER}.json"]
    assert not marker(directory).exists()
    assert json.loads(manifest.read_text()) == original


def test_assistance_cleanup_runs_when_the_caller_raises(registered):
    driver, directory, _, _ = registered
    with pytest.raises(RuntimeError, match="synthetic caller failure"):
        with browser_preview.assistance(driver) as enabled:
            assert enabled is True
            raise RuntimeError("synthetic caller failure")
    assert not marker(directory).exists()


@pytest.mark.parametrize("flag", [None, "false", "0", ""])
def test_disabled_assistance_never_creates_a_marker(registered, monkeypatch, flag):
    driver, directory, _, _ = registered
    monkeypatch.delenv("MORROW_BROWSER_INTERACTIVE", raising=False)
    if flag is not None:
        monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", flag)
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


@pytest.mark.parametrize("timeout", [0, -1, True, False, float("nan"), float("inf"), -float("inf"), None, "invalid"])
def test_invalid_timeouts_cannot_enable_assistance(registered, timeout):
    driver, directory, _, _ = registered
    with browser_preview.assistance(driver, timeout_s=timeout) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


def test_long_timeout_is_bounded_to_five_minutes(registered):
    driver, directory, _, _ = registered
    with browser_preview.assistance(driver, timeout_s=3600) as enabled:
        assert enabled is True
        assert NOW < json.loads(marker(directory).read_text())["expires_at"] <= NOW + 300
    assert not marker(directory).exists()


@pytest.mark.parametrize("provider", ["google", "unknown", "../naukri", "", None])
def test_unknown_providers_do_not_create_markers(registered, provider):
    driver, directory, _, _ = registered
    with browser_preview.assistance(driver, provider=provider) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


@pytest.mark.parametrize("registration", [None, {}, {"id": IDENTIFIER},
    {"id": IDENTIFIER, "browser_instance": ""},
    {"id": "../outside", "browser_instance": INSTANCE},
    {"id": IDENTIFIER, "browser_instance": OTHER_INSTANCE}])
def test_unregistered_or_stale_driver_identity_is_refused(registered, registration):
    driver, directory, _, _ = registered
    if registration is None:
        del driver._morrow_browser_preview_registration
    else:
        driver._morrow_browser_preview_registration = {"directory": str(directory), **registration}
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


@pytest.mark.parametrize("change", [{"browser_instance": ""}, {"browser_instance": OTHER_INSTANCE},
    {"id": "b" * 32}, {"version": 2}])
def test_manifest_must_match_the_registered_browser(registered, change):
    driver, directory, manifest, value = registered
    manifest.write_text(json.dumps({**value, **change}), encoding="utf-8")
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


@pytest.mark.parametrize("target", ["directory", "manifest"])
def test_unprivate_registry_or_manifest_is_refused(registered, target):
    driver, directory, manifest, _ = registered
    (directory if target == "directory" else manifest).chmod(0o755 if target == "directory" else 0o644)
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


def test_missing_registry_is_not_created_for_assistance(registered):
    driver, directory, _, _ = registered
    unavailable = directory / "missing"
    driver._morrow_browser_preview_registration["directory"] = str(unavailable)
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not unavailable.exists()


@pytest.mark.parametrize("target", ["directory", "manifest"])
def test_symlinked_registry_or_manifest_is_never_followed(registered, tmp_path, target):
    driver, directory, manifest, _ = registered
    if target == "directory":
        link = tmp_path / "linked-registry"
        link.symlink_to(directory, target_is_directory=True)
        driver._morrow_browser_preview_registration["directory"] = str(link)
    else:
        external = tmp_path / "external.json"
        manifest.rename(external)
        manifest.symlink_to(external)
    with browser_preview.assistance(driver) as enabled:
        assert enabled is False
    assert not marker(directory).exists()


def test_assistance_never_overwrites_a_marker_symlink_target(registered, tmp_path):
    driver, directory, _, _ = registered
    external = tmp_path / "outside.txt"
    external.write_text("leave this file alone", encoding="utf-8")
    marker(directory).symlink_to(external)
    with browser_preview.assistance(driver) as enabled:
        assert external.read_text() == "leave this file alone"
        if enabled:
            assert not marker(directory).is_symlink()
            assert stat.S_IMODE(marker(directory).stat().st_mode) == 0o600
    assert external.read_text() == "leave this file alone"


def test_registered_identity_is_attached_only_after_successful_verification(registered, monkeypatch):
    driver, directory, _, _ = registered
    driver.capabilities = {"browserName": "chrome", "goog:chromeOptions": {"debuggerAddress": "127.0.0.1:9222"}}
    monkeypatch.setenv(browser_preview.ENV_NAME, str(directory))
    monkeypatch.setattr(browser_preview, "request_json", lambda *args: {
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/" + INSTANCE})
    browser_preview.register(driver)
    attached = driver._morrow_browser_preview_registration
    assert attached["browser_instance"] == INSTANCE and attached["directory"] == str(directory)
    assert json.loads((directory / (attached["id"] + ".json")).read_text())["browser_instance"] == INSTANCE
    monkeypatch.setattr(browser_preview, "request_json", lambda *args: {})
    browser_preview.register(driver)
    assert driver._morrow_browser_preview_registration is None
    with browser_preview.assistance(driver) as enabled:
        assert not enabled


def test_lease_removal_waits_for_in_flight_input_before_agent_can_resume(registered):
    driver, directory, _, _ = registered
    entered, finish, resumed = threading.Event(), threading.Event(), threading.Event()
    def paused_agent():
        with browser_preview.assistance(driver) as enabled:
            assert enabled
            entered.set()
            assert finish.wait(2)
        resumed.set()
    worker = threading.Thread(target=paused_agent)
    worker.start()
    assert entered.wait(1)
    descriptor = os.open(marker(directory), os.O_RDONLY)
    try:
        browser_preview.fcntl.flock(descriptor, browser_preview.fcntl.LOCK_SH)
        finish.set()
        assert not resumed.wait(.05), "Automation resumed while authorized input was still running"
        assert marker(directory).exists()
    finally:
        browser_preview.fcntl.flock(descriptor, browser_preview.fcntl.LOCK_UN)
        os.close(descriptor)
        finish.set()
        worker.join(2)
    assert resumed.is_set() and not marker(directory).exists()


def test_failed_input_drain_lock_never_resumes_automation(registered, monkeypatch):
    driver, directory, _, _ = registered
    def fail(*args):
        raise OSError("Synthetic lease lock failure")
    resumed = []
    monkeypatch.setattr(browser_preview.fcntl, "flock", fail)
    with pytest.raises(OSError, match="lease lock failure"):
        with browser_preview.assistance(driver) as enabled:
            assert enabled
        resumed.append(True)
    assert resumed == []
