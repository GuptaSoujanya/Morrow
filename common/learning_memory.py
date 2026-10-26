"""Durable learning state shared by the dashboard, course reader and learning CLI.

One locked read/modify/atomic-replace transaction prevents distinct requests from
overwriting each other. Legacy files are imported once and left untouched.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading

_lock = threading.RLock()


def _json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as exc:
        raise ValueError(f"Cannot read {path.name}. Your saved progress has not been reset.") from exc


def _validate(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported .memory/learning.json. Your progress has not been reset.")
    if any(not isinstance(data.get(k), dict) for k in ("course", "documents", "plan")) or not isinstance(data.get("history"), list):
        raise ValueError("Invalid .memory/learning.json. Your progress has not been reset.")
    if any(not isinstance(v, dict) or not isinstance(v.get("done"), bool) for k in ("course", "documents") for v in data[k].values()):
        raise ValueError("Invalid saved completion. Your progress has not been reset.")
    plan = data["plan"]
    if not isinstance(plan.get("done", []), list) or any(type(n) is not int or not 1 <= n <= 90 for n in plan.get("done", [])) or not isinstance(plan.get("marked", {}), dict):
        raise ValueError("Invalid saved learning plan. Your progress has not been reset.")
    for event in data['history']:
        if (not isinstance(event, dict) or any(not isinstance(event.get(key), str) for key in ('at', 'id', 'title'))
                or event.get('kind') not in ('course', 'research', 'dsa') or event.get('action') not in ('completed', 'reopened')):
            raise ValueError("Invalid saved learning history. Your progress has not been reset.")
        try:
            dt.datetime.fromisoformat(event['at'])
        except ValueError as exc:
            raise ValueError("Invalid learning history date. Your progress has not been reset.") from exc
    if 'dsa' in data:
        dsa = data['dsa']
        if not isinstance(dsa, dict) or not isinstance(dsa.get('days'), dict):
            raise ValueError('Invalid DSA progress. Your progress has not been reset.')
        for day, entry in dsa['days'].items():
            try:
                if dt.date.fromisoformat(day).isoformat() != day:
                    raise ValueError()
                if (not isinstance(entry, dict) or not isinstance(entry.get('topic'), str)
                        or type(entry.get('read')) is not bool or not isinstance(entry.get('practiced'), list)
                        or any(not isinstance(problem, str) for problem in entry['practiced'])):
                    raise ValueError()
                if entry.get('completed_at'):
                    dt.datetime.fromisoformat(entry['completed_at'])
            except (ValueError, TypeError) as exc:
                raise ValueError('Invalid DSA progress. Your progress has not been reset.') from exc
    return data


def _initial(root, studied=None):
    courses = _json(studied or root / "data/reports/studied.json", [])
    plan = _json(root / ".research/learning/progress.json", {})
    if not isinstance(courses, list) or not isinstance(plan, dict):
        raise ValueError("Legacy learning progress is invalid. It has not been changed.")
    return _validate({"version": 1, "course": {p: {"done": True, "imported": True} for p in courses if isinstance(p, str)},
                      "documents": {}, "plan": plan, "history": []})


def transact(root, change=None, *, studied=None):
    root = Path(root)
    folder = root / ".memory"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "learning.json"
    with _lock, (folder / "learning.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        exists = path.exists()
        data = _validate(_json(path, None)) if exists else _initial(root, studied)
        before = json.dumps(data, sort_keys=True)
        if change:
            change(data)
        _validate(data)
        if not exists or before != json.dumps(data, sort_keys=True):
            name = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, prefix=".learning-", delete=False) as output:
                    name = output.name
                    json.dump(data, output, indent=2)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, path)
                descriptor = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
        return data


def stamp():
    return dt.datetime.now().astimezone().isoformat(timespec="microseconds")


def record(data, kind, identifier, title, done, *, at=None, day=None):
    at = at or stamp()
    bucket = data["course" if kind == "course" else "documents"]
    previous = bucket.get(identifier, {})
    if bool(previous.get("done")) == done:
        return
    bucket[identifier] = {"done": done, "title": title, "updated_at": at,
                          "completed_at": at if done else None}
    data["history"].append({"at": at, "kind": kind, "id": identifier, "title": title,
                            "action": "completed" if done else "reopened"})
    if day is not None:
        plan = data["plan"]
        days = set(plan.get("done", []))
        days.add(day) if done else days.discard(day)
        plan["done"] = sorted(days)
        plan.setdefault("start", at[:10])
        marked = plan.setdefault("marked", {})
        if done:
            marked[at[:10]] = day
        else:
            plan["marked"] = {date: n for date, n in marked.items() if n != day}


def set_course(root, path, done, title="", *, studied=None):
    return transact(root, lambda data: record(data, "course", path, title or path, done), studied=studied)


def set_document(root, identifier, title, done, day=None):
    def change(data):
        # A legacy plan completion already counts as complete; allow reopening it.
        if day in data["plan"].get("done", []) and identifier not in data["documents"]:
            data["documents"][identifier] = {"done": True, "imported": True, "title": title}
        record(data, "research", identifier, title, done, day=day)
    return transact(root, change)


def finish_plan_day(root, today):
    result = []
    def change(data):
        plan = data["plan"]
        if today in plan.get("marked", {}):
            result.append(int(plan["marked"][today]))
            return
        day = next((n for n in range(1, 91) if n not in plan.get("done", [])), 90)
        now = dt.datetime.now().astimezone()
        at = dt.datetime.combine(dt.date.fromisoformat(today), now.timetz()).isoformat(timespec="microseconds")
        record(data, "research", f"plan/day-{day}", f"Learning day {day}", True, at=at, day=day)
        result.append(day)
    transact(root, change)
    return result[0]
