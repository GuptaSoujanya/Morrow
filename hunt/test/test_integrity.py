"""Negative controls for resumed source, liveness and severity bindings."""

from __future__ import annotations

from typing import Any

import yaml
from conftest import write_pair

from identity import issues_digest, sha256_file
from verify import verify


def gate(harness: dict[str, Any]) -> Any:
    findings, evidence = write_pair(harness)
    return verify(findings, evidence, harness["hunt"])


def test_critical_lowering_blocks(harness: dict[str, Any]) -> None:
    harness["high"]["severity"] = "CRITICAL"
    harness["records"][0]["issues_digest"] = issues_digest(harness["records"][0]["issues"])
    verdict = gate(harness)
    assert verdict.computed == "BLOCK"
    assert any("severity floor" in reason for reason in verdict.caps)


def test_conflicting_duplicate_cannot_hide_critical(harness: dict[str, Any]) -> None:
    first = harness["high"]
    first["severity"] = "CRITICAL"
    harness["records"][0]["issues"].append({**first, "severity": "LOW"})
    harness["records"][0]["issues_digest"] = issues_digest(harness["records"][0]["issues"])
    verdict = gate(harness)
    assert verdict.computed == "BLOCK"
    assert any("conflicting duplicate" in reason for reason in verdict.rejections)


def test_forged_liveness_flag_rejected(harness: dict[str, Any]) -> None:
    harness["evidence"]["liveness"][0]["halves"]["positive"]["issues"] = 0
    verdict = gate(harness)
    assert not verdict.ok
    assert any("contradicts" in reason for reason in verdict.rejections)


def test_parser_failure_cannot_support_finding(harness: dict[str, Any]) -> None:
    harness["records"][0]["parser"] = "failed"
    verdict = gate(harness)
    assert any("parser failed" in reason for reason in verdict.rejections)


def test_changed_source_caps_even_with_same_git_sha(harness: dict[str, Any]) -> None:
    hunt = harness["hunt"]
    source = hunt.parent / "app.py"
    source.write_text("old = 1\n")
    scope_path = hunt / "scope.yaml"
    scope = yaml.safe_load(scope_path.read_text())
    scope["inventory"] = {"source_hashes": {"app.py": sha256_file(source)}}
    scope_path.write_text(yaml.safe_dump(scope))
    prov_path = hunt / "provenance.yaml"
    prov = yaml.safe_load(prov_path.read_text())
    prov["scope"]["sha256"] = sha256_file(scope_path)
    prov_path.write_text(yaml.safe_dump(prov))
    harness["evidence"]["scope_digest"] = sha256_file(scope_path)
    harness["evidence"]["provenance_digest"] = sha256_file(prov_path)
    clean = gate(harness)
    assert not any("target source changed" in reason for reason in clean.caps)
    source.write_text("new = 2\n")
    changed = gate(harness)
    assert any("target source changed" in reason for reason in changed.caps)
