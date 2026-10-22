"""Target, environment, tool, config, and database provenance with pin verification."""

from __future__ import annotations

import datetime as dt
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from identity import sha256_file, sha256_paths, sha256_text
from registry import Context, Instrument, locate
from runner import git
from schema import PROVENANCE_SCHEMA

HARNESS_GLOBS: tuple[str, ...] = (
    "*.py",
    "pyproject.toml",
    "uv.lock",
    "rule/*",
    "fixture/**/*",
    "test/*.py",
    "sandbox/*.py",
)


def _version(binary: Path | None, *flags: str) -> str | None:
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [str(binary), *flags],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).strip()
    return text.splitlines()[0][:120] if text else None


def _binary(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    real = path.resolve()
    return {"path": str(path), "resolved": str(real), "sha256": sha256_file(real) if real.is_file() else None}


def harness_digest(hunt: Path) -> str:
    paths: list[Path] = []
    for pattern in HARNESS_GLOBS:
        paths.extend(p for p in hunt.glob(pattern) if p.is_file() and "__pycache__" not in p.parts)
    return sha256_paths(paths, hunt)


def trivy_db(results: Path) -> dict[str, Any]:
    meta = results / "trivy" / "db" / "metadata.json"
    db = results / "trivy" / "db" / "trivy.db"
    if not meta.exists() or not db.exists():
        return {"pinned": False, "reason": "trivy database not present under hunt/results/trivy; run `hound provision`"}
    try:
        parsed = json.loads(meta.read_text("utf-8"))
    except ValueError:
        return {"pinned": False, "reason": "trivy metadata.json unparsable"}
    return {
        "pinned": True,
        "metadata_sha256": sha256_file(meta),
        "db_size": db.stat().st_size,
        "db_sha256": sha256_file(db),
        "version": parsed.get("Version"),
        "updated_at": parsed.get("UpdatedAt"),
        "next_update": parsed.get("NextUpdate"),
        "downloaded_at": parsed.get("DownloadedAt"),
    }


def semgrep_rules(rule: Path) -> dict[str, Any]:
    frozen = rule / "semgrep.yaml"
    lock = rule / "semgrep.lock.json"
    custom = rule / "custom.yaml"
    if not frozen.exists() or not lock.exists():
        return {"pinned": False, "reason": "frozen semgrep ruleset or its lock is missing"}
    try:
        lock_doc = json.loads(lock.read_text("utf-8"))
    except ValueError:
        return {"pinned": False, "reason": "semgrep.lock.json unparsable"}
    digest = sha256_file(frozen)
    expected = lock_doc.get("semgrep_yaml_sha256")
    pinned = expected == digest
    return {
        "pinned": pinned,
        "reason": None if pinned else "semgrep.yaml digest does not match semgrep.lock.json",
        "frozen": lock_doc.get("frozen"),
        "semgrep_yaml_sha256": digest,
        "custom_yaml_sha256": sha256_file(custom) if custom.exists() else None,
        "packs": lock_doc.get("packs"),
        "total_rules": lock_doc.get("total_rules"),
    }


def build(ctx: Context, instruments: list[Instrument], scope_digest: str, scope_path: Path) -> dict[str, Any]:
    root = ctx.root
    sha_code, sha_out = git(root, "rev-parse", "HEAD")
    dirty_code, porcelain = git(root, "status", "--porcelain", "--untracked-files=all")
    dirty_lines = sorted(line for line in porcelain.splitlines() if line.strip()) if dirty_code == 0 else []
    branch_code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    remote_code, remote = git(root, "remote", "get-url", "origin")
    count_code, count = git(root, "rev-list", "--all", "--count")

    tools: dict[str, Any] = {}
    seen: set[str] = set()
    for instrument in instruments:
        if instrument.kind == "internal" or instrument.binary in seen:
            continue
        seen.add(instrument.binary)
        located = locate(instrument, ctx)
        tools[instrument.binary] = {
            "kind": instrument.kind,
            "binary": _binary(located),
            "version": _version(located, "--version") if located else None,
        }
    for name in ("git", "uv"):
        found = shutil.which(name)
        tools[name] = {
            "kind": "host",
            "binary": _binary(Path(found) if found else None),
            "version": _version(Path(found) if found else None, "--version"),
        }
    tools["python-hunt"] = {"kind": "venv", "binary": _binary(Path(sys.executable)), "version": sys.version.split()[0]}
    if ctx.target_python:
        tools["python-target"] = {
            "kind": "target-venv",
            "binary": _binary(ctx.target_python),
            "version": _version(ctx.target_python, "--version"),
        }

    configs = {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(ctx.rule.iterdir()) if p.is_file()}
    databases = {
        "semgrep": semgrep_rules(ctx.rule),
        "trivy": trivy_db(ctx.results),
        "gitleaks": {
            "pinned": tools.get("gitleaks", {}).get("binary") is not None,
            "reason": None if tools.get("gitleaks", {}).get("binary") else "gitleaks binary absent",
            "note": "default rules are embedded in the binary; the binary digest pins them",
        },
    }
    needed = {i.binary for i in instruments if i.database}
    unpinned = [name for name, db in databases.items() if name in needed and not db.get("pinned")]
    lock = ctx.hunt / "uv.lock"
    pyproject = ctx.hunt / "pyproject.toml"
    return {
        "schema": PROVENANCE_SCHEMA,
        "generated": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "target": {
            "root": str(root),
            "sha": sha_out.strip() if sha_code == 0 else None,
            "branch": branch.strip() if branch_code == 0 else None,
            "remote": remote.strip() if remote_code == 0 else None,
            "commits": int(count.strip()) if count_code == 0 and count.strip().isdigit() else None,
            "dirty": bool(dirty_lines),
            "dirty_entries": dirty_lines,
            "porcelain_digest": sha256_text("\n".join(dirty_lines)),
        },
        "scope": {"path": scope_path.relative_to(root).as_posix(), "sha256": scope_digest},
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "hunt_python": sys.version.split()[0],
            "uv_lock_sha256": sha256_file(lock) if lock.exists() else None,
            "pyproject_sha256": sha256_file(pyproject) if pyproject.exists() else None,
            "harness_sha256": harness_digest(ctx.hunt),
        },
        "tools": tools,
        "configs": configs,
        "databases": databases,
        "pinned": not unpinned,
        "unpinned": unpinned,
    }


def dump(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=False, width=120)


def write(path: Path, doc: dict[str, Any]) -> str:
    text = dump(doc)
    path.write_text(text, "utf-8")
    return sha256_text(text)
