"""Parsers: raw scanner artifacts to normalized issues with content-anchored identity.

Every parser returns a parser status and a list of issues. Unknown severities fail
closed to MEDIUM; unknown classes map to `none`. Parsers never raise on bad input;
they return status `failed` so the verifier can cap the run.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from identity import issue_id, normalize, redact
from schema import Issue, floor_severity, normalize_class

Parsed = tuple[str, list[Issue]]

_SEMGREP_SEVERITY = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
_SHELLCHECK_SEVERITY = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW", "style": "INFO"}
_SHELLCHECK_CLASS = {
    2086: "injection",
    2046: "injection",
    2068: "injection",
    2048: "injection",
    2115: "logic",
    2114: "logic",
    2164: "error",
    2181: "error",
    2155: "error",
    2015: "logic",
    2034: "logic",
    2016: "logic",
    2129: "logic",
}
_RUFF_CLASS = {"F": "logic", "E": "logic", "PLE": "logic", "B": "error"}
_BANDIT_CLASS = {
    "B102": "injection",
    "B103": "api_misuse",
    "B104": "auth",
    "B105": "secret",
    "B106": "secret",
    "B107": "secret",
    "B108": "lifecycle",
    "B110": "error",
    "B112": "error",
    "B113": "api_misuse",
    "B201": "auth",
    "B301": "injection",
    "B302": "injection",
    "B303": "api_misuse",
    "B304": "api_misuse",
    "B305": "api_misuse",
    "B306": "lifecycle",
    "B307": "injection",
    "B308": "injection",
    "B310": "injection",
    "B311": "api_misuse",
    "B312": "api_misuse",
    "B313": "injection",
    "B314": "injection",
    "B315": "injection",
    "B316": "injection",
    "B317": "injection",
    "B318": "injection",
    "B319": "injection",
    "B320": "injection",
    "B321": "api_misuse",
    "B323": "api_misuse",
    "B324": "api_misuse",
    "B501": "api_misuse",
    "B502": "api_misuse",
    "B503": "api_misuse",
    "B504": "api_misuse",
    "B505": "api_misuse",
    "B506": "injection",
    "B507": "api_misuse",
    "B508": "api_misuse",
    "B509": "api_misuse",
    "B601": "injection",
    "B602": "injection",
    "B603": "injection",
    "B604": "injection",
    "B605": "injection",
    "B606": "injection",
    "B607": "injection",
    "B608": "injection",
    "B609": "injection",
    "B610": "injection",
    "B611": "injection",
    "B701": "injection",
    "B702": "injection",
    "B703": "injection",
}
_CLASS_HINTS: tuple[tuple[str, str], ...] = (
    ("hound_class:", ""),
    ("command-injection", "injection"),
    ("sql-injection", "injection"),
    ("sqli", "injection"),
    ("injection", "injection"),
    ("ssrf", "injection"),
    ("traversal", "injection"),
    ("xss", "injection"),
    ("eval", "injection"),
    ("exec", "injection"),
    ("deserial", "injection"),
    ("pickle", "injection"),
    ("yaml", "injection"),
    ("subprocess", "injection"),
    ("shell", "injection"),
    ("template", "injection"),
    ("secret", "secret"),
    ("hardcoded", "secret"),
    ("password", "secret"),
    ("token", "secret"),
    ("api-key", "secret"),
    ("private-key", "secret"),
    ("credential", "secret"),
    ("jwt", "auth"),
    ("auth", "auth"),
    ("csrf", "auth"),
    ("session", "auth"),
    ("cookie", "auth"),
    ("crypto", "api_misuse"),
    ("cipher", "api_misuse"),
    ("hash", "api_misuse"),
    ("md5", "api_misuse"),
    ("sha1", "api_misuse"),
    ("tls", "api_misuse"),
    ("ssl", "api_misuse"),
    ("insecure-transport", "api_misuse"),
    ("verify", "api_misuse"),
    ("random", "api_misuse"),
    ("tempfile", "lifecycle"),
    ("resource", "lifecycle"),
    ("race", "concurrency"),
    ("thread", "concurrency"),
    ("except", "error"),
    ("exception", "error"),
)


def _load_json(raw: Path | None, stdout: str) -> Any:
    text = ""
    if raw is not None and raw.exists():
        text = raw.read_text("utf-8", "replace")
    if not text.strip():
        text = stdout
    if not text.strip():
        return None
    return json.loads(text)


def _line_at(root: Path | None, rel: str, line: int | None) -> str:
    if root is None or line is None or line < 1:
        return ""
    path = root / rel
    try:
        lines = path.read_text("utf-8", "replace").splitlines()
    except OSError:
        return ""
    if line > len(lines):
        return ""
    return lines[line - 1].strip()


def _remap(path: str, remap: dict[str, str] | None) -> str:
    if not remap:
        return path
    for staged, origin in remap.items():
        if path == staged or path.startswith(staged + "/"):
            return origin + path[len(staged) :]
    return path


def _hint_class(text: str) -> str:
    lower = text.lower()
    for needle, klass in _CLASS_HINTS:
        if needle and needle in lower and klass:
            return klass
    return "none"


def _issue(
    instrument: str,
    rule: str,
    severity: str | None,
    klass: str | None,
    path: str,
    line: int | None,
    anchor: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> Issue:
    anchor_text = normalize(anchor) or f"{rule}@{path}"
    return Issue(
        id=issue_id(instrument, rule, path, anchor_text),
        instrument=instrument,
        rule=rule,
        severity=floor_severity(severity),
        critical_class=normalize_class(klass),
        path=path,
        line=line,
        anchor=anchor_text,
        message=redact(normalize(message))[:400],
        extra=extra or {},
    )


_SEMGREP_HIDDEN = {"requires login", ""}


def parse_semgrep(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(raw, stdout)
    except ValueError:
        return "failed", []
    if not isinstance(doc, dict) or "results" not in doc:
        return "failed", []
    issues: list[Issue] = []
    for result in doc.get("results") or []:
        if not isinstance(result, dict):
            continue
        extra = result.get("extra") or {}
        meta = extra.get("metadata") or {}
        rule = str(result.get("check_id", "semgrep"))
        path = _remap(str(result.get("path", "")), remap)
        line = (result.get("start") or {}).get("line")
        lines = str(extra.get("lines") or "")
        if lines.strip().lower() in _SEMGREP_HIDDEN:
            lines = ""  # the registry hides source lines for some rules; anchor on the file instead
        severity = _SEMGREP_SEVERITY.get(str(extra.get("severity", "")).upper())
        klass = meta.get("hound_class")
        if not klass:
            categories = " ".join(
                str(meta.get(key, "")) for key in ("category", "subcategory", "vulnerability_class", "cwe", "owasp")
            )
            klass = _hint_class(f"{rule} {categories}")
        issues.append(
            _issue(
                "semgrep",
                rule,
                severity,
                str(klass),
                path,
                int(line) if isinstance(line, int) else None,
                lines or _line_at(root, path, line if isinstance(line, int) else None),
                str(extra.get("message", "")),
                {"confidence": meta.get("confidence"), "cwe": meta.get("cwe")},
            )
        )
    errors = [e for e in (doc.get("errors") or []) if isinstance(e, dict) and e.get("level") == "error"]
    return ("ok" if not errors else "failed"), issues


def parse_bandit(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(raw, stdout)
    except ValueError:
        return "failed", []
    if not isinstance(doc, dict) or "results" not in doc:
        return "failed", []
    issues: list[Issue] = []
    for result in doc.get("results") or []:
        if not isinstance(result, dict):
            continue
        rule = str(result.get("test_id", "bandit"))
        path = _remap(str(result.get("filename", "")), remap)
        line = result.get("line_number")
        issues.append(
            _issue(
                "bandit",
                rule,
                str(result.get("issue_severity", "")),
                _BANDIT_CLASS.get(rule, "none"),
                path,
                int(line) if isinstance(line, int) else None,
                str(result.get("code", "")),
                str(result.get("issue_text", "")),
                {"confidence": result.get("issue_confidence"), "cwe": (result.get("issue_cwe") or {}).get("id")},
            )
        )
    return "ok", issues


def _ruff_severity(code: str) -> str:
    if code.startswith(("E9", "F82", "PLE", "F63", "F70")):
        return "HIGH"
    if code.startswith(("F8", "F5", "F6", "B")):
        return "MEDIUM"
    if code.startswith("F4"):
        return "INFO"
    return "LOW"


def parse_ruff(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(raw, stdout)
    except ValueError:
        return "failed", []
    if doc is None:
        return "ok", []
    if not isinstance(doc, list):
        return "failed", []
    issues: list[Issue] = []
    for result in doc:
        if not isinstance(result, dict):
            continue
        code = str(result.get("code") or "ruff")
        filename = str(result.get("filename", ""))
        if root is not None:
            try:
                filename = Path(filename).resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                pass
        path = _remap(filename, remap)
        line = (result.get("location") or {}).get("row")
        prefix = "PLE" if code.startswith("PLE") else code[:1]
        issues.append(
            _issue(
                "ruff",
                code,
                _ruff_severity(code),
                _RUFF_CLASS.get(prefix, "logic"),
                path,
                int(line) if isinstance(line, int) else None,
                _line_at(root, path, line if isinstance(line, int) else None) or f"{code} {result.get('message', '')}",
                str(result.get("message", "")),
            )
        )
    return "ok", issues


def parse_shellcheck(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(None, stdout)
    except ValueError:
        return "failed", []
    if doc is None:
        return "ok", []
    if not isinstance(doc, list):
        return "failed", []
    issues: list[Issue] = []
    for result in doc:
        if not isinstance(result, dict):
            continue
        code = result.get("code")
        rule = f"SC{code}" if isinstance(code, int) else "shellcheck"
        path = _remap(str(result.get("file", "")), remap)
        line = result.get("line")
        issues.append(
            _issue(
                "shellcheck",
                rule,
                _SHELLCHECK_SEVERITY.get(str(result.get("level", "")).lower()),
                _SHELLCHECK_CLASS.get(code if isinstance(code, int) else -1, "logic"),
                path,
                int(line) if isinstance(line, int) else None,
                _line_at(root, path, line if isinstance(line, int) else None) or f"{rule} {result.get('message', '')}",
                str(result.get("message", "")),
            )
        )
    return "ok", issues


def parse_gitleaks(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    instrument = "gitleaks"
    if raw is not None and raw.exists():
        text = raw.read_text("utf-8", "replace")
    elif "no leaks found" in stdout.lower():
        return "ok", []
    else:
        return "failed", []
    if not text.strip():
        return "ok", []
    try:
        doc = json.loads(text)
    except ValueError:
        return "failed", []
    if doc is None:
        return "ok", []
    if not isinstance(doc, list):
        return "failed", []
    issues: list[Issue] = []
    for result in doc:
        if not isinstance(result, dict):
            continue
        rule = str(result.get("RuleID", "gitleaks"))
        path = _remap(str(result.get("File", "")), remap)
        commit = str(result.get("Commit", "") or "")
        line = result.get("StartLine")
        anchor = f"{commit[:12]} {rule} {result.get('Match', '')}".strip()
        issues.append(
            _issue(
                instrument,
                rule,
                "HIGH",
                "secret",
                path,
                int(line) if isinstance(line, int) else None,
                anchor,
                str(result.get("Description", "")),
                {
                    "commit": commit,
                    "fingerprint": result.get("Fingerprint"),
                    "entropy": result.get("Entropy"),
                    "date": result.get("Date"),
                },
            )
        )
    return "ok", issues


def _cvss_max(cvss: Any) -> float | None:
    best: float | None = None
    if not isinstance(cvss, dict):
        return None
    for entry in cvss.values():
        if not isinstance(entry, dict):
            continue
        for key in ("V3Score", "V40Score", "V2Score"):
            value = entry.get(key)
            if isinstance(value, int | float):
                best = value if best is None or value > best else best
    return best


def parse_trivy(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(raw, stdout)
    except ValueError:
        return "failed", []
    if not isinstance(doc, dict) or "SchemaVersion" not in doc:
        return "failed", []
    issues: list[Issue] = []
    for result in doc.get("Results") or []:
        if not isinstance(result, dict):
            continue
        target = _remap(str(result.get("Target", "")), remap)
        for vuln in result.get("Vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            vid = str(vuln.get("VulnerabilityID", "trivy"))
            pkg = f"{vuln.get('PkgName', '')}@{vuln.get('InstalledVersion', '')}"
            score = _cvss_max(vuln.get("CVSS"))
            severity = floor_severity(str(vuln.get("Severity", "")))
            if score is not None and score >= 9.0:
                severity = "CRITICAL"
            issues.append(
                _issue(
                    "trivy",
                    vid,
                    severity,
                    "supply",
                    target,
                    None,
                    f"{pkg} {vid}",
                    str(vuln.get("Title") or vuln.get("Description") or vid),
                    {
                        "package": vuln.get("PkgName"),
                        "installed": vuln.get("InstalledVersion"),
                        "fixed": vuln.get("FixedVersion"),
                        "cvss": score,
                        "status": vuln.get("Status"),
                    },
                )
            )
    return "ok", issues


def _junit_cases(raw: Path) -> list[tuple[str, str, str, str]]:
    """Return (classname, name, outcome, message) per test case."""
    tree = ET.parse(raw)
    cases: list[tuple[str, str, str, str]] = []
    for case in tree.getroot().iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        outcome = "passed"
        message = ""
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = child.tag
                message = (child.get("message") or child.text or "").strip()
                break
        cases.append((classname, name, outcome, message))
    return cases


def parse_junit(
    raw: Path | None,
    stdout: str,
    root: Path | None,
    remap: dict[str, str] | None,
    instrument: str = "pytest-target",
) -> Parsed:
    if raw is None or not raw.exists():
        return "failed", []
    try:
        cases = _junit_cases(raw)
    except (ET.ParseError, OSError):
        return "failed", []
    issues: list[Issue] = []
    for classname, name, outcome, message in cases:
        if outcome not in ("failure", "error"):
            continue
        path = classname.replace(".", "/") + ".py" if classname else ""
        if "::" in name:
            name = name.split("::")[-1]
        klass = "logic" if outcome == "failure" else "error"
        issues.append(
            _issue(
                instrument,
                f"{outcome}:{name}",
                "MEDIUM",
                klass,
                _remap(path, remap),
                None,
                f"{classname}::{name}",
                message or f"{outcome} in {classname}::{name}",
                {"outcome": outcome},
            )
        )
    return "ok", issues


def parse_node_junit(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    """node --test junit: the file attribute, not the classname, locates a case."""
    if raw is None or not raw.exists():
        return "failed", []
    try:
        tree = ET.parse(raw)
    except (ET.ParseError, OSError):
        return "failed", []
    issues: list[Issue] = []
    for case in tree.getroot().iter("testcase"):
        failure = next((child for child in case if child.tag in ("failure", "error")), None)
        if failure is None:
            continue
        name = case.get("name", "")
        path = case.get("file", "")
        if root is not None and path.startswith(str(root)):
            path = Path(path).relative_to(root).as_posix()
        message = (failure.get("message") or failure.text or "").strip()
        issues.append(
            _issue(
                "node-test",
                f"failure:{name}",
                "MEDIUM",
                "logic",
                _remap(path, remap),
                None,
                f"{path}::{name}",
                message or f"failure in {path}::{name}",
                {"outcome": "failure", "type": failure.get("type", "")},
            )
        )
    return "ok", issues


def junit_summary(raw: Path | None) -> dict[str, Any]:
    if raw is None or not raw.exists():
        return {"total": 0, "passed": 0, "failed": 0, "error": 0, "skipped": 0, "cases": []}
    try:
        cases = _junit_cases(raw)
    except (ET.ParseError, OSError):
        return {"total": 0, "passed": 0, "failed": 0, "error": 0, "skipped": 0, "cases": []}
    summary: dict[str, Any] = {"total": len(cases), "passed": 0, "failed": 0, "error": 0, "skipped": 0, "cases": []}
    for classname, name, outcome, message in cases:
        key = {"passed": "passed", "failure": "failed", "error": "error", "skipped": "skipped"}[outcome]
        summary[key] += 1
        summary["cases"].append({"test": f"{classname}::{name}", "outcome": outcome, "message": message[:200]})
    return summary


def parse_oxlint(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    try:
        doc = _load_json(None, stdout)
    except ValueError:
        return "failed", []
    if not isinstance(doc, dict) or "diagnostics" not in doc:
        return "failed", []
    issues: list[Issue] = []
    for diag in doc.get("diagnostics") or []:
        if not isinstance(diag, dict):
            continue
        path = _remap(str(diag.get("filename", "")), remap)
        labels = diag.get("labels") or []
        line = (labels[0].get("span") or {}).get("line") if labels and isinstance(labels[0], dict) else None
        severity = "HIGH" if diag.get("severity") == "error" else "LOW"
        issues.append(
            _issue(
                "oxlint",
                str(diag.get("code", "oxlint")),
                severity,
                "logic",
                path,
                int(line) if isinstance(line, int) else None,
                _line_at(root, path, line if isinstance(line, int) else None) or str(diag.get("message", "")),
                str(diag.get("message", "")),
            )
        )
    return "ok", issues


def parse_tsc(raw: Path | None, stdout: str, root: Path | None, remap: dict[str, str] | None) -> Parsed:
    issues: list[Issue] = []
    for line in stdout.splitlines():
        if "): error TS" not in line:
            continue
        head, _, message = line.partition("): error ")
        location, _, position = head.partition("(")
        row = position.split(",")[0]
        code = message.split(":")[0]
        path = _remap(location.strip(), remap)
        issues.append(
            _issue(
                "tsc",
                code,
                "HIGH",
                "logic",
                path,
                int(row) if row.isdigit() else None,
                _line_at(root, path, int(row) if row.isdigit() else None) or message,
                message,
            )
        )
    return "ok", issues


def parse(
    instrument: str,
    raw: Path | None,
    stdout: str,
    root: Path | None = None,
    remap: dict[str, str] | None = None,
) -> Parsed:
    """Dispatch on instrument name. Internal instruments return parser status `none`."""
    if instrument == "semgrep":
        return parse_semgrep(raw, stdout, root, remap)
    if instrument == "bandit":
        return parse_bandit(raw, stdout, root, remap)
    if instrument == "ruff":
        return parse_ruff(raw, stdout, root, remap)
    if instrument == "shellcheck":
        return parse_shellcheck(raw, stdout, root, remap)
    if instrument in ("gitleaks-git", "gitleaks-dir"):
        status, issues = parse_gitleaks(raw, stdout, root, remap)
        for issue in issues:
            issue.instrument = instrument
            issue.id = issue_id(instrument, issue.rule, issue.path, issue.anchor)
        return status, issues
    if instrument in ("trivy-python", "trivy-node"):
        status, issues = parse_trivy(raw, stdout, root, remap)
        for issue in issues:
            issue.instrument = instrument
            issue.id = issue_id(instrument, issue.rule, issue.path, issue.anchor)
        return status, issues
    if instrument in ("pytest-target", "sandbox"):
        return parse_junit(raw, stdout, root, remap, instrument)
    if instrument == "node-test":
        return parse_node_junit(raw, stdout, root, remap)
    if instrument == "oxlint":
        return parse_oxlint(raw, stdout, root, remap)
    if instrument == "tsc":
        return parse_tsc(raw, stdout, root, remap)
    return "none", []
