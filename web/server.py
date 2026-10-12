"""The control site: a page on this computer that runs the bots, shows what waits for you, and holds the course.

It only listens on 127.0.0.1. Other web pages can't use it: every request has to
name this computer as its Host, and anything that changes something has to be a
JSON request from this site itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from . import state
from .state import Command

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8000

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


# --- running one command at a time ---------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


class Runner:
    """Runs one command at a time and keeps its output for the page to read."""

    MAX_LINES = 5000

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: Optional[subprocess.Popen] = None
        self.command: Optional[Command] = None
        self.action = ""
        self.day = ""
        self.started = 0.0
        self.stopping = False
        self.lines: List[Tuple[int, str]] = []
        self.count = 0
        self.last: Optional[Dict[str, Any]] = None

    @property
    def running(self) -> bool:
        return self.command is not None

    def _say(self, text: str) -> None:
        self.lines.append((self.count, text))
        self.count += 1
        if len(self.lines) > self.MAX_LINES:
            del self.lines[: len(self.lines) - self.MAX_LINES]

    def say(self, text: str) -> None:
        with self.lock:
            self._say(text)

    def start(self, command: Command, action: str = "", day: str = "") -> None:
        with self.lock:
            if self.command is not None:
                raise RuntimeError(f"{self.command.label} is still running. Stop it first.")
            self._say(f"→ {command.label}  $ {command.shown}")
            try:
                proc = subprocess.Popen(
                    command.argv,
                    cwd=str(state.APPLY),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    start_new_session=True,
                )
            except OSError as exc:
                self._say(f"× Could not start: {exc}")
                raise RuntimeError(f"Could not start {command.label}: {exc}") from None
            self.proc, self.command, self.action, self.day = proc, command, action, day
            self.started = time.monotonic()
            self.stopping = False
        threading.Thread(target=self._follow, args=(proc, command), daemon=True).start()

    def _follow(self, proc: subprocess.Popen, command: Command) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            text = _ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\r\n"))
            self.say(text.split("\r")[-1])
        code = proc.wait()
        with self.lock:
            took = time.monotonic() - self.started
            stopped = self.stopping and code != 0
            if code == 0:
                self._say(f"✓ {command.label}: done in {elapsed(took)}")
            elif stopped:
                self._say(f"○ {command.label}: stopped after {elapsed(took)}")
            else:
                self._say(f"× {command.label}: failed (exit {code}) after {elapsed(took)}")
            self.last = {
                "label": command.label,
                "action": self.action,
                "day": self.day,
                "exit": code,
                "stopped": stopped,
                "seconds": round(took),
                "finished": dt.datetime.now().isoformat(timespec="seconds"),
            }
            self.proc, self.command, self.action, self.day = None, None, "", ""

    def _signal(self, sig: int) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass

    def stop(self) -> Tuple[bool, str]:
        with self.lock:
            if self.command is None:
                return False, "Nothing is running."
            if self.stopping:
                self._signal(signal.SIGKILL)
                return True, "Forced to stop."
            self.stopping = True
            self._signal(signal.SIGINT)
            return True, "Stopping, letting it close the browser cleanly. Press Stop again to force it."

    def shutdown(self) -> None:
        with self.lock:
            self._signal(signal.SIGTERM)

    def snapshot(self, after: Optional[int] = None) -> Dict[str, Any]:
        with self.lock:
            out: Dict[str, Any] = {
                "running": self.command is not None,
                "label": self.command.label if self.command else "",
                "shown": self.command.shown if self.command else "",
                "action": self.action,
                "seconds": round(time.monotonic() - self.started) if self.command else 0,
                "stopping": self.stopping,
                "last": self.last,
                "next": self.count,
            }
            if after is not None:
                out["lines"] = [[n, text] for n, text in self.lines if n >= after]
            return out


def elapsed(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


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


def build(action: str, options: Dict[str, Any], save: bool = False) -> Command:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    return ACTIONS[action](options, save)


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
        self.send_header("Cache-Control", "no-cache")
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
        length = int(self.headers.get("Content-Length") or 0)
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

    def do_GET(self) -> None:
        if not self.host_ok():
            self.error(HTTPStatus.FORBIDDEN, "only this computer can use this site")
            return
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        route = url.path
        try:
            if route == "/":
                self.file(STATIC / "index.html")
            elif route.startswith("/static/"):
                self.file(inside(STATIC, route[len("/static/"):]))
            elif route == "/course":
                self.redirect("/course/")
            elif route.startswith("/course/"):
                self.file(inside(state.COURSE, route[len("/course/"):]))
            elif route.startswith("/reports/"):
                self.file(inside(state.REPORTS, route[len("/reports/"):]))
            elif route == "/api/meta":
                self.json(meta_json())
            elif route == "/api/status":
                self.json(status_json(self.server.runner))
            elif route == "/api/run":
                after = int(query.get("after") or 0)
                self.json(self.server.runner.snapshot(after=after))
            elif route == "/api/course":
                self.json(course_json())
            elif route == "/api/report":
                self.json(report_json(query.get("day", "")))
            elif route == "/api/file":
                self.json(file_json(query.get("name", "")))
            else:
                self.error(HTTPStatus.NOT_FOUND, "not found")
        except ValueError as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))

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
            elif route == "/api/run":
                action = str(data.get("action", ""))
                options = data.get("options") or {}
                command = build(action, options, save=True)
                day = state.parse_day(_text(options, "day")).isoformat() if action == "report" else ""
                try:
                    runner.start(command, action, day)
                except RuntimeError as exc:
                    raise ApiError(HTTPStatus.CONFLICT, str(exc)) from None
                self.json({"ok": True, "label": command.label, "shown": command.shown})
            elif route == "/api/stop":
                ok, message = runner.stop()
                self.json({"ok": ok, "message": message})
            elif route == "/api/course/read":
                path = str(data.get("path", ""))
                if path not in {m.path for m in state.course_modules(state.COURSE)}:
                    raise ValueError("only the modules in the course menu can be marked read")
                state.mark_studied(path, bool(data.get("read", True)))
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
        except ValueError as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))

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


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1) as reply:
            return "answer_modes" in json.loads(reply.read())
    except (OSError, ValueError):
        return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m web", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on this computer (default {DEFAULT_PORT})")
    parser.add_argument("--no-open", action="store_true", help="do not open the page in your browser")
    args = parser.parse_args(argv)
    # Started in the background, ctrl+c is ignored and every command run from here would inherit
    # that, so Stop could not interrupt it. Taking ctrl+c back makes the commands interruptible.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    url = f"http://localhost:{args.port}"
    try:
        server = ControlServer(args.port)
    except OSError:
        if already_running(args.port):
            print(f"Already running at {url}")
            if not args.no_open:
                open_outside(url)
            return 0
        print(f"Port {args.port} is taken by another app. Start with --port <another port>.", file=sys.stderr)
        return 1
    print(f"Job hunt is open at {url}  (ctrl+c stops it)", flush=True)
    if not args.no_open:
        open_outside(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.runner.shutdown()
        server.server_close()
    return 0
