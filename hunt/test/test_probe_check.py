"""Both halves for the harness-internal checks: probe anchors, history, inventory, identity."""

from __future__ import annotations

from pathlib import Path

import yaml

from check import history_issues, inventory_issues, parse_requirements, top_level_imports
from identity import issue_id, normalize, record_id
from probe import probe, verify_anchor


def test_anchor_whitespace_insensitive(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n\n\ndef   f(a,  b):\n    return a+b\n")
    ok, _ = verify_anchor(tmp_path, {"path": "a.py", "line": 4, "snippet": "def f(a, b):"})
    assert ok
    ok, reason = verify_anchor(tmp_path, {"path": "a.py", "line": 4, "snippet": "def g():"})
    assert not ok and "not found" in reason
    ok, reason = verify_anchor(tmp_path, {"path": "missing.py", "line": 1, "snippet": "x"})
    assert not ok and "does not exist" in reason
    ok, reason = verify_anchor(tmp_path, {"path": "../a.py", "line": 1, "snippet": "x"})
    assert not ok


def test_anchor_outside_window_rejected(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("\n" * 200 + "needle = 1\n")
    ok, reason = verify_anchor(tmp_path, {"path": "b.py", "line": 5, "snippet": "needle = 1"})
    assert not ok and "not within" in reason
    ok, _ = verify_anchor(tmp_path, {"path": "b.py", "line": 201, "snippet": "needle = 1"})
    assert ok


def test_probe_lane_binding_and_failure(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run(cmd):\n    return eval(cmd)\n")
    lanes = tmp_path / "probe"
    lanes.mkdir()
    doc = {
        "lane": "demo",
        "lane_run": {
            "first_attempt": {"task": "bg_1", "status": "failed", "error": "boom"},
            "second_attempt": {"task": "bg_2", "status": "completed"},
        },
        "pruned": [{"path": "x.py", "reason": "docstring only"}],
        "hypotheses": [
            {
                "key": "demo-01",
                "title": "eval",
                "critical_class": "injection",
                "severity": "HIGH",
                "anchors": [{"path": "app.py", "line": 2, "snippet": "return eval(cmd)"}],
            },
            {
                "key": "demo-02",
                "title": "fake",
                "critical_class": "logic",
                "severity": "LOW",
                "anchors": [{"path": "app.py", "line": 2, "snippet": "os.system(cmd)"}],
            },
            {"key": "demo-03", "title": "no anchors", "critical_class": "logic", "severity": "LOW", "anchors": []},
        ],
    }
    (lanes / "demo.yaml").write_text(yaml.safe_dump(doc))
    issues, pruned, report = probe(tmp_path, lanes)
    rules = {i.rule for i in issues}
    assert "demo-01" in rules and "lane-failure" in rules
    assert "demo-02" not in rules and "demo-03" not in rules
    assert report["verified"] == 1 and report["rejected"] == 2 and report["lane_failures"] == 1
    assert any(p["path"] == "hypothesis:demo-02" for p in pruned)
    assert any(p["path"] == "x.py" for p in pruned)
    verified = next(i for i in issues if i.rule == "demo-01")
    assert verified.severity == "HIGH" and verified.critical_class == "injection" and verified.source == "lane"


def test_probe_unknown_severity_floors(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    lanes = tmp_path / "probe"
    lanes.mkdir()
    (lanes / "l.yaml").write_text(
        yaml.safe_dump(
            {
                "lane": "l",
                "hypotheses": [
                    {
                        "key": "l-1",
                        "title": "t",
                        "critical_class": "bogus",
                        "anchors": [{"path": "a.py", "line": 1, "snippet": "x = 1"}],
                    }
                ],
            }
        )
    )
    issues, _, _ = probe(tmp_path, lanes)
    assert issues[0].severity == "MEDIUM" and issues[0].critical_class == "none"


def test_history_both_halves() -> None:
    assert history_issues(["README.md", "src/app.py", ".env.example"]) == []
    fired = history_issues([".env", "keys/id_rsa", "db/app.db", "legacy/x.ipynb"], {".env"})
    assert {i.rule for i in fired} == {"dotenv", "ssh-key", "database-file", "notebook-with-outputs"}
    assert next(i for i in fired if i.rule == "dotenv").severity == "HIGH"
    assert next(i for i in fired if i.rule == "dotenv").extra["tracked"] is True


def test_inventory_both_halves() -> None:
    clean = inventory_issues(
        "six==1.17.0\n", "requirements.txt", {"six": "1.17.0"}, {"app.py": {"os", "six"}}, {"app"}, True
    )
    assert clean == []
    fired = inventory_issues(
        "requests>=2\nmissing==1.0\n",
        "requirements.txt",
        {"requests": "2.0", "yaml": "6"},
        {"app.py": {"selenium", "yaml", "app"}},
        {"app"},
        False,
    )
    rules = sorted(i.rule for i in fired)
    assert rules == [
        "declared-not-installed",
        "no-lockfile",
        "undeclared-import",
        "undeclared-import",
        "unpinned-requirement",
    ]
    undeclared = [i for i in fired if i.rule == "undeclared-import"]
    assert {i.anchor for i in undeclared} == {"import selenium", "import yaml"}


def test_requirements_and_imports_parsing() -> None:
    reqs = parse_requirements("# c\nselenium>=4.15,<5\nPyYAML==6.0.3  # pinned\n-r other.txt\n")
    assert [(r["name"], r["pinned"]) for r in reqs] == [("selenium", False), ("PyYAML", True)]
    assert top_level_imports("import os.path\nfrom yaml import safe_load\nfrom . import x\nimport a, b.c\n") == {
        "os",
        "yaml",
        "a",
        "b",
    }
    assert top_level_imports("def (") == set()


def test_identity_survives_formatting() -> None:
    assert issue_id("semgrep", "r", "a.py", "eval( x )") == issue_id("semgrep", "r", "a.py", "eval(\n  x )")
    assert issue_id("semgrep", "r", "a.py", "eval(x)") != issue_id("bandit", "r", "a.py", "eval(x)")
    assert normalize("  a \n\t b  ") == "a b"
    assert record_id("x", ["a"], 0, "o", "e") != record_id("x", ["a"], 1, "o", "e")
