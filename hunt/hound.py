"""HOUND command line: provision, run, verify.

`run` derives scope, records provenance, proves both halves of every instrument,
executes every applicable instrument, binds lane hypotheses to code anchors, and
emits hunt/evidence.yaml as the only citable source. `verify` is the gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

import emit
import liveness as liveness_mod
import provenance as provenance_mod
import scope as scope_mod
from check import collect_imports, history_issues, inventory_issues, parse_freeze
from identity import record_id, sha256_file, sha256_text
from parse import junit_summary, parse
from probe import probe as probe_lanes
from registry import Context, Instrument, default_targets, locate
from runner import Execution, execute, git, internal
from schema import Issue, Record
from verify import verify as verify_docs

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)

HUNT = Path(__file__).resolve().parent
ROOT = HUNT.parent


def _paths(root: Path | None) -> tuple[Path, Path]:
    target = (root or ROOT).resolve()
    return target, target / "hunt"


def _record(
    execution: Execution,
    instrument: Instrument,
    ctx: Context,
    parser: str,
    issues: list[Issue],
    config_digest: str,
    db_digest: str,
    pruned: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
) -> Record:
    raw = [p.relative_to(ctx.root).as_posix() if p.is_relative_to(ctx.root) else str(p) for p in execution.raw]
    raw_digests = {rel: sha256_file(p) for rel, p in zip(raw, execution.raw, strict=True) if p.is_file()}
    return Record(
        raw_digests=raw_digests,
        id=record_id(
            execution.instrument, execution.argv, execution.exit_code, execution.stdout_digest, execution.stderr_digest
        ),
        instrument=execution.instrument,
        category=instrument.category,
        argv=execution.argv,
        cwd=execution.cwd,
        exit_code=execution.exit_code,
        status=execution.status,
        parser=parser,
        started=execution.started,
        ended=execution.ended,
        duration_s=execution.duration_s,
        timeout_s=execution.timeout_s,
        config_digest=config_digest,
        db_digest=db_digest,
        raw=raw,
        stdout_digest=execution.stdout_digest,
        stderr_digest=execution.stderr_digest,
        issues=issues,
        pruned=pruned or [],
        gaps=gaps or [],
        note=execution.note,
    )


def _config_digest(instrument: Instrument, ctx: Context) -> str:
    if instrument.name == "semgrep":
        return sha256_text(sha256_file(ctx.rule / "semgrep.yaml") + sha256_file(ctx.rule / "custom.yaml"))
    if instrument.name.startswith("gitleaks"):
        return sha256_file(ctx.rule / ("history.toml" if instrument.name == "gitleaks-git" else "gitleaks.toml"))
    return sha256_text(f"argv-only:{instrument.name}")


def _db_digest(instrument: Instrument, prov: dict[str, Any]) -> str:
    databases = prov.get("databases") or {}
    tools = prov.get("tools") or {}
    if instrument.name == "semgrep":
        return str((databases.get("semgrep") or {}).get("semgrep_yaml_sha256") or "unpinned")
    if instrument.name == "trivy-config":
        return str(((tools.get("trivy") or {}).get("binary") or {}).get("sha256") or "unpinned")
    if instrument.name.startswith("trivy"):
        return str((databases.get("trivy") or {}).get("metadata_sha256") or "unpinned")
    if instrument.name.startswith("gitleaks"):
        return str(((tools.get("gitleaks") or {}).get("binary") or {}).get("sha256") or "unpinned")
    return "none"


def _history(ctx: Context, instrument: Instrument, prov: dict[str, Any]) -> Record:
    code, out = git(ctx.root, "log", "--all", "--name-only", "--pretty=format:", "--diff-filter=A")
    paths = sorted({line.strip() for line in out.splitlines() if line.strip()}) if code == 0 else []
    tcode, tracked_out = git(ctx.root, "ls-files")
    tracked = set(tracked_out.splitlines()) if tcode == 0 else set()
    issues = history_issues(paths, tracked)
    payload = json.dumps({"paths_ever_added": len(paths), "flagged": [i.to_dict() for i in issues]}, indent=1).encode()
    execution = internal(
        instrument, ctx, payload, ctx.results / "raw" / "history.json", note=f"{len(paths)} paths ever added"
    )
    if code != 0:
        execution.status = "failed"
        execution.exit_code = code
        execution.note = "git log failed"
    return _record(execution, instrument, ctx, "none", issues, _config_digest(instrument, ctx), "none")


def _inventory(ctx: Context, instrument: Instrument, scope_doc: dict[str, Any]) -> Record:
    manifests = [m for m in scope_doc["inventory"]["manifests"] if Path(m).name == "requirements.txt"]
    freeze_path = ctx.staged.get("freeze")
    freeze = parse_freeze((freeze_path / "requirements.txt").read_text("utf-8")) if freeze_path else None
    python_files = [ctx.root / f for f in _tracked_python(ctx)]
    imports = collect_imports(ctx.root, python_files)
    local = {p.name for p in ctx.root.iterdir() if p.is_dir()} | {
        Path(f).stem for f in _tracked_python(ctx) if "/" not in f
    }
    issues: list[Issue] = []
    lockfile = bool(scope_doc["inventory"]["lockfiles"])
    for manifest in manifests:
        text = (ctx.root / manifest).read_text("utf-8", "replace")
        issues.extend(inventory_issues(text, manifest, freeze, imports, local, lockfile))
    payload = json.dumps(
        {
            "manifests": manifests,
            "lockfiles": scope_doc["inventory"]["lockfiles"],
            "freeze": freeze,
            "imports": {k: sorted(v) for k, v in imports.items()},
        },
        indent=1,
    ).encode()
    execution = internal(
        instrument, ctx, payload, ctx.results / "raw" / "inventory.json", note=f"{len(manifests)} manifests"
    )
    return _record(execution, instrument, ctx, "none", issues, _config_digest(instrument, ctx), "none")


def _tracked_python(ctx: Context) -> list[str]:
    code, out = git(ctx.root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = [f for f in out.split("\0") if f.endswith(".py")] if code == 0 else []
    return [f for f in files if f.split("/", 1)[0] not in ("hunt", "venv", "node_modules", "data")]


def _probe(ctx: Context, instrument: Instrument) -> Record:
    issues, pruned, report = probe_lanes(ctx.root, ctx.hunt / "probe")
    payload = yaml.safe_dump(report, sort_keys=False, allow_unicode=False).encode()
    execution = internal(
        instrument,
        ctx,
        payload,
        ctx.results / "raw" / "probe.yaml",
        note=f"{report['verified']} verified, {report['rejected']} rejected, {report['lane_failures']} lane failures",
    )
    return _record(
        execution,
        instrument,
        ctx,
        "none",
        issues,
        _config_digest(instrument, ctx),
        "none",
        pruned=pruned,
        gaps=report.get("gaps", []),
    )


def _external(ctx: Context, instrument: Instrument, prov: dict[str, Any], remap: dict[str, str]) -> Record:
    raw = (
        ctx.results
        / "raw"
        / f"{instrument.name}.{'xml' if instrument.name in ('pytest-target', 'sandbox', 'node-test') else 'json'}"
    )
    if raw.exists():
        raw.unlink()
    targets = default_targets(instrument, ctx)
    execution = execute(instrument, ctx, targets, raw)
    pruned: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    if execution.status == "blocked":
        parser = "none"
        issues: list[Issue] = []
        gaps.append({"surface": instrument.name, "gap": execution.note, "cap": instrument.cap_when_absent})
    else:
        parser, issues = parse(instrument.name, raw, execution.stdout, ctx.root, remap)
        if instrument.name == "quality" and raw.exists():
            payload = json.loads(raw.read_text("utf-8"))
            execution.note = "; ".join(f"{c['name']} exit={c['exit_code']}" for c in payload.get("checks", []))
            summary = junit_summary(ctx.results / "quality" / "actual" / "tests.xml")
            execution.note += f"; controls: {summary['total']} tests, {summary['passed']} passed"
        if instrument.name in ("pytest-target", "sandbox", "node-test"):
            summary = junit_summary(raw)
            execution.note = (
                f"{summary['total']} tests: {summary['passed']} passed, {summary['failed']} failed, "
                f"{summary['error']} errors, {summary['skipped']} skipped"
            )
            if instrument.name == "sandbox":
                for case in summary["cases"]:
                    if case["outcome"] == "passed":
                        pruned.append(
                            {"path": case["test"], "reason": "reproduction did not fire: the asserted contract held"}
                        )
                    elif case["outcome"] == "skipped":
                        pruned.append({"path": case["test"], "reason": f"reproduction skipped: {case['message']}"})
        if execution.status == "timeout":
            gaps.append({"surface": instrument.name, "gap": execution.note, "cap": instrument.cap_when_absent})
        if instrument.name == "quality" and issues:
            gaps.append(
                {"surface": "quality", "gap": "Harness self-verification or negative control failed", "cap": "BLOCK"}
            )
    return _record(
        execution,
        instrument,
        ctx,
        parser,
        issues,
        _config_digest(instrument, ctx),
        _db_digest(instrument, prov),
        pruned=pruned,
        gaps=gaps,
    )


def _ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    entry = "hunt/results/"
    existing = path.read_text("utf-8", "replace") if path.exists() else ""
    if entry in existing.splitlines():
        return
    with path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write("# HOUND volatile scanner artifacts\n" + entry + "\n")


@app.command()
def provision(
    root: Annotated[Path | None, typer.Option(help="target root; defaults to the parent of hunt/")] = None,
) -> None:
    """Pin scanner databases, record tool provenance, and emit the runbook."""
    target, hunt = _paths(root)
    results = hunt / "results"
    results.mkdir(exist_ok=True)
    meta = results / "trivy" / "db" / "metadata.json"
    trivy = shutil.which("trivy")
    if trivy and not meta.exists():
        typer.echo("downloading trivy vulnerability database into hunt/results/trivy")
        subprocess.run(
            [trivy, "image", "--download-db-only", "--cache-dir", str(results / "trivy")], check=False, timeout=1800
        )
    ctx, scope_doc = scope_mod.build(target, hunt, scope_mod.load(hunt / "scope.yaml"))
    scope_digest = scope_mod.write(hunt / "scope.yaml", scope_doc)
    instruments = scope_mod.instruments_for(ctx)
    prov = provenance_mod.build(ctx, instruments, scope_digest, hunt / "scope.yaml")
    provenance_mod.write(hunt / "provenance.yaml", prov)
    emit.runbook(hunt, ctx, instruments)
    for instrument in instruments:
        located = locate(instrument, ctx)
        typer.echo(f"{instrument.name:14s} {'ok     ' if located else 'MISSING'} {located or instrument.binary}")
    typer.echo(f"pinned: {prov['pinned']} unpinned: {prov['unpinned']}")
    typer.echo(f"scope digest {scope_digest}")
    raise typer.Exit(0 if prov["pinned"] else 1)


@app.command()
def run(
    root: Annotated[Path | None, typer.Option(help="target root; defaults to the parent of hunt/")] = None,
    only: Annotated[
        list[str] | None, typer.Option(help="restrict external instruments to these names (liveness still runs)")
    ] = None,
) -> None:
    """Scope, provenance, liveness, instruments, probe, evidence."""
    target, hunt = _paths(root)
    results = hunt / "results"
    for name in ("raw", "transcript", "scratch"):
        (results / name).mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(target)
    phases: list[dict[str, Any]] = []

    previous = scope_mod.load(hunt / "scope.yaml")
    ctx, scope_doc = scope_mod.build(target, hunt, previous)
    scope_digest = scope_mod.write(hunt / "scope.yaml", scope_doc)
    instruments = scope_mod.instruments_for(ctx)
    phases.append({"phase": "scope", "status": "complete", "artifact": "hunt/scope.yaml", "sha256": scope_digest})
    typer.echo(
        f"scope: {len(scope_doc['surfaces'])} surfaces, {len(instruments)} instruments, {len(scope_doc['gaps'])} gaps"
    )

    prov = provenance_mod.build(ctx, instruments, scope_digest, hunt / "scope.yaml")
    provenance_digest = provenance_mod.write(hunt / "provenance.yaml", prov)
    phases.append(
        {"phase": "provenance", "status": "complete", "artifact": "hunt/provenance.yaml", "sha256": provenance_digest}
    )
    typer.echo(f"provenance: pinned={prov['pinned']} unpinned={prov['unpinned']}")

    typer.echo("liveness: proving both halves")
    live = liveness_mod.run(ctx, instruments)
    for entry in live:
        typer.echo(f"  {entry['instrument']:14s} clean={entry['clean']} positive={entry['positive']}")
    phases.append({"phase": "liveness", "status": "complete", "ok": all(e["clean"] and e["positive"] for e in live)})

    records: list[Record] = []
    gaps: list[dict[str, Any]] = list(scope_doc["gaps"])
    remap = dict(scope_doc.get("remap") or {})
    for instrument in instruments:
        if only and instrument.name not in only and instrument.kind != "internal":
            continue
        typer.echo(f"run: {instrument.name}")
        if instrument.name == "history":
            record = _history(ctx, instrument, prov)
        elif instrument.name == "inventory":
            record = _inventory(ctx, instrument, scope_doc)
        elif instrument.name == "probe":
            record = _probe(ctx, instrument)
        else:
            record = _external(ctx, instrument, prov, remap)
        gaps.extend(record.gaps)
        records.append(record)
        typer.echo(
            f"  {record.status} exit={record.exit_code} parser={record.parser} "
            f"issues={len(record.issues)} {record.note}"
        )
    for entry in live:
        if not (entry["clean"] and entry["positive"]):
            gaps.append(
                {"surface": entry["instrument"], "gap": "liveness failed: instrument inert or unsound", "cap": "BLOCK"}
            )

    target_doc = {
        "root": str(target),
        "sha": scope_doc["target"]["sha"],
        "branch": scope_doc["target"]["branch"],
        "dirty": scope_doc["target"]["dirty"],
        "porcelain_digest": scope_doc["target"]["porcelain_digest"],
    }
    evidence_doc = emit.evidence(target_doc, scope_digest, provenance_digest, records, live, gaps)
    source_hashes = scope_doc["inventory"]["source_hashes"]
    changed = [
        rel
        for rel, digest in source_hashes.items()
        if not (target / rel).is_file() or sha256_file(target / rel) != digest
    ]
    evidence_doc["integrity"] = {
        "source_files": len(source_hashes),
        "changed_during_run": changed,
        "source_unchanged": not changed,
        "sandbox": {"dependencies_pinned": True, "os_hermetic": False},
        "required_instruments": [i.name for i in instruments if i.required],
    }
    if changed:
        evidence_doc["gaps"].append(
            {
                "surface": "source-integrity",
                "cap": "HOLD",
                "gap": f"Target inputs changed during the scan: {', '.join(changed)}",
            }
        )
        evidence_doc["summary"]["gaps"] = len(evidence_doc["gaps"])
    evidence_digest = emit.write(hunt / "evidence.yaml", evidence_doc)
    phases.append(
        {"phase": "instrument", "status": "complete", "artifact": "hunt/evidence.yaml", "sha256": evidence_digest}
    )
    emit.todo(hunt, evidence_doc, None)
    emit.runbook(hunt, ctx, instruments)
    emit.review(hunt)
    emit.progress(hunt, phases)
    summary = evidence_doc["summary"]
    typer.echo(f"evidence: {summary['records']} records, {summary['issues']} issues, {summary['by_severity']}")
    typer.echo(f"evidence digest {evidence_digest}")


@app.command()
def verify(
    findings: Annotated[Path, typer.Option(help="hunt/findings.yaml")],
    context: Annotated[Path, typer.Option(help="hunt/evidence.yaml")],
) -> None:
    """Gate: exit zero only when findings are grounded in evidence and the disposition is not raised."""
    verdict = verify_docs(findings.resolve(), context.resolve(), context.resolve().parent)
    typer.echo(verdict.report())
    hunt = context.resolve().parent
    if (hunt / "evidence.yaml").exists():
        try:
            evidence_doc = yaml.safe_load((hunt / "evidence.yaml").read_text("utf-8"))
            if isinstance(evidence_doc, dict):
                emit.todo(
                    hunt,
                    evidence_doc,
                    {"computed": verdict.computed, "caps": verdict.caps, "rejections": verdict.rejections},
                )
        except (OSError, yaml.YAMLError):
            pass
    raise typer.Exit(0 if verdict.ok else 1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
