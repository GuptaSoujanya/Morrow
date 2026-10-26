"""The bot engine behind the dashboard: runs the bots, shows what waits for you, and holds the course.

It only listens on 127.0.0.1. Other web pages can't use it: every request has to
name this computer as its Host, and anything that changes something has to be a
JSON request from this site itself.
"""
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import os
import secrets
import sqlite3
import subprocess
import time
from dataclasses import replace
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit, quote

from . import state
from .state import Command
from .runner import BatchCommand, Runner


ANSWER_MODES = [
    ("", "As set in .env"),
    ("auto", "auto: submit answers grounded in your files"),
    ("propose", "propose: log the answers, submit none"),
    ("ask", "ask: skip LLM answers, leave them for you"),
]

LINKEDIN_CHOICES = [
    ("dry-run", "Draft a post (nothing saved)"),
    ("propose", "Save a draft, send it on Telegram"),
    ("post", "Publish the draft on LinkedIn"),
    ("if-due", "Do today's scheduled step"),
]

for _suffix, _type in ((".md", "text/markdown"), (".log", "text/plain"), (".jsonl", "text/plain")):
    mimetypes.add_type(_type, _suffix)


def long_date(day: dt.date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y}"


# --- what each button runs ----------------------------------------------------------------


def _on(options: Dict[str, Any], key: str) -> bool:
    return bool(options.get(key))


def _text(options: Dict[str, Any], key: str) -> str:
    value = options.get(key)
    return str(value).strip() if value is not None else ""


def _limit(options: Dict[str, Any]) -> Optional[int]:
    text = _text(options, "limit")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError("the limit has to be a whole number") from None


def _resume(options: Dict[str, Any], save: bool) -> Command:
    pasted = str(options.get("jd_text") or "")
    if pasted.strip():
        jd_file = str(state.save_job_description(pasted)) if save else "data/logs/jd/<pasted text>.txt"
    else:
        jd_file = _text(options, "jd_file")
    return state.resume_command(
        jd_file=jd_file,
        title=_text(options, "title"),
        company=_text(options, "company"),
        headless=_on(options, "headless"),
        must_exist=save or not pasted.strip(),
    )


ACTIONS: Dict[str, Callable[[Dict[str, Any], bool], Command]] = {
    "naukri": lambda o, save: state.naukri_command(
        dry_run=_on(o, "dry_run"),
        headless=_on(o, "headless"),
        limit=_limit(o),
        answer_mode=_text(o, "answer_mode"),
        early_access=_on(o, "early_access"),
        early_access_only=_on(o, "early_access_only"),
        keywords=_text(o, "keywords"),
        location=_text(o, "location"),
    ),
    "assist": lambda o, save: state.assist_command(dry_run=_on(o, "dry_run")),
    "external": lambda o, save: state.external_command(
        url=_text(o, "url"),
        title=_text(o, "title"),
        company=_text(o, "company"),
        dry_run=_on(o, "dry_run"),
        no_tailor=_on(o, "no_tailor"),
        headless=_on(o, "headless"),
    ),
    "profile": lambda o, save: state.profile_command(
        dry_run=_on(o, "dry_run"), if_due=_on(o, "if_due"), headless=_on(o, "headless")
    ),
    "profile_status": lambda o, save: state.script("Profile schedule status", "profile_update_status.sh"),
    "profile_install": lambda o, save: state.script("Turn on the profile schedule", "install_profile_updater.sh"),
    "linkedin": lambda o, save: state.linkedin_command(
        mode=_text(o, "mode") or "dry-run", draft=_text(o, "draft"), headless=_on(o, "headless")
    ),
    "linkedin_status": lambda o, save: state.script("LinkedIn schedule status", "linkedin_status.sh"),
    "linkedin_install": lambda o, save: state.script("Turn on the LinkedIn schedule", "install_linkedin_poster.sh"),
    "resume": _resume,
    "report": lambda o, save: state.report_command(day=_text(o, "day")),
    "google": lambda o, save: state.script("Sign in to Google", "google_login.sh"),
    "install": lambda o, save: state.py("Install requirements", "-m", "pip", "install", "-r", "requirements.txt"),
    "tests": lambda o, save: state.py("Run the tests", "-m", "pytest", "-q"),
}


BROWSER_ACTIONS = frozenset({"naukri", "boards", "profile", "external", "linkedin", "linkedin_profile", "cold_email", "resume", "assist", "pipeline"})


def build(action: str, options: Dict[str, Any], save: bool = False) -> Command:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    mode = options.get("browser_mode")
    if "browser_mode" in options:
        if mode not in ("background", "visible"):
            raise ValueError("Choose Visible browser or Background job, then try again.")
        if action not in BROWSER_ACTIONS:
            raise ValueError("Browser mode is not available for this action.")
    if action in BROWSER_ACTIONS:
        # Open the agent's normal browser unless background work was chosen.
        # Honour an explicit legacy headless flag when no mode is supplied;
        # a modern mode selection takes precedence over saved legacy flags.
        if "browser_mode" not in options:
            mode = "background" if options.get("headless") is True else "visible"
        options = {**options, "browser_mode": mode, "headless": mode == "background"}
    command = ACTIONS[action](options, save)
    # Explicit UI choices must also override DRY_RUN inherited from .env.
    # Only this known option is mapped; requests cannot supply environment keys.
    if isinstance(options.get("dry_run"), bool):
        command = replace(command, env=(*command.env, ("DRY_RUN", "true" if options["dry_run"] else "false")))
    if action in BROWSER_ACTIONS:
        # Apply the choice to commands without a --headless switch and override
        # inherited .env values. BACKGROUND is an older off-screen browser mode;
        # explicit headless mode is used for background jobs instead.
        command = replace(command, env=(*command.env,
                                       ("HEADLESS", "true" if options["headless"] else "false"),
                                       ("BACKGROUND", "false")))
    return command


def batch_requests(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Validate the request envelope before preparing any selected command."""
    runs = data.get("runs")
    if not isinstance(runs, list) or not 1 <= len(runs) <= Runner.MAX_ACTIVE:
        raise ValueError(f"Select between 1 and {Runner.MAX_ACTIVE} agents to run together.")
    keys = set()
    for entry in runs:
        if not isinstance(entry, dict):
            raise ValueError("Each selected agent must include a key, action, and options object.")
        key, action, options = entry.get("key"), entry.get("action"), entry.get("options")
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise ValueError("Each selected agent needs a non-empty key of at most 128 characters.")
        if key in keys:
            raise ValueError("Each selected agent must have a unique key. Remove the duplicate selection.")
        keys.add(key)
        if not isinstance(action, str) or not action.strip() or len(action) > 128:
            raise ValueError("Each selected agent needs a valid action.")
        if not isinstance(options, dict):
            raise ValueError("Each selected agent's options must be a JSON object.")
    return runs


def build_batch(requests: List[Dict[str, Any]], save: bool = False) -> List[BatchCommand]:
    selections = []
    for entry in requests:
        key, action, options = entry["key"], entry["action"], entry["options"]
        try:
            command = build(action, options, save=save)
            day = state.parse_day(_text(options, "day")).isoformat() if action == "report" else ""
            selections.append(BatchCommand(key, action, command, day))
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            selections.append(BatchCommand(key, action, error=str(exc)))
    return selections


# --- what the page reads -----------------------------------------------------------------------


def files() -> Dict[str, Path]:
    """The files you can edit from the page."""
    return {
        "answers": state.ANSWERS,
        "profile": state.PROFILE,
        "company_sites": state.COMPANY_SITES,
        "env": state.APPLY / ".env",
    }


def shown_path(path: Path) -> str:
    return str(path.relative_to(state.APPLY)) if state.APPLY in path.parents else str(path)


def plan_json(plan: Optional[state.PlanDay]) -> Optional[Dict[str, Any]]:
    if plan is None:
        return None
    return {
        "path": plan.module.path,
        "route": plan.module.route,
        "title": plan.module.title,
        "track": plan.module.track,
        "number": plan.number,
        "total": plan.total,
        "revising": plan.revising,
        "tomorrow": {"path": plan.tomorrow.path, "route": plan.tomorrow.route, "title": plan.tomorrow.title},
    }


def course_json() -> Dict[str, Any]:
    modules = state.course_modules(state.COURSE)
    plan = state.todays_module(modules, course=state.COURSE)
    read = state.studied()
    tracks: List[Dict[str, Any]] = []
    for module in modules:
        if not tracks or tracks[-1]["name"] != module.track:
            tracks.append({"name": module.track, "modules": []})
        tracks[-1]["modules"].append({
            "path": module.path,
            "route": module.route,
            "title": module.title,
            "read": module.path in read,
            "today": bool(plan and plan.module == module),
        })
    return {
        "today": plan_json(plan),
        "read": len(read & {m.path for m in modules}),
        "total": len(modules),
        "tracks": tracks,
    }


def status_json(runner: Runner) -> Dict[str, Any]:
    today = dt.date.today()
    course = course_json()
    return {
        "greeting": state.greeting(),
        "name": state.first_name(state.PROFILE),
        "date": today.isoformat(),
        "date_long": long_date(today),
        "report": {"ready": state.report_path().is_file(), "days": state.report_days()[:60]},
        "questions": [{"line": line, "questions": qs} for line, qs in state.unanswered_questions(state.ANSWERS)],
        "facts": [{"line": line, "key": key} for line, key in state.blank_facts(state.PROFILE)],
        "sites": state.company_sites(state.COMPANY_SITES),
        "study": {"today": course["today"], "read": course["read"], "total": course["total"]},
        "run": runner.snapshot(),
    }


# Beyond this a date before year 1 overflows; 0 already means "since the first run".
MAX_OVERVIEW_DAYS = 36500


def overview_json(days_text: str) -> Dict[str, Any]:
    try:
        days = int(days_text or 14)
    except ValueError:
        raise ValueError(f"days must be a whole number, not {days_text!r}") from None
    if days > MAX_OVERVIEW_DAYS:
        raise ValueError(f"days can be at most {MAX_OVERVIEW_DAYS}")
    return state.overview(days)


def report_json(day_text: str) -> Dict[str, Any]:
    day = state.parse_day(day_text)
    exists = state.report_path(day).is_file()
    return {
        "day": day.isoformat(),
        "title": f"Report for {long_date(day)}",
        "exists": exists,
        "html": state.report_html(day) if exists else "",
    }


def file_json(name: str) -> Dict[str, Any]:
    paths = files()
    if name not in paths:
        raise ValueError(f"unknown file {name!r}")
    path = paths[name]
    line = None
    if name == "answers":
        waiting = state.unanswered_questions(path)
        line = waiting[0][0] if waiting else None
    elif name == "profile":
        blank = state.blank_facts(path)
        line = blank[0][0] if blank else None
    return {
        "name": name,
        "path": shown_path(path),
        "exists": path.is_file(),
        "text": path.read_text(encoding="utf-8") if path.is_file() else "",
        "line": line,
    }


def meta_json() -> Dict[str, Any]:
    return {
        "answer_modes": [{"value": v, "label": label} for v, label in ANSWER_MODES],
        "linkedin_modes": [{"value": v, "label": label} for v, label in LINKEDIN_CHOICES],
        "files": {name: shown_path(path) for name, path in files().items()},
        "apply": str(state.APPLY),
        "course": "/course/",
    }


def inside(root: Path, relative: str) -> Optional[Path]:
    """The file under root the URL names, or None for anything outside it or any dot-file."""
    parts = [p for p in relative.split("/") if p]
    if any(p.startswith(".") for p in parts):
        return None
    root = root.resolve()
    path = root.joinpath(*parts).resolve() if parts else root
    if path != root and root not in path.parents:
        return None
    return path


def open_outside(target: str) -> None:
    """Open a folder in Finder, a file in its app, or a link in the browser."""
    subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- the server -------------------------------------------------------------------------------------


MAX_BODY_BYTES = 10 * 1024 * 1024
EVENT_HEARTBEAT_S = 10.0
EVENT_AUTH_CHECK_S = 10.0


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server: "ControlServer"
    server_version = "jobhunt"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    # --- checks ---

    def own_hosts(self) -> List[str]:
        port = self.server.server_address[1]
        return [f"127.0.0.1:{port}", f"localhost:{port}"]

    def host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.own_hosts()

    def change_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is not None and origin not in [f"http://{h}" for h in self.own_hosts()]:
            return False
        return self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json"

    # --- replies ---

    def send(self, status: HTTPStatus, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if urlsplit(self.path).path in ("/api/run/browser", "/api/run/browsers", "/api/run/browser/input", "/api/run/answers") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def error(self, status: HTTPStatus, message: str) -> None:
        self.json({"error": message}, status)

    def file(self, path: Optional[Path]) -> None:
        if path is not None and path.is_dir():
            path = path / "index.html"
        if path is None or not path.is_file():
            self.error(HTTPStatus.NOT_FOUND, "not found")
            return
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "image/svg+xml"):
            kind += "; charset=utf-8"
        self.send(HTTPStatus.OK, path.read_bytes(), kind)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.MOVED_PERMANENTLY)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length is not a number") from None
        if not 0 <= length <= MAX_BODY_BYTES:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Content-Length must be 0 to {MAX_BODY_BYTES}")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "the request is not JSON") from None
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "the request is not a JSON object")
        return data

    # --- routes ---

    def do_HEAD(self) -> None:
        self.do_GET()

    def stream_authorized(self) -> bool:
        """Long-lived streams must also notice logout/session expiry.

        The dashboard checks account access before delegating here; repeat that
        owner check periodically without writing a JSON response mid-stream.
        """
        bridge = getattr(self.server, "account_bridge", None)
        if bridge is None:
            return True
        try:
            return bridge.is_owner(self, bridge.identity(self))
        except Exception:
            # Authorization service unavailable: close rather than expose more output.
            return False

    def events(self, query: Dict[str, str]) -> None:
        origin = self.headers.get("Origin")
        if ((origin is not None and origin not in [f"http://{host}" for host in self.own_hosts()])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.error(HTTPStatus.FORBIDDEN, "only this site can read live activity")
            return
        runner = self.server.runner
        cursor = self.headers.get("Last-Event-ID", "")
        epoch = query.get("epoch")
        after = int(query.get("after") or 0)
        if cursor:
            epoch, separator, number = cursor.rpartition(":")
            if not separator:
                raise ValueError("The activity cursor is invalid. Reconnect to start again.")
            after = int(number)
        if after < 0:
            raise ValueError("The activity cursor must be zero or greater.")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command == "HEAD":
            return
        # A disconnected or stalled browser must not hold a writer indefinitely.
        self.connection.settimeout(15)
        checked = time.monotonic()
        snapshot = runner.snapshot(after, epoch)
        try:
            while not runner.closed:
                if time.monotonic() - checked >= EVENT_AUTH_CHECK_S:
                    if not self.stream_authorized():
                        self.wfile.write(b"event: access-revoked\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                    checked = time.monotonic()
                payload = json.dumps(snapshot, separators=(",", ":"))
                event = f"id: {snapshot['epoch']}:{snapshot['next']}\nevent: run\ndata: {payload}\n\n"
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()
                # Coalesce noisy output so a busy agent cannot flood the UI.
                with runner.changed:
                    runner.changed.wait_for(lambda: runner.closed, timeout=0.1)
                snapshot = runner.wait_snapshot(snapshot["revision"], snapshot["next"], snapshot["epoch"],
                                                timeout=EVENT_HEARTBEAT_S)
        except (OSError, ConnectionError):
            return

    def browser_preview(self, query: Dict[str, str]) -> None:
        origin = self.headers.get("Origin")
        if ((origin is not None and origin not in [f"http://{host}" for host in self.own_hosts()])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            return self.error(HTTPStatus.FORBIDDEN, "Only this dashboard can view an agent’s browser.")
        run_id = query.get("id", "")
        if not run_id or len(run_id) > 128 or any(len(query.get(key, "")) > 256 for key in ("browser", "tab")):
            return self.error(HTTPStatus.BAD_REQUEST, "Choose a current agent run in Activity.")
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to view this browser.")
        try:
            frame = self.server.runner.browser_snapshot(run_id, query.get("browser", ""), query.get("tab", ""))
        except KeyError:
            return self.error(HTTPStatus.NOT_FOUND, "This run is no longer available. Choose a current run in Activity.")
        # A session can expire while a frame is being captured. Never deliver a
        # screenshot after account access has been revoked.
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to view this browser.")
        self.json(frame)

    def browser_inventory(self) -> None:
        origin = self.headers.get("Origin")
        if ((origin is not None and origin not in [f"http://{host}" for host in self.own_hosts()])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            return self.error(HTTPStatus.FORBIDDEN, "Only this dashboard can view agent browsers.")
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to view agent browsers.")
        query = parse_qs(urlsplit(self.path).query)
        inventory = (self.server.runner.browser_counts() if query.get("counts") == ["1"]
                     else self.server.runner.browser_inventory())
        # Tab titles and sites are private too. Recheck after the bounded read.
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to view agent browsers.")
        self.json(inventory)

    def browser_input(self, data: Dict[str, Any]) -> None:
        from .browser_preview import BrowserInputError, validate_input

        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.error(HTTPStatus.FORBIDDEN, "Only this dashboard can use browser controls.")
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to use this browser.")
        if getattr(self.server, "account_bridge", None) is not None:
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                cookie = cookies.get("morrow_csrf")
                expected, supplied = cookie.value if cookie else "", self.headers.get("X-CSRF-Token", "")
                valid = bool(expected and supplied and secrets.compare_digest(expected.encode(), supplied.encode()))
            except (CookieError, ValueError, TypeError):
                valid = False
            if not valid:
                return self.error(HTTPStatus.FORBIDDEN, "Refresh this dashboard before using browser controls.")
        try:
            validate_input(data)
            result = self.server.runner.browser_input(data["id"], data, authorized=self.stream_authorized)
        except KeyError:
            return self.error(HTTPStatus.NOT_FOUND, "This run is no longer available. Choose a current agent in Activity.")
        except BrowserInputError as error:
            return self.error(error.status, str(error))
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to use this browser.")
        self.json(result)

    def answer_sheet(self, data=None) -> None:
        from .answer_notifications import answers_path, revision, sheet_json
        from common.shared_files import locked_file, atomic_write_text

        origin = self.headers.get("Origin")
        if ((origin is not None and origin not in [f"http://{host}" for host in self.own_hosts()])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            return self.error(HTTPStatus.FORBIDDEN, "Only this dashboard can use the agent answer sheet.")
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to review agent answers.")
        writing = self.command == "POST"
        if writing and getattr(self.server, "account_bridge", None) is not None:
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", "")).get("morrow_csrf")
                expected = cookie.value if cookie else ""
                supplied = self.headers.get("X-CSRF-Token", "")
                valid = bool(expected and supplied and secrets.compare_digest(expected.encode(), supplied.encode()))
            except (CookieError, ValueError, TypeError):
                valid = False
            if not valid:
                return self.error(HTTPStatus.FORBIDDEN, "Refresh this dashboard before saving answers.")
        try:
            path = answers_path(state.APPLY, self.server.runner)
            if writing:
                if (not isinstance(data, dict) or set(data) != {"text", "revision"}
                        or not isinstance(data["text"], str) or not isinstance(data["revision"], str)
                        or len(data["text"].encode("utf-8")) > 1024 * 1024):
                    raise ValueError("Send the answer sheet text and its saved revision.")
                with locked_file(path) as target:
                    if not self.stream_authorized():
                        return self.error(HTTPStatus.UNAUTHORIZED, "Sign in before saving answers.")
                    current = target.read_text(encoding="utf-8") if target.exists() else ""
                    if data["revision"] != revision(current):
                        return self.error(HTTPStatus.CONFLICT, "The agent saved more answers since you opened this sheet. Your draft is safe; review the latest saved version before saving.")
                    if target.exists():
                        backup = target.parent / "backups" / f"answers-{dt.datetime.now():%Y%m%d-%H%M%S-%f}.bak"
                        atomic_write_text(backup, current)
                    atomic_write_text(target, data["text"])
                    result = {"ok": True, **sheet_json(target)}
            else:
                result = sheet_json(path)
        except (OSError, RuntimeError):
            return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "The agent answer sheet is unavailable. Try again shortly.")
        except (ValueError, TypeError) as exc:
            return self.error(HTTPStatus.BAD_REQUEST, str(exc))
        if not self.stream_authorized():
            return self.error(HTTPStatus.UNAUTHORIZED, "Sign in to review agent answers.")
        self.json(result)

    def do_GET(self) -> None:
        if not self.host_ok():
            self.error(HTTPStatus.FORBIDDEN, "only this computer can use this site")
            return
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        # Links in saved reports are percent-encoded ("my%20file.txt"); inside() still confines them.
        route = unquote(url.path)
        try:
            if route == "/course":
                self.redirect("/course/")
            elif route.startswith("/course/"):
                relative = route[len("/course/"):]
                target = inside(state.COURSE, relative)
                if relative and relative in {m.route for m in state.course_modules(state.COURSE)}:
                    self.redirect("/course/#/" + quote(relative, safe="/"))
                else:
                    self.file(target)
            elif route.startswith("/reports/"):
                self.file(inside(state.REPORTS, route[len("/reports/"):]))
            elif route == "/api/meta":
                self.json(meta_json())
            elif route == "/api/status":
                self.json(status_json(self.server.runner))
            elif route == "/api/run":
                after = int(query.get("after") or 0)
                self.json(self.server.runner.snapshot(after=after, epoch=query.get("epoch")))
            elif route == "/api/events":
                self.events(query)
            elif route == "/api/run/browser":
                self.browser_preview(query)
            elif route == "/api/run/browsers":
                self.browser_inventory()
            elif route == "/api/run/answers":
                self.answer_sheet()
            elif route == "/api/course":
                self.json(course_json())
            elif route == "/api/overview":
                self.json(overview_json(query.get("days", "")))
            elif route == "/api/report":
                self.json(report_json(query.get("day", "")))
            elif route == "/api/file":
                self.json(file_json(query.get("name", "")))
            else:
                self.error(HTTPStatus.NOT_FOUND, "not found")
        except (ValueError, TypeError) as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))
        except sqlite3.Error as exc:
            self.error(HTTPStatus.INTERNAL_SERVER_ERROR, f"can’t read the bots’ database: {exc}")

    def do_POST(self) -> None:
        if not self.host_ok() or not self.change_ok():
            self.error(HTTPStatus.FORBIDDEN, "only this site can change things")
            return
        route = urlsplit(self.path).path
        runner = self.server.runner
        try:
            data = self.body()
            if route == "/api/preview":
                # A form that isn't filled in yet is not an error, so this answers 200 either way.
                try:
                    self.json({"shown": build(str(data.get("action", "")), data.get("options") or {}).shown})
                except ValueError as exc:
                    self.json({"needed": str(exc)})
            elif route in ("/api/run/batch/preview", "/api/run/batch"):
                requests = batch_requests(data)
                selections = build_batch(requests)
                if route.endswith("/preview"):
                    self.json(runner.batch_plan(selections))
                else:
                    # Keep preflight, saved-command validation, and all starts
                    # in one reservation so another request cannot steal slots.
                    with runner.lock:
                        plan = runner.batch_plan(selections)
                        if plan["ready"]:
                            result = runner.start_batch(build_batch(requests, save=True))
                        else:
                            result = dict(plan, ok=False,
                                          error="Resolve the highlighted issues before starting these agents.")
                    self.json(result, HTTPStatus.OK if "results" in result else HTTPStatus.CONFLICT)
            elif route == "/api/run":
                action = str(data.get("action", ""))
                options = data.get("options") or {}
                command = build(action, options, save=True)
                day = state.parse_day(_text(options, "day")).isoformat() if action == "report" else ""
                try:
                    run_id = runner.start(command, action, day)
                except RuntimeError as exc:
                    raise ApiError(HTTPStatus.CONFLICT, str(exc)) from None
                self.json({"ok": True, "id": run_id, "label": command.label, "shown": command.shown,
                           "run": runner.snapshot()})
            elif route == "/api/stop":
                run_id = data.get("id")
                if run_id is not None and (not isinstance(run_id, str) or not run_id):
                    raise ValueError("Choose a valid agent run to stop.")
                ok, message = runner.stop(run_id)
                self.json({"ok": ok, "message": message})
            elif route == "/api/run/browser/input":
                self.browser_input(data)
            elif route == "/api/run/answers":
                self.answer_sheet(data)
            elif route == "/api/course/read":
                path = str(data.get("path", ""))
                if path not in {m.path for m in state.course_modules(state.COURSE)}:
                    raise ValueError("only the modules in the course menu can be marked read")
                if not isinstance(data.get("read", True), bool):
                    raise ValueError("read must be true or false")
                state.mark_studied(path, data.get("read", True))
                self.json({"ok": True, "read": sorted(state.studied())})
            elif route == "/api/file":
                name = str(data.get("name", ""))
                if name not in files():
                    raise ValueError(f"unknown file {name!r}")
                text = data.get("text")
                if not isinstance(text, str):
                    raise ValueError("send the file's text")
                files()[name].write_text(text, encoding="utf-8")
                self.json({"ok": True})
            elif route == "/api/answer":
                state.save_answer(int(data.get("line") or 0), str(data.get("answer", "")), state.ANSWERS)
                self.json({"ok": True})
            elif route == "/api/fact":
                state.save_fact(int(data.get("line") or 0), str(data.get("value", "")), state.PROFILE)
                self.json({"ok": True})
            elif route == "/api/open":
                self.json(self.open(data))
            else:
                self.error(HTTPStatus.NOT_FOUND, "not found")
        except ApiError as exc:
            self.error(exc.status, str(exc))
        except (ValueError, TypeError, AttributeError) as exc:
            # A field of the wrong shape (options as a string, say) is a bad request, not a dropped connection.
            self.error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError as exc:
            self.error(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not save: {exc}")

    def open(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Show a folder or file from data/ in Finder or its own app."""
        what = str(data.get("what", ""))
        if what == "resumes":
            folder = state.RESUMES / "out"
            target: Optional[Path] = folder if folder.exists() else state.RESUMES
        elif what == "path":
            path = Path(str(data.get("path", ""))).expanduser()
            data_dir = (state.APPLY / "data").resolve()
            target = path.resolve() if path.is_absolute() else None
            if target is None or data_dir not in target.parents:
                raise ValueError("only files under data/ can be opened")
        else:
            raise ValueError(f"unknown thing to open {what!r}")
        if not target.exists():
            raise ValueError(f"{shown_path(target)} does not exist")
        open_outside(str(target))
        return {"ok": True}


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.runner = Runner()

