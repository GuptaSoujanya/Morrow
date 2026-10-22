"""Phase 0: derive the hunt scope from what is on disk.

Inventory respects .gitignore through `git ls-files`, classifies ecosystems from
manifests and file kinds, derives the instrument set, stages non-scannable inputs
(notebook code cells, inline scripts, the frozen environment) under results/, and
names every surface that no automated instrument covers as a coverage gap.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from identity import sha256_file, sha256_text
from registry import EXCLUDES, Context, Instrument, applicable, argv, default_targets, locate, node_test_targets
from runner import git
from schema import SCOPE_SCHEMA

SHEBANG = re.compile(rb"^#!.*\b(ba|z|da)?sh\b")

# Surfaces whose behaviour no local instrument can exercise. Each is a named gap.
UNINSTRUMENTED: dict[str, str] = {
    "selenium": "browser automation against live third-party sites; no automated instrument drives it",
    "llm-cli": "shells out to an external AI CLI (claude or kiro); its runtime behaviour is not exercised",
    "launchd": "launchd plist installation and scheduling; not exercised on the audit host",
    "smtp-imap": "live mail sending and mailbox polling; not exercised",
    "telegram": "outbound Telegram notifications; not exercised",
    "latex": "external TeX compiler invocation; not exercised",
}


def _tracked(root: Path) -> tuple[list[str], list[str]]:
    code, out = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = [f for f in out.split("\0") if f] if code == 0 else []
    code, out = git(root, "ls-files", "--cached", "-z")
    cached = [f for f in out.split("\0") if f] if code == 0 else []
    return files, cached


def _excluded(rel: str) -> bool:
    head = rel.split("/", 1)[0]
    return head in EXCLUDES or "/node_modules/" in rel or "/__pycache__/" in rel


def _is_shell(root: Path, rel: str) -> bool:
    if rel.endswith(".sh"):
        return True
    path = root / rel
    if "." in Path(rel).name or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return bool(SHEBANG.match(handle.readline()))
    except OSError:
        return False


def _stage_notebook(root: Path, rel: str, staged_dir: Path) -> Path | None:
    try:
        doc = json.loads((root / rel).read_text("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    chunks: list[str] = [f"# staged from {rel}; code cells only, in order\n"]
    for cell in doc.get("cells") or []:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source") or []
        text = "".join(source) if isinstance(source, list) else str(source)
        body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("%", "!")))
        chunks.append(body + "\n")
    out = staged_dir / "notebook" / (Path(rel).stem.replace(" ", "_") + ".py")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(chunks), "utf-8")
    return out


_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
_FENCE = re.compile(r"```(?:js|javascript|html)\n(.*?)```", re.S)


def _stage_inline(root: Path, rels: list[str], staged_dir: Path) -> tuple[Path | None, dict[str, str]]:
    remap: dict[str, str] = {}
    out_dir = staged_dir / "inline-js"
    written = False
    for rel in rels:
        try:
            text = (root / rel).read_text("utf-8", "replace")
        except OSError:
            continue
        blocks = _SCRIPT.findall(text) if rel.endswith((".html", ".htm")) else []
        if rel.endswith(".md"):
            blocks = _SCRIPT.findall(text) + _FENCE.findall(text)
        if not blocks:
            continue
        out = out_dir / (rel.replace("/", "__") + ".js")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(blocks), "utf-8")
        remap[out.relative_to(root).as_posix()] = rel
        written = True
    return (out_dir if written else None), remap


def _freeze(target_python: Path | None, staged_dir: Path) -> Path | None:
    if target_python is None:
        return None
    try:
        completed = subprocess.run(
            [str(target_python), "-m", "pip", "freeze", "--disable-pip-version-check"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    out = staged_dir / "freeze" / "requirements.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(completed.stdout, "utf-8")
    return out.parent


def _surface(name: str, kind: str, paths: list[str], note: str, uses: list[str]) -> dict[str, Any]:
    return {"name": name, "kind": kind, "files": len(paths), "note": note, "uses": sorted(uses), "instruments": []}


def _uses(root: Path, rels: list[str]) -> set[str]:
    uses: set[str] = set()
    for rel in rels:
        if not rel.endswith((".py", ".sh")):
            continue
        try:
            text = (root / rel).read_text("utf-8", "replace")
        except OSError:
            continue
        if "selenium" in text or "webdriver" in text:
            uses.add("selenium")
        if re.search(r"\b(claude|kiro)\b", text) and "subprocess" in text:
            uses.add("llm-cli")
        if "launchctl" in text or "LaunchAgents" in text:
            uses.add("launchd")
        if "smtplib" in text or "imaplib" in text:
            uses.add("smtp-imap")
        if "api.telegram.org" in text:
            uses.add("telegram")
        if "TEX_COMPILER" in text or "tectonic" in text:
            uses.add("latex")
    return uses


def build(root: Path, hunt: Path, previous: dict[str, Any] | None = None) -> tuple[Context, dict[str, Any]]:
    results = hunt / "results"
    staged_dir = results / "staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    files, cached = _tracked(root)
    files = [f for f in files if not _excluded(f)]
    by_ext: dict[str, int] = {}
    for rel in files:
        by_ext[Path(rel).suffix or "(none)"] = by_ext.get(Path(rel).suffix or "(none)", 0) + 1

    python_files = [f for f in files if f.endswith(".py")]
    shell_targets = sorted(f for f in files if _is_shell(root, f))
    js_targets = sorted(f for f in files if f.endswith((".js", ".mjs", ".ts", ".tsx", ".html")))
    notebooks = [f for f in files if f.endswith(".ipynb")]
    markdown = [f for f in files if f.endswith(".md")]
    manifests = sorted(
        f
        for f in files
        if Path(f).name in ("requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "Dockerfile")
        or Path(f).name.startswith("docker-compose")
    )
    lockfiles = sorted(
        f
        for f in files
        if Path(f).name in ("uv.lock", "poetry.lock", "package-lock.json", "Pipfile.lock", "requirements.lock")
    )

    ecosystems: set[str] = set()
    if python_files or any(Path(m).name in ("requirements.txt", "pyproject.toml") for m in manifests):
        ecosystems.add("python")
    if shell_targets:
        ecosystems.add("shell")
    if js_targets:
        ecosystems.add("web")
    if markdown:
        ecosystems.add("docs")
    node_project: Path | None = None
    for manifest in manifests:
        if Path(manifest).name == "package.json" and "/node_modules/" not in manifest:
            node_project = (root / manifest).parent
            ecosystems.add("javascript")
            break
    if notebooks:
        ecosystems.add("python")

    sha_code, sha_out = git(root, "rev-parse", "HEAD")
    conditions: set[str] = set()
    if sha_code == 0 and (root / ".git").exists():
        conditions.add("git-history")
    target_python: Path | None = None
    for candidate in (root / "venv" / "bin" / "python3", root / ".venv" / "bin" / "python3"):
        if candidate.exists():
            target_python = candidate
            break
    if target_python is not None:
        conditions.add("python-environment")
    if any(f.startswith("tests/") and Path(f).name.startswith("test_") for f in files):
        conditions.add("python-tests")
    if node_project is not None and (node_project / "node_modules" / ".bin").is_dir():
        conditions.add("node-project")
    if node_project is not None and (node_project / "package-lock.json").exists():
        conditions.add("node-lockfile")
    if node_project is not None and node_test_targets(node_project):
        conditions.add("node-tests")
    # tsc and oxlint are only owed to a project that is written for them.
    if node_project is not None and any(node_project.glob("tsconfig*.json")):
        conditions.add("node-typescript")
    if node_project is not None and any(node_project.glob(".oxlintrc*")):
        conditions.add("node-oxlint")
    if any((hunt / "sandbox").glob("test_*.py")):
        conditions.add("sandbox-reproductions")

    python_dirs = sorted({f.split("/", 1)[0] if "/" in f else f for f in python_files})
    staged: dict[str, Path] = {}
    remap: dict[str, str] = {}
    for notebook in notebooks:
        path = _stage_notebook(root, notebook, staged_dir)
        if path is not None:
            staged["notebook"] = path
            remap[path.relative_to(root).as_posix()] = notebook
    inline_dir, inline_map = _stage_inline(root, [f for f in files if f.endswith((".html", ".md"))], staged_dir)
    if inline_dir is not None:
        staged["inline-js"] = inline_dir
        remap.update(inline_map)
    freeze = _freeze(target_python, staged_dir)
    if freeze is not None:
        staged["freeze"] = freeze
    if node_project is not None and (node_project / "package-lock.json").exists():
        staged["node-lock"] = node_project / "package-lock.json"

    ctx = Context(
        root=root,
        hunt=hunt,
        results=results,
        rule=hunt / "rule",
        fixture=hunt / "fixture",
        ecosystems=ecosystems,
        conditions=conditions,
        python_dirs=python_dirs,
        js_targets=js_targets,
        shell_targets=shell_targets,
        node_project=node_project,
        target_python=target_python,
        staged=staged,
    )

    instruments = applicable(ctx)
    by_dir: dict[str, list[str]] = {}
    for rel in files:
        by_dir.setdefault(rel.split("/", 1)[0] if "/" in rel else "(root)", []).append(rel)
    surfaces: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for name, rels in sorted(by_dir.items()):
        kinds: list[str] = []
        if any(r.endswith(".py") for r in rels):
            kinds.append("python")
        if any(r in shell_targets for r in rels):
            kinds.append("shell")
        if any(r.endswith((".html", ".js")) for r in rels):
            kinds.append("web")
        if any(r.endswith(".ipynb") for r in rels):
            kinds.append("notebook")
        if any(r.endswith(".md") for r in rels):
            kinds.append("docs")
        if any(r.endswith(".csv") for r in rels):
            kinds.append("data")
        uses = _uses(root, rels)
        surface = _surface(name, "+".join(kinds) or "other", rels, "", sorted(uses))
        covering = [
            i.name
            for i in instruments
            if (
                ("python" in kinds and "python" in i.ecosystems)
                or ("shell" in kinds and "shell" in i.ecosystems)
                or ("web" in kinds and i.name in ("semgrep", "gitleaks-dir", "gitleaks-git", "history"))
                or ("docs" in kinds and i.ecosystems and "docs" in i.ecosystems)
                or ("notebook" in kinds and i.name in ("semgrep", "bandit", "ruff"))
                or ("data" in kinds and i.name in ("gitleaks-dir", "gitleaks-git", "history"))
            )
        ]
        surface["instruments"] = sorted(set(covering))
        surface["untracked"] = sum(1 for r in rels if r not in cached)
        if not covering:
            gaps.append({"surface": name, "gap": "no automated instrument covers this surface", "cap": "HOLD"})
        for use in sorted(uses):
            gaps.append({"surface": name, "gap": f"{use}: {UNINSTRUMENTED[use]}", "cap": "HOLD"})
        surfaces.append(surface)

    for instrument in instruments:
        if locate(instrument, ctx) is None:
            gaps.append(
                {
                    "surface": instrument.name,
                    "gap": f"required instrument '{instrument.name}' ({instrument.binary}) is not available",
                    "cap": instrument.cap_when_absent,
                }
            )

    if node_project is not None and "node-tests" not in conditions:
        try:
            script = json.loads((node_project / "package.json").read_text()).get("scripts", {}).get("test", "")
        except (OSError, ValueError, AttributeError):
            script = ""
        if script:
            gaps.append(
                {
                    "surface": node_project.relative_to(root).as_posix(),
                    "gap": f"test script '{script}' needs a browser runner the harness does not drive",
                    "cap": "HOLD",
                }
            )

    dirty_code, porcelain = git(root, "status", "--porcelain", "--untracked-files=all")
    dirty_lines = [line for line in porcelain.splitlines() if line.strip()] if dirty_code == 0 else []
    if dirty_lines:
        gaps.append({"surface": "(tree)", "gap": f"working tree is dirty ({len(dirty_lines)} entries)", "cap": "HOLD"})
    branch_code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    remote_code, remote = git(root, "remote", "get-url", "origin")

    gitignore = root / ".gitignore"
    ignore_lines = gitignore.read_text("utf-8", "replace").splitlines() if gitignore.exists() else []

    policy: list[dict[str, Any]] = []
    for instrument in instruments:
        raw = results / "raw" / f"{instrument.name}.json"
        policy.append(
            {
                "name": instrument.name,
                "category": instrument.category,
                "required": instrument.required,
                "critical": list(instrument.critical),
                "evidence_class": instrument.evidence_class,
                "timeout_s": instrument.timeout_s,
                "database": instrument.database,
                "cap_when_absent": instrument.cap_when_absent,
                "available": locate(instrument, ctx) is not None,
                "argv": argv(instrument, ctx, default_targets(instrument, ctx), raw),
                "targets": default_targets(instrument, ctx),
            }
        )

    configs = {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted((hunt / "rule").iterdir()) if p.is_file()}

    doc: dict[str, Any] = {
        "schema": SCOPE_SCHEMA,
        "generated": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "target": {
            "root": str(root),
            "sha": sha_out.strip() if sha_code == 0 else None,
            "branch": branch.strip() if branch_code == 0 else None,
            "remote": remote.strip() if remote_code == 0 else None,
            "dirty": bool(dirty_lines),
            "dirty_entries": len(dirty_lines),
            "porcelain_digest": sha256_text("\n".join(sorted(dirty_lines))),
        },
        "inventory": {
            "files": len(files),
            "tracked": len([f for f in files if f in set(cached)]),
            "untracked": len([f for f in files if f not in set(cached)]),
            "by_extension": dict(sorted(by_ext.items())),
            "manifests": manifests,
            "lockfiles": lockfiles,
            "notebooks": notebooks,
            "python_dirs": python_dirs,
            "shell_targets": shell_targets,
            "js_targets": js_targets,
        },
        "ecosystems": sorted(ecosystems),
        "conditions": sorted(conditions),
        "product_types": _product_types(root, files),
        "surfaces": surfaces,
        "instruments": policy,
        "staged": {key: path.relative_to(root).as_posix() for key, path in staged.items()},
        "remap": remap,
        "configs": configs,
        "ignore": {
            "excluded_roots": list(EXCLUDES),
            "gitignore_entries": ignore_lines,
            "note": "scans walk tracked plus untracked-not-ignored files; ignored directories such as data/ "
            "and venv/ are out of scope except where gitleaks-dir walks the working tree under its allowlist",
        },
        "gaps": gaps,
        "ambiguities": _ambiguities(root, files),
        "harness": {"python": sys.version.split()[0]},
        "iteration": _iteration(previous, surfaces),
    }
    return ctx, doc


def _product_types(root: Path, files: list[str]) -> list[str]:
    types: list[str] = []
    joined = " ".join(files)
    if "naukri_bot/" in joined:
        types.append("job-board auto-apply bot (selenium)")
    if "web/server.py" in joined:
        types.append("local web control site (http.server)")
    if "linkedin_bot/" in joined:
        types.append("daily LinkedIn poster")
    if "sites_bot/" in joined:
        types.append("company-site apply, browser agent, cold email")
    if "pipeline/" in joined:
        types.append("daily pipeline orchestrator with AI CLI")
    if "course/index.html" in joined:
        types.append("docs site (docsify) with inline scripts")
    if "scripts/" in joined:
        types.append("shell launchers and launchd installers")
    if "legacy/" in joined:
        types.append("legacy scripts and notebook")
    return types


def _ambiguities(root: Path, files: list[str]) -> list[str]:
    out: list[str] = []
    untracked_dirs = sorted({f.split("/", 1)[0] for f in files if "/" in f})
    if "pipeline" in untracked_dirs:
        out.append(
            "pipeline/ and common/ai_cli.py, common/memory.py are untracked: "
            "in scope as deliverable code, provenance unverifiable"
        )
    if (root / ".env").exists():
        out.append(
            ".env exists in the working tree (ignored); gitleaks-dir scope excludes it by allowlist, "
            "history checks cover whether it was ever committed"
        )
    return out


def _iteration(previous: dict[str, Any] | None, surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    log: list[dict[str, Any]] = list((previous or {}).get("iteration") or [])
    stamp = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    if previous is None:
        log.append({"date": stamp, "kind": "fresh", "surfaces": [s["name"] for s in surfaces]})
        return log
    before = {s["name"]: s for s in previous.get("surfaces") or []}
    after = {s["name"]: s for s in surfaces}
    unchanged = sorted(n for n in before if n in after and before[n].get("files") == after[n].get("files"))
    changed = sorted(n for n in before if n in after and before[n].get("files") != after[n].get("files"))
    removed = sorted(n for n in before if n not in after)
    added = sorted(n for n in after if n not in before)
    log.append(
        {
            "date": stamp,
            "kind": "update",
            "unchanged": unchanged,
            "changed": changed,
            "removed": removed,
            "added": added,
        }
    )
    return log


def dump(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=False, width=120)


def write(path: Path, doc: dict[str, Any]) -> str:
    text = dump(doc)
    path.write_text(text, "utf-8")
    return sha256_text(text)


def load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        doc = yaml.safe_load(path.read_text("utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def instruments_for(ctx: Context) -> list[Instrument]:
    return applicable(ctx)
