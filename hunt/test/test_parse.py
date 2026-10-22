"""Parser both halves over inline samples: fire on findings, stay quiet on none, fail on garbage."""

from __future__ import annotations

import json
from pathlib import Path

from parse import parse


def _raw(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
    return path


def test_semgrep_fires_and_classifies(tmp_path: Path) -> None:
    doc = {
        "results": [
            {
                "check_id": "python.lang.security.audit.eval-detected",
                "path": "app.py",
                "start": {"line": 3},
                "extra": {
                    "lines": "return eval(expr)",
                    "message": "eval",
                    "severity": "ERROR",
                    "metadata": {"category": "security"},
                },
            },
            {
                "check_id": "hound.python.log-credential",
                "path": "x.py",
                "start": {"line": 9},
                "extra": {
                    "lines": "log(password)",
                    "message": "cred",
                    "severity": "INFO",
                    "metadata": {"hound_class": "secret"},
                },
            },
        ],
        "errors": [],
    }
    status, issues = parse("semgrep", _raw(tmp_path, "s.json", doc), "")
    assert status == "ok"
    assert [i.severity for i in issues] == ["HIGH", "LOW"]
    assert [i.critical_class for i in issues] == ["injection", "secret"]
    assert issues[0].id.startswith("IS-")


def test_semgrep_clean_and_garbage(tmp_path: Path) -> None:
    assert parse("semgrep", _raw(tmp_path, "c.json", {"results": [], "errors": []}), "") == ("ok", [])
    assert parse("semgrep", _raw(tmp_path, "g.json", "not json"), "")[0] == "failed"
    assert parse("semgrep", _raw(tmp_path, "w.json", {"foo": 1}), "")[0] == "failed"


def test_bandit(tmp_path: Path) -> None:
    doc = {
        "results": [
            {
                "test_id": "B602",
                "filename": "app.py",
                "line_number": 2,
                "code": "subprocess.call(cmd, shell=True)",
                "issue_text": "shell",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
            }
        ]
    }
    status, issues = parse("bandit", _raw(tmp_path, "b.json", doc), "")
    assert status == "ok" and issues[0].critical_class == "injection" and issues[0].severity == "HIGH"
    unknown = {
        "results": [
            {
                "test_id": "B999",
                "filename": "a.py",
                "line_number": 1,
                "code": "x",
                "issue_text": "t",
                "issue_severity": "WEIRD",
            }
        ]
    }
    _, issues = parse("bandit", _raw(tmp_path, "u.json", unknown), "")
    assert issues[0].severity == "MEDIUM" and issues[0].critical_class == "none"


def test_ruff(tmp_path: Path) -> None:
    doc = [
        {"code": "F821", "filename": "app.py", "location": {"row": 4, "column": 1}, "message": "undefined name 'x'"},
        {"code": "F401", "filename": "app.py", "location": {"row": 1, "column": 1}, "message": "unused"},
    ]
    status, issues = parse("ruff", _raw(tmp_path, "r.json", doc), "")
    assert status == "ok" and issues[0].severity == "HIGH" and issues[1].severity == "INFO"
    assert parse("ruff", None, "") == ("ok", [])


def test_shellcheck() -> None:
    out = json.dumps(
        [
            {"file": "run.sh", "line": 3, "level": "warning", "code": 2086, "message": "quote"},
            {"file": "run.sh", "line": 4, "level": "error", "code": 2114, "message": "rm -rf"},
        ]
    )
    status, issues = parse("shellcheck", None, out)
    assert status == "ok" and issues[0].critical_class == "injection" and issues[1].severity == "HIGH"
    assert parse("shellcheck", None, "[]") == ("ok", [])
    assert parse("shellcheck", None, "{bad")[0] == "failed"


def test_gitleaks(tmp_path: Path) -> None:
    doc = [
        {
            "RuleID": "aws-access-token",
            "File": "app.py",
            "StartLine": 30,
            "Commit": "abc123def456789",
            "Match": "AKIA...REDACTED",
            "Description": "AWS",
            "Fingerprint": "abc:app.py:aws:30",
        }
    ]
    status, issues = parse("gitleaks-git", _raw(tmp_path, "g.json", doc), "")
    assert (
        status == "ok"
        and issues[0].instrument == "gitleaks-git"
        and issues[0].severity == "HIGH"
        and issues[0].critical_class == "secret"
    )
    assert parse("gitleaks-dir", _raw(tmp_path, "e.json", "[]"), "") == ("ok", [])
    assert parse("gitleaks-dir", None, "no leaks found") == ("ok", [])
    assert parse("gitleaks-dir", None, "")[0] == "failed"


def test_trivy_cvss_floor(tmp_path: Path) -> None:
    doc = {
        "SchemaVersion": 2,
        "Results": [
            {
                "Target": "requirements.txt",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-1",
                        "PkgName": "pyyaml",
                        "InstalledVersion": "5.1",
                        "Severity": "HIGH",
                        "CVSS": {"nvd": {"V3Score": 9.8}},
                    },
                    {"VulnerabilityID": "CVE-2", "PkgName": "six", "InstalledVersion": "1.0", "Severity": "UNKNOWN"},
                ],
            }
        ],
    }
    status, issues = parse("trivy-python", _raw(tmp_path, "t.json", doc), "")
    assert status == "ok" and issues[0].severity == "CRITICAL" and issues[1].severity == "MEDIUM"
    assert all(i.critical_class == "supply" and i.instrument == "trivy-python" for i in issues)


def test_junit(tmp_path: Path) -> None:
    xml = (
        '<testsuites><testsuite name="pytest"><testcase classname="tests.web.test_x" name="test_a"/>'
        '<testcase classname="tests.web.test_x" name="test_b"><failure message="assert 1 == 2">trace</failure>'
        "</testcase></testsuite></testsuites>"
    )
    path = tmp_path / "j.xml"
    path.write_text(xml)
    status, issues = parse("pytest-target", path, "")
    assert (
        status == "ok"
        and len(issues) == 1
        and issues[0].path == "tests/web/test_x.py"
        and issues[0].rule == "failure:test_b"
    )
    status, issues = parse("sandbox", path, "")
    assert issues[0].instrument == "sandbox"
    assert parse("sandbox", tmp_path / "missing.xml", "")[0] == "failed"


def test_internal_parser_is_none() -> None:
    assert parse("history", None, "") == ("none", [])


def test_semgrep_hidden_lines_fall_back_to_the_file(tmp_path: Path) -> None:
    """The registry returns 'requires login' instead of source lines for some rules; the anchor must still be real."""
    (tmp_path / "app.py").write_text("import os\nsubprocess_call = 1\n", encoding="utf-8")
    raw = tmp_path / "semgrep.json"
    raw.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "check_id": "x.rule",
                        "path": "app.py",
                        "start": {"line": 2},
                        "extra": {"lines": "requires login", "severity": "WARNING", "message": "m", "metadata": {}},
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    status, issues = parse("semgrep", raw, "", tmp_path, None)
    assert status == "ok" and len(issues) == 1
    assert issues[0].anchor == "subprocess_call = 1"


def test_redact_blanks_quoted_credential_values() -> None:
    from identity import REDACTED, redact

    text = "Settings(email='a@b.c', password='#xdfY!q', app_password=\"zz\", dry_run=False)"
    out = redact(text)
    assert "#xdfY!q" not in out and "zz" not in out
    assert f"password='{REDACTED}'" in out and f'app_password="{REDACTED}"' in out
    assert "email='a@b.c'" in out and "dry_run=False" in out


def test_redact_leaves_code_anchors_alone() -> None:
    from identity import redact

    line = 'logger.error("Set NAUKRI_EMAIL and NAUKRI_PASSWORD in .env")'
    assert redact(line) == line


def test_node_junit_locates_by_file(tmp_path: Path) -> None:
    raw = tmp_path / "node.xml"
    raw.write_text(
        '<?xml version="1.0"?><testsuites>'
        f'<testcase name="ok" classname="test" file="{tmp_path}/t/a.test.mjs"/>'
        f'<testcase name="bad" classname="test" file="{tmp_path}/t/a.test.mjs">'
        '<failure type="testCodeFailure" message="expected 3"/></testcase></testsuites>'
    )
    status, issues = parse("node-test", raw, "", tmp_path)
    assert status == "ok"
    assert [(i.rule, i.path, i.severity) for i in issues] == [("failure:bad", "t/a.test.mjs", "MEDIUM")]
    assert parse("node-test", tmp_path / "missing.xml", "", tmp_path)[0] == "failed"


def test_node_test_targets_follow_the_test_script(tmp_path: Path) -> None:
    from registry import node_test_targets

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node --test tests/"}}))
    assert node_test_targets(tmp_path) == ["tests/"]
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
    assert node_test_targets(tmp_path) == []
