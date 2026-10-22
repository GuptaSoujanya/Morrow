"""Instrument registry: every tool HOUND may run, its argv builder, and its caps.

An instrument that is required for a selected ecosystem but absent or blocked
caps the disposition at `cap_when_absent`; it is never silently skipped.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

EXCLUDES: tuple[str, ...] = ("venv", "node_modules", "hunt", "data", ".omo", ".pytest_cache", ".git")

# Credential-bearing keys that must never reach a child process started by HOUND.
CREDENTIAL_KEYS: tuple[str, ...] = (
    "NAUKRI_EMAIL",
    "NAUKRI_PASSWORD",
    "LINKEDIN_EMAIL",
    "LINKEDIN_PASSWORD",
    "GOOGLE_EMAIL",
    "GOOGLE_PASSWORD",
    "GMAIL_APP_PASSWORD",
    "COMPANY_SITE_EMAIL",
    "COMPANY_SITE_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ANTHROPIC_API_KEY",
)

# Path-bearing keys redirected into a scratch directory when target code runs.
PATH_KEYS: tuple[str, ...] = (
    "DATA_DIR",
    "DB_PATH",
    "REPORT_DIR",
    "SCREENSHOT_DIR",
    "RESUME_OUT_DIR",
    "LINKEDIN_STATE_PATH",
    "LINKEDIN_DRAFT_DIR",
    "LINKEDIN_BROWSER_PROFILE_DIR",
    "PROFILE_UPDATE_STATE_PATH",
    "PROFILE_PATH",
    "COURSE_DIR",
)


@dataclass(frozen=True)
class Instrument:
    name: str
    category: str
    binary: str
    kind: str  # venv | external | node | target-venv | internal
    ecosystems: tuple[str, ...]
    required: bool
    critical: tuple[str, ...]
    evidence_class: str  # static | dynamic | provenance
    timeout_s: int
    database: bool
    cap_when_absent: str
    conditions: tuple[str, ...] = ()
    parser: bool = True
    raw: bool = True
    exit_ok: tuple[int, ...] = (0, 1)
    description: str = ""


@dataclass
class Context:
    root: Path
    hunt: Path
    results: Path
    rule: Path
    fixture: Path
    ecosystems: set[str]
    conditions: set[str]
    python_dirs: list[str]
    js_targets: list[str]
    shell_targets: list[str]
    node_project: Path | None
    target_python: Path | None
    staged: dict[str, Path] = field(default_factory=dict)


REGISTRY: tuple[Instrument, ...] = (
    Instrument(
        name="semgrep",
        category="sast",
        binary="semgrep",
        kind="venv",
        ecosystems=("python", "javascript", "shell"),
        required=True,
        critical=("injection", "auth", "secret", "api_misuse", "error"),
        evidence_class="static",
        timeout_s=1800,
        database=True,
        cap_when_absent="HOLD",
        exit_ok=(0, 1),
        description="Frozen registry packs plus HOUND custom rules; --config auto is forbidden.",
    ),
    Instrument(
        name="bandit",
        category="sast",
        binary="bandit",
        kind="venv",
        ecosystems=("python",),
        required=True,
        critical=("injection", "secret", "api_misuse", "error"),
        evidence_class="static",
        timeout_s=600,
        database=False,
        cap_when_absent="HOLD",
        exit_ok=(0, 1),
        description="Python security linter, pinned in the hunt environment.",
    ),
    Instrument(
        name="ruff",
        category="lint",
        binary="ruff",
        kind="venv",
        ecosystems=("python",),
        required=True,
        critical=("logic", "error"),
        evidence_class="static",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        exit_ok=(0, 1),
        description="Correctness subset only: pyflakes, syntax errors, pylint errors, bugbear.",
    ),
    Instrument(
        name="shellcheck",
        category="lint",
        binary="shellcheck",
        kind="venv",
        ecosystems=("shell",),
        required=True,
        critical=("injection", "logic", "error"),
        evidence_class="static",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        exit_ok=(0, 1),
        description="Shell static analysis via the pinned shellcheck-py wheel.",
    ),
    Instrument(
        name="gitleaks-git",
        category="secrets",
        binary="gitleaks",
        kind="external",
        ecosystems=("python", "javascript", "shell", "web", "docs"),
        required=True,
        critical=("secret",),
        evidence_class="static",
        timeout_s=900,
        database=True,
        cap_when_absent="HOLD",
        conditions=("git-history",),
        exit_ok=(0, 1),
        description="Full git history secret scan; rules pinned by the recorded binary digest.",
    ),
    Instrument(
        name="gitleaks-dir",
        category="secrets",
        binary="gitleaks",
        kind="external",
        ecosystems=("python", "javascript", "shell", "web", "docs"),
        required=True,
        critical=("secret",),
        evidence_class="static",
        timeout_s=900,
        database=True,
        cap_when_absent="HOLD",
        exit_ok=(0, 1),
        description="Working tree secret scan including untracked files, under the ignore policy.",
    ),
    Instrument(
        name="trivy-python",
        category="supply",
        binary="trivy",
        kind="external",
        ecosystems=("python",),
        required=True,
        critical=("supply",),
        evidence_class="static",
        timeout_s=900,
        database=True,
        cap_when_absent="HOLD",
        conditions=("python-environment",),
        exit_ok=(0,),
        description="Vulnerability scan of the frozen installed Python environment with a pinned DB.",
    ),
    Instrument(
        name="trivy-node",
        category="supply",
        binary="trivy",
        kind="external",
        ecosystems=("javascript",),
        required=True,
        critical=("supply",),
        evidence_class="static",
        timeout_s=900,
        database=True,
        cap_when_absent="HOLD",
        conditions=("node-lockfile",),
        exit_ok=(0,),
        description="Vulnerability scan of the npm lockfile with a pinned DB.",
    ),
    Instrument(
        name="oxlint",
        category="lint",
        binary="oxlint",
        kind="node",
        ecosystems=("javascript",),
        required=True,
        critical=("logic", "error"),
        evidence_class="static",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        conditions=("node-project", "node-oxlint"),
        exit_ok=(0, 1),
        description="The frontend's own pinned linter run with its own configuration.",
    ),
    Instrument(
        name="tsc",
        category="types",
        binary="tsc",
        kind="node",
        ecosystems=("javascript",),
        required=True,
        critical=("logic",),
        evidence_class="static",
        timeout_s=600,
        database=False,
        cap_when_absent="HOLD",
        conditions=("node-project", "node-typescript"),
        exit_ok=(0, 1, 2),
        description="TypeScript type check with emit disabled; writes nothing into the target.",
    ),
    Instrument(
        name="pytest-target",
        category="tests",
        binary="python3",
        kind="target-venv",
        ecosystems=("python",),
        required=True,
        critical=("logic", "error"),
        evidence_class="dynamic",
        timeout_s=1200,
        database=False,
        cap_when_absent="HOLD",
        conditions=("python-tests", "python-environment"),
        exit_ok=(0, 1),
        description="The project's own test suite in its declared environment with credentials stripped.",
    ),
    Instrument(
        name="node-test",
        category="tests",
        binary="node",
        kind="external",
        ecosystems=("javascript",),
        required=True,
        critical=("logic", "error"),
        evidence_class="dynamic",
        timeout_s=600,
        database=False,
        cap_when_absent="HOLD",
        conditions=("node-tests",),
        exit_ok=(0, 1),
        description="The node project's own `node --test` suite, as its package.json test script declares.",
    ),
    Instrument(
        name="history",
        category="secrets",
        binary="git",
        kind="external",
        ecosystems=("python", "javascript", "shell", "web", "docs"),
        required=True,
        critical=("secret",),
        evidence_class="provenance",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        conditions=("git-history",),
        exit_ok=(0,),
        description="Sensitive filenames ever committed anywhere in history.",
    ),
    Instrument(
        name="inventory",
        category="supply",
        binary="hound",
        kind="internal",
        ecosystems=("python", "javascript"),
        required=True,
        critical=("supply", "logic"),
        evidence_class="provenance",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        exit_ok=(0,),
        description="Manifest hygiene: pins, lockfiles, undeclared imports, declared-versus-installed drift.",
    ),
    Instrument(
        name="probe",
        category="probe",
        binary="hound",
        kind="internal",
        ecosystems=("python", "javascript", "shell", "web", "docs"),
        required=False,
        critical=tuple(),
        evidence_class="static",
        timeout_s=300,
        database=False,
        cap_when_absent="HOLD",
        exit_ok=(0,),
        description="Lane hypotheses bound to verbatim code anchors; unanchored hypotheses are rejected.",
    ),
    Instrument(
        name="sandbox",
        category="sandbox",
        binary="python3",
        kind="venv",
        ecosystems=("python",),
        required=False,
        critical=tuple(),
        evidence_class="dynamic",
        timeout_s=1200,
        database=False,
        cap_when_absent="HOLD",
        conditions=("sandbox-reproductions",),
        exit_ok=(0, 1),
        description="Reproductions run in the pinned hunt environment with sockets blocked.",
    ),
)


def by_name(name: str) -> Instrument:
    for instrument in REGISTRY:
        if instrument.name == name:
            return instrument
    raise KeyError(name)


def applicable(ctx: Context) -> list[Instrument]:
    chosen: list[Instrument] = []
    for instrument in REGISTRY:
        if not set(instrument.ecosystems) & ctx.ecosystems:
            continue
        if not set(instrument.conditions) <= ctx.conditions:
            continue
        chosen.append(instrument)
    return chosen


def node_test_targets(project: Path) -> list[str]:
    """Paths named by a package.json test script of the form `node --test <paths>`, else empty."""
    try:
        script = json.loads((project / "package.json").read_text()).get("scripts", {}).get("test", "")
    except (OSError, ValueError, AttributeError):
        return []
    words = str(script).split()
    if words[:2] != ["node", "--test"]:
        return []
    return [w for w in words[2:] if not w.startswith("-")] or ["."]


def venv_bin() -> Path:
    """The bin directory of the interpreter running the harness, without following the venv symlink."""
    return Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")


def locate(instrument: Instrument, ctx: Context) -> Path | None:
    if instrument.kind == "venv":
        candidate = venv_bin() / instrument.binary
        if instrument.binary == "python3":
            candidate = Path(sys.executable)
        return candidate if candidate.exists() else None
    if instrument.kind == "external":
        found = shutil.which(instrument.binary)
        return Path(found) if found else None
    if instrument.kind == "node":
        if ctx.node_project is None:
            return None
        candidate = ctx.node_project / "node_modules" / ".bin" / instrument.binary
        return candidate if candidate.exists() and os.access(candidate, os.X_OK) else None
    if instrument.kind == "target-venv":
        return ctx.target_python if ctx.target_python and ctx.target_python.exists() else None
    if instrument.kind == "internal":
        return Path(sys.executable)
    return None


def _rel(ctx: Context, path: Path) -> str:
    try:
        return path.relative_to(ctx.root).as_posix()
    except ValueError:
        return str(path)


def _semgrep(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    argv = [
        "semgrep",
        "scan",
        "--metrics=off",
        "--disable-version-check",
        "--json",
        "--output",
        _rel(ctx, raw),
        "--config",
        _rel(ctx, ctx.rule / "semgrep.yaml"),
        "--config",
        _rel(ctx, ctx.rule / "custom.yaml"),
        "--timeout",
        "30",
        "--max-target-bytes",
        "2000000",
    ]
    for name in EXCLUDES:
        argv.extend(["--exclude", name])
    argv.extend(targets)
    return argv


def _bandit(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "bandit",
        "-r",
        "-q",
        "-f",
        "json",
        "-o",
        _rel(ctx, raw),
        "-s",
        "B101",
        "--exclude",
        ",".join(EXCLUDES),
        *targets,
    ]


def _ruff(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "ruff",
        "check",
        "--isolated",
        "--no-cache",
        "--output-format",
        "json",
        "--output-file",
        _rel(ctx, raw),
        "--select",
        "F,E9,PLE,B",
        "--target-version",
        "py312",
        *[f"--exclude={name}" for name in EXCLUDES],
        *targets,
    ]


def _shellcheck(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return ["shellcheck", "-f", "json", "-S", "info", "-s", "bash", *targets]


def _gitleaks(mode: str, ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "gitleaks",
        mode,
        "--config",
        _rel(ctx, ctx.rule / "gitleaks.toml"),
        "--redact",
        "--no-banner",
        "--exit-code",
        "1",
        "--log-level",
        "warn",
        "--report-format",
        "json",
        "--report-path",
        _rel(ctx, raw),
        "--max-target-megabytes",
        "5",
        *targets,
    ]


def _trivy(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "trivy",
        "fs",
        "--cache-dir",
        _rel(ctx, ctx.results / "trivy"),
        "--skip-db-update",
        "--skip-java-db-update",
        "--offline-scan",
        "--scanners",
        "vuln",
        "--format",
        "json",
        "--output",
        _rel(ctx, raw),
        "--quiet",
        "--exit-code",
        "0",
        *targets,
    ]


def _oxlint(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    config = ctx.node_project / ".oxlintrc.json" if ctx.node_project else Path(".oxlintrc.json")
    return ["oxlint", "-c", _rel(ctx, config), "-f", "json", *targets]


def _tsc(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    if targets and targets[0].endswith(".json"):
        return ["tsc", "-p", targets[0], "--noEmit", "--incremental", "false", "--pretty", "false"]
    return ["tsc", "--noEmit", "--strict", "--pretty", "false", "--target", "es2022", *targets]


def _pytest(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "python3",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        _rel(ctx, ctx.results / "pytest-tmp"),
        "--junitxml",
        _rel(ctx, raw),
        "-o",
        "addopts=",
        *targets,
    ]


def _sandbox(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return [
        "python3",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--disable-socket",
        "--basetemp",
        _rel(ctx, ctx.results / "sandbox-tmp"),
        "--junitxml",
        _rel(ctx, raw),
        "-o",
        "addopts=",
        "--rootdir",
        _rel(ctx, ctx.hunt),
        *targets,
    ]


def _node_test(ctx: Context, targets: list[str], raw: Path) -> list[str]:
    return ["node", "--test", "--test-reporter=junit", f"--test-reporter-destination={raw}", *targets]


Builder = Callable[[Context, list[str], Path], list[str]]

BUILDERS: dict[str, Builder] = {
    "semgrep": _semgrep,
    "bandit": _bandit,
    "ruff": _ruff,
    "shellcheck": _shellcheck,
    "gitleaks-git": lambda ctx, targets, raw: _gitleaks("git", ctx, targets, raw),
    "gitleaks-dir": lambda ctx, targets, raw: _gitleaks("dir", ctx, targets, raw),
    "trivy-python": _trivy,
    "trivy-node": _trivy,
    "oxlint": _oxlint,
    "tsc": _tsc,
    "pytest-target": _pytest,
    "sandbox": _sandbox,
    "node-test": _node_test,
}


def default_targets(instrument: Instrument, ctx: Context) -> list[str]:
    name = instrument.name
    if name == "semgrep":
        extra = [_rel(ctx, p) for key, p in ctx.staged.items() if key in ("notebook", "inline-js")]
        return [*ctx.python_dirs, *ctx.js_targets, *ctx.shell_targets, *extra]
    if name in ("bandit", "ruff"):
        extra = [_rel(ctx, p) for key, p in ctx.staged.items() if key == "notebook"]
        return [*ctx.python_dirs, *extra]
    if name == "shellcheck":
        return list(ctx.shell_targets)
    if name in ("gitleaks-git", "gitleaks-dir"):
        return ["."]
    if name == "trivy-python":
        return [_rel(ctx, ctx.staged["freeze"])] if "freeze" in ctx.staged else []
    if name == "trivy-node":
        return [_rel(ctx, ctx.staged["node-lock"])] if "node-lock" in ctx.staged else []
    if name == "oxlint":
        return [_rel(ctx, ctx.node_project / "src")] if ctx.node_project else []
    if name == "tsc":
        return [_rel(ctx, ctx.node_project / "tsconfig.app.json")] if ctx.node_project else []
    if name == "pytest-target":
        return ["tests"]
    if name == "sandbox":
        return [_rel(ctx, ctx.hunt / "sandbox")]
    if name == "node-test":
        return (
            [_rel(ctx, ctx.node_project / t) for t in node_test_targets(ctx.node_project)] if ctx.node_project else []
        )
    return []


def argv(instrument: Instrument, ctx: Context, targets: list[str], raw: Path) -> list[str]:
    builder = BUILDERS.get(instrument.name)
    if builder is None:
        return ["hound", "internal", instrument.name]
    built = builder(ctx, targets, raw)
    located = locate(instrument, ctx)
    if located is not None:
        built[0] = str(located)
    return built


def environment(instrument: Instrument, ctx: Context, scratch: Path) -> dict[str, str]:
    """Child environment: credentials stripped, writable paths redirected, bytecode off."""
    env = {key: value for key, value in os.environ.items() if key not in CREDENTIAL_KEYS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOUND_TARGET"] = str(ctx.root)
    env["HOUND_SCRATCH"] = str(scratch)
    if instrument.name in ("pytest-target", "sandbox"):
        for key in PATH_KEYS:
            env[key] = str(scratch / key.lower())
        env["DRY_RUN"] = "1"
        env["HEADLESS"] = "1"
        env["LLM_BACKEND"] = "none"
    if instrument.name == "sandbox":
        env["PYTHONPATH"] = str(ctx.root)
    if instrument.name in ("oxlint", "tsc"):
        env["NO_COLOR"] = "1"
    if instrument.name == "semgrep":
        env["SEMGREP_SEND_METRICS"] = "off"
        env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
    if instrument.name.startswith("trivy"):
        env["TRIVY_NO_PROGRESS"] = "true"
    return env
