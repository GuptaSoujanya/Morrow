"""'Are you currently living in <place>?' is a fact about current_location, not a judgement call."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.answers import AnswerEngine
from common.ledger import Ledger
from common.models import Profile, Settings


class _NoLLM:
    def available(self):
        return False


def _engine(home="Indore, India"):
    settings = Settings(email="t@example.com", password="secret")
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), Profile(full_name="T", current_location=home), settings)


@pytest.mark.parametrize("question, home, expected", [
    ("Are you currently living in Delhi/ NCR ?", "Indore, India", "No"),
    ("Are you currently living in Delhi/ NCR ?", "Gurugram, Haryana", "Yes"),
    ("Are you currently living in Delhi/ NCR ?", "Noida", "Yes"),
    ("Are you based out of Pune?", "Pune, Maharashtra", "Yes"),
    ("Are you based in Bengaluru?", "Bangalore", "Yes"),
    ("Are you from Mumbai?", "Indore, India", "No"),
    ("Do you currently reside in Hyderabad or Chennai?", "Chennai", "Yes"),
])
def test_where_you_live_answers_yes_or_no_from_current_location(question, home, expected):
    picked = _engine(home).resolve(question, options=["Yes", "No"])
    assert picked.answer is not None, "abstained on %r" % question
    assert (picked.answer.text, picked.answer.grounded_in) == (expected, "current_location")


def test_without_choices_the_word_itself_is_the_answer():
    assert _engine().resolve("Are you currently living in Indore?").answer.text == "Yes"


def test_a_relocation_question_is_left_to_the_relocation_rule():
    picked = _engine().resolve("Are you located in Pune or willing to relocate?", options=["Yes", "No"])
    assert picked.answer is None or picked.answer.grounded_in != "current_location"


def test_no_known_home_means_no_guess():
    picked = _engine(home="").resolve("Are you currently living in Pune?", options=["Yes", "No"])
    assert picked.answer is None
