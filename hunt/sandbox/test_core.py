"""Reproductions for the core lane (common/ and naukri_bot/)."""

from pathlib import Path

import pytest
from lxml import html

from common import answers as answers_module
from common.answers import AnswerBook, AnswerEngine
from common.config import load_settings
from common.ledger import Ledger
from common.llm import NullClient
from common.models import ApplyResult, ApplyStatus, Profile, Settings


def test_core_01_answer_book_matches_questions_exactly(tmp_path: Path) -> None:
    """Contract: 'There is no fuzzy matching anywhere in the package' (naukri_bot/__init__.py, README)."""
    book_path = tmp_path / "answers.txt"
    book_path.write_text("Q: How many years of experience do you have in Python?\nA: 5\n", encoding="utf-8")
    book = AnswerBook(str(book_path))
    assert book.answer_for("How many years of experience do you have in Python?") == "5"
    assert book.answer_for("How many years of experience do you have in PySpark?") is None


def test_core_02_success_xpath_matches_only_the_element_that_says_it() -> None:
    """Contract: 'Nothing is reported as applied unless it is verified'; the refusal xpath documents the ancestor pitfall."""
    from naukri_bot import apply as apply_module

    page = html.fromstring(
        "<html><body><h1>Senior Engineer</h1>"
        "<div id='jd'>Once your application sent, we call you within a week.</div>"
        "</body></html>"
    )
    matched = page.xpath(apply_module._SUCCESS_XPATH)
    tags = [element.tag for element in matched]
    assert "html" not in tags and "body" not in tags, tags
    quota_page = html.fromstring("<html><body><p>Candidates must meet a daily quota of calls.</p></body></html>")
    quota_tags = [element.tag for element in quota_page.xpath(apply_module._QUOTA_XPATH)]
    assert "html" not in quota_tags and "body" not in quota_tags, quota_tags


def _engine(tmp_path: Path, profile: Profile) -> AnswerEngine:
    settings = Settings(data_dir=str(tmp_path), llm_backend="none", judge_answers=False)
    (tmp_path / "answers.txt").write_text("", encoding="utf-8")
    engine = AnswerEngine(Ledger(":memory:"), NullClient(), profile, settings)
    answers_module.install_answer_book(settings)
    return engine


def test_core_03_passport_number_is_never_answered(tmp_path: Path) -> None:
    """Contract: identity numbers are never answered; a skill named nowhere gets 0 years, never more."""
    engine = _engine(tmp_path, Profile(total_experience_years=2.5, has_passport=True))
    passport = engine.resolve("Enter your passport number")
    assert passport.abstained or passport.answer is None or passport.answer.text in ("", None), passport
    kafka = engine.resolve("Total experience in Apache Kafka (years)")
    if not kafka.abstained and kafka.answer is not None:
        assert kafka.answer.text not in ("2.5", "2.5 years"), kafka.answer


def test_core_08_empty_db_path_still_persists_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: 'db holds your applied-history and quota memory'; invalid settings fall back to defaults."""
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DB_PATH", "")
    settings = load_settings(env_path=str(env_file))
    first = Ledger(settings.db_path)
    first.record_attempt(ApplyResult("7", "https://x", ApplyStatus.APPLIED, quota_consumed=True))
    first.close()
    second = Ledger(settings.db_path)
    try:
        assert second.has_applied("7"), f"db_path={settings.db_path!r} did not persist"
    finally:
        second.close()


def test_core_09_unrecognised_dry_run_value_does_not_go_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: --dry-run clicks nothing; Settings.validate catches unusable configuration."""
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DRY_RUN", "enabled")
    settings = load_settings(env_path=str(env_file))
    assert settings.dry_run is True


def test_core_10_already_applied_counts_as_applied() -> None:
    """Contract: step 6 of the cli docstring, 'drop anything already applied to'."""
    ledger = Ledger(":memory:")
    try:
        ledger.record_attempt(ApplyResult("7", "https://x", ApplyStatus.ALREADY_APPLIED))
        assert ledger.has_applied("7") is True
    finally:
        ledger.close()
