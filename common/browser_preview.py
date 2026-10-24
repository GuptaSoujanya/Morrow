"""Register a run's browser and explicitly lease control during sign-in pauses."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import http.client
import ipaddress
import json
import logging
import math
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
REGISTRATION_ATTRIBUTE = "_morrow_browser_preview_registration"
MAX_ASSISTANCE_SECONDS = 300.0


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
        setattr(driver, REGISTRATION_ATTRIBUTE, None)
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
        if instance:
            setattr(driver, REGISTRATION_ATTRIBUTE,
                    dict(directory=directory, id=identifier, browser_instance=instance))
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


@contextmanager
def assistance(driver, timeout_s: float = MAX_ASSISTANCE_SECONDS, provider: str = "naukri"):
    """Lease interaction with this verified browser while its agent is paused.

    Closing a viewer never owns this context or the driver. The caller must
    finish this context before continuing automation; the control endpoint
    separately validates the lease and current browser identity on every input.
    """
    descriptor, lease_descriptor, created, enabled, name = None, None, False, False, ""
    try:
        try:
            if os.getenv("MORROW_BROWSER_INTERACTIVE", "").strip().lower() != "true" or provider != "naukri":
                raise ValueError("Browser assistance is not enabled")
            if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                    or not math.isfinite(timeout_s) or timeout_s <= 0):
                raise ValueError("Invalid assistance duration")
            timeout_s = min(timeout_s, MAX_ASSISTANCE_SECONDS)
            registered = getattr(driver, REGISTRATION_ATTRIBUTE, None)
            if not isinstance(registered, dict):
                raise ValueError("Browser registration is unavailable")
            identifier, instance = registered.get("id"), registered.get("browser_instance")
            if (not isinstance(identifier, str) or not MANIFEST_NAME.fullmatch(identifier + ".json")
                    or not isinstance(instance, str) or str(uuid.UUID(instance)) != instance):
                raise ValueError("Browser registration is unavailable")
            descriptor = open_private_directory(registered["directory"])
            file_descriptor = os.open(identifier + ".json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            with os.fdopen(file_descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                        or info.st_mode & 0o077 or info.st_uid != os.getuid()):
                    raise ValueError("Browser registration must be private")
                manifest = json.loads(stream.read(4097))
            if (not isinstance(manifest, dict) or manifest.get("version") != 1
                    or manifest.get("id") != identifier or manifest.get("browser_instance") != instance):
                raise ValueError("Browser identity changed")
            endpoint_parts(manifest["endpoint"])
            name = identifier + ".assist"
            temporary = "." + identifier + ".assist-" + uuid.uuid4().hex + ".tmp"
            try:
                output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=descriptor)
                with os.fdopen(output, "w", encoding="utf-8") as stream:
                    lease_descriptor = os.dup(stream.fileno())
                    json.dump(dict(version=1, provider=provider, browser_instance=instance,
                                   expires_at=time.time() + timeout_s), stream)
                # Linking the completed temporary file makes publication atomic
                # and refuses any existing lease or symlink at the destination.
                os.link(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
                created = enabled = True
            finally:
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            logger.debug("Interactive assistance is unavailable for this browser.")
        yield enabled
    finally:
        if descriptor is not None:
            try:
                if created:
                    # The controller holds a shared lock while sending input.
                    # Wait for it before revoking the lease and resuming the
                    # agent, so human input and automation cannot overlap.
                    fcntl.flock(lease_descriptor, fcntl.LOCK_EX)
                    try:
                        os.unlink(name, dir_fd=descriptor)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(descriptor)
                if lease_descriptor is not None:
                    os.close(lease_descriptor)
