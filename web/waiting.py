"""Every job the bots stopped on, and exactly what each one still needs from you.

Read-only. Three places remember an application that is waiting for a person:

* the Naukri ledger: screener questions the bot would not guess at, and company-site
  submits that saw no confirmation;
* the browser agent's attempts table: forms it filled but could not finish, outcomes
  it could not verify, and runs that died before recording one;
* company_sites.md: the worklist of company-site forms left for you.

The dashboard shows them as one list. Each open screener question is matched to its
blank ``A:`` line in answers.txt, so the answer can be saved from the same page.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from common.models import ApplyStatus, JobPosting

from . import state

logger = logging.getLogger(__name__)

#: Days a job stays listed after it stopped at a question; the Naukri bot holds it as long.
QUESTION_DAYS = 7
#: A browser agent that has not written for this long, with its process gone, never will.
ABANDONED_AFTER = dt.timedelta(hours=2)
#: How many of the agent's recorded steps are shown.
STEPS_SHOWN = 12
_STALLED_QUESTION = re.compile(r"question='([^']*)'")
#: How each board writes a job's id into its listing link; the ledger keys jobs the same way.
_LISTING_IDS = (
    ("naukri.com", re.compile(r"(\d{9,})\b"), "{}"),
    ("hirist.tech", re.compile(r"(?:/job/|-)(\d+)(?:/|\?|$)"), "hirist:{}"),
    ("instahyre.com", re.compile(r"/job-(\d+)"), "instahyre:{}"),
    ("wellfound.com", re.compile(r"/jobs/(\d+)"), "wellfound:{}"),
    ("cutshort.io", re.compile(r"/job/[^/?#]*-([A-Za-z0-9]{8})(?:[/?#]|$)"), "cutshort:{}"),
    ("news.ycombinator.com", re.compile(r"[?&]id=(\d+)"), "hn:{}"),
)
_ASKED_WHILE = re.compile(r"while applying to (.+?) at (.+?)(?: \||$)")

BOARD_LABELS = {
    "naukri": "Naukri", "hirist": "Hirist", "instahyre": "Instahyre", "cutshort": "Cutshort",
    "wellfound": "Wellfound", "startups": "Startups", "external": "Company site",
}
KIND_LABELS = {
    "question": "Screener question",
    "review": "Check whether it was sent",
    "access": "Login, CAPTCHA or account",
    "video": "Video or recording",
    "eligibility": "Eligibility to decide",
    "decision": "Your decision",
    "form": "Form details",
    "ready": "Answered, retried on the next run",
}
_KIND_ORDER = ["question", "review", "access", "video", "eligibility", "decision", "form", "ready"]
_KIND_WORDS = (
    ("video", re.compile(r"\b(?:video|loom|facecam|screen[- ]share|record(?:ing)?)\b", re.I)),
    ("access", re.compile(r"\b(?:captcha|hcaptcha|recaptcha|log ?in|sign[- ]?in|sign up|otp|one[- ]time (?:code|password)|"
                          r"verification (?:code|email|link)|password|account|restricted|unusual activity)\b", re.I)),
    ("eligibility", re.compile(r"\b(?:eligib|must (?:live|be located|reside)|living and working|citizen|work authori[sz]ation|"
                               r"visa|sponsorship|graduat|pursuing|not listed|apprenticeship)", re.I)),
    ("decision", re.compile(r"\b(?:salary|ctc|compensation|pay|authori[sz]e|authori[sz]ation|decide|whether|skip this job|"
                            r"commitments or agreements)\b|₹", re.I)),
)


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _key(text: Any) -> str:
    return _clean(text).casefold()


def _safe_url(value: Any) -> str:
    """Only HTTP(S) links become clickable; anything else is shown as text."""
    text = str(value or "").strip()
    parts = urlsplit(text)
    return text if parts.scheme in ("http", "https") and parts.netloc else ""


def _iso(moment: Optional[dt.datetime]) -> str:
    return moment.astimezone().isoformat(timespec="seconds") if moment else ""


def _utc_stamp(value: Any) -> Optional[dt.datetime]:
    """SQLite's CURRENT_TIMESTAMP and the ledger's ``at`` are both UTC; only the ledger says so."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def _local_stamp(value: Any) -> Optional[dt.datetime]:
    """company_sites.md headings carry the local wall clock ("2026-10-28 18:47")."""
    try:
        return dt.datetime.strptime(str(value or "").strip(), "%Y-%m-%d %H:%M").astimezone()
    except ValueError:
        return None


def _split(text: Any, separator: str = ";") -> List[str]:
    """Pieces between separators, keeping "(options 1-3; 3-5)" and the like whole."""
    pieces: List[str] = []
    depth = 0
    current = ""
    for char in str(text or ""):
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
        if char == separator and not depth:
            pieces.append(current)
            current = ""
        else:
            current += char
    pieces.append(current)
    return [piece for piece in (_clean(p) for p in pieces) if piece]


def listing_job_id(url: str) -> str:
    """The ledger's job id for a board or Naukri listing link, "" for a company page."""
    host = urlsplit(url or "").netloc.casefold()
    for domain, pattern, shape in _LISTING_IDS:
        if host == domain or host.endswith("." + domain):
            found = pattern.search(url)
            return shape.format(found.group(1)) if found else ""
    return ""


def _classify(needs: Iterable[str], fallback: str = "form") -> str:
    blob = " ".join(needs)
    for kind, pattern in _KIND_WORDS:
        if pattern.search(blob):
            return kind
    return fallback


def _rows(path: Path, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    except sqlite3.OperationalError as exc:
        # A ledger from before a column existed still has nothing to show for it.
        logger.warning("could not read %s: %s", path.name, exc)
        return []
    finally:
        connection.close()


def _pid_alive(pid: Any) -> bool:
    try:
        number = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- answers.txt -----------------------------------------------------------------


def blank_answers(path: Path = state.ANSWERS) -> List[Dict[str, Any]]:
    """Each empty ``A:`` in answers.txt with its questions and, when the bot wrote one, the
    role it was asked for: ``# 2026-11-11 08:04 | while applying to X at Y | reason``."""
    waiting: List[Dict[str, Any]] = []
    questions: List[str] = []
    comment = ""
    for number, raw in enumerate(state._read(path).splitlines(), start=1):
        text = raw.strip()
        if text.startswith("#"):
            comment = text.lstrip("#").strip()
        elif text.startswith("Q:"):
            questions.append(text[2:].strip())
        elif text.startswith("A:"):
            if not text[2:].strip() and questions:
                found = _ASKED_WHILE.search(comment)
                waiting.append({
                    "line": number, "questions": list(questions),
                    "title": _clean(found.group(1)) if found else "",
                    "company": _clean(found.group(2)) if found else "",
                    "asked": comment.split("|", 1)[0].strip() if comment else "",
                })
            questions = []
            comment = ""
    return waiting


def _answer_lines(blanks: List[Dict[str, Any]]) -> Dict[str, int]:
    lines: Dict[str, int] = {}
    for entry in blanks:
        for question in entry["questions"]:
            lines.setdefault(_key(question), entry["line"])
    return lines


def _answer_book(path: Path) -> Any:
    try:
        from common.answers import AnswerBook

        return AnswerBook(str(path))
    except Exception as exc:  # the page must open even if the answer sheet cannot be parsed
        logger.warning("answers.txt could not be read for matching: %s", exc)
        return None


def _answered(book: Any, question: str) -> bool:
    if book is None:
        return False
    try:
        return book.answer_for(question) is not None
    except Exception as exc:  # a similarity model failing is not a reason to hide the job
        logger.debug("answer lookup failed for %r: %s", question, exc)
        return False


# --- postings (title, link, score, odds) -------------------------------------------


def _total_years(path: Path) -> Optional[float]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        value = data.get("total_experience_years") if isinstance(data, dict) else None
        return float(value) if value not in (None, "") else None
    except Exception as exc:
        logger.debug("total_experience_years unavailable from %s: %s", path, exc)
        return None


def _postings(db: Path, job_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    wanted = sorted({str(job_id) for job_id in job_ids if job_id})
    found: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in _rows(db, f"SELECT job_id,url,title,company,score,experience,description FROM jobs_seen WHERE job_id IN ({marks})", tuple(chunk)):
            found[str(row["job_id"])] = row
    return found


def _odds(posting: Dict[str, Any], total_years: Optional[float]) -> str:
    if not posting:
        return ""
    from naukri_bot.ranking import long_shot_reason

    job = JobPosting(job_id=str(posting.get("job_id") or ""), url=str(posting.get("url") or ""),
                     title=str(posting.get("title") or ""), company=str(posting.get("company") or ""),
                     experience=str(posting.get("experience") or ""), description=str(posting.get("description") or ""))
    return long_shot_reason(job, total_years)


def _board(job_id: str, url: str = "") -> str:
    board = state._board_of_job(job_id) if job_id else ""
    if board == "naukri" and url and "naukri.com" not in urlsplit(url).netloc:
        return "external"
    return board or "external"


def _item(**fields: Any) -> Dict[str, Any]:
    item = {
        "id": "", "job_id": "", "title": "", "company": "", "board": "external", "kind": "form",
        "needs": [], "next_step": "", "why": "", "detail": "", "question": None,
        "links": {}, "already_filled": [], "steps": [], "when": "", "score": None, "odds": "",
        "reviewable": False, "source": "",
    }
    item.update(fields)
    return item


# --- the Naukri ledger -------------------------------------------------------------


def _naukri_items(db: Path, answer_lines: Dict[str, int], book: Any) -> List[Dict[str, Any]]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=QUESTION_DAYS)).isoformat()
    latest = """SELECT a.job_id,a.url,a.title,a.company,a.status,a.detail,a.at FROM applications a
                WHERE a.id = (SELECT MAX(b.id) FROM applications b WHERE b.job_id = a.job_id)"""
    items: List[Dict[str, Any]] = []
    for row in _rows(db, latest + " AND a.status IN (?, ?) AND a.at >= ? ORDER BY a.at DESC",
                     (ApplyStatus.ABSTAINED, ApplyStatus.CHATBOT_TIMEOUT, cutoff)):
        detail = _clean(row["detail"])
        question = detail
        if row["status"] == ApplyStatus.CHATBOT_TIMEOUT:
            found = _STALLED_QUESTION.search(detail)
            question = _clean(found.group(1)) if found else ""
        if not question:
            continue
        answered = _answered(book, question)
        job_id = str(row["job_id"])
        items.append(_item(
            id=f"naukri:{job_id}", job_id=job_id, title=_clean(row["title"]), company=_clean(row["company"]),
            board=_board(job_id, str(row["url"] or "")), kind="ready" if answered else "question",
            needs=[] if answered else [f"Answer: {question}"],
            next_step=("Your answer is saved; the next Naukri round applies with it." if answered
                       else "Save an answer here (or in answers.txt) and the next Naukri round retries this job."),
            why=("The Naukri questionnaire timed out at this question." if row["status"] == ApplyStatus.CHATBOT_TIMEOUT
                 else "The bot does not guess at screener questions without an answer from you."),
            detail=detail, question={"text": question, "line": answer_lines.get(_key(question)), "answered": answered},
            links={"job": _safe_url(row["url"])}, when=_iso(_utc_stamp(row["at"])), source="naukri",
        ))
    for row in _rows(db, latest + " AND (a.detail LIKE ? OR a.detail LIKE ?) ORDER BY a.at DESC",
                     ("%submit was clicked%", "%browser agent did not report%")):
        job_id = str(row["job_id"])
        items.append(_item(
            id=f"naukri:{job_id}", job_id=job_id, title=_clean(row["title"]), company=_clean(row["company"]),
            board=_board(job_id, str(row["url"] or "")), kind="review",
            needs=["Check the application page or your Sent mail, then record whether it was sent."],
            next_step="The bot holds this job so nothing is sent twice. Confirm it by hand, then record the outcome.",
            why="Submit was clicked on the company site but no confirmation appeared.",
            detail=_clean(row["detail"]), links={"job": _safe_url(row["url"])},
            when=_iso(_utc_stamp(row["at"])), source="naukri",
        ))
    return items


# --- the browser agent's attempts --------------------------------------------------


def _needs_from_detail(detail: str) -> List[str]:
    text = _clean(detail)
    lowered = text.casefold()
    for marker in ("needs you for:", "the browser agent stopped (needs_you):", "stopped (needs_you):"):
        at = lowered.find(marker)
        if at >= 0:
            text = text[at + len(marker):].strip()
            break
    # "(browser agent: …)" trails the facts list with the agent's own narration.
    text = re.sub(r"\s*\(browser agent:.*\)\s*$", "", text).strip()
    return _split(text) if text else []


def _agent_items(db: Path, now: dt.datetime) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    sql = "SELECT job_id,title,company,url,state,next_step,detail,report_json,owner_pid,updated_at FROM attempts WHERE state IN ('needs_you','uncertain','running') ORDER BY updated_at DESC"
    for row in _rows(db, sql):
        when = _utc_stamp(row["updated_at"])
        if row["state"] == "running":
            if _pid_alive(row["owner_pid"]) or (when and now - when < ABANDONED_AFTER):
                continue
        try:
            report = json.loads(row["report_json"] or "{}")
        except ValueError:
            report = {}
        if not isinstance(report, dict):
            report = {}
        detail = _clean(row["detail"])
        needs = _needs_from_detail(detail)
        job_id = str(row["job_id"] or "")
        url = _safe_url(row["url"])
        if row["state"] == "needs_you":
            kind = _classify(needs or [detail])
            why = _clean(report.get("why")) or detail
        else:
            kind = "review"
            why = _clean(report.get("why")) or detail or "The attempt ended without a recorded outcome."
            needs = ["Check the application page or your Sent mail, then record whether it was sent."]
        steps = [
            {"state": _clean(step.get("state")), "observation": _clean(step.get("observation")), "action": _clean(step.get("action"))}
            for step in (report.get("steps") or [])[:STEPS_SHOWN] if isinstance(step, dict)
        ]
        items.append(_item(
            id=f"agent:{job_id}", job_id=job_id, title=_clean(row["title"]), company=_clean(row["company"]),
            board=_board(job_id, url), kind=kind, needs=needs, next_step=_clean(row["next_step"]), why=why,
            detail=detail, links={"job": url}, steps=steps, when=_iso(when), reviewable=row["state"] != "needs_you",
            source="agent",
        ))
    return items


# --- company_sites.md --------------------------------------------------------------


def _site_items(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for index, entry in enumerate(state.company_sites(path)):
        naukri = _safe_url(entry.get("naukri"))
        job_id = listing_job_id(naukri)
        needs = _split(entry.get("left for you")) or _needs_from_detail(entry.get("why", ""))
        links = {"site": _safe_url(entry.get("site")), "naukri": naukri}
        if entry.get("resume to send"):
            links["resume"] = entry["resume to send"]
        items.append(_item(
            id=f"site:{job_id or index}", job_id=job_id, title=_clean(entry.get("title")), company=_clean(entry.get("company")),
            board=_board(job_id, naukri) if job_id else "external", kind=_classify(needs), needs=needs,
            next_step="Finish the form by hand on the company site, or answer the open questions and run the company-site bot again.",
            why=_clean(entry.get("why")), detail=_clean(entry.get("status")), links={k: v for k, v in links.items() if v},
            already_filled=_split(entry.get("already filled"), ","), when=_iso(_local_stamp(entry.get("when"))), source="sites",
        ))
    return items


def _aliases(item: Dict[str, Any]) -> List[str]:
    """Keys under which the same application can appear in two of the three sources."""
    keys = []
    if item["job_id"]:
        keys.append("job:" + item["job_id"])
    for link in (item["links"].get("job"), item["links"].get("site")):
        if link:
            parts = urlsplit(link)
            keys.append("url:" + parts.netloc.casefold() + parts.path.rstrip("/"))
    if item["company"] and item["title"]:
        keys.append("name:" + _key(item["company"]) + "|" + _key(item["title"]))
    return keys


def _need_key(text: str) -> str:
    """"Captcha (a check only a person may answer)" and "Captcha *" name the same field."""
    return _key(re.sub(r"\([^()]*\)", " ", text)).strip(" *:.;")


def _merge(primary: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """The agent's record leads; the worklist adds the links and field lists only it knows."""
    merged = dict(primary)
    merged["links"] = {**extra.get("links", {}), **primary.get("links", {})}
    merged["already_filled"] = primary.get("already_filled") or extra.get("already_filled", [])
    seen = {_need_key(need) for need in primary["needs"]}
    merged["needs"] = primary["needs"] + [need for need in extra["needs"] if _need_key(need) not in seen]
    for field in ("title", "company", "why", "when"):
        merged[field] = primary.get(field) or extra.get(field, "")
    return merged


# --- the page ------------------------------------------------------------------------


def _integer(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(str(default if value in (None, "") else value))
    except (TypeError, ValueError):
        raise ValueError("Use whole numbers for the period and the page.") from None
    if not low <= number <= high:
        raise ValueError(f"Value must be between {low} and {high}.")
    return number


def summary(days: int = 14, **paths: Any) -> Dict[str, Any]:
    """Just the counts the Launchpad shows: how many jobs wait, by what they need and by platform."""
    data = waiting_json({"days": days, "size": 1}, **paths)
    return {"total": data["total"], "days": data["days"], "kinds": data["kinds"], "boards": data["boards"]}


def waiting_json(
    params: Optional[Dict[str, Any]] = None,
    db: Optional[Path] = None,
    agent_db: Optional[Path] = None,
    answers: Path = state.ANSWERS,
    sites: Path = state.COMPANY_SITES,
    profile: Path = state.PROFILE,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Every job waiting on a person, newest first, with what each one needs.

    ``params``: days (default 14, 0 = since the first run), kind, board, q, page, size.
    The kind and board tallies cover the whole period so the filters can show counts.
    """
    params = params or {}
    days = _integer(params.get("days"), 14, 0, 36500)
    page = _integer(params.get("page"), 1, 1, 1000000)
    size = _integer(params.get("size"), 50, 1, 200)
    kind = str(params.get("kind") or "all")
    board = str(params.get("board") or "all")
    query = _key(params.get("q"))
    now = now or dt.datetime.now(dt.timezone.utc)
    db = db or state.database()
    agent_db = agent_db or (answers.parent / "application-agent.sqlite")
    blanks = blank_answers(answers)
    book = _answer_book(answers)

    items: List[Dict[str, Any]] = []
    position: Dict[str, int] = {}
    aliases_at: List[List[str]] = []

    def add(item: Dict[str, Any]) -> None:
        aliases = _aliases(item)
        index = next((position[alias] for alias in aliases if alias in position), None)
        if index is None:
            index = len(items)
            items.append(item)
            aliases_at.append([])
        else:
            items[index] = _merge(items[index], item)
        aliases_at[index] = sorted(set(aliases_at[index]) | set(aliases))
        for alias in aliases_at[index]:
            position[alias] = index

    for item in _agent_items(agent_db, now):
        add(item)
    for item in _naukri_items(db, _answer_lines(blanks), book):
        add(item)
    for item in _site_items(sites):
        add(item)

    start = (now.astimezone() - dt.timedelta(days=days - 1)).date() if days else None
    if start:
        items = [item for item in items if not item["when"] or dt.datetime.fromisoformat(item["when"]).date() >= start]

    postings = _postings(db, (item["job_id"] for item in items))
    total_years = _total_years(profile)
    for item in items:
        posting = postings.get(item["job_id"], {})
        item["title"] = item["title"] or _clean(posting.get("title"))
        item["company"] = item["company"] or _clean(posting.get("company"))
        if not item["links"].get("job") and posting.get("url"):
            item["links"]["job"] = _safe_url(posting["url"])
        item["score"] = posting.get("score")
        try:
            item["odds"] = _odds(posting, total_years)
        except Exception as exc:  # a malformed posting must not hide the job
            logger.debug("odds unavailable for %s: %s", item["job_id"], exc)
        item["board_label"] = BOARD_LABELS.get(item["board"], item["board"].capitalize())
        item["kind_label"] = KIND_LABELS.get(item["kind"], item["kind"])
    items.sort(key=lambda item: item["when"], reverse=True)

    def tally(field: str, labels: Dict[str, str], order: List[str]) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        for item in items:
            counts[item[field]] = counts.get(item[field], 0) + 1
        keys = [key for key in order if key in counts] + sorted(key for key in counts if key not in order)
        return [{"key": key, "label": labels.get(key, key.capitalize()), "count": counts[key]} for key in keys]

    kinds = tally("kind", KIND_LABELS, _KIND_ORDER)
    boards = tally("board", BOARD_LABELS, list(BOARD_LABELS))
    shown = [
        item for item in items
        if (kind == "all" or item["kind"] == kind) and (board == "all" or item["board"] == board)
        and (not query or query in _key(" ".join([item["title"], item["company"], item["why"], item["next_step"], *item["needs"]])))
    ]
    pages = max(1, (len(shown) + size - 1) // size)
    page = min(page, pages)
    linked = {item["question"]["line"] for item in items if item.get("question") and item["question"].get("line")}
    return {
        "generated_at": _iso(now),
        "days": days, "kind": kind, "board": board, "q": str(params.get("q") or ""),
        "page": page, "pages": pages, "size": size,
        "total": len(items), "matched": len(shown),
        "kinds": kinds,
        "boards": boards,
        "items": shown[(page - 1) * size:page * size],
        "questions": [{**entry, "linked": entry["line"] in linked} for entry in blanks],
        "facts": [{"line": line, "key": key} for line, key in state.blank_facts(profile)],
    }
