"""Two open applications per employer across every bot, and no cached answer outliving the facts it came from."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import ledger as ledger_module
from common.ledger import Ledger, company_key
from common.models import Answer, AnswerSource, ApplyResult, ApplyStatus, Settings


@pytest.mark.parametrize("raw,expected", [
    ("Accenture", "accenture"),
    ("Accenture Solutions Pvt Ltd", "accenture"),
    ("ACCENTURE  Solutions Private Limited", "accenture"),
    ("Soul Ai", "soul ai"),
    ("Soul AI  ", "soul ai"),
    ("Tata Consultancy Services", "tata consultancy"),
    ("", ""),
    (None, ""),
])
def test_company_key_groups_an_employers_spellings(raw, expected):
    assert company_key(raw) == expected


def _sent(ledger, job_id, company, status=ApplyStatus.APPLIED):
    ledger.record_attempt(ApplyResult(job_id=job_id, url="u/" + job_id, status=status,
                                      quota_consumed=status == ApplyStatus.APPLIED), company=company)


def test_open_applications_are_counted_per_employer_across_bots():
    ledger = Ledger(":memory:")
    _sent(ledger, "naukri:1", "Accenture")
    _sent(ledger, "hirist:2", "Accenture Solutions Pvt Ltd", ApplyStatus.APPLIED_PLATFORM)
    _sent(ledger, "site:3", "accenture", ApplyStatus.APPLIED_EXTERNAL)
    _sent(ledger, "naukri:4", "Acme")
    _sent(ledger, "naukri:5", "Acme", ApplyStatus.ABSTAINED)     # never went out
    _sent(ledger, "naukri:1", "Accenture")                       # the same posting twice is one application
    assert ledger.open_per_company() == {"accenture": 3, "acme": 1}


def test_applications_older_than_the_open_window_stop_counting():
    ledger = Ledger(":memory:")
    _sent(ledger, "naukri:1", "Acme")
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    with ledger._lock, ledger._connection:
        ledger._connection.execute("UPDATE applications SET at = ?", (old,))
    assert ledger.open_per_company() == {}
    assert ledger.open_per_company(days=60) == {"acme": 1}


def test_the_default_cap_is_two_open_per_company():
    assert Settings().max_per_company == 2


def _answer(text="15 days"):
    return Answer(text=text, grounded_in="notice_period_days", source=AnswerSource.PROFILE, confidence=1.0)


def test_a_cached_answer_under_old_facts_is_deleted_when_read():
    ledger = Ledger(":memory:")
    ledger.save_answer("Notice period?", _answer("30 days"), profile_fingerprint="old")
    assert ledger.get_answer("Notice period?", "old").text == "30 days"
    assert ledger.get_answer("Notice period?", "new") is None
    assert ledger.get_answer("Notice period?") is None, "a reader passing no fingerprint must not see it either"


def test_purging_stale_answers_keeps_the_current_ones():
    ledger = Ledger(":memory:")
    ledger.save_answer("Notice period?", _answer("30 days"), profile_fingerprint="old")
    ledger.save_answer("Total experience?", _answer("2.9"), profile_fingerprint="new")
    ledger.save_answer("City?", _answer("Indore"), profile_fingerprint=None)
    assert ledger.purge_stale_answers("new") == 2
    assert ledger.purge_stale_answers("new") == 0
    assert ledger.purge_stale_answers("") == 0
    assert ledger.get_answer("Total experience?", "new").text == "2.9"
    assert ledger.get_answer("Notice period?", "new") is None


def test_the_answer_engine_purges_on_a_fingerprint_refresh(tmp_path):
    from common.answers import AnswerEngine
    from common.models import Profile

    class _NoLLM:
        def available(self):
            return False

    ledger = Ledger(":memory:")
    ledger.save_answer("Notice period?", _answer("30 days"), profile_fingerprint="old")
    settings = Settings(data_dir=str(tmp_path / "inputs"))
    engine = AnswerEngine(ledger, _NoLLM(), Profile(full_name="T", notice_period_days=15), settings)
    engine._refresh_fingerprint()
    assert ledger.get_answer("Notice period?") is None
    assert ledger_module.OPEN_STATUSES == (ApplyStatus.APPLIED, ApplyStatus.APPLIED_EXTERNAL,
                                           ApplyStatus.APPLIED_PLATFORM)


def _engine(ledger, tmp_path, **facts):
    from common.answers import AnswerEngine
    from common.models import Profile

    class _NoLLM:
        def available(self):
            return False

    profile = Profile(full_name="T", notice_period_days=30, total_experience_years=3, **facts)
    return AnswerEngine(ledger, _NoLLM(), profile, Settings(data_dir=str(tmp_path / "inputs")))


def _cached(ledger):
    return sorted(row[0] for row in ledger._connection.execute("SELECT question_norm FROM answers"))


def test_answers_learned_under_unchanged_facts_stay_cached_across_questions(tmp_path, caplog):
    """#23: each new question purged every answer cached before it, and logged that the facts had changed."""
    ledger = Ledger(":memory:")
    engine = _engine(ledger, tmp_path)
    with caplog.at_level("INFO"):
        engine.resolve("What is your notice period?")
        engine.resolve("How many years of total experience do you have?")
        engine.resolve("What is your notice period?")
    assert _cached(ledger) == ["how many years of total experience do you have", "what is your notice period"]
    assert "earlier facts" not in caplog.text


def test_answers_survive_a_new_run_when_the_facts_are_the_same(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    _engine(ledger, tmp_path).resolve("What is your notice period?")
    _engine(ledger, tmp_path).resolve("How many years of total experience do you have?")
    assert len(_cached(ledger)) == 2


def test_a_change_of_facts_still_purges_what_was_learned_before(tmp_path, caplog):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    _engine(ledger, tmp_path).resolve("What is your notice period?")
    with caplog.at_level("INFO"):
        _engine(ledger, tmp_path, current_location="Pune").resolve("How many years of total experience do you have?")
    assert _cached(ledger) == ["how many years of total experience do you have"]
    assert "Dropped 1 learned answers made under earlier facts" in caplog.text


def test_an_older_ledger_gets_the_facts_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as old:
        old.execute("CREATE TABLE answers(question_norm TEXT PRIMARY KEY, question_text TEXT, answer TEXT, "
                    "field_type TEXT, grounded_in TEXT, source TEXT, confidence REAL, created_at TEXT, "
                    "updated_at TEXT, times_used INTEGER DEFAULT 0, profile_fingerprint TEXT)")
        old.execute("INSERT INTO answers(question_norm, answer, confidence, profile_fingerprint) "
                    "VALUES ('notice period', '30', 1.0, 'old')")
    ledger = Ledger(str(path))
    assert ledger.purge_stale_answers("new") == 1
    ledger.save_answer("Notice period?", _answer(), profile_fingerprint="key", facts_fingerprint="new")
    assert ledger.purge_stale_answers("new") == 0
