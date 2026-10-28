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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.answers import AnswerEngine
from common.ledger import Ledger
from common.models import Profile, Settings


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


def _resume_engine(**settings_overrides):
    values = dict(email="t@example.com", password="secret", skill_years_from_total=True, total_experience_years=3)
    values.update(settings_overrides)
    settings = Settings(**{k: v for k, v in values.items() if k in Settings.__annotations__})
    profile = Profile(full_name="T", total_experience_years=3, skills=["Python", "LangChain", "Generative AI", "C++"])
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), profile, settings)


@pytest.mark.parametrize(
    "question",
    [
        "How many years of experience do you have in Python?",
        "How many years of hands-on experience do you have in Python backend development?",
        "How many years of experience do you have in Generative Ai?",
        # "language" is a filler word elsewhere; here it is part of a name the alias table knows.
        "How many years of experience do you have in Large Language Model(s)?",
        "How many years of experience do you have in LLMs?",
        "Years of experience with C++",
    ],
)
def test_a_listed_skill_answers_with_total_experience_when_chosen(question):
    resolution = _resume_engine().resolve(question)
    assert resolution.answer is not None
    assert resolution.answer.text == "3"
    assert resolution.answer.grounded_in.endswith("total_experience_years")


@pytest.mark.parametrize("question", ["How many years of experience do you have in Kubernetes?",
                                      "How many years of experience do you have in Frontend Development?"])
def test_a_skill_not_on_the_resume_still_abstains(question):
    assert _resume_engine().resolve(question).answer is None


def test_the_narrow_rule_is_off_unless_chosen():
    assert _resume_engine(skill_years_from_total=False).resolve(
        "How many years of experience do you have in Python?").answer is None


def _own_resume_engine():
    """The skills list as the resume extraction writes it: long, specific lines."""
    settings = Settings(**{k: v for k, v in dict(
        email="t@example.com", password="secret", skill_years_from_total=True, total_experience_years=3,
    ).items() if k in Settings.__annotations__})
    profile = Profile(full_name="T", total_experience_years=3, skills=[
        "Python", "ML model evaluation", "multi-agent orchestration",
        "LLM evaluation (CodeBLEU, n-gram similarity, dataflow match, human-eval rubrics)",
        "AWS Bedrock", "microservices (FastAPI)", "CI/CD pipelines", "NLP", "React.js", "C++",
    ])
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), profile, settings)


@pytest.mark.parametrize(
    "question",
    [
        # Each of these abandoned a Naukri or Hirist application on 2026-10-28: the skill is on the
        # resume under another name, or wrapped in words no skills list repeats.
        "How many years of experience do you have in Generative Ai?",
        "How many years of experience do you have in LLM?",
        "How many years of experience do you have in AWS?",
        "How many years of experience do you have in Artificial Intelligence?",
        "How many years of experience do you have in Aiml?",
        "How many years of hands-on experience do you have in Microservices Architecture?",
        "How many years of experience do you have in Agent to Agent?",
        "How many years relevant experience in ML and orchestration frameworks?",
        "How many years of experience do you have in CI/CD?",
        "How many years of experience do you have in React?",
        "Years of experience with C++",
    ],
)
def test_the_resumes_own_skills_answer_under_the_names_recruiters_use(question):
    resolution = _own_resume_engine().resolve(question)
    assert resolution.answer is not None, "abstained on %r" % question
    assert resolution.answer.text == "3"
    assert resolution.answer.grounded_in.startswith("skills:")


@pytest.mark.parametrize(
    "question",
    [
        "how many years you have exp in health care domain",
        "How many years of experience do you have in platform engineer?",
        "How many years of experience do you have in Kubernetes?",
        "How many years of experience do you have in Django?",
        # One listed skill and one not: a single number would claim years in the missing one.
        "How many years of experience do you have in Python and Kubernetes?",
        "How many years of experience do you have in Machine Learning?",  # ML is not LLM work
    ],
)
def test_names_the_resume_does_not_cover_still_abstain(question):
    engine = _own_resume_engine()
    engine.profile.skills = [s for s in engine.profile.skills if s != "ML model evaluation"]
    assert engine.resolve(question).answer is None, "answered %r" % question


def _salary_engine():
    settings = Settings(email="t@example.com", password="secret")
    profile = Profile(full_name="T", current_ctc_lpa=16, expected_ctc_lpa=20, total_experience_years=3,
                      current_location="Indore, India")
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), profile, settings)


@pytest.mark.parametrize("question, answer", [
    ("What is your current annual salary? (in LPA, e.g., 45)", "16"),
    ("Current CTC", "16"),
    ("What is your present salary?", "16"),
    ("Expected annual salary in LPA", "20"),
    ("What is your expected compensation?", "20"),
])
def test_salary_asked_with_a_word_in_between_is_still_answered_from_the_facts(question, answer):
    """Hirist asks 'current annual salary'; the plain 'current salary' phrase missed it."""
    resolution = _salary_engine().resolve(question)
    assert not resolution.abstained, "abstained on %r" % question
    assert resolution.answer.text == answer
