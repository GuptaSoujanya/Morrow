"""Registered browser views and bounded input while an agent requests help."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, wait
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import socket
import stat
import threading
import time
from urllib.parse import urlsplit
import uuid

import websocket

from common.browser_preview import (MANIFEST_NAME, MAX_MANIFESTS, browser_instance,
                                    endpoint_parts, open_private_directory, remaining, request_json)

TOTAL_TIMEOUT = 8.0
MAX_MESSAGE = 4 * 1024 * 1024
MAX_IMAGE = 2 * 1024 * 1024
MAX_INVENTORY_WORKERS = 4
FRAME_TTL = 10.0
MAX_FRAMES = 512
NAUKRI_SIGN_IN = "https://www.naukri.com/nlogin/login"
_frames = {}
_frames_lock = threading.Lock()
_KEYS = {"Tab": 9, "Enter": 13, "Escape": 27, "Backspace": 8, "Delete": 46,
         "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
         "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34}


class PreviewUnavailable(Exception):
    pass


class BrowserInputError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _assistance(directory, entry):
    result = dict(enabled=False, reason="The agent is working. Controls are available only when it asks for sign-in help.")
    descriptor = None
    try:
        descriptor = open_private_directory(directory)
        fd = os.open(entry["id"] + ".assist", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or info.st_mode & 0o077 or info.st_uid != os.getuid():
                return result
            value = json.loads(stream.read(4097))
        expires = value.get("expires_at")
        if (value.get("version") != 1 or value.get("provider") != "naukri"
                or not entry.get("browser_instance") or value.get("browser_instance") != entry["browser_instance"]
                or not isinstance(expires, (int, float)) or isinstance(expires, bool) or not math.isfinite(expires)
                or not time.time() < expires <= time.time() + 600):
            return result
        return dict(enabled=True, provider="naukri", expires_at=expires,
                    reason="Naukri is waiting for you to finish sign-in. You can use this browser now.")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _remember_frame(directory, entry, target, viewport, control):
    token, now = secrets.token_urlsafe(24), time.monotonic()
    frame = dict(directory=os.path.abspath(os.fspath(directory)), browser=entry["id"],
                 instance=entry["browser_instance"], tab=target["targetId"],
                 address=hashlib.sha256(target.get("url", "").encode()).digest(), viewport=viewport,
                 lease=control["expires_at"], expires=now + FRAME_TTL)
    with _frames_lock:
        for key in [key for key, value in _frames.items() if value["expires"] <= now]:
            _frames.pop(key, None)
        while len(_frames) >= MAX_FRAMES:
            _frames.pop(next(iter(_frames)))
        _frames[token] = frame
    return token


def forget_frames(directory):
    """Release only ephemeral input receipts, never a browser or agent session."""
    directory = os.path.abspath(os.fspath(directory))
    with _frames_lock:
        for key in [key for key, value in _frames.items() if value["directory"] == directory]:
            _frames.pop(key, None)


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _lock_assistance(directory, entry):
    """Auth teardown waits for this shared lock before automation resumes."""
    descriptor, fd = None, None
    try:
        descriptor = open_private_directory(directory)
        name = entry["id"] + ".assist"
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("Invalid assistance lease")
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Assistance lease changed")
        return fd
    except (OSError, ValueError):
        if fd is not None:
            os.close(fd)
        raise BrowserInputError(409, "This agent is no longer waiting for sign-in help. Refresh its browser view.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def validate_input(data):
    """Reject extra commands, URLs and arbitrary CDP parameters before attachment."""
    if not isinstance(data, dict):
        raise BrowserInputError(400, "Choose a browser action.")
    base = {"id", "browser", "tab", "frame_id", "viewport", "action"}
    fields = {"click": {"x", "y"}, "type": {"text"}, "key": {"key", "shift"},
              "scroll": {"x", "y", "deltaX", "deltaY"}, "reload": set(), "sign-in": set()}
    action = data.get("action")
    if not isinstance(action, str) or action not in fields or set(data) - base - fields[action] or not base.issubset(data):
        raise BrowserInputError(400, "Choose a supported browser action.")
    if any(not isinstance(data[key], str) or not data[key] or len(data[key]) > 128
           for key in ("id", "browser", "tab", "frame_id")):
        raise BrowserInputError(400, "Choose the browser and tab shown in this view.")
    viewport = data["viewport"]
    if (not isinstance(viewport, dict) or set(viewport) != {"width", "height"}
            or any(not _number(viewport[key]) or not 0 < viewport[key] <= 100000 for key in viewport)):
        raise BrowserInputError(400, "Refresh the browser image before using its controls.")
    if action in ("click", "scroll") and any(not _number(data.get(key)) or not 0 <= data[key] < viewport[size]
                                             for key, size in (("x", "width"), ("y", "height"))):
        raise BrowserInputError(400, "Choose a point inside the browser image.")
    if action == "scroll" and any(not _number(data.get(key)) or abs(data[key]) > 1200 for key in ("deltaX", "deltaY")):
        raise BrowserInputError(400, "Scroll a smaller distance inside the browser view.")
    if action == "type":
        text = data.get("text")
        if (not isinstance(text, str) or not 0 < len(text) <= 4096 or "\x00" in text
                or any(0xD800 <= ord(character) <= 0xDFFF for character in text)):
            raise BrowserInputError(400, "Enter between 1 and 4096 characters.")
    if action == "key" and (not isinstance(data.get("key"), str) or data["key"] not in _KEYS
                             or not isinstance(data.get("shift", False), bool)):
        raise BrowserInputError(400, "Choose a supported browser key.")
    return data


class _BoundedWebSocket(websocket.WebSocket):
    """Bound a frame before allocation and every socket read by one deadline."""
    def __init__(self, *, deadline, **kwargs):
        self.deadline = deadline
        super().__init__(**kwargs)
        read_length = self.frame_buffer.recv_length

        def bounded_length():
            read_length()
            if self.frame_buffer.length is None or self.frame_buffer.length > MAX_MESSAGE:
                raise PreviewUnavailable("Browser image is too large")
        self.frame_buffer.recv_length = bounded_length

    def _recv(self, size):
        self.settimeout(remaining(self.deadline))
        return super()._recv(size)


class _CDP:
    def __init__(self, endpoint: str, instance: str, deadline: float):
        host, port, authority = endpoint_parts(endpoint)
        self.deadline, self.sequence = deadline, 0
        connection = socket.create_connection((host, port), timeout=remaining(deadline))
        try:
            # A supplied direct socket bypasses HTTP_PROXY/ALL_PROXY, and the
            # instance-specific browser path cannot attach to a reused port.
            self.socket = websocket.create_connection(
                f"ws://{authority}/devtools/browser/{instance}", socket=connection,
                timeout=remaining(deadline), deadline=deadline, class_=_BoundedWebSocket,
                suppress_origin=True, redirect_limit=0,
            )
        except Exception:
            connection.close()
            raise

    def close(self):
        self.socket.shutdown()

    def _message(self):
        fragments, size = [], 0
        for _ in range(128):
            remaining(self.deadline)
            frame = self.socket.recv_frame()
            if frame.opcode == websocket.ABNF.OPCODE_PING:
                self.socket.pong(frame.data)
                continue
            if frame.opcode == websocket.ABNF.OPCODE_PONG:
                continue
            if frame.opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_CONT):
                raise PreviewUnavailable("Browser preview connection closed")
            size += len(frame.data)
            if size > MAX_MESSAGE:
                raise PreviewUnavailable("Browser image is too large")
            fragments.append(frame.data)
            if frame.fin:
                value = json.loads(b"".join(fragments))
                if not isinstance(value, dict):
                    raise PreviewUnavailable("Invalid browser response")
                return value
        raise PreviewUnavailable("Browser response is too fragmented")

    def call(self, method: str, params=None, session_id: str = ""):
        self.sequence += 1
        request = dict(id=self.sequence, method=method, params=params or {})
        if session_id:
            request["sessionId"] = session_id
        self.socket.settimeout(remaining(self.deadline))
        self.socket.send(json.dumps(request))
        for _ in range(64):
            value = self._message()
            if value.get("id") == self.sequence:
                if "error" in value or not isinstance(value.get("result"), dict):
                    raise PreviewUnavailable("Browser page is not available")
                return value["result"]
        raise PreviewUnavailable("Browser response is unavailable")


def _manifests(directory):
    descriptor = open_private_directory(directory)
    entries = []
    try:
        for name in os.listdir(descriptor)[:MAX_MANIFESTS * 2]:
            if not MANIFEST_NAME.fullmatch(name):
                continue
            try:
                file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
                with os.fdopen(file_descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                            or info.st_mode & 0o077 or info.st_uid != os.getuid()):
                        continue
                    value = json.loads(stream.read(4097))
                if not isinstance(value, dict) or value.get("version") != 1 or value.get("id") != name[:-5]:
                    continue
                endpoint_parts(value["endpoint"])
                if not isinstance(value["browser_instance"], str):
                    continue
                if value["browser_instance"] and str(uuid.UUID(value["browser_instance"])) != value["browser_instance"].lower():
                    continue
                value["label"] = value.get("label") if value.get("label") in ("Chrome", "Edge") else "Browser"
                entries.append((info.st_mtime_ns, value))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
    finally:
        os.close(descriptor)
    return [value for _, value in sorted(entries, key=lambda item: item[0], reverse=True)[:MAX_MANIFESTS]]


def _tab(target):
    if not isinstance(target, dict) or target.get("type") != "page":
        return None
    identifier, address = target.get("targetId"), target.get("url", "")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 128 or not isinstance(address, str):
        return None
    try:
        parsed = urlsplit(address)
        if parsed.scheme not in ("http", "https") and address != "about:blank":
            return None
        site = parsed.hostname or "Blank page"
        if len(site) > 255:
            return None
    except ValueError:
        return None
    title = str(target.get("title") or site)
    # Titles sometimes consist of the full URL. Display only its host, never
    # URL credentials, OAuth query strings, fragments or debugger addresses.
    def host_only(match):
        try:
            return urlsplit(match.group()).hostname or "Page"
        except ValueError:
            return "Page"
    title = re.sub(r"https?://[^\s<>\"']+", host_only, title)
    title = " ".join(title.split())[:240]
    return dict(id=identifier, title=title or site, site=site)


def _browser_inventory(entry: dict, deadline: float) -> dict:
    """Read only target metadata from an instance whose identity still matches."""
    result = dict(id=entry["id"], label=entry["label"], state="unavailable", tabs=[],
                  message="This browser has closed or could not be reached. Try refreshing its details.")
    client = None
    try:
        remaining(deadline)
        if not entry["browser_instance"]:
            return dict(result, message="A verified preview is not available for this browser.")
        current = browser_instance(request_json(entry["endpoint"], "/json/version", deadline), entry["endpoint"])
        if current != entry["browser_instance"]:
            return result
        client = _CDP(entry["endpoint"], current, deadline)
        targets = client.call("Target.getTargets").get("targetInfos", [])
        if not isinstance(targets, list):
            return result
        tabs = [tab for target in targets[:128] if (tab := _tab(target)) is not None]
        return dict(result, state="ready" if tabs else "waiting", tabs=tabs,
                    message="" if tabs else "This browser has no viewable tabs open yet.")
    except Exception:
        # Browser diagnostics can contain private URLs and debugging addresses.
        return result
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def inventory_many(directories: dict) -> dict:
    """List registered browsers across runs within one budget and four workers.

    Directory keys are opaque run IDs supplied by Runner, never client paths.
    Slow browsers cannot multiply the endpoint's deadline or block run control.
    This path never captures a screenshot or attaches to a page session.
    """
    deadline = time.monotonic() + TOTAL_TIMEOUT
    results, work = {}, []
    for run_id, directory in directories.items():
        result = dict(state="waiting", message="This agent has not opened a browser yet.", browsers=[])
        results[run_id] = result
        try:
            entries = _manifests(directory)
        except (OSError, ValueError, TypeError):
            result.update(state="unavailable", message="Browser details for this run are not available.")
            continue
        for entry in entries:
            index = len(result["browsers"])
            result["browsers"].append(dict(id=entry["id"], label=entry["label"], state="waiting", tabs=[],
                                            message="Browser details are still loading. Refresh to try again."))
            work.append((run_id, index, entry))
    if work:
        # Give each run a turn before reading more browsers from the same run.
        # A workflow with many stale registrations must not starve another agent.
        work.sort(key=lambda item: item[1])
        pool = ThreadPoolExecutor(max_workers=MAX_INVENTORY_WORKERS, thread_name_prefix="browser-inventory")
        pending = {}
        try:
            for run_id, index, entry in work:
                if time.monotonic() >= deadline:
                    break
                pending[pool.submit(_browser_inventory, entry, deadline)] = (run_id, index)
            done, _ = wait(pending, timeout=max(0, deadline - time.monotonic()))
            for future in done:
                run_id, index = pending[future]
                try:
                    results[run_id]["browsers"][index] = future.result()
                except Exception:
                    results[run_id]["browsers"][index].update(
                        state="unavailable", message="This browser's details are temporarily unavailable.")
        finally:
            # Queued work must not keep running after the response budget ends.
            # Running calls have the same absolute socket deadline and never
            # mutate the returned dictionaries after they finish.
            pool.shutdown(wait=False, cancel_futures=True)
    for result in results.values():
        browsers = result["browsers"]
        if not browsers:
            continue
        ready = sum(browser["state"] == "ready" for browser in browsers)
        if ready:
            result.update(state="ready", message=f"{ready} browser{'s' if ready != 1 else ''} ready to watch.")
        elif any(browser["state"] == "waiting" for browser in browsers):
            result.update(state="waiting", message="Waiting for browser tabs to become available.")
        else:
            result.update(state="unavailable", message="These browsers are not available right now. The agent can keep working.")
    return results


def inventory(directory) -> dict:
    """Read one registry, primarily for integrations outside Runner."""
    return inventory_many({"run": directory})["run"]


def _browser_open(entry: dict, deadline: float) -> str:
    """Verify the registered Chrome instance without reading pages or attaching."""
    try:
        remaining(deadline)
        if not entry["browser_instance"]:
            return "unavailable"
        current = browser_instance(request_json(entry["endpoint"], "/json/version", deadline), entry["endpoint"])
        return "open" if current == entry["browser_instance"] else "closed"
    except ConnectionRefusedError:
        return "closed"
    except Exception:
        return "unavailable"


def count_many(directories: dict) -> dict:
    """Count live browser instances across runs; never inspect tabs or images.

    A private registry is only evidence of registration. Each distinct browser
    identity must still answer at its original local endpoint to be counted.
    Unknown or unfinished checks are reported instead of claiming an exact zero.
    """
    deadline = time.monotonic() + TOTAL_TIMEOUT
    results, statuses, work = {}, {}, []
    for run_id, directory in directories.items():
        results[run_id] = dict(open_browser_count=0, count_status="ready")
        statuses[run_id] = []
        try:
            entries = _manifests(directory)
        except (OSError, ValueError, TypeError):
            results[run_id]["count_status"] = "unavailable"
            continue
        seen = set()
        for entry in entries:
            identity = entry["browser_instance"]
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            index = len(statuses[run_id])
            statuses[run_id].append("checking")
            work.append((run_id, index, entry))
    if work:
        # A run with stale registrations cannot occupy every worker ahead of
        # another run. All calls share one deadline and bounded concurrency.
        work.sort(key=lambda item: item[1])
        pool = ThreadPoolExecutor(max_workers=MAX_INVENTORY_WORKERS, thread_name_prefix="browser-count")
        pending = {}
        try:
            for run_id, index, entry in work:
                if time.monotonic() >= deadline:
                    break
                pending[pool.submit(_browser_open, entry, deadline)] = (run_id, index)
            done, _ = wait(pending, timeout=max(0, deadline - time.monotonic()))
            for future in done:
                run_id, index = pending[future]
                try:
                    statuses[run_id][index] = future.result()
                except Exception:
                    statuses[run_id][index] = "unavailable"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    for run_id, values in statuses.items():
        result = results[run_id]
        result["open_browser_count"] = values.count("open")
        if "unavailable" in values:
            result["count_status"] = "unavailable"
        elif "checking" in values:
            result["count_status"] = "checking"
    return results


def _viewport(client, session):
    layout = client.call("Page.getLayoutMetrics", session_id=session)
    viewport = layout.get("cssVisualViewport") or layout.get("cssLayoutViewport") or {}
    width, height = viewport.get("clientWidth"), viewport.get("clientHeight")
    x, y = viewport.get("pageX", 0), viewport.get("pageY", 0)
    if not all(_number(value) for value in (width, height, x, y)) or not (0 < width <= 100000 and 0 < height <= 100000):
        raise PreviewUnavailable("Browser page size is not available")
    return dict(width=width, height=min(height, 1800), x=x, y=y)


def _capture(client, tab_id):
    attached = client.call("Target.attachToTarget", {"targetId": tab_id, "flatten": True})
    session = attached.get("sessionId")
    if not isinstance(session, str) or not session or len(session) > 256:
        raise PreviewUnavailable("Browser page is not available")
    try:
        viewport = _viewport(client, session)
        width, height, x, y = (viewport[key] for key in ("width", "height", "x", "y"))
        captured = client.call("Page.captureScreenshot", {
            "format": "jpeg", "quality": 60, "fromSurface": True,
            "captureBeyondViewport": False, "optimizeForSpeed": True,
            "clip": {"x": x, "y": y, "width": width, "height": min(height, 1800),
                     "scale": min(0.7, 1280 / width)},
        }, session_id=session)
        encoded = captured.get("data")
        if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE * 4 // 3 + 4:
            raise PreviewUnavailable("Browser image is too large")
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) > MAX_IMAGE or not decoded.startswith(b"\xff\xd8") or not decoded.endswith(b"\xff\xd9"):
            raise PreviewUnavailable("Browser image is unavailable")
        return "data:image/jpeg;base64," + encoded, viewport
    finally:
        # Detach only this temporary viewer session. It never changes or closes
        # the page, Selenium session, or Playwright MCP's connection.
        try:
            client.call("Target.detachFromTarget", {"sessionId": session})
        except Exception:
            pass


def snapshot(directory, browser_id: str = "", tab_id: str = "") -> dict:
    """No screenshots are persisted; caller supplies only its trusted run path."""
    deadline = time.monotonic() + TOTAL_TIMEOUT
    result = dict(state="waiting", message="Waiting for this agent to open a browser.", browsers=[], tabs=[])
    if not isinstance(browser_id, str) or not isinstance(tab_id, str) or len(browser_id) > 128 or len(tab_id) > 128:
        return dict(result, state="unavailable", message="Choose a browser and tab from this run.")
    try:
        entries = _manifests(directory)
    except (OSError, ValueError, TypeError):
        return dict(result, state="unavailable", message="This run's browser preview is no longer available.")
    result["browsers"] = [dict(id=entry["id"], label=entry["label"]) for entry in entries]
    if not entries:
        return result
    candidates = [entry for entry in entries if entry["id"] == browser_id] if browser_id else entries
    if not candidates:
        return dict(result, state="unavailable", message="This browser is no longer available. Choose another browser from this run.")
    for entry in candidates:
        client = None
        try:
            if not entry["browser_instance"]:
                raise PreviewUnavailable("The browser identity could not be verified")
            current = browser_instance(request_json(entry["endpoint"], "/json/version", deadline), entry["endpoint"])
            if current != entry["browser_instance"]:
                raise PreviewUnavailable("The registered browser has closed")
            client = _CDP(entry["endpoint"], current, deadline)
            targets = client.call("Target.getTargets").get("targetInfos", [])
            if not isinstance(targets, list):
                raise PreviewUnavailable("Browser tabs are unavailable")
            tabs = [tab for target in targets[:128] if (tab := _tab(target)) is not None]
            result.update(browser_id=entry["id"], tabs=tabs)
            if not tabs:
                return dict(result, state="waiting", message="This browser has no viewable page open yet.")
            selected = next((tab for tab in tabs if tab["id"] == tab_id), None) if tab_id else tabs[0]
            if selected is None:
                return dict(result, state="waiting", message="That tab has closed. Choose another tab to keep watching.")
            result.update(tab_id=selected["id"], title=selected["title"], site=selected["site"])
            image, viewport = _capture(client, selected["id"])
            control = _assistance(directory, entry)
            target = next(target for target in targets if target.get("targetId") == selected["id"])
            frame_id = _remember_frame(directory, entry, target, viewport, control) if control["enabled"] else ""
            result.update(state="ready", image=image, frame_id=frame_id, control=control,
                          viewport={key: viewport[key] for key in ("width", "height")},
                          captured_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"))
            result.pop("message", None)
            return result
        except Exception:
            if browser_id or time.monotonic() >= deadline:
                break
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    return dict(result, state="unavailable", message="The browser preview is temporarily unavailable. The agent can continue working.")


def control(directory, data, ensure_allowed=lambda: None):
    """Send one explicit input to an exact waiting browser; never close it."""
    validate_input(data)
    deadline = time.monotonic() + TOTAL_TIMEOUT
    with _frames_lock:
        frame = _frames.get(data["frame_id"])
    if (not frame or frame["expires"] <= time.monotonic()
            or frame["directory"] != os.path.abspath(os.fspath(directory))
            or frame["browser"] != data["browser"] or frame["tab"] != data["tab"]
            or any(data["viewport"][key] != frame["viewport"][key] for key in ("width", "height"))):
        raise BrowserInputError(409, "This browser image is out of date. Refresh it before trying again.")
    client, session, lease_fd = None, "", None
    try:
        ensure_allowed()
        entry = next((value for value in _manifests(directory) if value["id"] == data["browser"]), None)
        if not entry or not entry["browser_instance"] or entry["browser_instance"] != frame["instance"]:
            raise BrowserInputError(409, "This browser is no longer available. Open its current view from Activity.")
        lease_fd = _lock_assistance(directory, entry)

        def permitted():
            ensure_allowed()
            lease = _assistance(directory, entry)
            if not lease["enabled"] or lease["expires_at"] != frame["lease"]:
                raise BrowserInputError(409, "This agent is no longer waiting for sign-in help. Browser controls are unavailable.")
            if frame["expires"] <= time.monotonic():
                raise BrowserInputError(409, "Refresh the browser image before trying again.")

        permitted()
        current = browser_instance(request_json(entry["endpoint"], "/json/version", deadline), entry["endpoint"])
        if current != frame["instance"]:
            raise BrowserInputError(409, "This browser has closed. Open its current view from Activity.")
        client = _CDP(entry["endpoint"], current, deadline)
        targets = client.call("Target.getTargets").get("targetInfos", [])
        target = next((value for value in targets if isinstance(value, dict) and value.get("targetId") == data["tab"]), None)
        if not _tab(target) or target.get("targetId") != data["tab"] or hashlib.sha256(target.get("url", "").encode()).digest() != frame["address"]:
            raise BrowserInputError(409, "This tab changed or closed. Refresh the browser image before trying again.")
        session = client.call("Target.attachToTarget", {"targetId": data["tab"], "flatten": True}).get("sessionId")
        if not isinstance(session, str) or not session or len(session) > 256:
            raise PreviewUnavailable("Browser page is unavailable")
        viewport = _viewport(client, session)
        if any(abs(viewport[key] - frame["viewport"][key]) > 0.5 for key in viewport):
            raise BrowserInputError(409, "This page moved or resized. Refresh the browser image before trying again.")
        # Recheck the target after attaching: a live agent/page can navigate
        # between metadata collection and the selected page's layout read.
        target = client.call("Target.getTargetInfo", {"targetId": data["tab"]}).get("targetInfo")
        if not _tab(target) or target.get("targetId") != data["tab"] or hashlib.sha256(target.get("url", "").encode()).digest() != frame["address"]:
            raise BrowserInputError(409, "This tab changed. Refresh the browser image before trying again.")

        def send(method, params):
            permitted()
            client.call(method, params, session_id=session)

        action = data["action"]
        if action == "click":
            point = dict(x=data["x"], y=data["y"], button="left", clickCount=1)
            send("Input.dispatchMouseEvent", dict(point, type="mousePressed", buttons=1))
            send("Input.dispatchMouseEvent", dict(point, type="mouseReleased", buttons=0))
        elif action == "type":
            send("Input.insertText", {"text": data["text"]})
        elif action == "key":
            key = data["key"]
            event = dict(key=key, code=key, windowsVirtualKeyCode=_KEYS[key],
                         modifiers=8 if data.get("shift") else 0)
            # Enter needs its character event for native form/button activation;
            # navigation keys use rawKeyDown, like Chrome's own keyboard driver.
            down = dict(event, type="keyDown", text="\r", unmodifiedText="\r") if key == "Enter" else dict(event, type="rawKeyDown")
            send("Input.dispatchKeyEvent", down)
            send("Input.dispatchKeyEvent", dict(event, type="keyUp"))
        elif action == "scroll":
            send("Input.dispatchMouseEvent", dict(type="mouseWheel", x=data["x"], y=data["y"],
                                                 deltaX=data["deltaX"], deltaY=data["deltaY"]))
        elif action == "reload":
            send("Page.reload", {"ignoreCache": False})
        elif action == "sign-in":
            send("Page.navigate", {"url": NAUKRI_SIGN_IN})
        return {"ok": True}
    except BrowserInputError:
        raise
    except Exception:
        # No typed text, remote debugging addresses, URLs or page diagnostics
        # are reflected into logs or a response. Inputs are never auto-retried.
        raise BrowserInputError(409, "The browser could not confirm this action. Refresh the view before trying again.") from None
    finally:
        if client is not None:
            if session:
                try:
                    client.call("Target.detachFromTarget", {"sessionId": session})
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass
        if lease_fd is not None:
            os.close(lease_fd)
