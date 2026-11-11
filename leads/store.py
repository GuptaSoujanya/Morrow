"""The leads journal: one JSON object per lead under user/inputs/leads.json.

A lead is one thread a recruiter started or answered: a board inbox message, a Cutshort
questionnaire, an assessment invite, a reply in Gmail. The journal keeps every lead ever
seen so the bots never answer the same thread twice, and the day's summary tells the
dashboard how many came in, how many were answered and how many still need a person.

    {
      "<id>": {
        "id": "board:instahyre:3f9c...",     # stable: source, platform and the thread key
        "source": "board" | "mail",
        "platform": "instahyre",              # naukri, hirist, instahyre, cutshort, wellfound,
                                              # employer, ats, personal, ... (mail_rules platforms)
        "kind": "QUESTION",                   # one of KINDS
        "company": "GreyOrange", "title": "Software Engineer II",
        "who": "Shreya Rani", "subject": "", "text": "first 400 chars of the message",
        "url": "https://www.instahyre.com/candidate/inbox/",
        "received_at": "Nov 02" | ISO date,   # as the source shows it
        "first_seen": ISO, "updated_at": ISO,
        "state": "new" | "answered" | "needs_you" | "deferred" | "failed" | "skipped",
        "why": "", "answer": "", "answered_at": ISO | "",
        "facts": "<facts fingerprint the answer used>", "attempts": 0,
        "history": [{"at": ISO, "state": ..., "why": ...}]
      }
    }
"""

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from common.models import Settings
from common.shared_files import atomic_write_text, locked_file

FILE_NAME = "leads.json"

#: Kinds, in the order the dashboard lists them. Mirrors diagnose.mail_rules.POSITIVE.
KINDS = ("OFFER", "INTERVIEW", "ASSESSMENT", "SHORTLIST", "QUESTION", "REPLY", "RECRUITER_OUTREACH")
STATES = ("new", "answered", "needs_you", "deferred", "failed", "skipped")
#: States in which a lead still waits for an answer from the bots.
OPEN_STATES = ("new", "deferred", "failed")
#: States in which the lead waits for a person.
PERSON_STATES = ("needs_you",)
HISTORY_LIMIT = 20
TEXT_LIMIT = 400


def path(settings: Settings) -> Path:
    return Path(settings.data_dir) / FILE_NAME


def _now(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def lead_id(source: str, platform: str, key: str) -> str:
    """A stable identity for a thread: the same message seen tomorrow is the same lead."""
    digest = hashlib.sha1(("%s|%s|%s" % (source, _norm(platform), _norm(key))).encode("utf-8")).hexdigest()[:16]
    return "%s:%s:%s" % (source, _norm(platform) or "unknown", digest)


def thread_key(who: str = "", company: str = "", title: str = "", subject: str = "", text: str = "") -> str:
    """What identifies a thread when the source gives no id: the people and the role, else the subject, else the words.

    Dates, counts and 'ago' words are left out so a thread is one lead across days. A subject
    whose only difference is 'Re:'/'Fwd:' still names the same thread.
    """
    subject_core = re.sub(r"^(?:(?:re|fwd?|fw)\s*:\s*)+", "", _norm(subject))
    parts = [_norm(who), _norm(company), _norm(title)]
    if subject_core:
        parts.append(subject_core)
    if not any(parts):
        parts.append(re.sub(r"\d+|\bago\b", "", _norm(text))[:120])
    return "|".join(parts)


def make_lead(source: str, platform: str, kind: str, company: str = "", title: str = "", who: str = "",
              subject: str = "", text: str = "", url: str = "", received_at: str = "", key: str = "") -> Dict[str, Any]:
    """A lead as collect.py builds it; store.record() adds the journal fields."""
    kind = (kind or "REPLY").upper()
    if kind not in KINDS:
        kind = "REPLY"
    key = key or thread_key(who, company, title, subject, text)
    return {
        "id": lead_id(source, platform, key),
        "source": source,
        "platform": _norm(platform) or "unknown",
        "kind": kind,
        "company": str(company or "").strip()[:120],
        "title": str(title or "").strip()[:160],
        "who": str(who or "").strip()[:120],
        "subject": str(subject or "").strip()[:200],
        "text": " ".join(str(text or "").split())[:TEXT_LIMIT],
        "url": str(url or "").strip()[:500],
        "received_at": str(received_at or "").strip()[:40],
    }


def _read(target: Path) -> Dict[str, Dict[str, Any]]:
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise ValueError("The leads journal %s is not valid JSON: %s" % (target, exc))
    if not isinstance(payload, dict) or any(not isinstance(value, dict) for value in payload.values()):
        raise ValueError("The leads journal %s is not an object of lead objects" % target)
    return payload


def load(settings: Settings) -> Dict[str, Dict[str, Any]]:
    """Every lead ever recorded, by id. {} when the journal does not exist yet."""
    return _read(path(settings))


def record(settings: Settings, leads: Iterable[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, int]:
    """Add the leads not seen before; refresh text/url/received_at of the ones already known.

    A known lead keeps its state, so an answered thread is never reopened by seeing it again.
    Returns {"new": n, "seen": m}.
    """
    stamp = _now(now)
    counts = {"new": 0, "seen": 0}
    incoming = list(leads)
    if not incoming:
        return counts
    with locked_file(path(settings)) as target:
        journal = _read(target)
        for lead in incoming:
            identity = lead["id"]
            if identity in journal:
                current = journal[identity]
                for field in ("text", "url", "received_at", "company", "title", "who", "subject"):
                    if lead.get(field) and not current.get(field):
                        current[field] = lead[field]
                if lead.get("text") and lead["text"] != current.get("text"):
                    current["text"] = lead["text"]
                current["last_seen"] = stamp
                counts["seen"] += 1
                continue
            journal[identity] = {
                **lead,
                "first_seen": stamp, "last_seen": stamp, "updated_at": stamp,
                "state": "new", "why": "", "answer": "", "answered_at": "", "facts": "", "attempts": 0,
                "history": [{"at": stamp, "state": "new", "why": "seen"}],
            }
            counts["new"] += 1
        atomic_write_text(target, json.dumps(journal, indent=1, ensure_ascii=False))
    return counts


def update(settings: Settings, identity: str, state: str, why: str = "", answer: str = "", facts: str = "",
           now: Optional[datetime] = None, **values: Any) -> Dict[str, Any]:
    """Move one lead to `state`, remembering why, what was answered and with which facts."""
    if state not in STATES:
        raise ValueError("unknown lead state %r" % state)
    stamp = _now(now)
    with locked_file(path(settings)) as target:
        journal = _read(target)
        if identity not in journal:
            raise KeyError("no lead %s in %s" % (identity, target))
        lead = journal[identity]
        lead["state"] = state
        lead["why"] = " ".join(str(why or "").split())[:300]
        lead["updated_at"] = stamp
        if answer:
            lead["answer"] = str(answer)[:2000]
        if facts:
            lead["facts"] = facts
        if state == "answered":
            lead["answered_at"] = stamp
        if state in ("answered", "needs_you", "failed", "deferred"):
            lead["attempts"] = int(lead.get("attempts") or 0) + 1
        lead.update({k: v for k, v in values.items() if v is not None})
        history = list(lead.get("history") or [])
        history.append({"at": stamp, "state": state, "why": lead["why"]})
        lead["history"] = history[-HISTORY_LIMIT:]
        atomic_write_text(target, json.dumps(journal, indent=1, ensure_ascii=False))
        return dict(lead)


def claim(settings: Settings, identity: str, facts: str, now: Optional[datetime] = None) -> bool:
    """Take a lead for answering; False when it was answered already, waits on a person with the
    same facts, or is deferred until later. The same rule Cutshort's questionnaire journal uses."""
    with locked_file(path(settings)) as target:
        journal = _read(target)
        lead = journal.get(identity)
        if lead is None:
            return False
        state = lead.get("state")
        if state in ("answered", "skipped"):
            return False
        if state == "needs_you" and lead.get("facts") == facts:
            return False
        if state == "deferred":
            try:
                if datetime.fromisoformat(str(lead.get("retry_after"))) > (now or datetime.now()):
                    return False
            except (TypeError, ValueError):
                return False
        return True


def open_leads(settings: Settings, source: Optional[str] = None, platform: Optional[str] = None,
               states: Iterable[str] = OPEN_STATES) -> List[Dict[str, Any]]:
    """Leads still waiting for the bots, newest first; filtered by source and platform when given."""
    wanted = set(states)
    rows = [lead for lead in load(settings).values()
            if lead.get("state") in wanted
            and (source is None or lead.get("source") == source)
            and (platform is None or lead.get("platform") == _norm(platform))]
    rows.sort(key=lambda lead: str(lead.get("first_seen") or ""), reverse=True)
    return rows


def _on(stamp: str, day: date) -> bool:
    return str(stamp or "")[:10] == day.isoformat()


def _since(stamp: str, start: date) -> bool:
    return str(stamp or "")[:10] >= start.isoformat()


def summary(settings: Settings, day: Optional[date] = None, days: int = 14, limit: int = 200) -> Dict[str, Any]:
    """Counts for the dashboard and the audit, plus the newest leads.

    `today` counts leads first seen / answered on `day`; `period` counts the last `days` days
    up to `day`; `total` is everything in the journal. `waiting` is what still needs the bots,
    `needs_you` what needs a person.
    """
    day = day or date.today()
    start = day - timedelta(days=max(days, 1) - 1)
    try:
        journal = load(settings)
    except ValueError as exc:
        return {"error": str(exc), "total": 0, "waiting": 0, "needs_you": 0, "answered": 0,
                "today": {"new": 0, "answered": 0, "needs_you": 0}, "period": {"days": days, "new": 0, "answered": 0},
                "by_platform": {}, "by_kind": {}, "by_state": {}, "items": [], "path": str(path(settings))}
    leads = sorted(journal.values(), key=lambda lead: (str(lead.get("updated_at") or ""), str(lead.get("first_seen") or "")),
                   reverse=True)
    by_platform: Dict[str, Dict[str, int]] = {}
    by_kind: Dict[str, int] = {}
    by_state: Dict[str, int] = {}
    today = {"new": 0, "answered": 0, "needs_you": 0}
    period = {"days": days, "new": 0, "answered": 0}
    for lead in leads:
        state = lead.get("state") or "new"
        by_state[state] = by_state.get(state, 0) + 1
        by_kind[lead.get("kind") or "REPLY"] = by_kind.get(lead.get("kind") or "REPLY", 0) + 1
        bucket = by_platform.setdefault(lead.get("platform") or "unknown", {"total": 0, "waiting": 0, "answered": 0, "needs_you": 0})
        bucket["total"] += 1
        if state in OPEN_STATES:
            bucket["waiting"] += 1
        elif state == "answered":
            bucket["answered"] += 1
        elif state in PERSON_STATES:
            bucket["needs_you"] += 1
        if _on(lead.get("first_seen"), day):
            today["new"] += 1
        if _on(lead.get("answered_at"), day):
            today["answered"] += 1
        if state in PERSON_STATES and _on(lead.get("updated_at"), day):
            today["needs_you"] += 1
        if _since(lead.get("first_seen"), start):
            period["new"] += 1
        if _since(lead.get("answered_at"), start):
            period["answered"] += 1
    items = [{k: lead.get(k, "") for k in ("id", "source", "platform", "kind", "company", "title", "who", "subject", "text",
                                           "url", "received_at", "first_seen", "updated_at", "state", "why", "answered_at",
                                           "attempts")} for lead in leads[:limit]]
    return {
        "total": len(leads),
        "waiting": sum(by_state.get(state, 0) for state in OPEN_STATES),
        "needs_you": sum(by_state.get(state, 0) for state in PERSON_STATES),
        "answered": by_state.get("answered", 0),
        "today": today,
        "period": period,
        "by_platform": by_platform,
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "by_state": by_state,
        "items": items,
        "path": str(path(settings)),
        "day": day.isoformat(),
    }
