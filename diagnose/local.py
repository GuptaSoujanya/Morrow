"""Everything the local files already say about the funnel.

Nothing here touches the network. The ledger is opened read-only, backups are
merged so the pre-wipe history counts, and every number is returned with the
query that produced it so a reader can check it with sqlite3.
"""

import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from common import paths
from common.models import Settings

from . import mail_rules

logger = logging.getLogger(__name__)

#: Statuses that mean a form was really submitted somewhere.
SUBMITTED = ("applied", "applied_platform", "applied_external")
#: Statuses that spent the day's Naukri quota without a complete application.
WASTED_QUOTA = ("abstained", "chatbot_timeout")
#: Words in a title that the ranker should have excluded for a ~3 year profile.
MISMATCH_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|staff|principal|head|architect|manager|director|"
    r"intern|trainee|sdet|qa|test(ing)? engineer|data scientist|data analyst|"
    r"react native|android|ios|flutter|devops|sre|c\+\+|embedded|\biii\b|\b3\b)\b",
    re.IGNORECASE,
)
#: Saved answers that quietly tell a recruiter "not in your city".
BAD_ANSWER_VALUES = {"others", "other", "remote", "any", "anywhere", "n/a", "na", "none"}
LOCATION_QUESTION = re.compile(r"location|city|based|where", re.IGNORECASE)


def _rows(connection: sqlite3.Connection, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
    try:
        return connection.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.debug("Query failed (%s): %s", exc, sql)
        return []


def _open(path: Path) -> Optional[sqlite3.Connection]:
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % path.resolve(), uri=True)
    except sqlite3.Error as exc:
        logger.warning("Could not open %s: %s", path, exc)
        return None
    connection.row_factory = sqlite3.Row
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in _rows(connection, "PRAGMA table_info(%s)" % table)]


def ledger_paths(settings: Settings) -> List[Path]:
    """The live ledger first, then every backup copy next to it (and one folder down)."""
    live = Path(settings.db_path)
    found = [live]
    folder = live.parent
    if folder.is_dir():
        for candidate in sorted(folder.glob("*.db")) + sorted(folder.glob("*/*.db")):
            if candidate.resolve() != live.resolve():
                found.append(candidate)
    return found


def _day(stamp: str) -> str:
    """The day an application belongs to in the reader's own calendar.

    The ledger stamps every row in UTC. India is 5.5 hours ahead, so a run that is still going at
    18:30 UTC already counts as tomorrow on the reader's wall clock; cutting the stamp at ten
    characters would file that evening under yesterday and disagree with the dashboard, which
    converts. Both now name the same day for the same row.
    """
    try:
        return datetime.fromisoformat(str(stamp)).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return (stamp or "")[:10]


def read_applications(paths_: Iterable[Path]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every application row across the live ledger and its backups, once each.

    A row is the same event when job_id, status and timestamp match; backups
    taken before a wipe therefore add the old history without double counting
    what the live ledger still holds.
    """
    seen = set()
    merged: List[Dict[str, Any]] = []
    sources: Dict[str, Any] = {}
    for path in paths_:
        connection = _open(path)
        if connection is None:
            continue
        with connection:
            columns = _columns(connection, "applications")
            if not columns:
                continue
            rows = _rows(connection, "SELECT * FROM applications")
            scores = {row["job_id"]: row for row in _rows(
                connection, "SELECT job_id, score, gaps_json, source, description FROM jobs_seen")}
            added = 0
            for row in rows:
                record = dict(row)
                key = (record.get("job_id"), record.get("status"), record.get("at"))
                if key in seen:
                    continue
                seen.add(key)
                job = scores.get(record.get("job_id"))
                record["score"] = job["score"] if job is not None else None
                record["source"] = job["source"] if job is not None else None
                try:
                    record["gaps"] = json.loads(job["gaps_json"]) if job is not None and job["gaps_json"] else []
                except (TypeError, ValueError):
                    record["gaps"] = []
                record["description"] = (job["description"] or "") if job is not None else ""
                record["ledger"] = str(path)
                merged.append(record)
                added += 1
            sources[str(path)] = {"rows": len(rows), "new_rows": added}
    merged.sort(key=lambda item: item.get("at") or "")
    return merged, sources


#: Naukri's own job sources carry no board prefix ("search:AI Engineer", "recommended:profile"), and an
#: NVite whose link holds no Naukri id is recorded as "nvite:<hash>". None of them is a board of its own.
_NAUKRI_SOURCES = ("search", "recommended", "nvite")
#: A job id is the posting's own link whenever the board gave none of its own, so the host names the
#: board; anything else was applied to on the employer's own site.
_BOARD_HOSTS = ("naukri.com", "hirist.tech", "instahyre.com", "cutshort.io", "wellfound.com")


def channel(record: Dict[str, Any]) -> str:
    """The board an application came through, read off the job's source or, failing that, its id.

    How it was sent says nothing about where it came from: a Naukri job finished on the employer's own
    site is still a Naukri application. web.state._board_of_job must answer the same for the dashboard,
    bar showing yc and hn as one "startups"; tests/diagnose holds the two to it.
    """
    prefix = (record.get("source") or "").split(":")[0]
    if prefix and prefix not in _NAUKRI_SOURCES:
        return prefix
    job = str(record.get("job_id") or "")
    if job.startswith(("http://", "https://")):
        host = (urlsplit(job).hostname or "").lower()
        return next((domain.split(".")[0] for domain in _BOARD_HOSTS
                     if host == domain or host.endswith("." + domain)), "external")
    head = job.split(":", 1)[0] if ":" in job else "naukri"
    return "naukri" if head in _NAUKRI_SOURCES else (head or "external")


def funnel(applications: List[Dict[str, Any]]) -> Dict[str, Any]:
    status = Counter(record.get("status") or "?" for record in applications)
    submitted = [record for record in applications if record.get("status") in SUBMITTED]
    per_day: Dict[str, Counter] = defaultdict(Counter)
    for record in submitted:
        per_day[_day(record.get("at") or "")][record.get("status")] += 1
    channels = Counter()
    for record in submitted:
        source = channel(record)
        channels[source] += 1
    first = applications[0]["at"] if applications else ""
    last = applications[-1]["at"] if applications else ""
    return {
        "status_counts": dict(status.most_common()),
        "submitted_total": len(submitted),
        "submitted_by_status": {name: status.get(name, 0) for name in SUBMITTED},
        "submitted_by_day": {day: dict(counts) for day, counts in sorted(per_day.items())},
        "peak_day": dict(zip(("count", "day"), max(((sum(c.values()), day) for day, c in per_day.items()), default=(0, "")))),
        "submitted_by_channel": dict(channels.most_common()),
        "wasted_quota": sum(status.get(name, 0) for name in WASTED_QUOTA),
        "errors": status.get("error", 0),
        "first_at": first,
        "last_at": last,
        "days_running": max(1, (datetime.fromisoformat(last[:19]) - datetime.fromisoformat(first[:19])).days + 1)
        if first and last else 0,
    }


def _band(score: Optional[float]) -> str:
    if score is None:
        return "unscored"
    if score < 40:
        return "<40"
    if score < 50:
        return "40-49"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    return "70+"


def fit(applications: List[Dict[str, Any]], settings: Settings) -> Dict[str, Any]:
    submitted = [record for record in applications if record.get("status") in SUBMITTED]
    bands = Counter(_band(record.get("score")) for record in submitted)
    scored = [record["score"] for record in submitted if record.get("score") is not None]
    below = [record for record in submitted if record.get("score") is not None and record["score"] < settings.min_score]
    mismatched = [record for record in submitted if MISMATCH_TITLE.search(record.get("title") or "")]
    gaps = Counter()
    years_gap = 0
    for record in submitted:
        for gap in record.get("gaps") or []:
            gaps[gap] += 1
            if re.search(r"\d\+?\s*(years|yrs)", gap, re.IGNORECASE):
                years_gap += 1
    companies = Counter((record.get("company") or "").strip().lower() for record in submitted)
    repeats = {name: count for name, count in companies.items() if count > settings.max_per_company and name}
    return {
        "score_bands": dict(bands),
        "median_score": sorted(scored)[len(scored) // 2] if scored else None,
        "below_min_score": len(below),
        "below_min_score_share": round(len(below) / len(scored), 3) if scored else None,
        "min_score": settings.min_score,
        "mismatched_titles": len(mismatched),
        "mismatched_examples": sorted({re.sub(r"^\(\d+\)\s*", "", r.get("title") or "")[:60] for r in mismatched})[:15],
        "top_gaps": gaps.most_common(20),
        "experience_gap_count": years_gap,
        "companies_over_cap": repeats,
    }


def errors(applications: List[Dict[str, Any]]) -> Dict[str, Any]:
    details = Counter()
    for record in applications:
        if record.get("status") not in ("error", "naukri_refused", "chatbot_timeout", "abstained"):
            continue
        detail = re.sub(r"https?://\S+", "<url>", record.get("detail") or "")
        detail = re.sub(r"/Users/\S+", "<path>", detail)
        detail = re.sub(r"\d{6}\s.*$", "", detail).strip() or record.get("status")
        details[(record.get("status"), detail[:120])] += 1
    unfinished = [record for record in applications
                  if record.get("status") in ("error", "chatbot_timeout", "abstained", "no_apply_button")]
    return {
        "unfinished_total": len(unfinished),
        "detail_counts": [{"status": s, "detail": d, "count": c} for (s, d), c in details.most_common(12)],
    }


def answers(settings: Settings) -> Dict[str, Any]:
    connection = _open(Path(settings.db_path))
    if connection is None:
        return {"rows": 0, "suspicious": []}
    with connection:
        rows = _rows(connection, "SELECT question_text, answer, source, times_used, confidence FROM answers")
    suspicious = []
    for row in rows:
        question = row["question_text"] or ""
        answer = (row["answer"] or "").strip()
        if LOCATION_QUESTION.search(question) and answer.lower() in BAD_ANSWER_VALUES:
            suspicious.append({"question": question, "answer": answer,
                               "why": "a recruiter filtering by city reads this as 'not here'"})
        elif not answer:
            suspicious.append({"question": question, "answer": answer, "why": "blank answer is saved"})
    return {
        "rows": len(rows),
        "never_used": sum(1 for row in rows if not row["times_used"]),
        "suspicious": suspicious,
    }


def company_sites(settings: Settings) -> Dict[str, Any]:
    path = paths.inputs_dir() / "application-agent.sqlite"
    connection = _open(path)
    if connection is None:
        return {"path": str(path), "rows": 0}
    with connection:
        rows = _rows(connection, "SELECT state, next_step, job_id FROM attempts")
    states = Counter(row["state"] or "?" for row in rows)
    boards = Counter((row["job_id"] or "").split(":")[0] for row in rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "states": dict(states.most_common()),
        "boards": dict(boards.most_common()),
        "unresolved": states.get("uncertain", 0) + states.get("needs_you", 0) + states.get("running", 0),
    }


def _jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def replies(settings: Settings) -> Dict[str, Any]:
    folder = Path(settings.data_dir)
    mails = _jsonl(folder / "employer_replies.jsonl")
    kinds = Counter((mail.get("kind") or "?").upper() for mail in mails)
    sources = Counter()
    for mail in mails:
        sender = (mail.get("from") or "").lower()
        domain = sender.rsplit("@", 1)[-1] if "@" in sender else sender
        sources[domain.split(".")[-2] if domain.count(".") >= 1 else domain] += 1
    contacts = _jsonl(folder / "job_contacts.jsonl")
    cold = _jsonl(folder / "cold_emails.jsonl")
    positive = sum(kinds.get(kind, 0) for kind in mail_rules.POSITIVE)
    return {
        "rows": len(mails),
        "kinds": dict(kinds.most_common()),
        "positive": positive,
        "sender_platforms": dict(sources.most_common(8)),
        "naukri_mails_seen": sources.get("naukri", 0),
        "contacts_known": len(contacts),
        "cold_emails_sent": len(cold),
    }


def cutshort_journal(settings: Settings) -> Dict[str, Any]:
    path = Path(settings.data_dir) / "cutshort_questionnaires.json"
    if not path.is_file():
        return {"threads": 0, "states": {}}
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"threads": 0, "states": {}, "error": "unreadable"}
    states = Counter((entry or {}).get("state") or "?" for entry in journal.values())
    return {"threads": len(journal), "states": dict(states.most_common()),
            "unfinished": sum(c for s, c in states.items() if s != "done")}


def profile_facts(settings: Settings) -> Dict[str, Any]:
    import yaml

    path = Path(settings.profile_path)
    try:
        facts = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {"error": str(exc)}
    years = facts.get("total_experience_years") or facts.get("experience_years")
    return {
        "years": years,
        "titles": facts.get("titles") or facts.get("target_titles") or [],
        "locations": facts.get("preferred_locations") or facts.get("locations") or [],
        "current_ctc": facts.get("current_ctc"),
        "expected_ctc": facts.get("expected_ctc"),
        "notice_days": facts.get("notice_period_days") or facts.get("notice_period"),
        "skills_count": len(facts.get("skills") or []),
        "skills": [str(item) for item in (facts.get("skills") or []) if isinstance(item, (str, int, float))],
        "naukri_email": facts.get("email") or "",
        "remote_in_locations": any("remote" in str(item).lower() for item in (facts.get("preferred_locations") or [])),
        "under_three_years": isinstance(years, (int, float)) and years < 3,
    }


#: The report's leads section: the window counted as the period, and how many threads it lists.
LEADS_DAYS = 14
LEADS_LIMIT = 100


def leads_journal(settings: Settings, day: date) -> Dict[str, Any]:
    """user/inputs/leads.json as leads.store counts it for `day`: zeros and the error when it cannot be read."""
    try:
        from leads import store

        return store.summary(settings, day=day, days=LEADS_DAYS, limit=LEADS_LIMIT)
    except Exception as exc:  # noqa: BLE001 - the journal belongs to other stages; the audit still runs without it
        return {"error": str(exc), "total": 0, "waiting": 0, "needs_you": 0, "answered": 0,
                "today": {"new": 0, "answered": 0, "needs_you": 0}, "period": {"days": LEADS_DAYS, "new": 0, "answered": 0},
                "by_platform": {}, "by_kind": {}, "by_state": {}, "items": [], "path": "", "day": day.isoformat()}


def analyse(settings: Settings, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every local signal in one dictionary; each key is one section of the report."""
    now = now or datetime.now(timezone.utc)
    applications, sources = read_applications(ledger_paths(settings))
    live = [record for record in applications if record.get("ledger") == str(Path(settings.db_path))]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "ledgers": sources,
        "funnel_all": funnel(applications),
        "funnel_live": funnel(live),
        "fit": fit(applications, settings),
        "errors": errors(applications),
        "answers": answers(settings),
        "company_sites": company_sites(settings),
        "replies": replies(settings),
        "cutshort": cutshort_journal(settings),
        # The journal stamps local time, so "today" is the local day of `now`, not its UTC day.
        "leads": leads_journal(settings, now.astimezone().date()),
        "profile": profile_facts(settings),
        "settings": {
            "min_score": settings.min_score,
            "daily_quota": settings.daily_quota,
            "target_applications": settings.target_applications,
            "exclude_titles": list(settings.exclude_titles),
            "max_per_company": settings.max_per_company,
        },
        "applications": applications,
    }
