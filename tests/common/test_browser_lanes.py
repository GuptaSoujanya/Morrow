"""Private synthetic browser profiles only; no real sessions or browser starts."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import stat

import pytest

from common import browser_lanes as lanes, connections


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "browser" / "naukri"
    connections.mark_managed(folder)
    chrome = folder / "chrome" / "Default"
    chrome.mkdir(parents=True)
    (chrome / "Cookies").write_text("synthetic closed session")
    (chrome / "Cookies-wal").write_text("synthetic closed journal")
    (folder / connections.METADATA).write_text(
        '{"google":{"state":"connected","verified_account":"saved@example.test"}}')
    return folder


def destination(source, lane="hirist"):
    return source.parent / "lanes" / lane


def test_paths_are_stable_independent_and_pure(source):
    expected = [destination(source, site) for site in lanes.BOARD_LANES]
    assert [lanes.profile_dir(site, str(source)) for site in lanes.BOARD_LANES] == expected
    assert len(set(expected)) == 4
    assert not any(folder.exists() for folder in expected)
    assert lanes.profile_dir("naukri", str(source)) is None
    assert lanes.profile_dir("linkedin", str(source)) is None
    assert lanes.profile_dir("hirist", "") is None


@pytest.mark.parametrize("site", ["../escape", "", "google", "hirist/../naukri"])
def test_unknown_or_path_like_site_is_rejected(source, site):
    with pytest.raises(ValueError, match="Unknown browser site"):
        lanes.prepare(site, str(source))


def test_seed_copies_saved_session_only_once_and_is_private(source):
    env = lanes.prepare("hirist", str(source))
    folder = destination(source)
    assert env == {"BROWSER_PROFILE_DIR": str(folder)}
    assert (folder / "chrome" / "Default" / "Cookies").read_text() == "synthetic closed session"
    assert (folder / "chrome" / "Default" / "Cookies-wal").read_text() == "synthetic closed journal"
    assert connections.read_metadata(folder) == connections.read_metadata(source)
    assert connections.managed_profile(str(folder))
    assert json.loads((folder / connections.MARKER).read_text()) == {"version": 1, "session_only": True}
    for item in (folder, *folder.rglob("*")):
        assert stat.S_IMODE(item.stat().st_mode) == (0o700 if item.is_dir() else 0o600)
    (folder / "chrome" / "Default" / "Cookies").write_text("hirist independently refreshed login")
    (source / "chrome" / "Default" / "Cookies").write_text("naukri newer login")
    assert lanes.prepare("hirist", str(source)) == env
    assert (folder / "chrome" / "Default" / "Cookies").read_text() == "hirist independently refreshed login"


def test_copy_omits_locks_caches_symlinks_and_special_files(source, monkeypatch):
    chrome = source / "chrome"
    (chrome / "SingletonLock").symlink_to("synthetic-host-999")
    (chrome / "Default" / "Cache").mkdir()
    (chrome / "Default" / "Cache" / "unneeded").write_text("cache")
    (chrome / "DevToolsActivePort").write_text("old endpoint")
    (chrome / "Default" / "LOCK").write_text("old leveldb lock")
    elsewhere = source.parent / "private-personal-data"
    elsewhere.mkdir()
    (elsewhere / "secret").write_text("do not copy")
    (chrome / "linked-directory").symlink_to(elsewhere, target_is_directory=True)
    (chrome / "linked-file").symlink_to(elsewhere / "secret")
    os.mkfifo(chrome / "fifo")
    browser_socket = socket.socket(socket.AF_UNIX)
    # macOS limits AF_UNIX paths to 104 bytes; pytest's temp root is longer.
    monkeypatch.chdir(chrome)
    browser_socket.bind("socket")
    # Simulate a positively known dead source; the copier must omit old locks.
    monkeypatch.setattr(connections, "profile_locked", lambda _: False)
    try:
        lanes.prepare("hirist", str(source))
    finally:
        browser_socket.close()
    copied = destination(source) / "chrome"
    assert sorted(item.name for item in copied.iterdir()) == ["Default"]
    assert sorted(item.name for item in (copied / "Default").iterdir()) == ["Cookies", "Cookies-wal"]
    assert (elsewhere / "secret").read_text() == "do not copy"


def test_open_or_unknown_source_is_not_copied_or_changed(source):
    lock = source / "chrome" / "SingletonLock"
    lock.write_text("unknown browser ownership")
    original = (source / "chrome" / "Default" / "Cookies").read_bytes()
    lanes.prepare("hirist", str(source))
    folder = destination(source)
    assert connections.managed_profile(str(folder))
    assert list(folder.iterdir()) == [folder / connections.MARKER]
    assert lock.read_text() == "unknown browser ownership"
    assert (source / "chrome" / "Default" / "Cookies").read_bytes() == original


@pytest.mark.parametrize("donor", ["missing", "unmanaged", "empty-managed"])
def test_missing_or_unmanaged_donor_produces_a_clean_managed_lane(tmp_path, donor):
    source = tmp_path / "browser" / "main"
    if donor == "empty-managed":
        connections.mark_managed(source)
    elif donor == "unmanaged":
        (source / "chrome").mkdir(parents=True)
        (source / "chrome" / "Cookies").write_text("unmanaged personal session")
    lanes.prepare("instahyre", str(source))
    folder = destination(source, "instahyre")
    assert connections.managed_profile(str(folder))
    assert list(folder.iterdir()) == [folder / connections.MARKER]


def test_existing_lane_is_reused_without_inspecting_the_donor(source, monkeypatch):
    folder = destination(source)
    (folder / "chrome").mkdir(parents=True)
    (folder / "chrome" / "Cookies").write_text("existing lane session")
    monkeypatch.setattr(lanes, "_seed", lambda *_: pytest.fail("Existing lane must never be reseeded"))
    lanes.prepare("hirist", str(source))
    assert (folder / "chrome" / "Cookies").read_text() == "existing lane session"
    assert connections.managed_profile(str(folder))


@pytest.mark.parametrize("alias", ["source", "lanes-root", "destination", "destination-chrome"])
def test_profile_path_aliases_are_rejected(source, alias):
    folder = destination(source)
    other = source.parent / "other"
    other.mkdir()
    if alias == "source":
        link = source.parent / "source-link"
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif alias == "lanes-root":
        folder.parent.symlink_to(other, target_is_directory=True)
    elif alias == "destination":
        folder.parent.mkdir()
        folder.symlink_to(other, target_is_directory=True)
    else:
        folder.mkdir(parents=True)
        (folder / "chrome").symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        lanes.prepare("hirist", str(source))
    assert list(other.iterdir()) == []


def test_recursive_source_destination_alias_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="separate from its source"):
        lanes.profile_dir("hirist", str(tmp_path / "lanes"))
    assert list(tmp_path.iterdir()) == []


def test_partial_copy_is_discarded_and_never_published(source, monkeypatch):
    folder = destination(source)

    def fail_after_one_file(_source, staging):
        (staging / "chrome").mkdir()
        (staging / "chrome" / "partial-cookie").write_text("incomplete")
        assert not folder.exists()
        raise OSError("synthetic disk read failure")

    monkeypatch.setattr(lanes, "_seed", fail_after_one_file)
    lanes.prepare("hirist", str(source))
    assert connections.managed_profile(str(folder))
    assert list(folder.iterdir()) == [folder / connections.MARKER]
    assert not list(folder.parent.glob(".hirist-*"))


def test_donor_mutation_during_copy_discards_all_copied_sqlite_files(source, monkeypatch):
    original = lanes.shutil.copyfileobj
    changed = False

    def changing_copy(incoming, output):
        nonlocal changed
        original(incoming, output)
        if not changed:
            changed = True
            (source / "chrome" / "Default" / "Cookies").write_text("changed while copying")

    monkeypatch.setattr(lanes.shutil, "copyfileobj", changing_copy)
    lanes.prepare("hirist", str(source))
    folder = destination(source)
    assert list(folder.iterdir()) == [folder / connections.MARKER]
    assert not list(folder.parent.glob(".hirist-*"))


def test_chrome_opening_mid_copy_discards_the_seed(source, monkeypatch):
    original = lanes.shutil.copyfileobj

    def opening_copy(incoming, output):
        original(incoming, output)
        (source / "chrome" / "SingletonLock").write_text("browser started")

    monkeypatch.setattr(lanes.shutil, "copyfileobj", opening_copy)
    lanes.prepare("hirist", str(source))
    folder = destination(source)
    assert list(folder.iterdir()) == [folder / connections.MARKER]
    assert (source / "chrome" / "SingletonLock").read_text() == "browser started"


@pytest.mark.parametrize("bad_metadata", ["symlink", "invalid-json", "too-big"])
def test_only_bounded_regular_connection_metadata_is_copied(source, bad_metadata):
    metadata = source / connections.METADATA
    if bad_metadata == "symlink":
        metadata.unlink()
        metadata.symlink_to(source / "chrome" / "Default" / "Cookies")
    elif bad_metadata == "invalid-json":
        metadata.write_text("not connection data")
    else:
        metadata.write_text('{"oversized":"' + "x" * 65536 + '"}')
    lanes.prepare("hirist", str(source))
    assert not (destination(source) / connections.METADATA).exists()
    assert (destination(source) / "chrome" / "Default" / "Cookies").exists()


def test_connection_identity_changing_mid_copy_discards_the_seed(source, monkeypatch):
    original = lanes.shutil.copyfileobj

    def changed_identity(incoming, output):
        original(incoming, output)
        (source / connections.METADATA).write_text('{"google":{"state":"disconnected"}}')

    monkeypatch.setattr(lanes.shutil, "copyfileobj", changed_identity)
    lanes.prepare("hirist", str(source))
    folder = destination(source)
    assert list(folder.iterdir()) == [folder / connections.MARKER]


def test_seeded_verified_google_identity_overrides_an_old_environment_hint(source, monkeypatch):
    from common.config import load_settings

    lanes.prepare("hirist", str(source))
    monkeypatch.setenv("GOOGLE_EMAIL", "wrong-old-account@example.test")
    settings = load_settings(str(source.parent / "absent-synthetic.env"),
                             overrides={"browser_profile_dir": str(destination(source))})
    assert settings.session_only is True
    assert settings.google_email == "saved@example.test"


def test_concurrent_initialization_publishes_one_complete_profile(source, monkeypatch):
    original = lanes._seed
    seeds = []

    def tracked_seed(*args):
        seeds.append(1)
        return original(*args)

    monkeypatch.setattr(lanes, "_seed", tracked_seed)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: lanes.prepare("hirist", str(source)), range(4)))
    assert seeds == [1]
    assert all(value == results[0] for value in results)
    assert (destination(source) / "chrome" / "Default" / "Cookies").read_text() == "synthetic closed session"


def test_prepare_all_is_eager_deduplicated_and_preserves_site_order(source):
    all_envs = lanes.prepare_all(str(source), ("naukri", "hirist", "linkedin", "instahyre", "hirist"))
    assert list(all_envs) == ["naukri", "hirist", "linkedin", "instahyre"]
    assert all_envs["naukri"] == all_envs["linkedin"] == {}
    for site in ("hirist", "instahyre"):
        assert (Path(all_envs[site]["BROWSER_PROFILE_DIR"]) / "chrome" / "Default" / "Cookies").exists()


def test_default_prepare_all_creates_all_four_independent_board_sessions(source):
    all_envs = lanes.prepare_all(str(source))
    assert tuple(all_envs) == lanes.BOARD_LANES
    assert len({value["BROWSER_PROFILE_DIR"] for value in all_envs.values()}) == 4
