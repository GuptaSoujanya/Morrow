"""Bind lane hypotheses to verbatim code anchors.

A hypothesis becomes probe evidence only when every anchor it cites is found,
whitespace-insensitively, inside a window around the stated line of a file that
exists in the target. Everything else is recorded as pruned with its reason.
Failed lanes become named issues, never silent drops.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from identity import normalize
from parse import _issue
from schema import Issue

WINDOW = 40


def _collapse(text: str) -> str:
    """Whitespace-insensitive haystack; unlike identity.normalize it is never truncated."""
    return " ".join(text.split())


def _window(lines: list[str], line: int) -> str:
    lo = max(0, line - 1 - WINDOW)
    hi = min(len(lines), line - 1 + WINDOW + 1)
    return _collapse("\n".join(lines[lo:hi]))


def verify_anchor(root: Path, anchor: dict[str, Any]) -> tuple[bool, str]:
    path = anchor.get("path")
    snippet = anchor.get("snippet")
    line = anchor.get("line")
    if not isinstance(path, str) or not isinstance(snippet, str) or not snippet.strip():
        return False, "anchor needs path and a non-empty snippet"
    if not isinstance(line, int) or line < 1:
        return False, f"{path}: anchor line must be a positive integer"
    target = root / path
    if ".." in Path(path).parts or not target.is_file():
        return False, f"{path}: file does not exist in the target"
    try:
        text = target.read_text("utf-8", "replace")
    except OSError as exc:
        return False, f"{path}: unreadable ({exc})"
    lines = text.splitlines()
    needle = normalize(snippet)
    if needle in _window(lines, line):
        return True, "ok"
    if needle in _collapse(text):
        return False, f"{path}:{line}: snippet exists but not within {WINDOW} lines of the stated line"
    return False, f"{path}:{line}: snippet not found in file"


def load_lanes(probe_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    lanes: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(probe_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text("utf-8"))
        except (yaml.YAMLError, OSError):
            doc = {"lane": path.stem, "invalid": True}
        if not isinstance(doc, dict):
            doc = {"lane": path.stem, "invalid": True}
        lanes.append((path, doc))
    return lanes


def probe(root: Path, probe_dir: Path) -> tuple[list[Issue], list[dict[str, Any]], dict[str, Any]]:
    """Return (issues, pruned, report) over every lane file."""
    issues: list[Issue] = []
    pruned: list[dict[str, Any]] = []
    report: dict[str, Any] = {"lanes": [], "verified": 0, "rejected": 0, "lane_failures": 0}
    for path, doc in load_lanes(probe_dir):
        lane = str(doc.get("lane") or path.stem)
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        entry: dict[str, Any] = {"lane": lane, "file": rel, "hypotheses": [], "attempts": []}
        if doc.get("invalid"):
            issues.append(
                _issue(
                    "probe", "lane-invalid", "INFO", "none", rel, None, f"lane:{lane}", "lane file is not valid YAML"
                )
            )
            report["lanes"].append(entry)
            continue
        for name, attempt in sorted((doc.get("lane_run") or {}).items()):
            if not isinstance(attempt, dict):
                continue
            entry["attempts"].append({"attempt": name, **attempt})
            if attempt.get("status") != "completed":
                report["lane_failures"] += 1
                issues.append(
                    _issue(
                        "probe",
                        "lane-failure",
                        "INFO",
                        "none",
                        rel,
                        None,
                        f"lane:{lane}:{name}:{attempt.get('task', '')}",
                        f"lane {lane} {name} did not complete: {attempt.get('error', attempt.get('status'))}",
                        {"task": attempt.get("task"), "status": attempt.get("status")},
                    )
                )
        for item in doc.get("pruned") or []:
            if isinstance(item, dict):
                pruned.append({"lane": lane, "path": str(item.get("path", "")), "reason": str(item.get("reason", ""))})
        for hyp in doc.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            key = str(hyp.get("key") or "")
            anchors = hyp.get("anchors") or []
            problems: list[str] = []
            if not key:
                problems.append("hypothesis has no key")
            if not anchors:
                problems.append("hypothesis cites no anchors")
            for anchor in anchors:
                ok, reason = verify_anchor(root, anchor if isinstance(anchor, dict) else {})
                if not ok:
                    problems.append(reason)
            status = "verified" if not problems else "rejected"
            entry["hypotheses"].append({"key": key, "status": status, "problems": problems})
            if problems:
                report["rejected"] += 1
                pruned.append({"lane": lane, "path": f"hypothesis:{key}", "reason": "; ".join(problems)})
                continue
            report["verified"] += 1
            first = anchors[0]
            issues.append(
                _issue(
                    "probe",
                    key,
                    str(hyp.get("severity") or ""),
                    str(hyp.get("critical_class") or ""),
                    str(first.get("path")),
                    int(first["line"]) if isinstance(first.get("line"), int) else None,
                    str(first.get("snippet")),
                    str(hyp.get("title") or key),
                    {
                        "lane": lane,
                        "reachability": str(hyp.get("reachability") or ""),
                        "defect": str(hyp.get("defect") or ""),
                        "contract": str(hyp.get("contract") or ""),
                        "repro": str(hyp.get("repro") or ""),
                        "confidence": str(hyp.get("confidence") or ""),
                        "anchors": [
                            {"path": a.get("path"), "line": a.get("line"), "snippet": normalize(str(a.get("snippet")))}
                            for a in anchors
                            if isinstance(a, dict)
                        ],
                    },
                )
            )
        report["lanes"].append(entry)
    for issue in issues:
        issue.source = "lane"
    return issues, pruned, report
