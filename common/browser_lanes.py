"""Persistent, private Chrome sessions for independently running job sites.

The main automation session belongs to Naukri; LinkedIn already has its own
configured session. Other sites receive a permanent sibling profile. A new
profile may inherit a *closed*, Morrow-managed Chrome session once. We never
merge it again, copy a personal browser profile, or publish an incomplete copy.

Call ``prepare_all`` before starting any processes in a batch. Dashboard callers
also coordinate this preparation with Connections browser starts under their
runner lock. Chrome ownership and source changes are checked during copying as
additional protection; unavailable donors produce a fresh session-only profile.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Dict, Iterable, Optional

from common import connections


logger = logging.getLogger(__name__)
BOARD_LANES = ("hirist", "instahyre", "cutshort", "wellfound")
_OWN_PROFILE = frozenset(("naukri", "linkedin"))
_LANES = frozenset(BOARD_LANES) | _OWN_PROFILE
_OMIT = frozenset(name.casefold() for name in (
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "GrShaderCache", "GraphiteDawnCache", "ShaderCache",
    "Media Cache", "CacheStorage", "ScriptCache", "Crashpad", "Crash Reports",
    "BrowserMetrics", "component_crx_cache", "extensions_crx_cache",
    "optimization_guide_model_store", "DevToolsActivePort", "lockfile", "LOCK",
))


class _DonorChanged(OSError):
    """A donor became active or changed while a private copy was being made."""


def _path(raw: str) -> Path:
    path = Path(raw).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Automation profile directories cannot be symbolic links.")
    return path.resolve()


def profile_dir(lane: str, base: str) -> Optional[Path]:
    """Return a site's persistent profile path without creating anything."""
    if lane not in _LANES:
        raise ValueError("Unknown browser site: %s" % lane)
    if lane in _OWN_PROFILE or not base.strip():
        return None
    source = _path(base)
    root = source.parent / "lanes"
    folder = root / lane
    if root.is_symlink() or folder.is_symlink():
        raise ValueError("Site browser profiles cannot be symbolic links.")
    if source == folder or source in folder.parents or folder in source.parents:
        raise ValueError("A site browser profile must be separate from its source.")
    return folder


def _private_directory(folder: Path) -> None:
    if folder.is_symlink():
        raise ValueError("Site browser profiles cannot be symbolic links.")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Site browser profiles must be directories owned by this user.")
    folder.chmod(0o700)


@contextlib.contextmanager
def _preparation_lock(root: Path, lane: str):
    _private_directory(root)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    descriptor = os.open(root / (".%s.prepare.lock" % lane), flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("The browser preparation lock is not a private regular file.")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _write_marker(folder: Path) -> None:
    marker = folder / connections.MARKER
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"version": 1, "session_only": True}, stream)


def _existing(folder: Path) -> bool:
    """Keep previous lane state, including a person's independently saved login."""
    if not folder.exists() and not folder.is_symlink():
        return False
    _private_directory(folder)
    if (folder / "chrome").is_symlink():
        raise ValueError("The site Chrome profile cannot be a symbolic link.")
    marker = folder / connections.MARKER
    if marker.is_symlink():
        raise ValueError("The managed profile marker cannot be a symbolic link.")
    if marker.exists():
        if not connections.managed_profile(str(folder)):
            raise ValueError("The site browser profile has an invalid managed marker.")
        marker.chmod(0o600)
    else:
        _write_marker(folder)
    return True


def _signature(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _retained(name: str) -> bool:
    return not name.startswith("Singleton") and name.casefold() not in _OMIT


def _closed(source: Path) -> None:
    if connections.profile_locked(source):
        raise _DonorChanged("The source automation browser is open or its ownership is uncertain.")


def _walk(descriptor: int, source: Path, destination: Optional[Path] = None, prefix: str = "") -> dict:
    """Copy/snapshot using directory descriptors, never following profile symlinks."""
    _closed(source)
    entries = {prefix: _signature(os.fstat(descriptor))}
    with os.scandir(descriptor) as children:
        names = sorted(entry.name for entry in children if _retained(entry.name))
    for name in names:
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        relative = prefix + "/" + name
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                target = destination / name if destination is not None else None
                if target is not None:
                    target.mkdir(mode=0o700)
                entries.update(_walk(child, source, target, relative))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            # Sockets, pipes, devices, and symbolic links carry no saved sign-in.
            _closed(source)
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                before = os.fstat(child)
                if not stat.S_ISREG(before.st_mode) or _signature(before) != _signature(info):
                    raise _DonorChanged("The source profile changed during preparation.")
                if destination is not None:
                    target = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(target, "wb") as output, os.fdopen(os.dup(child), "rb") as incoming:
                        shutil.copyfileobj(incoming, output)
                    if _signature(os.fstat(child)) != _signature(before):
                        raise _DonorChanged("The source profile changed during preparation.")
                entries[relative] = _signature(before)
            finally:
                os.close(child)
    return entries


def _seed(source: Path, staging: Path) -> bool:
    if not connections.managed_profile(str(source)):
        return False
    if source.stat().st_uid != os.getuid():
        return False
    _closed(source)
    chrome = source / "chrome"
    if not chrome.is_dir() or chrome.is_symlink():
        return False
    metadata = _metadata_snapshot(source)
    descriptor = os.open(chrome, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        target = staging / "chrome"
        target.mkdir(mode=0o700)
        before = _walk(descriptor, source, target)
        _closed(source)
        after = _walk(descriptor, source)
        if before != after or _signature(chrome.lstat()) != before[""]:
            raise _DonorChanged("The source profile changed during preparation.")
        if metadata != _metadata_snapshot(source):
            raise _DonorChanged("Saved connection information changed during preparation.")
        if metadata is not None:
            # This preserves verified account identity together with its cookies.
            # Bots still verify the actual site session before starting work.
            target_fd = os.open(staging / connections.METADATA, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(target_fd, "wb") as stream:
                stream.write(metadata[1])
        _closed(source)
        return True
    finally:
        os.close(descriptor)


def _metadata_snapshot(source: Path):
    """Read only a bounded, private regular metadata file without following links."""
    path = source / connections.METADATA
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 65536:
        return None
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if _signature(before) != _signature(info):
            raise _DonorChanged("Saved connection information changed during preparation.")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            body = stream.read(65537)
        if len(body) > 65536 or _signature(os.fstat(descriptor)) != _signature(before):
            raise _DonorChanged("Saved connection information changed during preparation.")
        try:
            metadata = json.loads(body)
        except (ValueError, RecursionError):
            return None
        return (_signature(before), body) if isinstance(metadata, dict) else None
    finally:
        os.close(descriptor)


def prepare(lane: str, base: str) -> Dict[str, str]:
    """Prepare one persistent site session, returning child-process overrides.

    A live, unowned, or changing donor is not copied. That site's clean managed
    profile can be connected normally; it will never borrow a running browser.
    Existing site profiles are reused without replacing their saved sessions.
    """
    folder = profile_dir(lane, base)
    if folder is None:
        return {}
    source = _path(base)
    environment = {"BROWSER_PROFILE_DIR": str(folder)}
    with _preparation_lock(folder.parent, lane):
        if _existing(folder):
            return environment
        staging = Path(tempfile.mkdtemp(prefix=".%s-" % lane, dir=folder.parent))
        try:
            try:
                seeded = _seed(source, staging)
            except OSError as exc:
                logger.info("[lanes] %s: starting with a fresh private session (%s)", lane, exc)
                # Never keep a few copied SQLite files from a failed seed.
                shutil.rmtree(staging)
                staging = Path(tempfile.mkdtemp(prefix=".%s-" % lane, dir=folder.parent))
                seeded = False
            _write_marker(staging)
            if not _existing(folder):
                os.rename(staging, folder)
            if not seeded:
                logger.info("[lanes] %s has its own browser session; connect this site before applying.", lane)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return environment


def prepare_all(base: str, lanes: Iterable[str] = BOARD_LANES) -> Dict[str, Dict[str, str]]:
    """Prepare a batch before its first Chrome starts, preserving site order."""
    return {lane: prepare(lane, base) for lane in dict.fromkeys(lanes)}
