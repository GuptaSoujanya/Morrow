"""Bucket D verifier: deterministic checks that findings are grounded in evidence.

The verifier rejects (exit nonzero) on integrity failures and caps the disposition on
coverage, provenance, and instrument gaps. Model judgment may lower a disposition or
severity; this module never raises one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from identity import issue_id, issues_digest, normalize, record_id, sha256_file
from provenance import harness_digest
from registry import REGISTRY, by_name
from schema import (
    SEVERITIES,
    STRICT_CLASSES,
    STRICT_INSTRUMENTS,
    cap,
    disposition_rank,
    severity_rank,
    validate_evidence,
    validate_findings,
)

MIN_REASON = 20


@dataclass
class Verdict:
    computed: str = "SHIP"
    declared: str | None = None
    caps: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.rejections

    def cap(self, limit: str, reason: str) -> None:
        self.caps.append(f"{limit}: {reason}")
        self.computed = cap(self.computed, limit)

    def reject(self, reason: str) -> None:
        self.rejections.append(reason)

    def report(self) -> str:
        lines = [f"verifier: {'PASS' if self.ok else 'FAIL'}", f"computed disposition: {self.computed}"]
        if self.declared:
            lines.append(f"declared disposition: {self.declared}")
        for key, value in self.counts.items():
            lines.append(f"{key}: {value}")
        for reason in self.caps:
            lines.append(f"cap {reason}")
        for reason in self.rejections:
            lines.append(f"REJECT {reason}")
        for note in self.notes:
            lines.append(f"note {note}")
        return "\n".join(lines)


def _load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text("utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {"__error__": str(exc)}


def _critical_capable(severity: str, klass: str) -> bool:
    return severity == "CRITICAL" or (severity == "HIGH" and klass in STRICT_CLASSES)


def _must_triage(issue: dict[str, Any]) -> bool:
    severity = issue.get("severity", "MEDIUM")
    if severity in ("HIGH", "CRITICAL"):
        return True
    if severity == "MEDIUM" and (
        issue.get("instrument") in STRICT_INSTRUMENTS or issue.get("critical_class") in STRICT_CLASSES
    ):
        return True
    return False


def _anchor_matches(anchor: dict[str, Any], issue: dict[str, Any]) -> bool:
    path = anchor.get("path")
    snippet = normalize(str(anchor.get("snippet", "")))
    if not snippet:
        return False
    candidates: list[tuple[str, str]] = [(str(issue.get("path", "")), normalize(str(issue.get("anchor", ""))))]
    for extra in (issue.get("extra") or {}).get("anchors") or []:
        if isinstance(extra, dict):
            candidates.append((str(extra.get("path", "")), normalize(str(extra.get("snippet", "")))))
    for cpath, canchor in candidates:
        if cpath != path or not canchor:
            continue
        if snippet in canchor or canchor in snippet:
            return True
    return False


def verify(findings_path: Path, evidence_path: Path, hunt: Path | None = None) -> Verdict:
    verdict = Verdict()
    hunt = hunt or evidence_path.parent
    findings_doc = _load(findings_path)
    evidence_doc = _load(evidence_path)
    for name, doc in (("findings", findings_doc), ("evidence", evidence_doc)):
        if isinstance(doc, dict) and "__error__" in doc:
            verdict.reject(f"{name}: unreadable ({doc['__error__']})")
            verdict.cap("BLOCK", f"{name} unreadable")
    if not verdict.ok:
        return verdict
    for problem in validate_evidence(evidence_doc):
        verdict.reject(problem)
    for problem in validate_findings(findings_doc):
        verdict.reject(problem)
    if not verdict.ok:
        verdict.cap("BLOCK", "schema violations")
        return verdict
    return _verify_docs(verdict, findings_doc, evidence_doc, evidence_path, hunt)


def _verify_docs(
    verdict: Verdict,
    findings_doc: dict[str, Any],
    evidence_doc: dict[str, Any],
    evidence_path: Path,
    hunt: Path,
) -> Verdict:
    verdict.declared = str(findings_doc.get("disposition"))

    # Binding: findings must hash the exact evidence file they cite.
    actual = sha256_file(evidence_path)
    if findings_doc.get("evidence_digest") != actual:
        verdict.reject(
            f"evidence_digest {findings_doc.get('evidence_digest')} does not match {evidence_path.name} ({actual})"
        )
        verdict.cap("BLOCK", "findings bound to a different evidence file")

    # Target honesty.
    etarget = evidence_doc.get("target") or {}
    ftarget = findings_doc.get("target") or {}
    if ftarget.get("sha") != etarget.get("sha"):
        verdict.reject(f"findings target sha {ftarget.get('sha')} differs from evidence {etarget.get('sha')}")
    if etarget.get("dirty") and not ftarget.get("dirty"):
        verdict.reject("dirty tree presented as clean")
        verdict.cap("BLOCK", "dirty tree presented as clean")
    if etarget.get("sha") in (None, "", "null"):
        verdict.cap("HOLD", "no recorded git sha")
    if etarget.get("dirty"):
        verdict.cap("HOLD", "working tree dirty at evidence time")

    # Record and issue integrity: ids are recomputed from content.
    records: dict[str, dict[str, Any]] = {}
    issues: dict[str, dict[str, Any]] = {}
    issue_owner: dict[str, str] = {}
    for record in evidence_doc.get("records") or []:
        rid = record.get("id")
        expected = record_id(
            record.get("instrument", ""),
            [str(a) for a in record.get("argv") or []],
            record.get("exit_code"),
            record.get("stdout_digest", ""),
            record.get("stderr_digest", ""),
        )
        if rid != expected:
            verdict.reject(f"record {rid} id does not match its content (expected {expected})")
            verdict.cap("BLOCK", "evidence record tampered")
        records[str(rid)] = record
        for issue in record.get("issues") or []:
            iid = issue.get("id")
            want = issue_id(
                issue.get("instrument", ""), issue.get("rule", ""), issue.get("path", ""), issue.get("anchor", "")
            )
            if iid != want:
                verdict.reject(f"issue {iid} in {rid} id does not match its content (expected {want})")
            issues[str(iid)] = issue
            issue_owner[str(iid)] = str(rid)

    # Required instruments: blocked, timed out, or parser failures cap; inert liveness blocks.
    required_present: set[str] = set()
    for rid, record in records.items():
        name = str(record.get("instrument"))
        if record.get("issues_digest") != issues_digest(record.get("issues") or []):
            verdict.reject(f"record {rid} issues digest mismatch: issues were edited after emission")
        for rel, digest in (record.get("raw_digests") or {}).items():
            raw_path = hunt.parent / str(rel)
            if not raw_path.exists():
                verdict.notes.append(f"record {rid} raw artifact {rel} is absent (volatile results)")
            elif sha256_file(raw_path) != digest:
                verdict.reject(f"record {rid} raw artifact {rel} does not match its recorded digest")
        try:
            instrument = by_name(name)
        except KeyError:
            verdict.cap("HOLD", f"record {rid} names unknown instrument {name}")
            continue
        if instrument.required:
            required_present.add(name)
        if record.get("status") in ("blocked", "timeout"):
            verdict.cap(
                instrument.cap_when_absent if instrument.required else "HOLD",
                f"{name} {record.get('status')}: {record.get('note') or 'no detail'}",
            )
        elif record.get("status") == "failed" and record.get("parser") != "ok":
            verdict.cap(
                instrument.cap_when_absent, f"{name} failed with exit {record.get('exit_code')} and no parsable output"
            )
        elif record.get("parser") == "failed":
            verdict.cap(instrument.cap_when_absent, f"{name} output unparsable")
    scope_path = hunt / "scope.yaml"
    scope_doc = _load(scope_path) if scope_path.exists() else None
    scoped: list[str] = []
    if isinstance(scope_doc, dict):
        scoped = [str(i.get("name")) for i in scope_doc.get("instruments") or [] if i.get("required")]
    present = {str(r.get("instrument")) for r in records.values()}
    for name in sorted(set(scoped) - present):
        verdict.reject(f"required instrument {name} is in scope but has no evidence record")
        try:
            verdict.cap(by_name(name).cap_when_absent, f"required instrument {name} never ran")
        except KeyError:
            verdict.cap("HOLD", f"required instrument {name} never ran")
    for entry in evidence_doc.get("liveness") or []:
        if not (isinstance(entry.get("clean"), bool) and isinstance(entry.get("positive"), bool)):
            verdict.reject(f"liveness proof for {entry.get('instrument')} is not boolean")
    liveness = {str(e.get("instrument")): e for e in evidence_doc.get("liveness") or []}
    for name in sorted(required_present):
        entry = liveness.get(name)
        if entry is None:
            verdict.cap("BLOCK", f"required instrument {name} has no liveness proof")
        elif not (entry.get("clean") and entry.get("positive")):
            verdict.cap(
                "BLOCK",
                f"required instrument {name} is inert or unsound "
                f"(clean={entry.get('clean')} positive={entry.get('positive')})",
            )
    for name, entry in liveness.items():
        if name not in required_present and not (entry.get("clean") and entry.get("positive")):
            verdict.cap("HOLD", f"optional instrument {name} failed liveness")

    # Coverage gaps cap at HOLD.
    for gap in evidence_doc.get("gaps") or []:
        verdict.cap(str(gap.get("cap") or "HOLD"), f"gap {gap.get('surface')}: {gap.get('gap')}")

    # Provenance, scope, and harness integrity.
    _verify_provenance(verdict, evidence_doc, hunt)

    # Findings grounded in evidence.
    cited_issue_ids: set[str] = set()
    findings = findings_doc.get("findings") or []
    for finding in findings:
        fid = finding.get("id")
        cited_records = [str(r) for r in finding.get("evidence") or []]
        cited_issues = [str(i) for i in finding.get("issues") or []]
        if not cited_records:
            verdict.reject(f"{fid} cites no evidence records")
        for rid in cited_records:
            record = records.get(rid)
            if record is None:
                verdict.reject(f"{fid} cites unknown record {rid}")
                continue
            if record.get("status") in ("blocked", "timeout"):
                verdict.reject(f"{fid} cites {rid} whose instrument was {record.get('status')}")
                verdict.cap("BLOCK", f"blocked run {rid} cited as evidence")
            elif record.get("status") == "failed" and record.get("parser") != "ok":
                verdict.reject(f"{fid} cites {rid} which failed without parsable output")
        if not cited_issues:
            verdict.reject(f"{fid} cites no issues")
        max_rank = -1
        for iid in cited_issues:
            issue = issues.get(iid)
            if issue is None:
                verdict.reject(f"{fid} cites unknown issue {iid}")
                continue
            if issue_owner.get(iid) not in cited_records:
                verdict.reject(f"{fid} cites issue {iid} outside its cited records")
            max_rank = max(max_rank, severity_rank(str(issue.get("severity", "MEDIUM"))))
            cited_issue_ids.add(iid)
        severity = str(finding.get("severity"))
        if max_rank >= 0 and severity_rank(severity) > max_rank:
            verdict.reject(f"{fid} severity {severity} is above every cited issue ({SEVERITIES[max_rank]})")
        if not finding.get("anchors"):
            verdict.reject(f"{fid} has no anchors into the evidence")
        for anchor in finding.get("anchors") or []:
            if not any(_anchor_matches(anchor, issues[i]) for i in cited_issues if i in issues):
                verdict.reject(f"{fid} anchor {anchor.get('path')}: span not present in cited evidence")
        if finding.get("reproduction") == "confirmed":
            dynamic = [
                issues[i]
                for i in cited_issues
                if i in issues and issues[i].get("instrument") in ("sandbox", "pytest-target")
            ]
            fired = [d for d in dynamic if str(d.get("rule", "")).startswith("failure:")]
            if not fired:
                verdict.reject(
                    f"{fid} claims confirmed reproduction without a cited sandbox failure "
                    "(setup errors and passes do not confirm)"
                )
            keys = {
                str(issues[i].get("rule"))
                for i in cited_issues
                if i in issues and issues[i].get("instrument") == "probe"
            }
            if keys and not any(k.replace("-", "_") in str(d.get("rule")) for k in keys for d in fired):
                verdict.reject(f"{fid} cites a reproduction that does not exercise its hypothesis ({sorted(keys)})")
        waiver = finding.get("waiver")
        klass = str(finding.get("critical_class"))
        if waiver is not None:
            if len(str(waiver.get("reason", ""))) < MIN_REASON:
                verdict.reject(f"{fid} waiver reason too short")
            if severity == "CRITICAL":
                verdict.cap("HOLD", f"{fid} is CRITICAL and waived; a critical finding never waives into SHIP")
        elif _critical_capable(severity, klass):
            verdict.cap("HOLD", f"{fid} is an unwaived critical-capable finding ({severity} {klass})")

    # Triage: every entry names a real issue with a real reason.
    triaged: set[str] = set()
    for entry in findings_doc.get("triage") or []:
        iid = str(entry.get("issue"))
        if iid not in issues:
            verdict.reject(f"triage names unknown issue {iid}")
            continue
        if len(str(entry.get("reason", ""))) < MIN_REASON:
            verdict.reject(f"triage of {iid} has no substantive reason")
        triaged.add(iid)

    # Omission: every issue that must be triaged is either in a finding or triaged.
    omitted = [
        iid
        for iid, issue in issues.items()
        if _must_triage(issue) and iid not in cited_issue_ids and iid not in triaged
    ]
    for iid in omitted:
        issue = issues[iid]
        verdict.reject(
            f"omitted issue {iid} ({issue.get('instrument')} {issue.get('rule')} "
            f"{issue.get('severity')} {issue.get('path')})"
        )

    # Empty all-clear over nonempty evidence.
    if not findings and not triaged and issues:
        verdict.reject(f"empty all-clear report over {len(issues)} evidence issues")

    # Counts recomputed.
    counts = findings_doc.get("counts") or {}
    by_severity = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        by_severity[str(finding.get("severity"))] = by_severity.get(str(finding.get("severity")), 0) + 1
    if counts.get("findings_by_severity") != by_severity:
        verdict.reject(f"counts.findings_by_severity {counts.get('findings_by_severity')} != recomputed {by_severity}")
    if counts.get("evidence_issues") != len(issues):
        verdict.reject(f"counts.evidence_issues {counts.get('evidence_issues')} != {len(issues)}")
    if counts.get("triaged") != len(triaged):
        verdict.reject(f"counts.triaged {counts.get('triaged')} != {len(triaged)}")

    # Disposition: declared may be lower than computed, never higher.
    declared = str(findings_doc.get("disposition"))
    if declared in ("BLOCK", "HOLD", "SHIP") and disposition_rank(declared) > disposition_rank(verdict.computed):
        verdict.reject(f"declared disposition {declared} is above the deterministic ceiling {verdict.computed}")
    verdict.counts = {
        "records": len(records),
        "issues": len(issues),
        "findings": len(findings),
        "triaged": len(triaged),
        "must_triage": sum(1 for i in issues.values() if _must_triage(i)),
        "omitted": len(omitted),
    }
    return verdict


def _verify_provenance(verdict: Verdict, evidence_doc: dict[str, Any], hunt: Path) -> None:
    prov_path = hunt / "provenance.yaml"
    scope_path = hunt / "scope.yaml"
    if not prov_path.exists():
        verdict.cap("HOLD", "provenance.yaml missing")
        return
    if sha256_file(prov_path) != evidence_doc.get("provenance_digest"):
        verdict.cap("HOLD", "provenance.yaml changed since evidence was emitted")
    prov = _load(prov_path)
    if not isinstance(prov, dict):
        verdict.cap("BLOCK", "provenance.yaml unreadable")
        return
    if not prov.get("pinned", False):
        verdict.cap("BLOCK", f"unpinned scanner database: {prov.get('unpinned')}")
    if not scope_path.exists():
        verdict.cap("HOLD", "scope.yaml missing")
    else:
        digest = sha256_file(scope_path)
        if digest != evidence_doc.get("scope_digest"):
            verdict.cap("HOLD", "scope.yaml changed since evidence was emitted")
        if (prov.get("scope") or {}).get("sha256") != digest:
            verdict.cap("HOLD", "provenance scope digest does not match scope.yaml")
    recorded = (prov.get("environment") or {}).get("harness_sha256")
    if recorded and recorded != harness_digest(hunt):
        verdict.cap("HOLD", "harness source changed since provenance was recorded")
    if (prov.get("target") or {}).get("sha") != (evidence_doc.get("target") or {}).get("sha"):
        verdict.cap("HOLD", "provenance target sha differs from evidence")
    known = {i.name for i in REGISTRY}
    for record in evidence_doc.get("records") or []:
        if record.get("instrument") not in known:
            verdict.cap("HOLD", f"record for unregistered instrument {record.get('instrument')}")
