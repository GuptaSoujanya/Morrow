"""Synthetic Chrome ownership checks; never touch a real profile or process."""
import errno
from pathlib import Path

import pytest

from common import connections


@pytest.fixture
def profile(tmp_path, monkeypatch):
    base = tmp_path / "private-linkedin"
    (base / "chrome").mkdir(parents=True)
    monkeypatch.setattr(connections.socket, "gethostname", lambda: "test-machine.local")
    monkeypatch.setattr(connections.os, "kill", lambda *_: pytest.fail("Unexpected process probe"))
    return base


def add_lock(profile, target="test-machine.local-12345"):
    lock = profile / "chrome" / "SingletonLock"
    lock.symlink_to(target)
    return lock


def test_unused_profile_has_no_lock(profile):
    assert connections.profile_locked(profile) is False


def test_dead_local_browser_allows_chrome_recovery_without_deleting_files(profile, monkeypatch):
    lock = add_lock(profile)
    socket_file = profile / "retained-socket"
    socket_file.write_bytes(b"left after crash")
    (profile / "chrome" / "SingletonSocket").symlink_to(socket_file)
    cookie = profile / "chrome" / "SingletonCookie"
    cookie.symlink_to("old-random-cookie")
    saved_session = profile / "chrome" / "Cookies"
    saved_session.write_bytes(b"synthetic saved sign-in")
    probes = []

    def dead(pid, sig):
        probes.append((pid, sig))
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(connections.os, "kill", dead)
    assert connections.profile_locked(profile) is False
    assert probes == [(12345, 0)]
    assert lock.readlink() == Path("test-machine.local-12345")
    assert (profile / "chrome" / "SingletonSocket").readlink() == socket_file
    assert cookie.readlink() == Path("old-random-cookie")
    assert socket_file.read_bytes() == b"left after crash"
    assert saved_session.read_bytes() == b"synthetic saved sign-in"


def test_live_local_browser_stays_locked(profile, monkeypatch):
    add_lock(profile)
    probes = []
    monkeypatch.setattr(connections.os, "kill", lambda pid, sig: probes.append((pid, sig)))
    assert connections.profile_locked(profile) is True
    assert probes == [(12345, 0)]


@pytest.mark.parametrize("error", [
    PermissionError(errno.EPERM, "Permission denied"),
    OSError(errno.EIO, "Cannot inspect process"),
])
def test_uninspectable_process_remains_locked(profile, monkeypatch, error):
    add_lock(profile)

    def unavailable(*_):
        raise error

    monkeypatch.setattr(connections.os, "kill", unavailable)
    assert connections.profile_locked(profile) is True


@pytest.mark.parametrize("target", [
    "another-machine.local-12345",
    "test-machine.local", "test-machine.local-zero", "test-machine.local-0",
    "test-machine.local--1", "test-machine.local-012345",
    "test-machine.local-2147483648", "test-machine.local-9999999999999999999999",
    "test-machine.local-１２３４５", "/tmp/test-machine.local-12345",
])
def test_foreign_or_malformed_lock_is_not_probed_or_reclaimed(profile, target):
    add_lock(profile, target)
    assert connections.profile_locked(profile) is True


@pytest.mark.parametrize("name", ["SingletonSocket", "SingletonCookie"])
def test_orphan_marker_without_owner_evidence_stays_locked(profile, name):
    (profile / "chrome" / name).symlink_to("unknown-target")
    assert connections.profile_locked(profile) is True


def test_legacy_regular_lock_file_stays_locked(profile):
    (profile / "chrome" / "SingletonLock").write_text("legacy lock")
    assert connections.profile_locked(profile) is True


def test_new_owner_during_process_probe_is_not_treated_as_stale(profile, monkeypatch):
    lock = add_lock(profile)

    def changed(*_):
        lock.unlink()
        lock.symlink_to("test-machine.local-12346")
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(connections.os, "kill", changed)
    assert connections.profile_locked(profile) is True
    assert lock.readlink() == Path("test-machine.local-12346")


def test_unreadable_owner_is_not_reclaimed(profile, monkeypatch):
    add_lock(profile)

    def denied(*_):
        raise PermissionError(errno.EACCES, "Cannot read owner")

    monkeypatch.setattr(connections.os, "readlink", denied)
    assert connections.profile_locked(profile) is True


def test_uninspectable_marker_is_not_treated_as_absent(profile, monkeypatch):
    original = Path.lstat

    def denied(path, *args, **kwargs):
        if path == profile / "chrome" / "SingletonLock":
            raise PermissionError(errno.EACCES, "Cannot inspect marker")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    assert connections.profile_locked(profile) is True
