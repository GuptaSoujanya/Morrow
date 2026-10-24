"""Register only a run's own browser for an optional, read-only preview."""
from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit
import uuid

ENV_NAME = "MORROW_BROWSER_PREVIEW_DIR"
MAX_MANIFESTS = 32
MANIFEST_NAME = re.compile(r"^[0-9a-f]{32}\.json$")
logger = logging.getLogger(__name__)


def remaining(deadline: float, cap: float = 1.5) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Browser preview timed out")
    return min(value, cap)


def endpoint_parts(value: str) -> tuple[str, int, str]:
    """Accept a literal loopback address; never resolve an arbitrary hostname."""
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("Invalid local browser address")
    url = urlsplit(value if "://" in value else "http://" + value)
    host = url.hostname
    if host == "localhost":
        host = "127.0.0.1"
    if (url.scheme != "http" or not host or not ipaddress.ip_address(host).is_loopback
            or not url.port or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("Invalid local browser address")
    authority = f"[{host}]:{url.port}" if ":" in host else f"{host}:{url.port}"
    return host, url.port, authority


def request_json(endpoint: str, path: str, deadline: float, limit: int = 65536):
    host, port, _ = endpoint_parts(endpoint)
    connection = http.client.HTTPConnection(host, port, timeout=remaining(deadline))
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        if connection.sock:
            connection.sock.settimeout(remaining(deadline))
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Local browser metadata is unavailable")
        if int(response.getheader("Content-Length", "0")) > limit:
            raise ValueError("Browser metadata is too large")
        chunks, size = [], 0
        while True:
            if connection.sock:
                connection.sock.settimeout(remaining(deadline))
            else:
                remaining(deadline)
            chunk = response.read1(min(8192, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise ValueError("Browser metadata is too large")
        return json.loads(b"".join(chunks))
    finally:
        connection.close()


def browser_instance(version, endpoint: str) -> str:
    if not isinstance(version, dict):
        raise ValueError("Browser identity is unavailable")
    url = urlsplit(version.get("webSocketDebuggerUrl", ""))
    _, _, expected = endpoint_parts(endpoint)
    _, _, actual = endpoint_parts("http://" + url.netloc)
    if (url.scheme != "ws" or actual != expected or url.query or url.fragment
            or not url.path.startswith("/devtools/browser/")):
        raise ValueError("Browser identity is unavailable")
    identifier = url.path.removeprefix("/devtools/browser/")
    if str(uuid.UUID(identifier)) != identifier.lower():
        raise ValueError("Browser identity is unavailable")
    return identifier


def open_private_directory(directory) -> int:
    descriptor = os.open(os.fspath(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        os.close(descriptor)
        raise ValueError("Browser preview directory must be private")
    return descriptor


def _remove(directory: Path, name: str) -> None:
    try:
        descriptor = open_private_directory(directory)
        try:
            os.unlink(name, dir_fd=descriptor)
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        pass


def register(driver) -> None:
    """Best effort only: preview setup must never interrupt an agent's browser."""
    directory = os.environ.get(ENV_NAME)
    if not directory:
        return
    try:
        capabilities = getattr(driver, "capabilities", None) or {}
        address = next(((capabilities.get(key) or {}).get("debuggerAddress")
                        for key in ("goog:chromeOptions", "ms:edgeOptions")
                        if (capabilities.get(key) or {}).get("debuggerAddress")), "")
        _, _, authority = endpoint_parts(address)
        endpoint = "http://" + authority
        try:
            instance = browser_instance(request_json(endpoint, "/json/version", time.monotonic() + 1), endpoint)
        except Exception:
            # Keep an unavailable entry so the UI does not promise a browser
            # is still opening. Never adopt a later identity from a reused port.
            instance = ""
        identifier = uuid.uuid4().hex
        label = {"chrome": "Chrome", "msedge": "Edge", "MicrosoftEdge": "Edge"}.get(capabilities.get("browserName"), "Browser")
        value = dict(version=1, id=identifier, label=label, endpoint=endpoint,
                     browser_instance=instance, registered_at=time.time())
        descriptor = open_private_directory(directory)
        temporary, name = "." + identifier + ".tmp", identifier + ".json"
        try:
            file_descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                      0o600, dir_fd=descriptor)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream)
            os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            # Browser retries must not grow a run's registry without bound.
            entries = [(os.stat(item, dir_fd=descriptor, follow_symlinks=False).st_mtime, item)
                       for item in os.listdir(descriptor) if MANIFEST_NAME.fullmatch(item)]
            for _, old_name in sorted(entries, reverse=True)[MAX_MANIFESTS:]:
                os.unlink(old_name, dir_fd=descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
            os.close(descriptor)
        # Unregister after a successful quit, without adding browser commands.
        original_quit = getattr(driver, "quit", None)
        if callable(original_quit):
            def quit_and_unregister(*args, **kwargs):
                result = original_quit(*args, **kwargs)
                _remove(Path(directory), name)
                return result
            driver.quit = quit_and_unregister
    except Exception:
        # No endpoint, local path or browser content goes into user-facing logs.
        logger.debug("The optional browser preview could not be registered.")
