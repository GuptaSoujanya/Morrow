"""Years-of-experience questions must not depend on the LLM's cooperation.

resolve_answer instructs the model to answer only from the supplied facts and
never to infer, so it correctly refuses to state years of experience in a
technology the resume never mentions. Writing the instruction into
profile.yaml does not help: a directive inside the data does not outrank the
prompt, and a live check confirmed the model still abstained on GCP,
AI Security and Kubernetes. The policy therefore lives in code, where it is
the user's explicit, configurable choice.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot.answers import AnswerEngine
from naukri_bot.ledger import Ledger
from naukri_bot.models import Profile, Settings


class _NoLLM:
    """Forces the deterministic path, so nothing here depends on a live model."""

    def available(self):
        return False


def _engine(years, **overrides):
    values = dict(
        email="t@example.com",
        password="secret",
        default_skill_experience_years=years,
        total_experience_years=3,
        notice_period_days=30,
        current_location="Gurugram",
    )
    values.update(overrides)
    settings = Settings(**{k: v for k, v in values.items() if k in Settings.__annotations__})
    profile = Profile(
        full_name="T",
        total_experience_years=3,
        notice_period_days=30,
        current_location="Gurugram",
    )
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), profile, settings)


@pytest.mark.parametrize(
    "question",
    [
        "How many years of experience do you have in GCP?",
        "How many years of experience do you have in AI Security?",
        "How many years of experience do you have in Kubernetes?",
        "How many years of exp do you have in Python and AI?",
        "Relevant Experience (In Years)",
        "How many yrs of experience in Bedrock?",
    ],
)
def test_any_named_skill_answers_the_configured_years(question):
    resolution = _engine(3.0).resolve(question)
    assert not resolution.abstained, "abstained on %r" % question
    assert resolution.answer.text == "3"
    assert resolution.answer.grounded_in == "default_skill_experience_years"


def test_zero_disables_the_rule():
    """Opt-in: unset, these questions abstain exactly as they did before."""
    resolution = _engine(0.0).resolve("How many years of experience do you have in GCP?")
    assert resolution.abstained


@pytest.mark.parametrize(
    "question,expected_grounding",
    [
        # These match the years regex AND a specific mapping, so they are the
        # only cases that can actually detect the rule shadowing a real fact.
        ("How many years of total experience do you have?", "total_experience_years"),
        ("How many years of overall experience do you have?", "total_experience_years"),
        ("Total Experience (In Years)", "total_experience_years"),
        ("What is your overall experience?", "total_experience_years"),
        ("What is your notice period?", "notice_period_days"),
        ("What is your current location?", "current_location"),
    ],
)
def test_specific_facts_still_win(question, expected_grounding):
    """The rule sits behind the specific mappings and must not shadow them."""
    resolution = _engine(3.0).resolve(question)
    assert not resolution.abstained
    assert resolution.answer.grounded_in == expected_grounding


def test_options_are_matched_exactly_or_deferred():
    engine = _engine(3.0)
    picked = engine.resolve("How many years of experience in Java?", options=["1", "2", "3", "4+"])
    assert picked.answer.text == "3"

    # No option corresponds to 3, so the rule must defer rather than invent one.
    deferred = _engine(3.0).resolve(
        "How many years of experience in Java?", options=["0-1", "5-10"]
    )
    assert deferred.abstained, "rule should defer, not force a mismatched option"
