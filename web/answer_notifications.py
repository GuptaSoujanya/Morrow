"""Validate private answer-save events and read the runner's actual answer sheet."""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from common import paths

PREFIX = "MORROW_ANSWER_EVENT "
MAX_EVENT_BYTES = 65536


def parse_event(line: str, token: str):
    if not line.startswith(PREFIX) or not token:
        return None
    try:
        event = json.loads(line[len(PREFIX):])
    except (ValueError, RecursionError):
        return None
    if not isinstance(event, dict) or set(event) != {"version", "id", "kind", "question", "answer", "source", "token"}:
        return None
    if type(event["version"]) is not int or event["version"] != 1 or event["kind"] != "answer_saved":
        return None
    if not isinstance(event["token"], str) or not event["token"].isascii() or not secrets.compare_digest(event["token"], token):
        return None
    if not isinstance(event["id"], str) or len(event["id"]) != 32 or any(c not in "0123456789abcdef" for c in event["id"]):
        return None
    for name, limit in (("question", 2000), ("answer", 8000), ("source", 200)):
        if not isinstance(event[name], str) or not event[name].strip() or len(event[name]) > limit:
            return None
    return {key: event[key] for key in ("id", "kind", "question", "answer", "source")}


def answers_path(root: Path, runner) -> Path:
    from .run_isolation import _settings
    from .state import Command

    command = Command("Agent answer sheet", ())
    runtime = runner.environment_provider(command, "answers") if runner.environment_provider else {}
    values = _settings(root, command, runtime)
    folder = paths.resolve(values.get("DATA_DIR") or "user/inputs", root)
    return (folder / "answers.txt").resolve()


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sheet_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {"name": "automation_answers", "path": "Agent answer sheet · answers.txt", "text": text,
            "revision": revision(text), "scope": "automation"}
