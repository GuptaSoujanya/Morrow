"""One flat record per profile update, so the result of a run is a single file read.

A profile run leaves a folder of dozens of MCP snapshots and screenshots. This module
keeps the part worth reading: a flat digest per board, written to one index that holds
the latest run for every board and an append-only log of every run before it.

    data/reports/profile/latest.json     board -> the last run's digest
    data/reports/profile/history.jsonl   one digest per line, oldest first

    python3 -m common.profile_record             # the table: board, when, saved, sections, ATS
    python3 -m common.profile_record --json      # the whole latest.json
    python3 -m common.profile_record --board naukri

Every digest has the same keys whatever the board, so a dashboard or a script can read
`latest.json` without walking run folders or parsing Markdown.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INDEX_DIR = Path("data/reports") / "profile"
LATEST = "latest.json"
HISTORY = "history.jsonl"


def index_dir(settings: Any = None) -> Path:
    """The index folder beside the run folders, so REPORT_DIR moves both together."""
    root = getattr(settings, "report_dir", "") or "data/reports"
    return Path(root) / "profile"


#: Keys every digest carries, so a reader never has to test for their presence.
FIELDS = ("board", "label", "at", "saved", "why", "changed", "confirmed", "unconfirmed", "missing",
          "completeness_before", "completeness_after", "headline", "skills", "ats_score", "sections",
          "report", "run")


def _short(value: Any, limit: int = 200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


RUN = "run"
#: A read-only check of the live profile against the plan made from the resume: nothing was changed,
#: so "changed/confirmed" count the planned sections checked and the ones the page shows.
SCORE = "score"


def digest(board_name: str, label: str, result: Any, plan: Any = None, report: Optional[Path] = None,
           run: Optional[Path] = None, at: Optional[datetime] = None, kind: str = RUN) -> Dict[str, Any]:
    """The flat record for one profile run: the verdict, what changed, what did not land."""
    sections = []
    for section in result.sections:
        row = {"name": section.name, "action": section.action, "confirmed": section.on_page}
        if section.action in ("updated", "filled", "checked"):
            row["after"] = _short(section.after, 300)
        if section.missing:
            row["missing"] = list(section.missing)
        if section.note:
            row["note"] = _short(section.note)
        sections.append(row)
    ats = getattr(plan, "ats", None) if plan is not None else None
    if kind == SCORE:
        checked = [section for section in result.sections if section.on_page is not None]
        shown = [section for section in checked if section.on_page]
        absent = [section.name for section in checked if not section.on_page]
    else:
        checked, shown = result.changed, result.confirmed
        absent = [section.name for section in result.unverified]
    return {
        "board": board_name,
        "label": label,
        "kind": kind,
        "at": (at or datetime.now()).isoformat(timespec="seconds"),
        "saved": bool(result.saved),
        "why": _short(result.why),
        "changed": len(checked),
        "confirmed": len(shown),
        "unconfirmed": absent,
        "missing": sorted({item for section in result.sections for item in section.missing}),
        "completeness_before": result.completeness_before,
        "completeness_after": result.completeness_after,
        "headline": _short(getattr(plan, "headline", ""), 300),
        "skills": list(getattr(plan, "key_skills", []) or []),
        "ats_score": ats.score if ats is not None else None,
        "sections": sections,
        "report": str(report) if report else "",
        "run": str(run) if run else "",
    }


def save(record: Dict[str, Any], folder: Path = INDEX_DIR) -> Path:
    """Put the digest in latest.json under its board and append it to history.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LATEST
    latest = load(folder)
    latest[record["board"]] = record
    path.write_text(json.dumps(latest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (folder / HISTORY).open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def load(folder: Path = INDEX_DIR) -> Dict[str, Dict[str, Any]]:
    """The latest digest for every board; {} when nothing has run yet."""
    try:
        data = json.loads((folder / LATEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def history(folder: Path = INDEX_DIR, board: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        lines = (folder / HISTORY).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and (board is None or record.get("board") == board):
            out.append(record)
    return out


def verdict(record: Dict[str, Any]) -> str:
    """One word for a record: a run saved or not; a score matching the resume plan or showing gaps."""
    if record.get("kind") == SCORE:
        return "MATCHES RESUME" if record.get("saved") else "GAPS"
    return "saved" if record.get("saved") else "NOT SAVED"


def table(latest: Dict[str, Dict[str, Any]]) -> str:
    """The index as a table short enough to read in a terminal."""
    if not latest:
        return "No profile update has been recorded yet. Run one: python3 -m naukri_bot.update_profile"
    rows = [("BOARD", "WHEN", "RESULT", "SECTIONS", "COMPLETE", "ATS", "NOT ON PAGE")]
    for record in sorted(latest.values(), key=lambda item: str(item.get("at")), reverse=True):
        absent = ", ".join(record.get("unconfirmed") or []) or ", ".join(record.get("missing") or [])
        rows.append((
            str(record.get("label") or record.get("board") or "?"),
            str(record.get("at") or "")[:16].replace("T", " "),
            verdict(record),
            "%s/%s" % (record.get("confirmed", "?"), record.get("changed", "?")),
            "%s -> %s" % (record.get("completeness_before") or "?", record.get("completeness_after") or "?"),
            str(record.get("ats_score") if record.get("ats_score") is not None else "-"),
            _short(absent or "-", 40),
        ))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip()
                     for row in rows)


def detail(record: Dict[str, Any]) -> str:
    """One board's last run: the verdict, then a line per section."""
    lines = ["%s profile %s- %s (%s)" % (record.get("label") or record.get("board"),
                                         "score " if record.get("kind") == SCORE else "",
                                         verdict(record), record.get("at")),
             record.get("why") or ""]
    if record.get("completeness_after"):
        lines.append("Completeness %s -> %s" % (record.get("completeness_before") or "?",
                                                record.get("completeness_after")))
    if record.get("ats_score") is not None:
        lines.append("Resume ATS %s/100" % record["ats_score"])
    lines.append("")
    for section in record.get("sections") or []:
        mark = {True: "ok ", False: "NO ", None: "?  "}.get(section.get("confirmed"), "?  ")
        lines.append("%s %-28s %-10s %s" % (mark, _short(section.get("name"), 28),
                                            section.get("action", ""), _short(section.get("after"), 80)))
        if section.get("missing"):
            lines.append("%s %-28s %-10s not on the page: %s"
                         % ("   ", "", "", ", ".join(section["missing"])))
    if record.get("report"):
        lines += ["", "Full report: %s" % record["report"]]
    return "\n".join(line for line in lines if line is not None)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="common.profile_record",
                                     description="What the last profile update changed on each board.")
    parser.add_argument("--board", default=None, help="Only this board, with a line per section.")
    parser.add_argument("--json", action="store_true", help="Print the records as JSON.")
    parser.add_argument("--history", action="store_true", help="Every recorded run, not just the latest.")
    parser.add_argument("--dir", default=None, metavar="PATH", help="The index folder (default data/reports/profile).")
    args = parser.parse_args(argv)
    folder = Path(args.dir) if args.dir else INDEX_DIR

    if args.history:
        records = history(folder, args.board)
        print(json.dumps(records, indent=2, ensure_ascii=False) if args.json
              else table({str(index): record for index, record in enumerate(records)}))
        return 0
    latest = load(folder)
    if args.board:
        record = latest.get(args.board)
        if record is None:
            print("No profile update recorded for %r. Boards: %s"
                  % (args.board, ", ".join(sorted(latest)) or "none"))
            return 1
        print(json.dumps(record, indent=2, ensure_ascii=False) if args.json else detail(record))
        return 0
    print(json.dumps(latest, indent=2, ensure_ascii=False) if args.json else table(latest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
