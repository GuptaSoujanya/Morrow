#!/usr/bin/env python3
"""Start and stop this checkout's complete local beta, without account services."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "reports" / "morrow"
START_TIMEOUT = 60
STOP_TIMEOUT = 10


class LauncherError(Exception):
    pass


def state_path():
    return RUNTIME / "launcher.json"


@contextmanager
def locked():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "launcher.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def process_started(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True
    )
    if result.returncode and result.stderr.strip():
        raise LauncherError(result.stderr.strip())
    return result.stdout.strip()


def owned_process(state):
    if not state or state.get("root") != str(ROOT):
        return False
    pid = state.get("pid")
    if type(pid) is not int or pid <= 1 or not state.get("started"):
        return False
    for member, started in ((pid, state["started"]), (state.get("server_pid"), state.get("server_started"))):
        if type(member) is not int or member <= 1 or not started:
            continue
        try:
            if os.getpgid(member) == pid and process_started(member) == started:
                return True
        except ProcessLookupError:
            pass
    return False


def load_state():
    try:
        state = json.loads(state_path().read_text())
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise LauncherError(f"Cannot read launcher state: {state_path()}") from error
    if not isinstance(state, dict) or type(state.get("port")) is not int or not 1 <= state["port"] <= 65535:
        raise LauncherError(f"Invalid launcher state: {state_path()}")
    return state


def write_state(state):
    pending = RUNTIME / "launcher.tmp"
    with pending.open("w") as handle:
        os.chmod(pending, 0o600)
        json.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())
    pending.replace(state_path())


def port_in_use(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except ConnectionRefusedError:
        return False


def beta_ready(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/session", timeout=1) as response:
            data = json.load(response)
        return data.get("mode") == "local" and data.get("legacy_access") is True and data.get("user") is None
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return False


def listener_pids(port):
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    return [int(pid) for pid in result.stdout.split()]


def listener_owned(port, group):
    """A racing server must not satisfy our readiness check."""
    pids = listener_pids(port)
    if not pids:
        return False
    try:
        return all(os.getpgid(int(pid)) == group for pid in pids)
    except (ProcessLookupError, ValueError):
        return False


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_group(pid):
    # This is called only for a verified group or a child we just started.
    for sig, timeout in ((signal.SIGINT, STOP_TIMEOUT), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not group_alive(pid):
                return
            time.sleep(0.1)
    raise LauncherError(f"Process group {pid} did not stop. See {RUNTIME / 'dashboard.log'}.")


def check_dependencies():
    if not shutil.which("node") or not shutil.which("npm"):
        raise LauncherError("Install Node.js 22.19 or newer, then run morrow start again.")
    version = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True)
    try:
        supported = tuple(int(part) for part in version.stdout.strip().lstrip("v").split(".")[:2]) >= (22, 19)
    except ValueError:
        supported = False
    if not supported:
        raise LauncherError("Morrow needs Node.js 22.19 or newer.")
    if not shutil.which("lsof"):
        raise LauncherError("Install lsof so Morrow can verify which server it starts.")
    frontend = ROOT / "froned-dashbord"
    if not (frontend / "package.json").exists():
        raise LauncherError("Dashboard files are missing. Run git submodule update --init --recursive.")
    if not (frontend / "node_modules" / ".bin" / "esbuild").exists():
        print("Installing dashboard dependencies…", flush=True)
        subprocess.run(["npm", "ci"], cwd=frontend, check=True)


def start(port):
    state = load_state()
    if owned_process(state):
        if state["port"] != port:
            raise LauncherError(f"Morrow is already using port {state['port']}. Run morrow stop first.")
        if not listener_owned(port, state["pid"]) or not beta_ready(port):
            raise LauncherError("Morrow is running but is not ready. Check morrow logs, then morrow restart.")
        print(f"Morrow beta is already running: http://127.0.0.1:{port}")
        return
    if port_in_use(port):
        raise LauncherError(
            f"Port {port} is used by another server. Stop that server, or use morrow start --port 8116."
        )
    check_dependencies()
    env = os.environ.copy()
    env.update(MORROW_MODE="beta", DASHBOARD_PYTHON=sys.executable, PYTHONUNBUFFERED="1")
    log_path = RUNTIME / "dashboard.log"
    print("Starting Morrow beta · building the dashboard and starting local tools…", flush=True)
    with log_path.open("w") as log:
        process = subprocess.Popen(
            ["node", "scripts/start.mjs", "--mode", "beta", "--port", str(port)],
            cwd=ROOT / "froned-dashbord", env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    try:
        started = process_started(process.pid)
        if not started:
            raise LauncherError(f"Morrow exited during startup. See {log_path}.")
        state = {"pid": process.pid, "started": started, "root": str(ROOT), "port": port, "mode": "beta"}
        write_state(state)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LauncherError(f"Morrow could not start (exit {process.returncode}). See {log_path}.")
            if beta_ready(port) and listener_owned(port, process.pid):
                # Keep ownership verifiable even if the Node parent later dies.
                server_pids = listener_pids(port)
                if not server_pids:
                    continue
                server_started = process_started(server_pids[0])
                if not server_started:
                    continue
                state.update(server_pid=server_pids[0], server_started=server_started)
                write_state(state)
                print(f"Morrow beta is ready: http://127.0.0.1:{port}\nStop: morrow stop · Logs: morrow logs")
                return
            time.sleep(0.25)
        raise LauncherError(f"Morrow did not become ready within {START_TIMEOUT}s. See {log_path}.")
    except BaseException:
        stop_group(process.pid)
        state_path().unlink(missing_ok=True)
        raise


def stop():
    state = load_state()
    if not owned_process(state):
        state_path().unlink(missing_ok=True)
        print("Morrow beta is stopped.")
        return
    print("Stopping Morrow beta and its local tasks…", flush=True)
    stop_group(state["pid"])
    state_path().unlink(missing_ok=True)
    print("Morrow beta is stopped.")


def status():
    state = load_state()
    if not owned_process(state):
        print("Morrow beta is stopped. Start it with: morrow start")
        return 0
    if not listener_owned(state["port"], state["pid"]) or not beta_ready(state["port"]):
        print("Morrow is running but is not ready. Check: morrow logs")
        return 1
    print(f"Morrow beta is running: http://127.0.0.1:{state['port']}\nCheckout: {ROOT}")
    return 0


def install():
    target = Path.home() / ".local" / "bin" / "morrow"
    source = ROOT / "scripts" / "morrow"
    if target.exists() or target.is_symlink():
        if target.resolve() != source:
            raise LauncherError(f"{target} already points elsewhere; it has not been changed.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    print(f"Installed {target}\nStart Morrow beta with: morrow start")
    if str(target.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print('Add this to your shell profile: export PATH="$HOME/.local/bin:$PATH"')


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the complete local Morrow beta.")
    parser.add_argument("command", nargs="?", default="start", choices=("start", "stop", "restart", "status", "logs", "install"))
    parser.add_argument("mode", nargs="?", choices=("beta",), help="The launcher always uses beta mode.")
    parser.add_argument("--port", type=int, help="Local port for start/restart (default: 8100).")
    args = parser.parse_args(argv)
    if args.port is not None and (args.command not in ("start", "restart") or not 1 <= args.port <= 65535):
        parser.error("--port must be 1–65535 and is only available with start or restart.")
    try:
        if args.command == "install":
            install()
        elif args.command == "logs":
            log_path = RUNTIME / "dashboard.log"
            if not log_path.exists():
                raise LauncherError("No startup log yet. Run morrow start first.")
            return subprocess.call(["tail", "-n", "40", "-f", str(log_path)])
        else:
            with locked():
                if args.command == "status":
                    return status()
                if args.command == "stop":
                    stop()
                else:
                    state = load_state()
                    port = args.port or (state["port"] if owned_process(state) else 8100)
                    if args.command == "restart":
                        stop()
                    start(port)
    except (LauncherError, OSError, subprocess.SubprocessError) as error:
        print(f"Morrow: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
