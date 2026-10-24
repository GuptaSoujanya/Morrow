"""Concurrent workspace jobs, bounded output, and replayable live snapshots."""
from __future__ import annotations

import datetime as dt
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import state
from .state import Command

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
READ_GRACE_S = 1.0
BOARDS = ("naukri", "hirist", "instahyre", "cutshort", "wellfound")
STAGES = ("learn", "research:resume", "profile:linkedin",
          *(f"{group}:{board}" for group in ("profile", "apply") for board in BOARDS),
          *(f"brief:{name}" for name in ("goal", "system-design", "papers", "tech-news", "companies")))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def resources_for(command: Command, action: str) -> frozenset[str]:
    """Reserve shared sessions and outputs; unrelated agents can work together.

    Direct browser bots currently reuse the main Chrome profile. Pipeline runs
    may use that profile too (depending on their --bots/.env settings), so do
    not assume that an apparently different site has an isolated browser.
    """
    args = command.argv
    resources = {f"action:{action or command.shown}"}
    if action in ("install", "tests"):
        return frozenset({"workspace"})
    if action in ("naukri", "profile", "boards", "external", "assist", "google"):
        resources.add("browser:main")
    if action == "cold_email" and "--scan-naukri" in args:
        resources.add("browser:main")
    if action in ("linkedin", "linkedin_profile"):
        resources.add("browser:linkedin")
    if action in ("naukri", "profile", "boards", "external", "resume", "cold_email"):
        resources.add("output:resume")
    if action != "pipeline":
        return frozenset(resources)

    subcommand = args[args.index("pipeline") + 1] if "pipeline" in args else "continue"
    if subcommand in ("status", "check"):
        return frozenset({f"pipeline:read:{subcommand}"})
    only = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "--only"]
    skip = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "--skip"]
    if subcommand == "learn":
        only = ["learn"]
    matches = lambda stage, groups: any(stage == group or stage.startswith(group + ":") for group in groups)
    selected = [stage for stage in STAGES if (not only or matches(stage, only)) and not matches(stage, skip)]
    resources = {"pipeline:writer", *(f"stage:{stage}" for stage in selected)}
    if "--fresh" in args:
        resources.add("pipeline:reset")
    if any(stage.startswith(("profile:", "apply:")) and stage != "profile:linkedin" for stage in selected):
        resources.update(("browser:main", "output:resume"))
    if "profile:linkedin" in selected:
        resources.add("browser:linkedin")
    return frozenset(resources)


def conflicts(left: frozenset[str], right: frozenset[str]) -> bool:
    if "workspace" in left or "workspace" in right:
        return True
    if "pipeline:reset" in left | right and "pipeline:writer" in left & right:
        return True
    return bool((left & right) - {"pipeline:writer"})


@dataclass
class Run:
    command: Command
    action: str
    day: str
    resources: frozenset[str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.monotonic)
    started_at: str = field(default_factory=_now)
    proc: Optional[subprocess.Popen] = None
    stopping: bool = False
    result: Optional[dict[str, Any]] = None
    preview_store: Optional[tempfile.TemporaryDirectory] = field(default=None, repr=False)
    preview_lock: Any = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        out = dict(id=self.id, label=self.command.label, shown=self.command.shown,
                   action=self.action, day=self.day, started_at=self.started_at,
                   resources=sorted(self.resources), running=self.result is None,
                   stopping=self.stopping, seconds=round(time.monotonic() - self.started),
                   status="stopping" if self.stopping else "running")
        if self.result is not None:
            out.update(self.result)
        return out


@dataclass(frozen=True)
class BatchCommand:
    """A validated selection, including build errors that the UI can explain."""

    key: str
    action: str
    command: Optional[Command] = None
    day: str = ""
    error: str = ""


def _shared_resource_description(left: frozenset[str], right: frozenset[str]) -> str:
    shared = left & right
    if "workspace" in left | right:
        return "change shared workspace files"
    reasons = []
    if any(resource.startswith("browser:") for resource in shared):
        reasons.append("share a browser session")
    if "output:resume" in shared:
        reasons.append("write to the same résumé files")
    if reasons:
        return " and ".join(reasons)
    if any(resource.startswith("stage:") for resource in shared) or "pipeline:reset" in left | right:
        return "update the same workflow progress"
    return "run the same agent"


class Runner:
    """Own each subprocess independently; never stop another run by accident."""

    MAX_LINES = 5000
    MAX_LINE_CHARS = 16000
    MAX_RUNS = 50
    MAX_ACTIVE = 8

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.runs: dict[str, Run] = {}
        self.lines: list[tuple[int, str, str, str]] = []
        self.count = 0
        self.revision = 0
        self.epoch = uuid.uuid4().hex
        self.last = None
        self.closed = False
        self.start_guard = None
        self.environment_provider = None
        self.browser_inventory_lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self.lock:
            return any(run.result is None for run in self.runs.values())

    def _say(self, text: str, run_id: str = "") -> None:
        self.lines.append((self.count, text[:self.MAX_LINE_CHARS], run_id, _now()))
        self.count += 1
        del self.lines[:-self.MAX_LINES]
        self.revision += 1
        self.changed.notify_all()

    def say(self, text: str, run_id: str = "") -> None:
        with self.lock:
            self._say(text, run_id)

    def start(self, command: Command, action: str = "", day: str = "") -> str:
        resources = resources_for(command, action)
        with self.lock:
            if self.closed:
                raise RuntimeError("The workspace is shutting down. Reconnect before starting a run.")
            if self.start_guard:
                reason = self.start_guard(command, action)
                if reason:
                    raise RuntimeError(reason)
            active = [run for run in self.runs.values() if run.result is None]
            for other in active:
                if conflicts(resources, other.resources):
                    raise RuntimeError(f"{other.command.label} is still running and uses the same browser session or files. "
                                       "Wait for it to finish, or stop that run. Other independent agents can run alongside it.")
            if len(active) >= self.MAX_ACTIVE:
                raise RuntimeError(f"{self.MAX_ACTIVE} agents are already running. Wait for one to finish before starting another.")
            return self._start_locked(command, action, day, resources)

    def _start_locked(self, command: Command, action: str, day: str, resources: frozenset[str]) -> str:
        """Caller owns the lock and has checked conflicts and capacity."""
        run = Run(command, action, day, resources)
        runtime_env = self.environment_provider(command, action) if self.environment_provider else {}
        try:
            run.preview_store = tempfile.TemporaryDirectory(prefix=f"morrow-browser-{run.id[:8]}-", ignore_cleanup_errors=True)
            run.proc = subprocess.Popen(command.argv, cwd=str(state.APPLY), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env={**os.environ, "PYTHONUNBUFFERED": "1", **runtime_env, **dict(command.env),
                                             "MORROW_BROWSER_PREVIEW_DIR": run.preview_store.name},
                                        start_new_session=True)
        except OSError as exc:
            self._clear_browser_preview(run)
            raise RuntimeError(f"Could not start {command.label}: {exc}") from None
        self.runs[run.id] = run
        self._say(f"→ {command.label}  $ {command.shown}", run.id)
        self._prune()
        threading.Thread(target=self._follow, args=(run,), daemon=True).start()
        return run.id

    def batch_plan(self, selections: list[BatchCommand]) -> dict[str, Any]:
        """Describe conflicts without saving files or launching any processes."""
        with self.lock:
            active = [run for run in self.runs.values() if run.result is None]
            items = []
            blocked = []
            resources = [resources_for(item.command, item.action) if item.command else frozenset()
                         for item in selections]
            for index, selection in enumerate(selections):
                command = selection.command
                item = dict(key=selection.key, label=command.label if command else selection.action,
                            shown=command.shown if command else "", resources=sorted(resources[index]))
                if selection.error or command is None:
                    item["error"] = selection.error or "This agent could not be prepared."
                items.append(item)
                if command is None:
                    continue
                if self.start_guard:
                    reason = self.start_guard(command, selection.action)
                    if reason:
                        blocked.append(dict(keys=[selection.key], message=reason))
                for other in active:
                    if conflicts(resources[index], other.resources):
                        reason = _shared_resource_description(resources[index], other.resources)
                        blocked.append(dict(keys=[selection.key],
                                            message=f"{command.label} cannot start while {other.command.label} is running: "
                                                    f"they {reason}. Wait for that run to finish, or stop it in Activity."))
                for previous in range(index):
                    if selections[previous].command and conflicts(resources[index], resources[previous]):
                        reason = _shared_resource_description(resources[index], resources[previous])
                        blocked.append(dict(keys=[selections[previous].key, selection.key],
                                            message=f"{selections[previous].command.label} and {command.label} {reason}. "
                                                    "Choose one of these agents, then run the other after it finishes."))
            if self.closed:
                blocked.append(dict(keys=[item.key for item in selections],
                                    message="The workspace is shutting down. Reconnect before starting these agents."))
            if len(active) + len(selections) > self.MAX_ACTIVE:
                available = max(0, self.MAX_ACTIVE - len(active))
                blocked.append(dict(keys=[item.key for item in selections],
                                    message=f"You can run up to {self.MAX_ACTIVE} agents at once. "
                                            f"{len(active)} are running and {available} slots are available. "
                                            "Select fewer agents or wait for an active run to finish."))
            return dict(ready=bool(selections) and not blocked and not any(item.get("error") for item in items),
                        items=items, conflicts=blocked, max_active=self.MAX_ACTIVE, active_count=len(active))

    def start_batch(self, selections: list[BatchCommand]) -> dict[str, Any]:
        """Reserve the whole selection atomically; report every launch outcome.

        Preflight conflicts start nothing. A process creation failure cannot
        roll back an already started process, so successful IDs remain visible.
        """
        with self.lock:
            plan = self.batch_plan(selections)
            if not plan["ready"]:
                return dict(plan, ok=False, error="Resolve the highlighted issues before starting these agents.")
            results = []
            for selection in selections:
                command = selection.command
                assert command is not None
                result = dict(key=selection.key, label=command.label)
                try:
                    run_id = self._start_locked(command, selection.action, selection.day,
                                                resources_for(command, selection.action))
                    result.update(ok=True, id=run_id)
                except RuntimeError as exc:
                    result.update(ok=False, error=str(exc))
                results.append(result)
            return dict(ok=all(item["ok"] for item in results), results=results, run=self.snapshot())

    def _prune(self) -> None:
        for run_id, run in list(self.runs.items()):
            if len(self.runs) <= self.MAX_RUNS:
                break
            if run.result is not None:
                del self.runs[run_id]

    def _read(self, run: Run) -> None:
        assert run.proc is not None and run.proc.stdout is not None
        try:
            # Cap individual reads as well as retained output for noisy agents.
            for raw in iter(lambda: run.proc.stdout.readline(self.MAX_LINE_CHARS), b""):
                text = _ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\r\n"))
                with self.lock:
                    if run.result is None:
                        self._say(text.split("\r")[-1], run.id)
        finally:
            run.proc.stdout.close()

    def _follow(self, run: Run) -> None:
        assert run.proc is not None
        reader = threading.Thread(target=self._read, args=(run,), daemon=True)
        reader.start()
        code = run.proc.wait()
        reader.join(timeout=READ_GRACE_S)
        if reader.is_alive():
            self._signal(run, signal.SIGTERM, include_children=True)
            reader.join(timeout=READ_GRACE_S)
            if reader.is_alive():
                self._signal(run, signal.SIGKILL, include_children=True)
                reader.join(timeout=READ_GRACE_S)
        with self.lock:
            took = time.monotonic() - run.started
            stopped = run.stopping
            status = "stopped" if stopped else "completed" if code == 0 else "failed"
            minutes, seconds = divmod(int(took), 60)
            elapsed = f"{minutes}:{seconds:02d}"
            if stopped:
                message = f"○ {run.command.label}: stopped after {elapsed}"
            elif code == 0:
                message = f"✓ {run.command.label}: done in {elapsed}"
            else:
                message = f"× {run.command.label}: failed (exit {code}) after {elapsed}"
            run.result = dict(exit=code, stopped=stopped, status=status, seconds=round(took), finished=_now())
            self.last = run.snapshot()
            self._say(message, run.id)
            self._prune()
        self._clear_browser_preview(run)

    def _clear_browser_preview(self, run: Run) -> None:
        with self.lock:
            store, run.preview_store = run.preview_store, None
        if store is not None:
            store.cleanup()

    def browser_snapshot(self, run_id: str, browser_id: str = "", tab_id: str = "") -> dict[str, Any]:
        """Read one owned browser frame without blocking run output or controls."""
        from .browser_preview import snapshot

        with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                raise KeyError("This run is no longer available. Choose a current run in Activity.")
            if run.result is not None or self.closed:
                return dict(state="finished", message="This run has finished. Its browser preview is closed.")
            if "--containers" in run.command.argv:
                return dict(state="unavailable", message="This run uses a separate desktop. Open the browser screens in Flows to watch it.")
            directory = run.preview_store.name if run.preview_store else None
        if directory is None:
            return dict(state="waiting", message="Waiting for this agent to open a browser.")
        if not run.preview_lock.acquire(blocking=False):
            return dict(state="waiting", message="The browser preview is refreshing. Another image will be available shortly.")
        try:
            try:
                frame = snapshot(directory, browser_id=browser_id, tab_id=tab_id)
            except Exception:
                # Preview failures must not leak local addresses or affect the
                # agent. Keep operational controls usable while Chrome reconnects.
                frame = dict(state="unavailable", message="The browser preview is temporarily unavailable. Your agent can keep working.")
            with self.lock:
                if run.result is not None or self.closed:
                    return dict(state="finished", message="This run has finished. Its browser preview is closed.")
            return frame
        finally:
            run.preview_lock.release()

    def browser_inventory(self) -> dict[str, Any]:
        """Read every active run's browser list without holding the runner lock."""
        from .browser_preview import inventory_many

        def waiting():
            return dict(state="waiting", message="This agent has not opened a browser yet.", browsers=[])

        with self.lock:
            if self.closed:
                return {"runs": []}
            active = [run for run in self.runs.values() if run.result is None]
            directories, details = {}, {}
            for run in active:
                if "--containers" in run.command.argv:
                    details[run.id] = dict(state="unavailable", browsers=[], message=
                        "This run uses a separate desktop. Open the browser screens in Flows to watch it.")
                elif run.preview_store is not None:
                    directories[run.id] = run.preview_store.name
                else:
                    details[run.id] = waiting()
        acquired = self.browser_inventory_lock.acquire(blocking=False)
        try:
            if acquired and directories:
                try:
                    details.update(inventory_many(directories))
                except Exception:
                    for run_id in directories:
                        details[run_id] = dict(state="unavailable", browsers=[], message=
                            "Browser details are temporarily unavailable. Your agents can keep working.")
            elif not acquired:
                for run_id in directories:
                    details[run_id] = dict(state="waiting", browsers=[], message="The browser list is refreshing. Try again shortly.")
            with self.lock:
                if self.closed:
                    return {"runs": []}
                result = []
                for run in active:
                    if run.result is not None or self.runs.get(run.id) is not run:
                        continue
                    current = run.snapshot()
                    entry = {key: current[key] for key in ("id", "label", "action", "running", "stopping", "status", "seconds")}
                    detail = details.get(run.id) or waiting()
                    entry.update(browser_state=detail["state"], message=detail["message"], browsers=detail["browsers"])
                    result.append(entry)
                return {"runs": result}
        finally:
            if acquired:
                self.browser_inventory_lock.release()

    @staticmethod
    def _signal(run: Run, sig: int, include_children: bool = False) -> None:
        if run.proc is not None and (include_children or run.proc.poll() is None):
            try:
                os.killpg(run.proc.pid, sig)
            except ProcessLookupError:
                pass

    def stop(self, run_id: Optional[str] = None) -> tuple[bool, str]:
        with self.lock:
            active = [run for run in self.runs.values() if run.result is None]
            run = self.runs.get(run_id) if run_id else active[0] if len(active) == 1 else None
            if not run_id and len(active) > 1:
                return False, "Choose the agent you want to stop in Activity. Other agents will keep running."
            if run is None or run.result is not None:
                return False, "This run has already finished or is no longer available." if run_id else "Nothing is running."
            # A process may finish before its output-draining thread catches up.
            if run.proc is not None and run.proc.poll() is not None:
                return False, "This agent has finished. Its remaining output is being collected."
            if run.stopping:
                self._signal(run, signal.SIGKILL)
                self._say("Force stop requested. Closing this agent now.", run.id)
                return True, "Forced to stop."
            run.stopping = True
            self._signal(run, signal.SIGINT)
            self._say("Stop requested. Waiting for this agent to close cleanly.", run.id)
            return True, "Stopping this agent. Other agents will keep running. Press Stop again to force it."

    def shutdown(self) -> None:
        with self.lock:
            self.closed = True
            active = [run for run in self.runs.values() if run.result is None]
            for run in active:
                run.stopping = True
                self._signal(run, signal.SIGTERM)
            self.changed.notify_all()
        deadline = time.monotonic() + READ_GRACE_S
        for run in active:
            try:
                run.proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            self._signal(run, signal.SIGKILL, include_children=True)
        with self.lock:
            retained = list(self.runs.values())
        for run in retained:
            self._clear_browser_preview(run)

    def snapshot(self, after: Optional[int] = None, epoch: Optional[str] = None) -> dict[str, Any]:
        with self.lock:
            runs = [run.snapshot() for run in self.runs.values()]
            active = [run for run in runs if run["running"]]
            first = active[0] if active else {}
            out = dict(running=bool(active), label=first.get("label", ""), shown=first.get("shown", ""),
                       action=first.get("action", ""), seconds=first.get("seconds", 0),
                       stopping=first.get("stopping", False), last=self.last, next=self.count,
                       epoch=self.epoch, revision=self.revision, runs=runs, active_count=len(active))
            if after is not None:
                reset = (epoch is not None and epoch != self.epoch) or after > self.count
                after = 0 if reset else max(0, after)
                first_line = self.lines[0][0] if self.lines else self.count
                out.update(lines=[list(line) for line in self.lines if line[0] >= after],
                           reset=reset, truncated=after < first_line, first=first_line)
            return out

    def wait_snapshot(self, revision: int, after: int, epoch: str, timeout: float = 10) -> dict[str, Any]:
        with self.changed:
            self.changed.wait_for(lambda: self.closed or self.revision != revision, timeout)
            return self.snapshot(after, epoch)
