import os
from pathlib import Path

import pytest

from common import paths


@pytest.fixture
def mac_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(paths.USER_DIR_ENV, raising=False)
    return home


def _desktop_checkout(home):
    root = home / "Desktop" / "apply"
    (root / "user" / "browser" / "naukri" / "chrome").mkdir(parents=True)
    (root / "user" / "browser" / "naukri" / "chrome" / "Cookies").write_text("session")
    return root


def test_sessions_under_the_desktop_move_to_the_library_and_a_link_stays_behind(mac_home):
    root = _desktop_checkout(mac_home)
    folder = paths.browser_home(root)
    assert folder == root / "user" / "browser" and folder.is_symlink()
    target = paths.private_browser_home(root)
    assert folder.resolve() == target.resolve()
    assert target.is_relative_to(mac_home / "Library" / "Application Support" / "Morrow")
    assert (folder / "naukri" / "chrome" / "Cookies").read_text() == "session"
    assert not paths.mac_protected(folder)


def test_a_second_call_leaves_the_link_alone(mac_home):
    root = _desktop_checkout(mac_home)
    first = paths.browser_home(root)
    assert paths.browser_home(root) == first and first.is_symlink()


def test_a_checkout_without_sessions_yet_gets_an_empty_folder_in_the_library(mac_home):
    root = mac_home / "Documents" / "apply"
    root.mkdir(parents=True)
    folder = paths.browser_home(root)
    assert folder.is_symlink() and folder.is_dir() and not any(folder.iterdir())


def test_a_checkout_outside_the_protected_folders_keeps_its_own_folder(mac_home):
    root = mac_home / "src" / "apply"
    (root / "user" / "browser").mkdir(parents=True)
    folder = paths.browser_home(root)
    assert folder == root / "user" / "browser" and not folder.is_symlink()
    assert not paths.private_browser_home(root).exists()


def test_other_systems_are_left_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv(paths.USER_DIR_ENV, raising=False)
    root = tmp_path / "Desktop" / "apply"
    (root / "user" / "browser").mkdir(parents=True)
    assert not paths.browser_home(root).is_symlink()


def test_sessions_with_a_browser_open_are_not_moved(mac_home):
    root = _desktop_checkout(mac_home)
    lock = root / "user" / "browser" / "naukri" / "chrome" / "SingletonLock"
    lock.symlink_to("this-mac-%d" % os.getpid())
    folder = paths.browser_home(root)
    assert not folder.is_symlink() and (folder / "naukri" / "chrome" / "Cookies").exists()


def test_a_stale_lock_from_a_dead_browser_does_not_block_the_move(mac_home):
    root = _desktop_checkout(mac_home)
    (root / "user" / "browser" / "naukri" / "chrome" / "SingletonLock").symlink_to("this-mac-999999999")
    assert paths.browser_home(root).is_symlink()


def test_an_absolute_user_dir_is_honoured(mac_home, monkeypatch):
    user = mac_home / "Downloads" / "morrow-user"
    (user / "browser").mkdir(parents=True)
    monkeypatch.setenv(paths.USER_DIR_ENV, str(user))
    folder = paths.browser_home(mac_home / "src" / "apply")
    assert folder == user / "browser" and folder.is_symlink()
