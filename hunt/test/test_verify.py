"""Negative controls: the verifier must reject every way a report can lie about evidence."""

from __future__ import annotations

from typing import Any

import yaml
from conftest import issue, record, write_pair

from verify import verify


def _run(handles: dict[str, Any]) -> Any:
    findings_path, evidence_path = write_pair(handles)
    return verify(findings_path, evidence_path, handles["hunt"])


def test_baseline_passes(harness: dict[str, Any]) -> None:
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert verdict.computed == "HOLD"
    assert harness["findings"]["disposition"] == "HOLD"


def test_omitted_high_issue_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"] = harness["findings"]["findings"][1:]
    harness["findings"]["counts"]["findings_by_severity"]["HIGH"] = 0
    verdict = _run(harness)
    assert not verdict.ok
    assert any("omitted issue" in r for r in verdict.rejections), verdict.report()


def test_omitted_strict_medium_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"] = harness["findings"]["findings"][:1]
    harness["findings"]["counts"]["findings_by_severity"]["MEDIUM"] = 0
    verdict = _run(harness)
    assert any("omitted issue" in r and "probe" in r for r in verdict.rejections), verdict.report()


def test_triage_with_reason_covers_omission(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"] = harness["findings"]["findings"][:1]
    harness["findings"]["counts"]["findings_by_severity"]["MEDIUM"] = 0
    harness["findings"]["triage"] = [
        {
            "issue": harness["medium"]["id"],
            "decision": "false_positive",
            "reason": "the pipe is closed by the leader on exit in every observed path",
        }
    ]
    harness["findings"]["counts"]["triaged"] = 1
    verdict = _run(harness)
    assert verdict.ok, verdict.report()


def test_triage_without_reason_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["triage"] = [{"issue": harness["low"]["id"], "decision": "informational", "reason": "meh"}]
    harness["findings"]["counts"]["triaged"] = 1
    verdict = _run(harness)
    assert any("no substantive reason" in r for r in verdict.rejections)


def test_fabricated_span_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"][0]["anchors"] = [{"path": "app.py", "snippet": "os.system(cmd)"}]
    verdict = _run(harness)
    assert any("span not present" in r for r in verdict.rejections), verdict.report()


def test_span_from_secondary_probe_anchor_is_accepted(harness: dict[str, Any]) -> None:
    verdict = _run(harness)
    assert verdict.ok, verdict.report()


def test_blocked_run_cited_is_block(harness: dict[str, Any]) -> None:
    blocked = record("gitleaks-git", [], status="blocked", exit_code=None, parser="none")
    harness["evidence"]["records"].append(blocked)
    harness["evidence"]["liveness"].append({"instrument": "gitleaks-git", "clean": True, "positive": True})
    harness["findings"]["findings"][0]["evidence"].append(blocked["id"])
    verdict = _run(harness)
    assert not verdict.ok
    assert verdict.computed == "BLOCK"
    assert any("blocked" in r for r in verdict.rejections)


def test_blocked_required_run_uncited_caps_hold(harness: dict[str, Any]) -> None:
    blocked = record("gitleaks-git", [], status="blocked", exit_code=None, parser="none")
    harness["evidence"]["records"].append(blocked)
    harness["evidence"]["liveness"].append({"instrument": "gitleaks-git", "clean": True, "positive": True})
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert any("gitleaks-git blocked" in c for c in verdict.caps)


def test_empty_all_clear_over_nonempty_evidence_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"] = []
    harness["findings"]["triage"] = []
    harness["findings"]["counts"] = {
        "findings_by_severity": dict.fromkeys(("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"), 0),
        "evidence_issues": 3,
        "triaged": 0,
    }
    verdict = _run(harness)
    assert any("empty all-clear" in r for r in verdict.rejections), verdict.report()


def test_dirty_tree_presented_as_clean_is_block(harness: dict[str, Any]) -> None:
    harness["evidence"]["target"]["dirty"] = True
    verdict = _run(harness)
    assert verdict.computed == "BLOCK"
    assert any("dirty tree presented as clean" in r for r in verdict.rejections)


def test_dirty_tree_declared_honestly_caps_hold(harness: dict[str, Any]) -> None:
    harness["evidence"]["target"]["dirty"] = True
    harness["findings"]["target"]["dirty"] = True
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert verdict.computed == "HOLD"


def test_unpinned_database_is_block(harness: dict[str, Any]) -> None:
    hunt = harness["hunt"]
    prov = yaml.safe_load((hunt / "provenance.yaml").read_text())
    prov["pinned"] = False
    prov["unpinned"] = ["trivy"]
    text = yaml.safe_dump(prov, sort_keys=False)
    (hunt / "provenance.yaml").write_text(text)
    from identity import sha256_text

    harness["evidence"]["provenance_digest"] = sha256_text(text)
    verdict = _run(harness)
    assert verdict.computed == "BLOCK"
    assert any("unpinned" in c for c in verdict.caps)


def test_inert_required_check_is_block(harness: dict[str, Any]) -> None:
    for entry in harness["evidence"]["liveness"]:
        if entry["instrument"] == "semgrep":
            entry["positive"] = False
    verdict = _run(harness)
    assert verdict.computed == "BLOCK"
    assert any("inert" in c for c in verdict.caps)


def test_missing_liveness_for_required_is_block(harness: dict[str, Any]) -> None:
    harness["evidence"]["liveness"] = [e for e in harness["evidence"]["liveness"] if e["instrument"] != "bandit"]
    verdict = _run(harness)
    assert verdict.computed == "BLOCK"


def test_tampered_record_is_rejected(harness: dict[str, Any]) -> None:
    harness["evidence"]["records"][0]["exit_code"] = 7
    verdict = _run(harness)
    assert any("does not match its content" in r for r in verdict.rejections)
    assert verdict.computed == "BLOCK"


def test_tampered_issue_is_rejected(harness: dict[str, Any]) -> None:
    harness["evidence"]["records"][0]["issues"][0]["anchor"] = "eval(user)"
    verdict = _run(harness)
    assert any("issue" in r and "does not match" in r for r in verdict.rejections)


def test_stale_evidence_digest_is_rejected(harness: dict[str, Any]) -> None:
    findings_path, evidence_path = write_pair(harness)
    evidence_path.write_text(evidence_path.read_text() + "# touched\n")
    verdict = verify(findings_path, evidence_path, harness["hunt"])
    assert any("evidence_digest" in r for r in verdict.rejections)


def test_raised_severity_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"][1]["severity"] = "CRITICAL"
    harness["findings"]["counts"]["findings_by_severity"] = {"INFO": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 1, "CRITICAL": 1}
    verdict = _run(harness)
    assert any("above every cited issue" in r for r in verdict.rejections)


def test_raised_disposition_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["disposition"] = "SHIP"
    verdict = _run(harness)
    assert any("above the deterministic ceiling" in r for r in verdict.rejections)


def test_lowered_disposition_is_accepted(harness: dict[str, Any]) -> None:
    harness["findings"]["disposition"] = "BLOCK"
    verdict = _run(harness)
    assert verdict.ok, verdict.report()


def test_confirmed_without_sandbox_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"][1]["reproduction"] = "confirmed"
    verdict = _run(harness)
    assert any("without a cited sandbox failure" in r for r in verdict.rejections)


def test_unknown_issue_citation_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"][0]["issues"].append("IS-ffffffffffff")
    verdict = _run(harness)
    assert any("unknown issue" in r for r in verdict.rejections)


def test_coverage_gap_caps_hold_even_when_clean(harness: dict[str, Any]) -> None:
    harness["evidence"]["records"] = [record(name, []) for name in ("bandit", "semgrep", "ruff")]
    harness["evidence"]["liveness"] = [
        {
            "instrument": name,
            "clean": True,
            "positive": True,
            "halves": {"clean": {"issues": 0, "status": "ok"}, "positive": {"issues": 1, "status": "ok"}},
        }
        for name in ("bandit", "semgrep", "ruff")
    ]
    harness["evidence"]["gaps"] = [{"surface": "scripts", "gap": "launchd not exercised", "cap": "HOLD"}]
    harness["findings"]["findings"] = []
    harness["findings"]["counts"] = {
        "findings_by_severity": dict.fromkeys(("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"), 0),
        "evidence_issues": 0,
        "triaged": 0,
    }
    harness["findings"]["disposition"] = "HOLD"
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert verdict.computed == "HOLD"


def test_clean_evidence_with_intact_provenance_supports_ship(harness: dict[str, Any]) -> None:
    harness["evidence"]["records"] = [record(name, []) for name in ("bandit", "semgrep", "ruff")]
    harness["evidence"]["liveness"] = [
        {
            "instrument": name,
            "clean": True,
            "positive": True,
            "halves": {"clean": {"issues": 0, "status": "ok"}, "positive": {"issues": 1, "status": "ok"}},
        }
        for name in ("bandit", "semgrep", "ruff")
    ]
    harness["findings"]["findings"] = []
    harness["findings"]["counts"] = {
        "findings_by_severity": dict.fromkeys(("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"), 0),
        "evidence_issues": 0,
        "triaged": 0,
    }
    harness["findings"]["disposition"] = "SHIP"
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert verdict.computed == "SHIP"


def test_waived_critical_never_ships(harness: dict[str, Any]) -> None:
    critical = issue(
        "trivy-python", "CVE-2099-0001", "CRITICAL", "supply", "requirements.txt", "pyyaml@5.1 CVE-2099-0001"
    )
    harness["evidence"]["records"].append(record("trivy-python", [critical]))
    harness["evidence"]["liveness"].append({"instrument": "trivy-python", "clean": True, "positive": True})
    harness["findings"]["findings"].append(
        {
            "id": "HND-0000000003",
            "title": "critical dependency",
            "critical_class": "supply",
            "severity": "CRITICAL",
            "reachability": "reachable",
            "reproduction": "static_only",
            "remediation": "upgrade",
            "evidence": [harness["evidence"]["records"][-1]["id"]],
            "issues": [critical["id"]],
            "anchors": [{"path": "requirements.txt", "snippet": "pyyaml@5.1"}],
            "waiver": {
                "reason": "accepted risk documented by the owner for this release train",
                "by": "owner",
                "until": "2027-01-01",
            },
        }
    )
    harness["findings"]["counts"]["findings_by_severity"]["CRITICAL"] = 1
    harness["findings"]["counts"]["evidence_issues"] = 4
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert any("never waives into SHIP" in c for c in verdict.caps)


def test_required_instrument_without_record_is_rejected(harness: dict[str, Any]) -> None:
    harness["evidence"]["records"] = [r for r in harness["evidence"]["records"] if r["instrument"] != "bandit"]
    harness["evidence"]["liveness"] = [e for e in harness["evidence"]["liveness"] if e["instrument"] != "bandit"]
    verdict = _run(harness)
    assert not verdict.ok
    assert any("bandit is in scope but has no evidence record" in r for r in verdict.rejections), verdict.report()


def test_nonboolean_liveness_is_rejected(harness: dict[str, Any]) -> None:
    harness["evidence"]["liveness"][0]["clean"] = "false"
    verdict = _run(harness)
    assert any("not boolean" in r for r in verdict.rejections), verdict.report()


def _sandbox_failure(harness: dict[str, Any], rule: str) -> None:
    test = rule.split(":", 1)[1]
    fired = issue("sandbox", rule, "MEDIUM", "logic", "sandbox/test_web.py", f"sandbox.test_web::{test}")
    rec = record("sandbox", [fired], exit_code=1)
    harness["evidence"]["records"].append(rec)
    harness["evidence"]["liveness"].append({"instrument": "sandbox", "clean": True, "positive": True})
    target = harness["findings"]["findings"][1]
    target["reproduction"] = "confirmed"
    target["evidence"].append(rec["id"])
    target["issues"].append(fired["id"])
    harness["findings"]["counts"]["evidence_issues"] = 4


def test_confirmed_requires_a_failure_that_exercises_the_hypothesis(harness: dict[str, Any]) -> None:
    _sandbox_failure(harness, "failure:test_web_05_post_handlers_survive")
    verdict = _run(harness)
    assert any("does not exercise its hypothesis" in r for r in verdict.rejections), verdict.report()


def test_confirmed_accepts_the_matching_failure(harness: dict[str, Any]) -> None:
    _sandbox_failure(harness, "failure:test_web_03_follow_returns_after_exit")
    verdict = _run(harness)
    assert verdict.ok, verdict.report()


def test_setup_error_does_not_confirm(harness: dict[str, Any]) -> None:
    _sandbox_failure(harness, "error:test_web_03_follow_returns_after_exit")
    verdict = _run(harness)
    assert any("setup errors and passes do not confirm" in r for r in verdict.rejections), verdict.report()


def test_finding_without_anchors_is_rejected(harness: dict[str, Any]) -> None:
    harness["findings"]["findings"][0]["anchors"] = []
    verdict = _run(harness)
    assert any("has no anchors" in r for r in verdict.rejections), verdict.report()


def test_edited_issue_severity_is_rejected(harness: dict[str, Any]) -> None:
    harness["high"]["severity"] = "LOW"
    harness["findings"]["findings"][0]["severity"] = "LOW"
    harness["findings"]["counts"]["findings_by_severity"] = {
        s: 0 for s in harness["findings"]["counts"]["findings_by_severity"]
    } | {"LOW": 1, "MEDIUM": 1}
    verdict = _run(harness)
    assert any("issues digest mismatch" in r for r in verdict.rejections), verdict.report()


def test_tampered_raw_artifact_is_rejected(harness: dict[str, Any]) -> None:
    raw = harness["hunt"] / "results" / "raw" / "semgrep.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("[]")
    harness["records"][0]["raw_digests"] = {"hunt/results/raw/semgrep.json": "0" * 64}
    verdict = _run(harness)
    assert any("raw artifact" in r and "does not match" in r for r in verdict.rejections), verdict.report()


def test_absent_raw_artifact_is_only_noted(harness: dict[str, Any]) -> None:
    harness["records"][0]["raw_digests"] = {"hunt/results/raw/semgrep.json": "0" * 64}
    verdict = _run(harness)
    assert verdict.ok, verdict.report()
    assert any("is absent" in n for n in verdict.notes)
