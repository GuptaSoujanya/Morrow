"""Execute harness checks and their independent clean/planted fixtures."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(hunt: Path, output: Path, fixture: str | None = None) -> dict[str, Any]:
    binaries = Path(sys.prefix) / "bin"
    label = fixture or "actual"
    work = hunt / "results" / "quality" / label
    work.mkdir(parents=True, exist_ok=True)
    subject = hunt / "fixture" / str(fixture) / "quality" if fixture else hunt
    commands = {
        "formatter": [str(binaries / "ruff"), "format", "--check", *(["--isolated"] if fixture else []), str(subject)],
        "linter": [str(binaries / "ruff"), "check", "--no-cache", *(["--isolated"] if fixture else []), str(subject)],
        "types": [
            str(binaries / "mypy"),
            "--cache-dir",
            str(work / "mypy"),
            *(["--strict", str(subject / "subject.py")] if fixture else ["."]),
        ],
        "controls": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "--basetemp",
            str(work / "tmp"),
            "--junitxml",
            str(work / "tests.xml"),
            str(subject if fixture else hunt / "test"),
        ],
    }
    checks: list[dict[str, Any]] = []
    for name, command in commands.items():
        proc = subprocess.run(
            command,
            cwd=hunt,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        checks.append(
            {"name": name, "argv": command, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        )
    payload = {"fixture": fixture, "checks": checks}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", choices=("clean", "positive"))
    args = parser.parse_args()
    result = run(Path(__file__).resolve().parent, args.output, args.fixture)
    print(json.dumps({c["name"]: c["exit_code"] for c in result["checks"]}))
    raise SystemExit(int(any(c["exit_code"] != 0 for c in result["checks"])))


if __name__ == "__main__":
    main()
