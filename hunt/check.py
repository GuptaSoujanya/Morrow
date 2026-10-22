"""Harness-internal deterministic checks: git history hygiene and manifest inventory.

Both are pure functions over text so the liveness runner can prove both halves on
fixtures, and `hound run` feeds them real `git` and manifest output.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

from identity import normalize
from parse import _issue
from schema import Issue

SENSITIVE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"(^|/)\.env(\.|$)(?!example$)", "dotenv", "HIGH"),
    (r"\.(pem|key|p12|pfx|jks|keystore)$", "private-key-file", "HIGH"),
    (r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$", "ssh-key", "HIGH"),
    (r"(^|/)(credentials|secrets?|token)s?\.(json|ya?ml|txt|toml|ini)$", "credential-file", "HIGH"),
    (r"(^|/)cookies?\.(json|txt|pkl)$", "cookie-jar", "HIGH"),
    (r"\.(db|sqlite3?|sqlite-wal|sqlite-shm)$", "database-file", "MEDIUM"),
    (r"\.ipynb$", "notebook-with-outputs", "MEDIUM"),
    (r"(^|/)(naukriapplied|application_answers|applied|answers)[^/]*\.csv$", "personal-data-csv", "MEDIUM"),
    (r"(^|/)profile\.ya?ml$", "profile-data", "MEDIUM"),
    (r"(^|/)answers\.txt$", "answer-book", "MEDIUM"),
)

STDLIB: frozenset[str] = frozenset(sys.stdlib_module_names)

# import name -> distribution name, for the common mismatches.
IMPORT_ALIASES: dict[str, str] = {
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "PIL": "pillow",
    "dotenv": "python-dotenv",
    "markdown_it": "markdown-it-py",
    "webdriver_manager": "webdriver-manager",
    "dateutil": "python-dateutil",
    "pytest_socket": "pytest-socket",
}

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*?)\s*(#.*)?$")
_PIN = re.compile(r"^==\s*[0-9][^,\s]*$")


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def history_issues(paths: list[str], tracked: set[str] | None = None) -> list[Issue]:
    """Flag sensitive-looking paths that were ever committed. Still-tracked paths are noted."""
    issues: list[Issue] = []
    tracked = tracked or set()
    for path in sorted(set(paths)):
        for pattern, rule, severity in SENSITIVE_PATTERNS:
            if re.search(pattern, path):
                state = "still tracked" if path in tracked else "deleted or ignored now, but recoverable from history"
                issues.append(
                    _issue(
                        "history",
                        rule,
                        severity,
                        "secret",
                        path,
                        None,
                        f"committed:{path}",
                        f"sensitive-looking path was committed to git history ({state})",
                        {"tracked": path in tracked},
                    )
                )
                break
    return issues


def parse_requirements(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _REQ_LINE.match(line)
        if not match:
            continue
        spec = (match.group(3) or "").strip()
        out.append({"name": match.group(1), "spec": spec, "pinned": bool(_PIN.match(spec)), "line": lineno, "raw": raw})
    return out


def parse_freeze(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "==" in line and not line.startswith(("#", "-")):
            name, _, version = line.partition("==")
            out[_canon(name.strip())] = version.strip()
    return out


def top_level_imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def inventory_issues(
    manifest: str,
    manifest_path: str,
    freeze: dict[str, str] | None,
    imports: dict[str, set[str]],
    local_packages: set[str],
    lockfile_present: bool,
) -> list[Issue]:
    """Manifest hygiene over parsed inputs; every input is text, so both halves are provable."""
    issues: list[Issue] = []
    declared = parse_requirements(manifest)
    declared_names = {_canon(d["name"]) for d in declared}
    for dep in declared:
        if not dep["pinned"]:
            issues.append(
                _issue(
                    "inventory",
                    "unpinned-requirement",
                    "LOW",
                    "supply",
                    manifest_path,
                    dep["line"],
                    dep["raw"],
                    f"{dep['name']} is declared with a range, so installs are not reproducible",
                )
            )
    if declared and not lockfile_present:
        issues.append(
            _issue(
                "inventory",
                "no-lockfile",
                "MEDIUM",
                "supply",
                manifest_path,
                None,
                f"lockfile:{manifest_path}",
                "no lockfile pins the resolved dependency set; the scanned environment may drift from any install",
            )
        )
    if freeze is not None:
        for dep in declared:
            if _canon(dep["name"]) not in freeze:
                issues.append(
                    _issue(
                        "inventory",
                        "declared-not-installed",
                        "MEDIUM",
                        "error",
                        manifest_path,
                        dep["line"],
                        dep["raw"],
                        f"{dep['name']} is declared but absent from the project environment",
                    )
                )
    for path, names in sorted(imports.items()):
        for name in sorted(names):
            if name in STDLIB or name in local_packages or name.startswith("_"):
                continue
            dist = _canon(IMPORT_ALIASES.get(name, name))
            if dist in declared_names:
                continue
            installed = freeze is not None and dist in freeze
            issues.append(
                _issue(
                    "inventory",
                    "undeclared-import",
                    "MEDIUM" if not installed else "LOW",
                    "supply",
                    path,
                    None,
                    f"import {name}",
                    f"module '{name}' is imported but no requirement declares it"
                    + (" (present in the environment by accident)" if installed else " (not installed either)"),
                    {"distribution": dist, "installed": installed},
                )
            )
    return issues


def collect_imports(root: Path, python_files: list[Path]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in python_files:
        try:
            source = path.read_text("utf-8", "replace")
        except OSError:
            continue
        names = top_level_imports(source)
        if names:
            out[path.relative_to(root).as_posix()] = names
    return out


def describe(issue: Issue) -> str:
    return normalize(f"{issue.rule} {issue.path} {issue.message}")
