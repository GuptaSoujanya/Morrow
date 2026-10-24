"""The day's checkpoint in .memory/, so a second run the same day continues.

.memory/progress.json holds, per date, every pipeline stage with its status and
attempts, and the companies applied to that day (read back from the ledger, so
only verified applications are listed). .memory/<date>.md is the same thing for
a person to read, and .memory/README.md says how to continue.
.memory/profiles.json tracks every board profile the bots created or updated,
with its link, so the checkpoint links straight to each profile.
"""

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .models import ApplyStatus
from .pipeline_diagnostics import process_alive, sanitize_detail
from .shared_files import atomic_write_text, locked_file

MEMORY_DIR = Path(".memory")
PROFILES_FILE = "profiles.json"

#: What a bot did to a board profile.
PROFILE_CREATED = "created"
PROFILE_UPDATED = "updated"

DONE = "done"
FAILED = "failed"
PENDING = "pending"
RUNNING = "running"

#: The day as a whole, in progress.json and on top of <date>.md.
DAY_DONE = "done"
DAY_IN_PROGRESS = "in progress"
DAY_NOT_STARTED = "not started"

#: Ledger statuses that mean an application really went through.
APPLIED_STATUSES = (ApplyStatus.APPLIED, ApplyStatus.APPLIED_EXTERNAL, ApplyStatus.APPLIED_PLATFORM)

_README = """# .memory: the pipeline's checkpoint

`python3 -m pipeline` writes here after every stage. Run it again the same day
(or say "continue") and it skips every stage already done and retries the rest.
Once every stage of the day is done the day is marked `done`, and a later run
that day only prints the checkpoint.

A stage counts as done only while the files it wrote are still there: delete a
briefing file and the next run writes it again.

- `progress.json`: per day, the day's status, each stage (status, attempts, last run, detail,
  files written) and the companies applied to.
- `<date>.md`: the same day, readable, with a link to every profile and job.
- `profiles.json`: per board, the profile link, when it was created and last updated.
- `python3 -m pipeline status` prints today's checkpoint; `--fresh` starts the day over.
"""


_PROFILES_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def day_bounds_utc(day: date) -> tuple:
    """The local calendar day as UTC ISO strings, the form the ledger stores."""
    start = datetime.combine(day, time.min).astimezone()
    end = start + timedelta(days=1)
    return (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())


def load_profiles(folder: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads((Path(folder or MEMORY_DIR) / PROFILES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_profile(platform: str, action: str, url: str, notes: str = "",
                   folder: Optional[Path] = None) -> None:
    """Note that a bot created or updated a board profile, keeping its link and history.

    The bots run inside the pipeline but write this file, not progress.json, so
    the pipeline's own Memory never overwrites it.
    """
    folder = Path(folder or MEMORY_DIR)
    with _PROFILES_LOCK, locked_file(folder / PROFILES_FILE) as path:
        profiles = load_profiles(folder)
        entry = profiles.setdefault(platform, {"history": []})
        at = _now()
        entry.update(url=url or entry.get("url", ""), last_action=action, at=at, notes=notes)
        if action == PROFILE_CREATED:
            entry["created_at"] = at
        entry["history"] = (entry.get("history") or [])[-29:] + [{"action": action, "at": at}]
        atomic_write_text(path, json.dumps(profiles, indent=1, sort_keys=True))


def _link(text: str, url: str) -> str:
    return "[%s](%s)" % (text, url) if url else text


class Memory:
    def __init__(self, folder: Path, day: Optional[date] = None):
        self.folder = Path(folder)
        self.day = day or date.today()
        self.key = self.day.isoformat()
        self.path = self.folder / "progress.json"
        self.data = self._load()
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"days": {}}
        try:
            data = json.loads(text)
        except ValueError as exc:
            # Starting over would overwrite every earlier day's history.
            raise ValueError("%s is not valid JSON (%s); fix it or move it aside" % (self.path, exc)) from exc
        if not isinstance(data, dict) or not isinstance(data.get("days", {}), dict):
            raise ValueError("%s does not hold a progress object" % self.path)
        return data

    @contextmanager
    def _update(self) -> Iterator[None]:
        """Re-read the file under a lock, apply one change, save.

        Two runs the same day each change only their own stages, so neither
        drops what the other recorded.
        """
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.folder / ".lock", "w") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    self.data = self._load()
                    yield
                    self.save()
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @property
    def today(self) -> Dict[str, Any]:
        return self.data.setdefault("days", {}).setdefault(self.key, {"stages": {}, "applied": []})

    def stage(self, name: str) -> Dict[str, Any]:
        return self.today["stages"].get(name) or {"status": PENDING, "attempts": 0}

    def is_done(self, name: str) -> bool:
        """Done, and every file the stage wrote is still on disk."""
        entry = self.stage(name)
        return entry["status"] == DONE and all(Path(p).exists() for p in entry.get("outputs") or ())

    def mark(self, name: str, status: str, detail: str = "", outputs: Iterable[Path] = (), *,
             exit_code: Optional[int] = None, run_options: Optional[Dict[str, Any]] = None) -> None:
        outputs = [str(p) for p in outputs]
        with self._update():
            entry = self.stage(name)
            at = _now()
            if status == RUNNING:
                if entry.get("status") == FAILED and not entry.get("last_error"):
                    entry["last_error"] = {
                        "message": sanitize_detail(entry.get("detail")) or "The previous attempt failed. Open the run log for details.",
                        "at": entry.get("at") or at,
                    }
                if entry.get("status") == RUNNING and not process_alive(entry.get("owner_pid")):
                    entry["last_error"] = {
                        "message": "The previous attempt stopped before recording completion. Resume this stage from the saved checkpoint.",
                        "at": entry.get("at") or at,
                    }
                entry.update(started_at=at, owner_pid=os.getpid())
                entry.pop("finished_at", None)
                if run_options is not None:
                    entry["run_options"] = self._run_options(run_options)
            else:
                entry.pop("owner_pid", None)
            entry.update(status=status, at=at, detail=sanitize_detail(detail))
            if status in (DONE, FAILED):
                entry["attempts"] = entry.get("attempts", 0) + 1
                entry["finished_at"] = at
            if status == FAILED:
                error = {"message": sanitize_detail(detail) or "This stage failed. Open the run log for details, then resume it.",
                         "at": at}
                if exit_code is not None:
                    error["exit_code"] = exit_code
                entry["last_error"] = error
            if status == DONE:
                entry["outputs"] = outputs
                if entry.get("last_error"):
                    entry["last_error"].setdefault("resolved_at", at)
            self.today["stages"][name] = entry

    def planned(self) -> List[str]:
        """The day's stages: the last full plan, else every stage seen today."""
        return list(self.today.get("plan") or self.today["stages"])

    def day_status(self) -> str:
        names = self.planned()
        if names and all(self.is_done(name) for name in names):
            return DAY_DONE
        if any(self.stage(name)["status"] != PENDING for name in names):
            return DAY_IN_PROGRESS
        return DAY_NOT_STARTED

    def left(self) -> List[str]:
        return [name for name in self.planned() if not self.is_done(name)]

    def history(self) -> List[tuple]:
        """(date, verified applications) for every recorded day, oldest first."""
        return [(day, len(entry.get("applied") or [])) for day, entry in sorted(self.data.get("days", {}).items())]

    @staticmethod
    def _run_options(options: Dict[str, Any]) -> Dict[str, Any]:
        """Only replayable, non-secret CLI choices belong in a checkpoint."""
        safe = {}
        if options.get("cli") in ("both", "claude", "kiro"):
            safe["cli"] = options["cli"]
        for key in ("agents", "bots"):
            value = options.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                safe[key] = value
        if isinstance(options.get("containers"), bool):
            safe["containers"] = options["containers"]
        return safe

    def plan(self, names: Iterable[str], run_options: Optional[Dict[str, Any]] = None,
             replace_options: bool = True) -> None:
        """Record the stages this day will run, so the readable file lists the ones still to do."""
        names = list(names)
        with self._update():
            self.today["plan"] = names
            if run_options is not None and (replace_options or "run_options" not in self.today):
                self.today["run_options"] = self._run_options(run_options)
            for name in names:
                self.today["stages"].setdefault(name, {"status": PENDING, "attempts": 0})

    def reset_day(self) -> None:
        with self._update():
            self.data.setdefault("days", {})[self.key] = {"stages": {}, "applied": []}

    def sync_applied(self, rows: List[Dict[str, Any]]) -> None:
        """Keep the day's verified applications from ledger rows."""
        seen = set()
        applied = []
        for row in rows:
            if row.get("status") not in APPLIED_STATUSES:
                continue
            key = row.get("job_id") or row.get("url")
            if key in seen:
                continue
            seen.add(key)
            applied.append({
                "company": row.get("company") or "",
                "title": row.get("title") or "",
                "status": row.get("status"),
                "url": row.get("url") or "",
                "at": row.get("at") or "",
            })
        with self._update():
            self.today["applied"] = applied

    def save(self) -> None:
        with self._lock:
            status = self.day_status()
            if status == DAY_DONE and self.today.get("status") != DAY_DONE:
                self.today["completed_at"] = _now()
            elif status != DAY_DONE:
                self.today.pop("completed_at", None)
            self.today["status"] = status
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
            (self.folder / ("%s.md" % self.key)).write_text(self.markdown(), encoding="utf-8")
            readme = self.folder / "README.md"
            if not readme.exists():
                readme.write_text(_README, encoding="utf-8")

    def markdown(self) -> str:
        stages = {name: self.stage(name) for name in self.planned()}
        status = self.day_status()
        done = len(stages) - len(self.left())
        lines = ["# Pipeline checkpoint %s" % self.key, "",
                 "**Day: %s** (%d of %d stages done)%s" % (
                     status.upper(), done, len(stages),
                     ", finished %s" % self.today["completed_at"] if self.today.get("completed_at") else ""), ""]
        if self.left():
            lines += ["Left: %s. Run `python3 -m pipeline continue`." % ", ".join(self.left()), ""]
        if stages:
            lines += ["```mermaid", "pie title Stages", '    "done" : %d' % done,
                      '    "left" : %d' % (len(stages) - done), "```", ""]
        lines += ["## Stages", ""]
        for name, entry in stages.items():
            detail = (" - %s" % entry["detail"]) if entry.get("detail") else ""
            lines.append("- [%s] %s (%s, attempts %d)%s" % (
                "x" if self.is_done(name) else " ", name,
                entry["status"] if self.is_done(name) or entry["status"] != DONE else "output missing",
                entry.get("attempts", 0), detail))
        profiles = load_profiles(self.folder)
        if profiles:
            lines += ["", "## Profiles", "", "| Board | Profile | Last | When | Created |", "|---|---|---|---|---|"]
            lines += ["| %s | %s | %s | %s | %s |" % (
                name, _link("open", entry.get("url", "")), entry.get("last_action", ""),
                entry.get("at", ""), entry.get("created_at", "")) for name, entry in sorted(profiles.items())]
        applied = self.today["applied"]
        lines += ["", "## Applied today (%d)" % len(applied), ""]
        lines += ["- %s: %s (%s)" % (row["company"] or "?", _link(row["title"] or "job", row["url"]), row["status"])
                  for row in applied]
        return "\n".join(lines) + "\n"
