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
from .run_isolation import board_site, BOARD_LANES
from .answer_notifications import PREFIX as ANSWER_EVENT_PREFIX, MAX_EVENT_BYTES, parse_event

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

    Direct board agents have their own persistent browser profile. Duplicate
    work on the same site still shares an account and must not run twice.
    """
    args = command.argv
    site = board_site(command, action)
    resources = {f"action:boards:{site}" if site else f"action:{action or command.shown}"}
    if action in ("install", "tests"):
        return frozenset({"workspace"})
    if action in ("naukri", "profile", "external", "assist", "google"):
        resources.add("browser:main")
    if action == "boards":
        resources.update((f"browser:lane:{site}",) if site else
                         ("browser:main", *(f"browser:lane:{lane}" for lane in BOARD_LANES)))
    if action == "cold_email" and "--scan-naukri" in args:
        resources.add("browser:main")
    if action in ("linkedin", "linkedin_profile"):
        resources.add("browser:linkedin")
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
        resources.add("browser:main")
        resources.update(f"browser:lane:{stage.split(':', 1)[1]}" for stage in selected
                         if stage.startswith(("profile:", "apply:")) and stage.split(':', 1)[1] in BOARD_LANES)
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
    answer_event_token: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)

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
    MAX_NOTIFICATIONS = 100

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
        self.notifications: list[dict[str, Any]] = []
        self.notification_ids: set[str] = set()

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

    def _prepare_run(self, command: Command, action: str, day: str, resources: frozenset[str]):
        from .run_isolation import prepare
        run = Run(command, action, day, resources)
        runtime_env = self.environment_provider(command, action) if self.environment_provider else {}
        try:
            # Runtime isolation must win over any legacy command path override.
            environment = prepare(state.APPLY, command, action, run.id, runtime_env, resources)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Could not prepare {command.label}: {exc}") from None
        return run, environment

    def _start_locked(self, command: Command, action: str, day: str, resources: frozenset[str], prepared=None) -> str:
        """Caller owns the lock and has checked conflicts and capacity."""
        run, runtime_env = prepared or self._prepare_run(command, action, day, resources)
        try:
            run.preview_store = tempfile.TemporaryDirectory(prefix=f"morrow-browser-{run.id[:8]}-", ignore_cleanup_errors=True)
            run.proc = subprocess.Popen(command.argv, cwd=str(state.APPLY), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env={**inherited_environment(), "PYTHONUNBUFFERED": "1", **runtime_env, **dict(command.env),
                                             **{key: value for key, value in runtime_env.items() if key in
                                                ("BROWSER_PROFILE_DIR", "RESUME_OUT_DIR", "MORROW_RESUME_LIBRARY_DIR", "SCREENSHOT_DIR")},
                                             "MORROW_RUN_ID": run.id,
                                             "MORROW_ANSWER_EVENT_TOKEN": run.answer_event_token,
                                             "MORROW_BROWSER_PREVIEW_DIR": run.preview_store.name,
                                             # Browser windows belong to the run itself. The
                                             # dashboard only counts them; never inherit an
                                             # obsolete remote-control/sign-in lease flag.
                                             "MORROW_BROWSER_INTERACTIVE": "false"},
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
            prepared = {}
            preparation_errors = {}
            # Copy/initialize every lane before launching the first Chrome.
            # A later board must never copy a profile the first agent has opened.
            for selection in selections:
                try:
                    prepared[selection.key] = self._prepare_run(selection.command, selection.action,
                        selection.day, resources_for(selection.command, selection.action))
                except RuntimeError as exc:
                    preparation_errors[selection.key] = str(exc)
            for selection in selections:
                command = selection.command
                assert command is not None
                result = dict(key=selection.key, label=command.label)
                try:
                    if selection.key in preparation_errors:
                        raise RuntimeError(preparation_errors[selection.key])
                    run_id = self._start_locked(command, selection.action, selection.day,
                                                resources_for(command, selection.action), prepared[selection.key])
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
        continuation = discard_event_tail = False
        try:
            # Cap individual reads as well as retained output for noisy agents.
            for raw in iter(lambda: run.proc.stdout.readline(MAX_EVENT_BYTES), b""):
                complete = raw.endswith(b"\n")
                reserved = not continuation and raw.startswith(ANSWER_EVENT_PREFIX.encode())
                if discard_event_tail or (reserved and not complete):
                    # An oversized/unfinished protocol record stays private in
                    # its entirety, including tokens located in a later chunk.
                    continuation = discard_event_tail = not complete
                    continue
                continuation = not complete
                text = _ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\r\n"))
                with self.lock:
                    if run.result is None:
                        if reserved:
                            event = parse_event(text, run.answer_event_token)
                            if event and event["id"] not in self.notification_ids:
                                self.notifications.append({**event, "run_id": run.id, "label": run.command.label, "at": _now()})
                                del self.notifications[:-self.MAX_NOTIFICATIONS]
                                self.notification_ids = {item["id"] for item in self.notifications}
                                self.revision += 1
                                self.changed.notify_all()
                        else:
                            self._say(text.split("\r")[-1], run.id)
        finally:
            run.proc.stdout.close()

    def _follow(self, run: Run) -> None:
        assert run.proc is not None
        reader = threading.Thread(target=self._read, args=(run,), daemon=True)
        reader.start()
        code = run.proc.wait()
        try:
            reader.join(timeout=READ_GRACE_S)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not reader.is_alive() and not self._group_alive(run):
                    break
                try:
                    self._signal(run, sig, include_children=True)
                except OSError:
                    # The parent already exited. A leftover child's cleanup
                    # failure must never strand this run in the active list.
                    # Still try the stronger signal and publish the exit below.
                    self.say("The agent process exited, but a background process could not be closed.", run.id)
                if sig == signal.SIGTERM:
                    # Chrome can detach its output from the agent's pipe. Its
                    # lifetime still belongs to this run, so wait for the
                    # owned process group, not just the output reader, before
                    # escalating. Other agents have separate process groups.
                    deadline = time.monotonic() + READ_GRACE_S
                    while time.monotonic() < deadline:
                        if not reader.is_alive() and not self._group_alive(run):
                            break
                        time.sleep(min(.02, max(0, deadline - time.monotonic())))
                else:
                    reader.join(timeout=READ_GRACE_S)
        finally:
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
            from .browser_preview import forget_frames
            forget_frames(store.name)
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

    def browser_input(self, run_id: str, data: dict, authorized=None) -> dict[str, Any]:
        """One user input, serialized with previews and bound to a live run."""
        from .browser_preview import BrowserInputError, control, validate_input

        validate_input(data)
        if data["id"] != run_id:
            raise BrowserInputError(400, "Choose the agent shown in this browser view.")
        with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                raise KeyError("This run is no longer available.")
            directory = run.preview_store.name if run.preview_store else None
            if "--containers" in run.command.argv:
                raise BrowserInputError(409, "This agent uses a separate desktop. Use its browser screen in Flows.")

        def ensure_allowed():
            if authorized is not None and not authorized():
                raise BrowserInputError(401, "Sign in again before using this browser.")
            with self.lock:
                if (self.closed or self.runs.get(run_id) is not run or run.result is not None or run.stopping
                        or (run.proc is not None and run.proc.poll() is not None)):
                    raise BrowserInputError(409, "This agent has stopped or is stopping. Its browser controls are closed.")
                if not directory or not run.preview_store or run.preview_store.name != directory:
                    raise BrowserInputError(409, "This agent's browser is not available yet.")

        ensure_allowed()
        if not run.preview_lock.acquire(blocking=False):
            raise BrowserInputError(409, "The browser view is refreshing. Wait for the next image before trying again.")
        try:
            ensure_allowed()
            return control(directory, data, ensure_allowed)
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

    def browser_counts(self) -> dict[str, Any]:
        """Count owned live browser instances without reading their pages."""
        from .browser_preview import count_many

        def active(run):
            return (not self.closed and self.runs.get(run.id) is run and run.result is None
                    and (run.proc is None or run.proc.poll() is None))

        with self.lock:
            runs = [run for run in self.runs.values() if active(run)]
            directories, details = {}, {}
            for run in runs:
                if "--containers" in run.command.argv:
                    details[run.id] = dict(open_browser_count=0, count_status="unavailable")
                elif run.preview_store is not None:
                    directories[run.id] = run.preview_store.name
                else:
                    details[run.id] = dict(open_browser_count=0, count_status="checking")
        acquired = self.browser_inventory_lock.acquire(blocking=False)
        try:
            if acquired and directories:
                try:
                    details.update(count_many(directories))
                except Exception:
                    for run_id in directories:
                        details[run_id] = dict(open_browser_count=0, count_status="unavailable")
            elif not acquired:
                for run_id in directories:
                    details[run_id] = dict(open_browser_count=0, count_status="checking")
            with self.lock:
                result = []
                for run in runs:
                    if not active(run):
                        continue
                    detail = details.get(run.id, {})
                    count = detail.get("open_browser_count", 0)
                    status = detail.get("count_status", "unavailable")
                    if (not isinstance(count, int) or isinstance(count, bool) or count < 0
                            or status not in ("ready", "checking", "unavailable")):
                        count, status = 0, "unavailable"
                    # Only the count leaves this method. Browser URLs, titles,
                    # tab identifiers and local addresses are never UI state.
                    result.append(dict(id=run.id, running=True, open_browser_count=count,
                                       count_status=status))
                return {"runs": result}
        finally:
            if acquired:
                self.browser_inventory_lock.release()

    @staticmethod
    def _group_alive(run: Run) -> bool:
        if run.proc is None:
            return False
        try:
            # Popen(start_new_session=True) makes the owned PID its group ID.
            # Probe only that group; never discover or signal unrelated Chrome.
            os.killpg(run.proc.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            # A failed probe must not skip the bounded cleanup attempts.
            return True

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
            out["notifications"] = [dict(item) for item in self.notifications]
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


def inherited_environment() -> dict[str, str]:
    """os.environ without the keys the settings file defines, so a run reads .env as it is now.

    The dashboard loads .env into its own environment once at startup; a value edited
    since would otherwise shadow the file for every run it starts.
    """
    try:
        from dotenv import dotenv_values
        stale = set(dotenv_values(state.APPLY / ".env", interpolate=False))
    except (OSError, ImportError):
        stale = set()
    return {key: value for key, value in os.environ.items() if key not in stale}
