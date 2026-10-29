"""Age comes from the date of birth on file.

On 29 October a company form asked "Age *". The date of birth was in profile.yaml,
but nothing worked the age out from it, so the application stopped for a person.
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import answers
from common.ledger import Ledger
from common.models import Profile, Settings


class NoLLM:
    def available(self):
        return False


def _engine(tmp_path, monkeypatch, **facts):
    monkeypatch.chdir(tmp_path)
    return answers.AnswerEngine(
        Ledger(":memory:"),
        NoLLM(),
        Profile(full_name="T", extra_facts=dict(facts)),
        Settings(data_dir=str(tmp_path)),
    )


def _years_old(born):
    day = datetime.strptime(born, "%d/%m/%Y")
    today = datetime.now()
    return today.year - day.year - ((today.month, today.day) < (day.month, day.day))


@pytest.mark.parametrize("question", [
    "Age *",
    "What is your age?",
    "How old are you?",
    "Age (in years)",
    "Your age",
])
def test_a_form_asking_for_age_is_answered_from_the_date_of_birth(question, tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch, date_of_birth="05/04/2003")

    resolution = engine.resolve(question)

    assert resolution.answer is not None
    assert resolution.answer.text == str(_years_old("05/04/2003"))
    assert resolution.answer.grounded_in == "extra_facts.date_of_birth"


@pytest.mark.parametrize("born", [
    "2003-04-05",
    "05-04-2003",
    "05.04.2003",
    "5 April 2003",
    "5 Apr 2003",
    "April 5, 2003",
])
def test_the_date_of_birth_is_read_however_it_was_written(born, tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch, date_of_birth=born)

    resolution = engine.resolve("Age *")

    assert resolution.answer is not None
    assert resolution.answer.text == str(_years_old("05/04/2003"))


@pytest.mark.parametrize("question", [
    "Average package in your team?",
    "Message to the hiring manager",
    "Total coverage of your tests?",
    "Who was your line manager?",
    "What is your current usage of AWS?",
])
def test_a_word_that_merely_contains_age_is_not_an_age_question(question, tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch, date_of_birth="05/04/2003")

    assert engine.resolve(question).answer is None


def test_without_a_date_of_birth_the_question_is_left_to_the_other_sources(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch)

    assert engine.resolve("Age *").answer is None


def test_a_date_of_birth_that_is_not_a_date_is_not_guessed_at(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch, date_of_birth="sometime in 2003")

    assert engine.resolve("Age *").answer is None


def test_an_age_bracket_takes_the_band_the_age_falls_in(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch, date_of_birth="05/04/2003")
    bands = ["18 - 22", "23 - 27", "28 - 35", "36 and above"]

    resolution = engine.resolve("Age group", options=bands)

    assert resolution.answer is not None
    assert resolution.answer.text == "23 - 27"


def test_an_age_question_offering_only_yes_or_no_is_left_to_the_other_sources(tmp_path, monkeypatch):
    """"Are you above 18 years of age?" is a yes/no, and a bare "23" would not be an answer."""
    engine = _engine(tmp_path, monkeypatch, date_of_birth="05/04/2003")

    assert engine.resolve("Are you above 18 years of age?", options=["Yes", "No"]).answer is None
