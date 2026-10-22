"""Content-anchored identity and digest helpers for the HOUND harness.

Issue identity is derived from instrument, rule, path, and a whitespace-normalized
anchor, never from line numbers, so it survives formatting and line drift.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

_WHITESPACE = re.compile(r"\s+")
ANCHOR_LIMIT = 400


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(paths: Iterable[Path], root: Path) -> str:
    """Digest of relative path plus content for every regular file, order independent."""
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def normalize(text: str) -> str:
    """Collapse whitespace so an anchor survives reformatting and line drift."""
    return _WHITESPACE.sub(" ", text).strip()[:ANCHOR_LIMIT]


def issue_id(instrument: str, rule: str, path: str, anchor: str) -> str:
    body = "\x1f".join([instrument, rule, path, normalize(anchor)])
    return "IS-" + sha256_text(body)[:12]


def record_id(
    instrument: str,
    argv: list[str],
    exit_code: int | None,
    stdout_digest: str,
    stderr_digest: str,
) -> str:
    body = "\x1f".join([instrument, "\x1e".join(argv), str(exit_code), stdout_digest, stderr_digest])
    return "EV-" + sha256_text(body)[:12]


def finding_id(issue_ids: Iterable[str]) -> str:
    return "HND-" + sha256_text("|".join(sorted(set(issue_ids))))[:10]


_SECRET_ASSIGN = re.compile(
    r"(?i)\b((?:[a-z_]*(?:password|passwd|secret|token|api_key|apikey|app_password)[a-z_]*))"
    r"(\s*[=:]\s*)(['\"])(?:(?!\3).)*\3"
)
REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Blank quoted values assigned to credential-looking names in captured output."""
    return _SECRET_ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}", text)


def issues_digest(issues: Iterable[dict[str, object]]) -> str:
    """Order-independent digest over every field of every normalized issue."""
    parts = sorted(json.dumps(issue, sort_keys=True, default=str) for issue in issues)
    return sha256_text("\n".join(parts))
