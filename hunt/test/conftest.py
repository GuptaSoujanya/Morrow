"""Shared fixtures: a tiny but complete evidence plus findings pair that passes the verifier."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

HUNT = Path(__file__).resolve().parent.parent
if str(HUNT) not in sys.path:
    sys.path.insert(0, str(HUNT))

from identity import issue_id, issues_digest, record_id, sha256_file, sha256_text  # noqa: E402
from provenance import harness_digest  # noqa: E402
from schema import EVIDENCE_SCHEMA, FINDINGS_SCHEMA, PROVENANCE_SCHEMA, SCOPE_SCHEMA, SEVERITIES  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def issue(
    instrument: str, rule: str, severity: str, klass: str, path: str, anchor: str, **extra: Any
) -> dict[str, Any]:
    return {
        "id": issue_id(instrument, rule, path, anchor),
        "instrument": instrument,
        "rule": rule,
        "severity": severity,
        "critical_class": klass,
        "path": path,
        "line": 1,
        "anchor": anchor,
        "message": f"{rule} at {path}",
        "source": "instrument",
        "extra": extra,
    }


def record(
    instrument: str, issues: list[dict[str, Any]], status: str = "ok", exit_code: int | None = 0, parser: str = "ok"
) -> dict[str, Any]:
    argv = [instrument, "--json"]
    out = sha256_text(instrument)
    err = sha256_text("")
    return {
        "id": record_id(instrument, argv, exit_code, out, err),
        "instrument": instrument,
        "category": "sast",
        "argv": argv,
        "cwd": "/tmp/target",
        "exit_code": exit_code,
        "status": status,
        "parser": parser,
        "started": "2026-01-01T00:00:00+00:00",
        "ended": "2026-01-01T00:00:01+00:00",
        "duration_s": 1.0,
        "timeout_s": 60,
        "config_digest": sha256_text("config"),
        "db_digest": sha256_text("db"),
        "raw": [],
        "stdout_digest": out,
        "stderr_digest": err,
        "issues": issues,
        "pruned": [],
        "gaps": [],
        "note": "",
        "issues_digest": issues_digest(issues),
        "raw_digests": {},
    }


@pytest.fixture
def harness(tmp_path: Path) -> dict[str, Any]:
    """Write scope, provenance, evidence, and findings into a temp hunt dir and return handles."""
    hunt = tmp_path / "hunt"
    hunt.mkdir()
    (hunt / "rule").mkdir()
    (hunt / "rule" / "custom.yaml").write_text("rules: []\n")
    (hunt / "hound.py").write_text("# stub\n")
    instruments = [{"name": n, "required": n != "probe"} for n in ("semgrep", "probe", "ruff", "bandit")]
    scope_text = yaml.safe_dump({"schema": SCOPE_SCHEMA, "surfaces": [], "instruments": instruments})
    (hunt / "scope.yaml").write_text(scope_text)
    scope_digest = sha256_text(scope_text)

    high = issue("semgrep", "python.lang.security.audit.eval", "HIGH", "injection", "app.py", "eval(expr)")
    medium = issue(
        "probe",
        "web-03",
        "MEDIUM",
        "lifecycle",
        "web/server.py",
        "for raw in iter(proc.stdout.readline)",
        anchors=[
            {"path": "web/server.py", "line": 117, "snippet": "for raw in iter(proc.stdout.readline)"},
            {"path": "web/server.py", "line": 142, "snippet": "if self.proc is not None and self.proc.poll() is None:"},
        ],
    )
    low = issue("ruff", "F401", "INFO", "logic", "app.py", "import os")
    records = [
        record("semgrep", [high]),
        record("probe", [medium]),
        record("ruff", [low]),
        record("bandit", []),
    ]
    liveness = [
        {"instrument": name, "clean": True, "positive": True} for name in ("semgrep", "probe", "ruff", "bandit")
    ]
    prov = {
        "schema": PROVENANCE_SCHEMA,
        "target": {"sha": SHA, "dirty": False},
        "scope": {"path": "hunt/scope.yaml", "sha256": scope_digest},
        "environment": {"harness_sha256": harness_digest(hunt)},
        "databases": {},
        "pinned": True,
        "unpinned": [],
    }
    prov_text = yaml.safe_dump(prov, sort_keys=False)
    (hunt / "provenance.yaml").write_text(prov_text)
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "target": {"root": "/tmp/target", "sha": SHA, "dirty": False},
        "scope_digest": scope_digest,
        "provenance_digest": sha256_text(prov_text),
        "records": records,
        "liveness": liveness,
        "gaps": [],
    }
    findings = {
        "schema": FINDINGS_SCHEMA,
        "target": {"sha": SHA, "dirty": False},
        "evidence_digest": "",
        "disposition": "HOLD",
        "disposition_reasons": ["one unwaived injection finding"],
        "findings": [
            {
                "id": "HND-0000000001",
                "title": "eval on user input",
                "critical_class": "injection",
                "severity": "HIGH",
                "reachability": "reachable",
                "reproduction": "static_only",
                "remediation": "use ast.literal_eval",
                "evidence": [records[0]["id"]],
                "issues": [high["id"]],
                "anchors": [{"path": "app.py", "snippet": "eval(expr)"}],
            },
            {
                "id": "HND-0000000002",
                "title": "runner follow blocks on grandchild pipe",
                "critical_class": "lifecycle",
                "severity": "MEDIUM",
                "reachability": "conditional",
                "reproduction": "not_attempted",
                "remediation": "wait on the process group",
                "evidence": [records[1]["id"]],
                "issues": [medium["id"]],
                "anchors": [
                    {"path": "web/server.py", "snippet": "if self.proc is not None and self.proc.poll() is None:"}
                ],
            },
        ],
        "triage": [],
        "counts": {
            "findings_by_severity": {s: 0 for s in SEVERITIES} | {"HIGH": 1, "MEDIUM": 1},
            "evidence_issues": 3,
            "triaged": 0,
        },
    }
    return {
        "hunt": hunt,
        "evidence": evidence,
        "findings": findings,
        "high": high,
        "medium": medium,
        "low": low,
        "records": records,
    }


def write_pair(handles: dict[str, Any]) -> tuple[Path, Path]:
    hunt = handles["hunt"]
    evidence_path = hunt / "evidence.yaml"
    findings_path = hunt / "findings.yaml"
    evidence_path.write_text(yaml.safe_dump(handles["evidence"], sort_keys=False))
    handles["findings"]["evidence_digest"] = sha256_file(evidence_path)
    findings_path.write_text(yaml.safe_dump(handles["findings"], sort_keys=False))
    return findings_path, evidence_path
