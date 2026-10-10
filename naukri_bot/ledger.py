"""Persistent application and screening-answer ledger."""

# noqa: SIZE_OK - the requested Ledger contract is an indivisible persistence unit.

import csv
import json
import logging
import os
import sqlite3
import string
import threading
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any, Dict, List, Optional, Set, Type

from .models import Answer, AnswerSource, ApplyResult, ApplyStatus, JobPosting, Settings


logger = logging.getLogger(__name__)


class LedgerExportError(ValueError):
    """Raised when an export would overwrite the ledger database."""


def _now() -> str:
    """Return the current time as a UTC ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _normalise_question(text: str) -> str:
    """Create the exact-match cache key for a screening question."""
    collapsed = " ".join(text.lower().split())
    return collapsed.rstrip(string.punctuation).rstrip()


class Ledger:
    """Own the durable SQLite state shared by all bot runs."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        try:
            self._connection = sqlite3.connect(
                db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._migrate()
            self._ensure_fingerprint_column()
            self._ensure_facts_column()
        except sqlite3.Error:
            logger.exception("failed to open ledger database at %s", db_path)
            raise

    def _ensure_fingerprint_column(self) -> None:
        with self._lock, self._connection:
            columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(answers)")
            }
            if "profile_fingerprint" not in columns:
                self._connection.execute(
                    "ALTER TABLE answers ADD COLUMN profile_fingerprint TEXT"
                )

    def _ensure_facts_column(self) -> None:
        with self._lock, self._connection:
            columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(applications)")
            }
            if "facts_fingerprint" not in columns:
                self._connection.execute(
                    "ALTER TABLE applications ADD COLUMN facts_fingerprint TEXT"
                )

    def _migrate(self) -> None:
        """Create the ledger schema if it does not already exist."""
        try:
            with self._lock, self._connection:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS jobs_seen(
                        job_id TEXT PRIMARY KEY, url TEXT, title TEXT,
                        company TEXT, source TEXT, first_seen TEXT,
                        last_seen TEXT, score REAL
                    );
                    CREATE TABLE IF NOT EXISTS applications(
                        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT,
                        url TEXT, title TEXT, company TEXT, status TEXT,
                        detail TEXT, quota_consumed INTEGER,
                        questions_answered INTEGER, questions_abstained INTEGER,
                        at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_applications_job_id
                        ON applications(job_id);
                    CREATE INDEX IF NOT EXISTS idx_applications_at
                        ON applications(at);
                    CREATE TABLE IF NOT EXISTS answers(
                        question_norm TEXT PRIMARY KEY, question_text TEXT,
                        answer TEXT, field_type TEXT, grounded_in TEXT,
                        source TEXT, confidence REAL, created_at TEXT,
                        updated_at TEXT, times_used INTEGER DEFAULT 0,
                        profile_fingerprint TEXT
                    );
                    CREATE TABLE IF NOT EXISTS runs(
                        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT,
                        finished_at TEXT, collected INTEGER, ranked INTEGER,
                        attempted INTEGER, applied INTEGER, summary_json TEXT
                    );
                    CREATE TABLE IF NOT EXISTS early_access_shares(
                        role_key TEXT PRIMARY KEY, title TEXT, company TEXT,
                        experience TEXT, location TEXT, posted_label TEXT,
                        shared_at TEXT
                    );
                    """
                )
        except sqlite3.Error:
            logger.exception("failed to migrate ledger database")
            raise

    def has_applied(self, job_id: str) -> bool:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT 1 FROM applications WHERE job_id = ? AND status IN (?, ?) LIMIT 1",
                    (job_id, ApplyStatus.APPLIED, ApplyStatus.APPLIED_EXTERNAL),
                ).fetchone()
            return row is not None
        except sqlite3.Error:
            logger.exception("failed to check applied status for job %s", job_id)
            raise

    def attempt_count(self, job_id: str) -> int:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS count FROM applications WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            return int(row["count"])
        except sqlite3.Error:
            logger.exception("failed to count attempts for job %s", job_id)
            raise

    def seen_before(self, job_id: str) -> bool:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT 1 FROM jobs_seen WHERE job_id = ? LIMIT 1", (job_id,)
                ).fetchone()
            return row is not None
        except sqlite3.Error:
            logger.exception("failed to check seen status for job %s", job_id)
            raise

    def has_shared_interest(self, role_key: str) -> bool:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT 1 FROM early_access_shares WHERE role_key = ? LIMIT 1",
                    (role_key,),
                ).fetchone()
        except sqlite3.Error:
            logger.exception("failed to read early access share %s", role_key)
            raise
        return row is not None

    def record_interest_share(
        self,
        role_key: str,
        title: str = "",
        company: str = "",
        experience: str = "",
        location: str = "",
        posted_label: str = "",
    ) -> None:
        now = _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO early_access_shares(
                        role_key, title, company, experience, location,
                        posted_label, shared_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(role_key) DO UPDATE SET
                        shared_at = excluded.shared_at
                    """,
                    (role_key, title, company, experience, location, posted_label, now),
                )
        except sqlite3.Error:
            logger.exception("failed to record early access share %s", role_key)
            raise

    def record_seen(self, job: JobPosting, score: Optional[float] = None) -> None:
        seen_at = _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """INSERT INTO jobs_seen(
                           job_id, url, title, company, source, first_seen, last_seen, score
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(job_id) DO UPDATE SET
                           last_seen = excluded.last_seen,
                           score = COALESCE(excluded.score, score)""",
                    (
                        job.job_id, job.url, job.title, job.company, job.source,
                        seen_at, seen_at, score,
                    ),
                )
        except sqlite3.Error:
            logger.exception("failed to record seen job %s", job.job_id)
            raise

    def record_attempt(
        self, result: ApplyResult, title: str = "", company: str = "", facts: str = ""
    ) -> None:
        if (result.status == ApplyStatus.APPLIED) != result.quota_consumed:
            logger.warning(
                "inconsistent application result for job %s: status=%s, quota_consumed=%s",
                result.job_id,
                result.status,
                result.quota_consumed,
            )
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """INSERT INTO applications(
                           job_id, url, title, company, status, detail,
                           quota_consumed, questions_answered,
                           questions_abstained, at, facts_fingerprint
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result.job_id, result.url, title, company, result.status,
                        result.detail, int(result.quota_consumed),
                        result.questions_answered, result.questions_abstained, _now(),
                        facts or None,
                    ),
                )
        except sqlite3.Error:
            logger.exception("failed to record attempt for job %s", result.job_id)
            raise

    def waiting_on_you(self, facts: str) -> Set[str]:
        """Jobs whose latest attempt stopped for you while `facts` was what it is now.

        `facts` fingerprints the answers and facts the user edits; until it
        changes, the same question stops the same application again.
        """
        if not facts:
            return set()
        try:
            with self._lock:
                rows = self._connection.execute(
                    """SELECT a.job_id FROM applications a
                       WHERE a.id = (SELECT MAX(b.id) FROM applications b WHERE b.job_id = a.job_id)
                         AND a.status IN (?, ?) AND a.facts_fingerprint = ?""",
                    (ApplyStatus.ABSTAINED, ApplyStatus.EXTERNAL_MANUAL, facts),
                ).fetchall()
            return {row[0] for row in rows}
        except sqlite3.Error:
            logger.exception("failed to list applications waiting on the user")
            raise

    def external_history(self) -> Dict[str, Dict[str, Any]]:
        """When each company-site role was first and last encountered.

        The worklist file is cleared by hand most mornings, so it cannot
        remember which roles have already been offered. The ledger can: every
        skipped company-site role is recorded with a timestamp.
        """
        try:
            with self._lock:
                rows = self._connection.execute(
                    """SELECT url,
                              MIN(at) AS first_seen,
                              MAX(at) AS last_seen,
                              COUNT(*) AS times_seen
                       FROM applications
                       WHERE status = ?
                       GROUP BY url""",
                    (ApplyStatus.EXTERNAL_SKIPPED,),
                ).fetchall()
            return {
                row["url"]: {
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "times_seen": int(row["times_seen"]),
                }
                for row in rows
            }
        except sqlite3.Error:
            logger.exception("failed to read company-site history")
            return {}

    def quota_used(self, window_hours: int = 24) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        try:
            with self._lock:
                row = self._connection.execute(
                    """SELECT COUNT(*) AS count FROM applications
                       WHERE quota_consumed = ? AND at >= ?""",
                    (1, cutoff),
                ).fetchone()
            return int(row["count"])
        except sqlite3.Error:
            logger.exception("failed to calculate quota used")
            raise

    def quota_remaining(self, daily_quota: int = 50, window_hours: int = 24) -> int:
        return max(0, daily_quota - self.quota_used(window_hours))

    def recent_applications(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT * FROM applications ORDER BY at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            logger.exception("failed to list recent applications")
            raise

    def applications_between(self, start: str, end: str) -> List[Dict[str, Any]]:
        """Every attempt with start <= at < end (UTC ISO strings), oldest first."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT * FROM applications WHERE at >= ? AND at < ? ORDER BY at, id",
                    (start, end),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            logger.exception("failed to list applications between %s and %s", start, end)
            raise

    def runs_between(self, start: str, end: str) -> List[Dict[str, Any]]:
        """Runs that started in [start, end), with summary_json decoded as `summary`."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT * FROM runs WHERE started_at >= ? AND started_at < ? ORDER BY started_at, id",
                    (start, end),
                ).fetchall()
        except sqlite3.Error:
            logger.exception("failed to list runs between %s and %s", start, end)
            raise
        runs = []
        for row in rows:
            record = dict(row)
            try:
                record["summary"] = json.loads(record.get("summary_json") or "{}")
            except ValueError:
                record["summary"] = {}
            runs.append(record)
        return runs

    def get_answer(
        self, question_text: str, profile_fingerprint: Optional[str] = None
    ) -> Optional[Answer]:
        question_norm = _normalise_question(question_text)
        try:
            with self._lock, self._connection:
                row = self._connection.execute(
                    """SELECT answer, grounded_in, confidence, profile_fingerprint
                       FROM answers WHERE question_norm = ?""",
                    (question_norm,),
                ).fetchone()
                if row is None:
                    return None
                if (
                    profile_fingerprint is not None
                    and row["profile_fingerprint"] != profile_fingerprint
                ):
                    return None
                self._connection.execute(
                    "UPDATE answers SET times_used = times_used + 1 WHERE question_norm = ?",
                    (question_norm,),
                )
            return Answer(
                text=row["answer"],
                grounded_in=row["grounded_in"],
                source=AnswerSource.CACHE,
                confidence=float(row["confidence"]),
            )
        except sqlite3.Error:
            logger.exception("failed to get cached answer")
            raise

    def save_answer(
        self,
        question_text: str,
        answer: Answer,
        field_type: str = "text",
        profile_fingerprint: Optional[str] = None,
    ) -> None:
        question_norm = _normalise_question(question_text)
        saved_at = _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """INSERT INTO answers(
                           question_norm, question_text, answer, field_type,
                           grounded_in, source, confidence, created_at,
                           updated_at, profile_fingerprint
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(question_norm) DO UPDATE SET
                           question_text = excluded.question_text,
                           answer = excluded.answer,
                           field_type = excluded.field_type,
                           grounded_in = excluded.grounded_in,
                           source = excluded.source,
                           confidence = excluded.confidence,
                           updated_at = excluded.updated_at,
                           profile_fingerprint = excluded.profile_fingerprint""",
                    (
                        question_norm, question_text, answer.text, field_type,
                        answer.grounded_in, answer.source, answer.confidence,
                        saved_at, saved_at, profile_fingerprint,
                    ),
                )
        except sqlite3.Error:
            logger.exception("failed to save cached answer")
            raise

    def start_run(self) -> int:
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO runs(started_at) VALUES (?)", (_now(),)
                )
                run_id = cursor.lastrowid
            if run_id is None:
                raise sqlite3.DatabaseError("run insert did not return an id")
            return run_id
        except sqlite3.Error:
            logger.exception("failed to start run")
            raise

    def finish_run(self, run_id: int, summary: Dict[str, Any]) -> None:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """UPDATE runs SET finished_at = ?, collected = ?, ranked = ?,
                           attempted = ?, applied = ?, summary_json = ? WHERE id = ?""",
                    (
                        _now(), summary.get("collected", 0), summary.get("ranked", 0),
                        summary.get("attempted", 0), summary.get("applied", 0),
                        json.dumps(summary, sort_keys=True), run_id,
                    ),
                )
        except sqlite3.Error:
            logger.exception("failed to finish run %s", run_id)
            raise

    def export_csv(self, path: str) -> None:
        export_path = os.path.abspath(path)
        database_path = os.path.abspath(self._db_path)
        overwrites_database = self._db_path != ":memory:" and (
            export_path == database_path
            or (
                os.path.exists(export_path)
                and os.path.exists(database_path)
                and os.path.samefile(export_path, database_path)
            )
        )
        if overwrites_database:
            raise LedgerExportError("CSV export path is the ledger database")
        try:
            with self._lock:
                cursor = self._connection.execute(
                    "SELECT * FROM applications ORDER BY id ASC"
                )
                rows = cursor.fetchall()
                fieldnames = [column[0] for column in cursor.description]
        except sqlite3.Error:
            logger.exception("failed to read applications for CSV export")
            raise
        parent = os.path.dirname(export_path)
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)

    def close(self) -> None:
        try:
            with self._lock:
                self._connection.close()
        except sqlite3.Error:
            logger.exception("failed to close ledger database")
            raise

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.close()


def open_ledger(settings: Settings) -> Ledger:
    return Ledger(settings.db_path)
