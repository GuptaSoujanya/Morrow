"""Both-halves liveness: every required check must be clean on a clean fixture and
fire on a planted positive fixture. A check that cannot fire is inert, and an inert
required check is a broken instrument.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from check import history_issues, inventory_issues
from identity import sha256_file
from parse import parse
from probe import verify_anchor
from registry import Context, Instrument
from runner import execute

HALVES = ("clean", "positive")

CLEAN_MANIFEST = "six==1.17.0\n"
POSITIVE_MANIFEST = "requests>=2.0\nsix==1.17.0\n"


def _copy_half(ctx: Context, instrument: Instrument, half: str) -> Path:
    src = ctx.fixture / half
    dst = ctx.results / "liveness" / instrument.name / half
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def _git_fixture(ctx: Context, instrument: Instrument, half: str) -> Path:
    repo = _copy_half(ctx, instrument, half)
    env = {
        **{k: v for k, v in os.environ.items() if k.startswith(("PATH", "HOME"))},
        "GIT_AUTHOR_NAME": "hound",
        "GIT_AUTHOR_EMAIL": "hound@localhost",
        "GIT_COMMITTER_NAME": "hound",
        "GIT_COMMITTER_EMAIL": "hound@localhost",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture", "--no-gpg-sign"]):
        subprocess.run(["git", *args], cwd=str(repo), env=env, capture_output=True, check=False, timeout=60)
    return repo


def _targets(instrument: Instrument, half: str) -> list[str]:
    name = instrument.name
    if name == "quality":
        return [half]
    if name == "semgrep":
        return ["app.py", "web.js", "run.sh"]
    if name in ("bandit", "ruff"):
        return ["app.py"]
    if name == "shellcheck":
        return ["run.sh"]
    if name in ("gitleaks-git", "gitleaks-dir"):
        return ["."]
    if name == "trivy-python":
        return ["supply/python"]
    if name == "trivy-node":
        return ["supply/node"]
    if name == "trivy-config":
        return ["container"]
    if name == "pytest-target":
        return ["sandbox/test_pass.py"] if half == "clean" else ["sandbox/test_fire.py"]
    if name == "sandbox":
        return ["sandbox"]
    if name == "node-test":
        return ["nodetest"]
    if name == "oxlint":
        return ["node"]
    if name == "tsc":
        return ["node/good.ts"] if half == "clean" else ["node/bad.ts"]
    return []


INTERNAL_CHECKS = ("history", "inventory", "probe")


def _internal(instrument: Instrument, half: str, fixture: Path) -> int:
    """Issue count from a harness-internal check over fixture inputs."""
    positive = half == "positive"
    if instrument.name == "history":
        paths = [".env", "legacy/id_rsa", "data/app.db"] if positive else ["README.md", "src/app.py", ".env.example"]
        return len(history_issues(paths, {".env"} if positive else set()))
    if instrument.name == "inventory":
        manifest = POSITIVE_MANIFEST if positive else CLEAN_MANIFEST
        imports = {"app.py": {"os", "selenium"}} if positive else {"app.py": {"os", "six"}}
        freeze = {"six": "1.17.0"}
        return len(inventory_issues(manifest, "requirements.txt", freeze, imports, {"app"}, not positive))
    if instrument.name == "probe":
        anchor = {"path": "app.py", "line": 1, "snippet": "def add(" if not positive else "nothing like this"}
        ok, _ = verify_anchor(fixture / "clean", anchor)
        return 0 if ok else 1
    return -1


def run(ctx: Context, instruments: list[Instrument]) -> list[dict[str, Any]]:
    """Run both halves for every applicable instrument and return liveness entries."""
    out: list[dict[str, Any]] = []
    for instrument in instruments:
        entry: dict[str, Any] = {"instrument": instrument.name, "required": instrument.required, "halves": {}}
        if instrument.kind == "internal" or instrument.name in INTERNAL_CHECKS:
            for half in HALVES:
                count = _internal(instrument, half, ctx.fixture)
                entry["halves"][half] = {"issues": count, "status": "ok" if count >= 0 else "unsupported"}
            entry["clean"] = entry["halves"]["clean"]["issues"] == 0
            entry["positive"] = entry["halves"]["positive"]["issues"] > 0
            out.append(entry)
            continue
        for half in HALVES:
            if instrument.name == "gitleaks-git":
                root = _git_fixture(ctx, instrument, half)
            else:
                root = _copy_half(ctx, instrument, half)
            local = replace(
                ctx,
                root=root,
                python_dirs=["app.py"],
                js_targets=["web.js"],
                shell_targets=["run.sh"],
                node_project=root / "node" if instrument.kind == "node" else ctx.node_project,
                staged={},
            )
            raw = ctx.results / "raw" / "liveness" / f"{instrument.name}.{half}.json"
            if raw.exists():
                raw.unlink()
            execution = execute(
                instrument, local, _targets(instrument, half), raw, label=f"liveness-{instrument.name}-{half}"
            )
            parser, issues = parse(instrument.name, raw, execution.stdout, root, None)
            if instrument.name == "quality" and half == "positive" and len(issues) != 4:
                parser = "failed"
            entry["halves"][half] = {
                "argv": execution.argv,
                "cwd": execution.cwd,
                "exit_code": execution.exit_code,
                "status": execution.status,
                "parser": parser,
                "issues": len(issues),
                "rules": sorted({issue.rule for issue in issues})[:12],
                "raw": [
                    p.relative_to(ctx.root).as_posix() if p.is_relative_to(ctx.root) else str(p) for p in execution.raw
                ],
                "raw_digests": {p.relative_to(ctx.root).as_posix(): sha256_file(p) for p in execution.raw},
                "note": execution.note,
            }
        clean = entry["halves"]["clean"]
        positive = entry["halves"]["positive"]
        entry["clean"] = clean["status"] == "ok" and clean["parser"] == "ok" and clean["issues"] == 0
        entry["positive"] = positive["status"] == "ok" and positive["parser"] == "ok" and positive["issues"] > 0
        out.append(entry)
    return out
