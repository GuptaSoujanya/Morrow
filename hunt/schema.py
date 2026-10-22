"""Record shapes shared by the harness and the structural half of the verifier.

Everything here is Bucket D: shape, enumerations, ranks. No judgment lives here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from identity import issues_digest

SEVERITIES: tuple[str, ...] = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CLASSES: tuple[str, ...] = (
    "injection",
    "auth",
    "secret",
    "memory",
    "supply",
    "concurrency",
    "lifecycle",
    "error",
    "logic",
    "api_misuse",
)
NO_CLASS = "none"
DISPOSITIONS: tuple[str, ...] = ("BLOCK", "HOLD", "SHIP")
RECORD_STATUS: tuple[str, ...] = ("ok", "blocked", "timeout", "failed")
PARSER_STATUS: tuple[str, ...] = ("ok", "failed", "none")
REPRODUCTION: tuple[str, ...] = ("confirmed", "unconfirmed", "not_attempted", "static_only")
REACHABILITY: tuple[str, ...] = ("reachable", "conditional", "unreachable", "unknown")
TRIAGE: tuple[str, ...] = ("accepted", "false_positive", "duplicate", "out_of_scope", "informational")

EVIDENCE_SCHEMA = "hound.evidence.v1"
FINDINGS_SCHEMA = "hound.findings.v1"
SCOPE_SCHEMA = "hound.scope.v1"
PROVENANCE_SCHEMA = "hound.provenance.v1"
PROGRESS_SCHEMA = "hound.progress.v1"

# Instruments whose MEDIUM issues must be triaged individually (hypothesis-driven or secret-bearing).
STRICT_INSTRUMENTS: frozenset[str] = frozenset({"probe", "sandbox", "gitleaks-git", "gitleaks-dir", "history"})
# Critical classes whose MEDIUM issues must be triaged individually regardless of instrument.
STRICT_CLASSES: frozenset[str] = frozenset({"injection", "auth", "secret", "memory", "supply"})


def severity_rank(value: str) -> int:
    return SEVERITIES.index(value)


def floor_severity(value: str | None) -> str:
    """Unknown severities fail closed to MEDIUM."""
    if value is None:
        return "MEDIUM"
    upper = value.strip().upper()
    if upper in SEVERITIES:
        return upper
    return "MEDIUM"


def disposition_rank(value: str) -> int:
    return DISPOSITIONS.index(value)


def cap(current: str, limit: str) -> str:
    """Return the lower of two dispositions."""
    return current if disposition_rank(current) <= disposition_rank(limit) else limit


def normalize_class(value: str | None) -> str:
    if value is None:
        return NO_CLASS
    lower = value.strip().lower()
    return lower if lower in CLASSES else NO_CLASS


@dataclass
class Issue:
    id: str
    instrument: str
    rule: str
    severity: str
    critical_class: str
    path: str
    line: int | None
    anchor: str
    message: str
    source: str = "instrument"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Record:
    id: str
    instrument: str
    category: str
    argv: list[str]
    cwd: str
    exit_code: int | None
    status: str
    parser: str
    started: str
    ended: str
    duration_s: float
    timeout_s: int
    config_digest: str
    db_digest: str
    raw: list[str]
    stdout_digest: str
    stderr_digest: str
    issues: list[Issue] = field(default_factory=list)
    pruned: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    issues_digest: str = ""
    raw_digests: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() for issue in self.issues]
        data["issues_digest"] = issues_digest(data["issues"])
        return data


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _require(doc: dict[str, Any], key: str, kind: type | tuple[type, ...], where: str, out: list[str]) -> Any:
    if key not in doc:
        out.append(f"{where}: missing key '{key}'")
        return None
    value = doc[key]
    if not isinstance(value, kind):
        out.append(f"{where}: key '{key}' has type {type(value).__name__}")
        return None
    return value


def validate_issue(issue: Any, where: str) -> list[str]:
    out: list[str] = []
    if not isinstance(issue, dict):
        return [f"{where}: issue is not a mapping"]
    for key in ("id", "instrument", "rule", "severity", "critical_class", "path", "anchor", "message"):
        _require(issue, key, str, where, out)
    if "line" in issue and issue["line"] is not None and not isinstance(issue["line"], int):
        out.append(f"{where}: line is not an integer")
    if _is_str(issue.get("severity")) and issue["severity"] not in SEVERITIES:
        out.append(f"{where}: severity '{issue['severity']}' not in {SEVERITIES}")
    if _is_str(issue.get("critical_class")) and issue["critical_class"] not in (*CLASSES, NO_CLASS):
        out.append(f"{where}: critical_class '{issue['critical_class']}' unknown")
    if _is_str(issue.get("id")) and not issue["id"].startswith("IS-"):
        out.append(f"{where}: id '{issue['id']}' is not an issue id")
    return out


def validate_record(record: Any, where: str) -> list[str]:
    out: list[str] = []
    if not isinstance(record, dict):
        return [f"{where}: record is not a mapping"]
    for key in ("id", "instrument", "category", "status", "parser", "config_digest", "db_digest", "cwd"):
        _require(record, key, str, where, out)
    _require(record, "argv", list, where, out)
    _require(record, "raw", list, where, out)
    _require(record, "issues", list, where, out)
    if "exit_code" in record and record["exit_code"] is not None and not isinstance(record["exit_code"], int):
        out.append(f"{where}: exit_code is not an integer")
    if _is_str(record.get("status")) and record["status"] not in RECORD_STATUS:
        out.append(f"{where}: status '{record['status']}' unknown")
    if _is_str(record.get("parser")) and record["parser"] not in PARSER_STATUS:
        out.append(f"{where}: parser '{record['parser']}' unknown")
    if _is_str(record.get("id")) and not record["id"].startswith("EV-"):
        out.append(f"{where}: id '{record['id']}' is not a record id")
    for index, issue in enumerate(record.get("issues") or []):
        out.extend(validate_issue(issue, f"{where}.issues[{index}]"))
    return out


def validate_evidence(doc: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(doc, dict):
        return ["evidence: document is not a mapping"]
    if doc.get("schema") != EVIDENCE_SCHEMA:
        out.append(f"evidence: schema is not {EVIDENCE_SCHEMA}")
    target = _require(doc, "target", dict, "evidence", out)
    if isinstance(target, dict):
        if "dirty" not in target or not isinstance(target["dirty"], bool):
            out.append("evidence.target: dirty must be a boolean")
        if "sha" not in target:
            out.append("evidence.target: missing sha")
    _require(doc, "scope_digest", str, "evidence", out)
    records = _require(doc, "records", list, "evidence", out)
    if isinstance(records, list):
        seen: set[str] = set()
        for index, record in enumerate(records):
            out.extend(validate_record(record, f"evidence.records[{index}]"))
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                if record["id"] in seen:
                    out.append(f"evidence.records[{index}]: duplicate record id {record['id']}")
                seen.add(record["id"])
    liveness = _require(doc, "liveness", list, "evidence", out)
    if isinstance(liveness, list):
        for index, check in enumerate(liveness):
            if not isinstance(check, dict):
                out.append(f"evidence.liveness[{index}]: not a mapping")
                continue
            for key in ("instrument", "clean", "positive"):
                if key not in check:
                    out.append(f"evidence.liveness[{index}]: missing {key}")
    _require(doc, "gaps", list, "evidence", out)
    return out


def validate_finding(finding: Any, where: str) -> list[str]:
    out: list[str] = []
    if not isinstance(finding, dict):
        return [f"{where}: finding is not a mapping"]
    for key in ("id", "title", "critical_class", "severity", "reachability", "reproduction", "remediation"):
        _require(finding, key, str, where, out)
    _require(finding, "evidence", list, where, out)
    _require(finding, "issues", list, where, out)
    _require(finding, "anchors", list, where, out)
    if _is_str(finding.get("severity")) and finding["severity"] not in SEVERITIES:
        out.append(f"{where}: severity '{finding['severity']}' unknown")
    if _is_str(finding.get("critical_class")) and finding["critical_class"] not in (*CLASSES, NO_CLASS):
        out.append(f"{where}: critical_class '{finding['critical_class']}' unknown")
    if _is_str(finding.get("reachability")) and finding["reachability"] not in REACHABILITY:
        out.append(f"{where}: reachability '{finding['reachability']}' unknown")
    if _is_str(finding.get("reproduction")) and finding["reproduction"] not in REPRODUCTION:
        out.append(f"{where}: reproduction '{finding['reproduction']}' unknown")
    waiver = finding.get("waiver")
    if waiver is not None:
        if not isinstance(waiver, dict):
            out.append(f"{where}: waiver is not a mapping")
        else:
            for key in ("reason", "by", "until"):
                if not _is_str(waiver.get(key)):
                    out.append(f"{where}.waiver: missing {key}")
    for index, anchor in enumerate(finding.get("anchors") or []):
        if not isinstance(anchor, dict) or not _is_str(anchor.get("path")) or not _is_str(anchor.get("snippet")):
            out.append(f"{where}.anchors[{index}]: needs path and snippet")
    return out


def validate_findings(doc: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(doc, dict):
        return ["findings: document is not a mapping"]
    if doc.get("schema") != FINDINGS_SCHEMA:
        out.append(f"findings: schema is not {FINDINGS_SCHEMA}")
    target = _require(doc, "target", dict, "findings", out)
    if isinstance(target, dict):
        if not isinstance(target.get("dirty"), bool):
            out.append("findings.target: dirty must be a boolean")
        if "sha" not in target:
            out.append("findings.target: missing sha")
    _require(doc, "evidence_digest", str, "findings", out)
    disposition = _require(doc, "disposition", str, "findings", out)
    if _is_str(disposition) and disposition not in DISPOSITIONS:
        out.append(f"findings: disposition '{disposition}' unknown")
    _require(doc, "disposition_reasons", list, "findings", out)
    findings = _require(doc, "findings", list, "findings", out)
    if isinstance(findings, list):
        seen: set[str] = set()
        for index, finding in enumerate(findings):
            out.extend(validate_finding(finding, f"findings.findings[{index}]"))
            if isinstance(finding, dict) and isinstance(finding.get("id"), str):
                if finding["id"] in seen:
                    out.append(f"findings.findings[{index}]: duplicate finding id {finding['id']}")
                seen.add(finding["id"])
    triage = _require(doc, "triage", list, "findings", out)
    if isinstance(triage, list):
        for index, entry in enumerate(triage):
            where = f"findings.triage[{index}]"
            if not isinstance(entry, dict):
                out.append(f"{where}: not a mapping")
                continue
            for key in ("issue", "decision", "reason"):
                _require(entry, key, str, where, out)
            if _is_str(entry.get("decision")) and entry["decision"] not in TRIAGE:
                out.append(f"{where}: decision '{entry['decision']}' unknown")
    _require(doc, "counts", dict, "findings", out)
    return out
