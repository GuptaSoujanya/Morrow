"""Execute instruments with real exit codes, captured streams, timeouts, and raw artifacts."""

from __future__ import annotations

import datetime as dt
import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from identity import redact, sha256_bytes
from registry import Context, Instrument, argv, environment, locate

REDACTED_RAW = ("pytest-target", "sandbox")


def now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


@dataclass
class Execution:
    instrument: str
    argv: list[str]
    cwd: str
    exit_code: int | None
    status: str  # ok | blocked | timeout | failed
    started: str
    ended: str
    duration_s: float
    timeout_s: int
    stdout: str
    stderr: str
    stdout_digest: str
    stderr_digest: str
    raw: list[Path] = field(default_factory=list)
    note: str = ""


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _default_signals() -> None:
    """Start each instrument with default signal handling.

    A harness started as a background job inherits SIGINT ignored, and so would
    every test that relies on interrupting a child.
    """
    for sig in (signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, signal.SIG_DFL)


def execute(
    instrument: Instrument,
    ctx: Context,
    targets: list[str],
    raw: Path,
    *,
    label: str | None = None,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> Execution:
    """Run one instrument once. Never raises for tool failures; records them instead."""
    label = label or instrument.name
    command = argv(instrument, ctx, targets, raw)
    workdir = cwd or ctx.root
    scratch = ctx.results / "scratch" / label
    scratch.mkdir(parents=True, exist_ok=True)
    env = environment(instrument, ctx, scratch)
    if env_extra:
        env.update(env_extra)
    started = now()
    clock = dt.datetime.now(dt.UTC)
    located = locate(instrument, ctx)
    if located is None:
        ended = now()
        return Execution(
            instrument=instrument.name,
            argv=command,
            cwd=str(workdir),
            exit_code=None,
            status="blocked",
            started=started,
            ended=ended,
            duration_s=0.0,
            timeout_s=instrument.timeout_s,
            stdout="",
            stderr="",
            stdout_digest=sha256_bytes(b""),
            stderr_digest=sha256_bytes(b""),
            raw=[],
            note=f"binary '{instrument.binary}' not found for kind {instrument.kind}",
        )
    raw.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            timeout=instrument.timeout_s,
            check=False,
            preexec_fn=_default_signals,
        )
        exit_code: int | None = completed.returncode
        out, err = completed.stdout, completed.stderr
        status = "ok" if completed.returncode in instrument.exit_ok else "failed"
        note = ""
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        out = exc.stdout or b""
        err = exc.stderr or b""
        status = "timeout"
        note = f"timed out after {instrument.timeout_s}s"
    except (OSError, PermissionError) as exc:
        exit_code = None
        out, err = b"", str(exc).encode()
        status = "blocked"
        note = f"could not start: {exc}"
    ended = now()
    duration = (dt.datetime.now(dt.UTC) - clock).total_seconds()
    # Captured output is evidence; credential-looking assignments never reach disk or digests.
    out = redact(out.decode("utf-8", "replace")).encode("utf-8")
    err = redact(err.decode("utf-8", "replace")).encode("utf-8")
    if raw.exists() and instrument.name in REDACTED_RAW:
        raw.write_text(redact(raw.read_text("utf-8", "replace")), "utf-8")
    stdout_path = ctx.results / "transcript" / f"{label}.stdout.txt"
    stderr_path = ctx.results / "transcript" / f"{label}.stderr.txt"
    _write(stdout_path, out)
    _write(stderr_path, err)
    raw_paths = [stdout_path, stderr_path]
    if raw.exists():
        raw_paths.insert(0, raw)
    return Execution(
        instrument=instrument.name,
        argv=command,
        cwd=str(workdir),
        exit_code=exit_code,
        status=status,
        started=started,
        ended=ended,
        duration_s=round(duration, 3),
        timeout_s=instrument.timeout_s,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
        stdout_digest=sha256_bytes(out),
        stderr_digest=sha256_bytes(err),
        raw=raw_paths,
        note=note,
    )


def internal(instrument: Instrument, ctx: Context, payload: bytes, raw: Path, note: str = "") -> Execution:
    """Synthesize an execution record for a harness-internal deterministic check."""
    started = now()
    _write(raw, payload)
    return Execution(
        instrument=instrument.name,
        argv=["hound", "internal", instrument.name],
        cwd=str(ctx.root),
        exit_code=0,
        status="ok",
        started=started,
        ended=now(),
        duration_s=0.0,
        timeout_s=instrument.timeout_s,
        stdout="",
        stderr="",
        stdout_digest=sha256_bytes(payload),
        stderr_digest=sha256_bytes(b""),
        raw=[raw],
        note=note,
    )


def git(root: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    """Read-only git helper; returns exit code and stdout."""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return completed.returncode, completed.stdout
