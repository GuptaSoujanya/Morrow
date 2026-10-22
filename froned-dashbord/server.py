"""Serve the dashboard and the existing job-hunt API from one localhost origin."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import shlex
import sqlite3
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit, quote

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
from web import server, state
import commands
import dashboard_data

BOARDS = ("hirist", "instahyre", "cutshort", "wellfound")
BOT_IDS = ("naukri", *BOARDS, "external", "profile", "linkedin", "linkedin_profile", "cold_email", "resume", "learn", "brief", "research", *(board + '_profile' for board in BOARDS))


def board_command(options, save=False):
    board = str(options.get("board") or "all")
    if board not in (*BOARDS, "all"):
        raise ValueError("Choose a supported job board.")
    args = ["-m", "sites_bot.platforms", "--site", board]
    mode = options.get("mode") or "apply"
    if mode not in ("apply", "profile"):
        raise ValueError("Choose applications or profile update.")
    if mode == "profile":
        args += ["--profile-only", "--create-profile"]
    elif server._on(options,'update_profile'):
        args += ['--update-profile']
    if options.get("dry_run"):
        args.append("--dry-run")
    limit = server._limit(options)
    if limit is not None:
        if not 1 <= limit <= 500:
            raise ValueError("The limit must be between 1 and 500.")
        args += ["--limit", str(limit)]
    name = "All job boards" if board == "all" else state.board_name(board)
    if mode == 'profile':
        name = 'All board profiles' if board == 'all' else name + ' profile'
    return state.py(name + " · " + ("practice" if options.get("dry_run") else mode), *args)


def pipeline_command(options, save=False):
    return commands.pipeline_command(options, save)


def pipeline_status():
    today = dt.date.today().isoformat()
    path = state.APPLY / ".memory" / "progress.json"
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, OSError):
        raise ValueError("The pipeline checkpoint could not be read. Check .memory/progress.json.")
    entry = data.get("days", {}).get(today, {})
    stages = entry.get("stages", {})
    from pipeline import lanes
    return {"date": today, "status": entry.get("status", "not started"),
            "watch": [{"site": site, "url": lanes.watch_url(site)} for site in lanes.WATCH_PORTS],
            "stages": [{"name": name, **stages.get(name, {"status": "pending", "attempts": 0})}
                       for name in entry.get("plan", list(stages))]}


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def schedule_command(schedule, mode):
    if schedule not in ("profile", "linkedin") or mode not in ("enable", "disable"):
        raise ValueError("Choose a supported schedule and action.")
    return state.py(f"{schedule.title()} schedule · {mode}", str(ROOT / "schedule.py"), schedule, mode)


def bots_status(runner):
    """Inventory and recorded runs, without treating old checkpoints as live processes."""
    run = runner.snapshot()
    latest = {}
    history_error = ""
    try:
        rows = state._query(state.database(), "SELECT started_at, finished_at, summary_json FROM runs ORDER BY started_at DESC, id DESC")
        for row in rows:
            try:
                summary = json.loads(row["summary_json"] or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(summary, dict):
                continue
            key = summary.get("board") or "naukri"
            if summary.get('profile_only') or summary.get('mode') == 'profile':
                key = 'profile' if key == 'naukri' else key + '_profile'
            if key in BOT_IDS and key not in latest:
                latest[key] = {"at": row["started_at"], "finished": bool(row["finished_at"]),
                               "practice": bool(summary.get("dry_run")), "sent": summary.get("applied"),
                               "found": summary.get("collected")}
    except (OSError, sqlite3.Error):
        history_error = "Run history is unavailable. Bot controls are still available."
    tokens = shlex.split(run.get("shown") or "")
    active = []
    if run["running"]:
        action = run.get("action")
        if action == "boards" and "--site" in tokens:
            index = tokens.index("--site") + 1
            board = tokens[index] if index < len(tokens) else ""
            active = list(BOARDS) if board == "all" else [board]
            if '--profile-only' in tokens:
                active = [key + '_profile' for key in active]
        elif action == "pipeline" and "--only" in tokens:
            index = tokens.index("--only") + 1
            group = tokens[index] if index < len(tokens) else ""
            active = [group] if group in ("learn", "brief", "research") else []
        elif action in BOT_IDS:
            active = [action]
    return {"bots": [{"id": key, "running": key in active,
                      "status": "running" if key in active else "idle", "last_run": latest.get(key)}
                     for key in BOT_IDS], "run": run, "history_error": history_error}


class DashboardHandler(server.Handler):
    def send(self, status, body, kind):
        compressed = len(body) > 1024 and 'gzip' in self.headers.get('Accept-Encoding', '') and (kind.startswith('text/') or 'javascript' in kind or 'json' in kind)
        if compressed:
            body = gzip.compress(body)
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store' if '/api/' in self.path else 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        if not self.host_ok():
            return self.error(HTTPStatus.FORBIDDEN, "Only this computer can use this dashboard.")
        url = urlsplit(self.path)
        try:
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            if url.path == "/api/overview":
                data = server.overview_json(query.get('days', '14'))
                data['recent'] = dashboard_data.records({'days': data['days'], 'size': 6})['rows']
                data['source'] = {'database': state.database().name,
                                  'updated_at': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
                                  'timezone': dt.datetime.now().astimezone().tzname()}
                try:
                    data['workspace'] = dashboard_data.workspace()
                except (ValueError, OSError) as exc:
                    data['workspace_error'] = str(exc)
                return self.json(data)
            if url.path == "/api/records":
                return self.json(dashboard_data.records(query))
            if url.path == "/api/library":
                return self.json(dashboard_data.artifacts())
            if url.path == "/api/data":
                return self.json(dashboard_data.inventory(server.files()))
            if url.path == "/api/resume-file":
                path = dashboard_data.resume_file(query.get('file', ''))
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', 'attachment; filename="resume.pdf"; filename*=UTF-8\'\'' + quote(path.name))
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
                return
            if url.path == "/api/document":
                return self.json(dashboard_data.artifact(query.get('id', '')))
            if url.path == "/api/pipeline":
                return self.json(pipeline_status())
            if url.path == "/api/bots":
                return self.json(bots_status(self.server.runner))
            if url.path == "/api/file":
                data = server.file_json(parse_qs(url.query).get("name", [""])[-1])
                data["revision"] = revision(data["text"])
                return self.json(data)
            if url.path.startswith(("/api/", "/course", "/reports/")):
                return super().do_GET()
            assets = ROOT / 'dist' if (ROOT / 'dist' / 'index.html').is_file() else ROOT / 'app'
            return self.file(server.inside(assets, url.path.lstrip("/")))
        except ValueError as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError:
            self.error(HTTPStatus.INTERNAL_SERVER_ERROR, "The requested file could not be read.")
        except sqlite3.Error:
            self.error(HTTPStatus.SERVICE_UNAVAILABLE, "The application database could not be read. Try again shortly.")

    def do_POST(self):
        if urlsplit(self.path).path != "/api/file":
            return super().do_POST()
        if not self.host_ok() or not self.change_ok():
            return self.error(HTTPStatus.FORBIDDEN, "Only this site can change files.")
        try:
            data = self.body()
            path = server.files().get(data.get("name", ""))
            if path is None or not isinstance(data.get("text"), str):
                raise ValueError("Choose an editable file and send its text.")
            with self.server.file_lock:
                original = path.read_text() if path.exists() else ""
                if data.get("revision") != revision(original):
                    return self.error(HTTPStatus.CONFLICT, "This file changed since you opened it. Reload before saving; your draft is still available.")
                backup = state.APPLY / "data" / "inputs" / "backups"
                backup.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    target = backup / f"dashboard-{data['name']}-{dt.datetime.now():%Y%m%d-%H%M%S-%f}.bak"
                    target.write_text(original)
                    target.chmod(0o600)
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as temp:
                    temp.write(data["text"])
                os.replace(temp.name, path)
            self.json({"ok": True, "revision": revision(data["text"])})
        except (ValueError, server.ApiError) as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError:
            self.error(HTTPStatus.INTERNAL_SERVER_ERROR, "The file could not be saved. Your draft has been kept.")


class DashboardServer(server.ControlServer):
    def __init__(self, port):
        import threading
        super().__init__(port)
        self.RequestHandlerClass = DashboardHandler
        self.file_lock = threading.Lock()


def register_actions():
    server.ACTIONS.update(boards=board_command, pipeline=pipeline_command)
    server.ACTIONS.update(naukri=commands.naukri_command, profile=commands.profile_command,
                         linkedin_profile=commands.linkedin_profile_command,
                         cold_email=commands.cold_email_command)
    for key in ("profile", "linkedin"):
        server.ACTIONS[key + "_install"] = lambda o, save, key=key: schedule_command(key, "enable")
        server.ACTIONS[key + "_disable"] = lambda o, save, key=key: schedule_command(key, "disable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    register_actions()
    try:
        app = DashboardServer(args.port)
    except OSError as exc:
        parser.exit(1, f"Cannot start dashboard on port {args.port}: {exc}\n")
    print(f"Job hunt dashboard: http://127.0.0.1:{args.port}", flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.runner.shutdown()
        app.server_close()


if __name__ == "__main__":
    main()
