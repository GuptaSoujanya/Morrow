"""The judged pass: what the bot may infer when no fact answers a screening question.

A question with no stated answer used to skip the whole job. The judge may draw
only honest inferences (0 years for a skill named nowhere, N/A for a false
premise, Other when the list lacks her value), must quote any positive claim,
never types a number her files do not contain, and leaves legal and identity
questions to her.
"""

import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import assist, llm, report
from common.answers import AnswerEngine, AnswerBook
from common.ledger import Ledger
from common.models import AnswerMode, AnswerSource, Profile, Settings


RESUME = (
    "SOFTWARE ENGINEER, Ethara AI, Mar 2024 - Present. Built LangChain pipelines "
    "that benchmark OpenAI, Gemini and Claude agents."
)
PROFILE_YAML = "full_name: T\ntotal_experience_years: 2.5\ncurrent_location: Indore\n"
ANSWERS = "Q: Have you worked at Info Edge before?\nA: No\n\nQ: Preferred work location\nA: Pune\n"
ABSTAIN = {"can_answer": False, "answer": "not in the facts", "grounded_in": "", "confidence": 0}


class _Brain:
    """Answers the strict pass with an abstain, then gives the judged response."""

    def __init__(self, *judged):
        self.responses = []
        for item in judged:
            self.responses += [ABSTAIN, item]
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else None


def _judged(answer, reason="CrewAI is named nowhere in her files", evidence="", depends=False):
    return {"can_answer": True, "answer": answer, "reason": reason, "evidence": evidence,
            "depends_on_posting": depends}


def _engine(tmp_path, brain, **overrides):
    (tmp_path / "data" / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "inputs" / "answers.txt").write_text(ANSWERS, encoding="utf-8")
    (tmp_path / "data" / "inputs" / "profile.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    values = dict(email="t@example.com", password="secret", report_dir=str(tmp_path / "reports"))
    values.update(overrides)
    settings = Settings(**values)
    profile = Profile(full_name="T", total_experience_years=2.5, current_location="Indore", resume_text=RESUME)
    engine = AnswerEngine(Ledger(":memory:"), brain, profile, settings)
    engine.set_job_context(type("Job", (), {"title": "AI Engineer", "company": "Acme", "location": "Pune"})())
    return engine


def _answers(tmp_path):
    return (tmp_path / "data" / "inputs" / "answers.txt").read_text(encoding="utf-8")


def _judgements(engine):
    return [record for record in assist.read_changes(engine.settings) if record.get("kind") == "judged"]


QUESTION = "How many years of experience do you have in CrewAI?"


def test_a_skill_named_nowhere_is_answered_0_and_saved_for_her_to_check(tmp_path):
    brain = _Brain(_judged("0"))
    engine = _engine(tmp_path, brain)

    resolution = engine.resolve(QUESTION)

    assert not resolution.abstained
    assert resolution.answer.text == "0"
    assert resolution.answer.source == AnswerSource.LLM
    text = _answers(tmp_path)
    assert "Q: %s\nA: 0\n" % QUESTION in text
    assert "# AI judged this on %s while applying to AI Engineer at Acme: CrewAI is named nowhere" % (
        datetime.now().strftime("%Y-%m-%d")) in text
    assert "Change it if it is wrong." in text
    [record] = _judgements(engine)
    assert record["value"] == "0" and record["file"].endswith("answers.txt")

    asked = len(brain.prompts)
    assert engine.resolve(QUESTION).answer.text == "0"
    assert len(brain.prompts) == asked, "the saved answer is read from the file, not judged again"


def test_a_question_she_left_blank_is_filled_in_place(tmp_path):
    brain = _Brain(_judged("0"))
    engine = _engine(tmp_path, brain)
    with open(engine.book.path, "a", encoding="utf-8") as handle:
        handle.write("\n# 2026-10-10 | llm_abstained\nQ: %s\nA:\n" % QUESTION)

    engine.resolve(QUESTION)

    text = _answers(tmp_path)
    assert text.count("Q: %s" % QUESTION) == 1
    assert "Q: %s\nA: 0" % QUESTION in text


def test_a_skill_in_her_resume_gets_years_backed_by_a_quote(tmp_path):
    brain = _Brain(_judged("2.5", reason="LangChain is in her current role",
                           evidence="Built LangChain pipelines that benchmark"))
    engine = _engine(tmp_path, brain)

    resolution = engine.resolve("How many years of experience do you have in LangChain?")

    assert resolution.answer.text == "2.5"


@pytest.mark.parametrize(
    "question, response, why",
    [
        (QUESTION, _judged("2", evidence="Built CrewAI agents daily"), "the claim is not a quote"),
        (QUESTION, _judged("2.5", evidence="Built LangChain pipelines that benchmark"), "CrewAI is named nowhere"),
        ("How many years of experience do you have in LangChain?",
         _judged("4", evidence="Built LangChain pipelines that benchmark"), "4 is in none of her files"),
        ("How many backlogs do you have?", _judged("45", evidence="total_experience_years: 2.5"), "invented number"),
        ("Rate your Python", _judged("x" * 120, evidence="Built LangChain pipelines that benchmark"), "too long"),
        ("How many backlogs do you have?", _judged("Yes", reason=""), "no reason"),
    ],
)
def test_refused_judgements_leave_the_question_for_her(tmp_path, question, response, why):
    engine = _engine(tmp_path, _Brain(response))

    resolution = engine.resolve(question)

    assert resolution.abstained, why
    assert "Q: %s\nA:\n" % question in _answers(tmp_path)
    assert _judgements(engine) == []


def test_more_years_than_her_whole_career_are_refused(tmp_path):
    brain = _Brain(_judged("3", evidence="Built LangChain pipelines that benchmark"))
    engine = _engine(tmp_path, brain)
    with open(engine.book.path, "a", encoding="utf-8") as handle:
        handle.write("\nQ: Years since graduation\nA: 3\n")

    assert engine.resolve("How many years of experience do you have in LangChain?").abstained


def test_a_false_premise_gets_na(tmp_path):
    question = "If Yes, Please share the Employee Code"
    engine = _engine(tmp_path, _Brain(_judged("N/A", reason="her answers say she never worked at Info Edge")))

    assert engine.resolve(question).answer.text == "N/A"
    assert "Q: %s\nA: N/A" % question in _answers(tmp_path)


def test_a_pick_from_one_forms_list_is_used_but_not_saved(tmp_path):
    question = "Current location"
    engine = _engine(tmp_path, _Brain(_judged("Other", reason="Indore is not in the list")))

    resolution = engine.resolve(question, options=["Bengaluru", "Pune", "Other"])

    assert resolution.answer.text == "Other"
    assert "Q: Current location" not in _answers(tmp_path)
    [record] = _judgements(engine)
    assert record["file"] == "this application only"


def test_an_option_the_form_does_not_offer_is_refused(tmp_path):
    engine = _engine(tmp_path, _Brain(_judged("Indore", evidence="current_location: Indore")))

    assert engine.resolve("Current location", options=["Bengaluru", "Pune"]).abstained


def test_an_answer_resting_on_the_posting_is_not_saved(tmp_path):
    question = "Are you comfortable attending the walk-in?"
    engine = _engine(tmp_path, _Brain(_judged("Yes", reason="the walk-in is in Pune, which she prefers",
                                              evidence="Preferred work location\nA: Pune", depends=True)))

    assert engine.resolve(question).answer.text == "Yes"
    assert question not in _answers(tmp_path)


@pytest.mark.parametrize(
    "question",
    [
        "What is your gender?",
        "Will you now or in the future require visa sponsorship?",
        "Are you legally authorized to work in the United States?",
        "Please share your PAN number",
        "Why do you want to join Acme?",
        "Have you ever been convicted of a criminal offence?",
    ],
)
def test_legal_identity_and_essay_questions_are_never_judged(tmp_path, question):
    brain = _Brain(_judged("No", reason="guess"))
    engine = _engine(tmp_path, brain)

    assert engine.resolve(question).abstained
    assert all("HER FACTS" not in prompt for prompt in brain.prompts)


@pytest.mark.parametrize("overrides", [{"judge_answers": False}, {"answer_mode": AnswerMode.ASK}])
def test_the_judge_can_be_switched_off(tmp_path, overrides):
    brain = _Brain(_judged("0"))
    engine = _engine(tmp_path, brain, **overrides)

    assert engine.resolve(QUESTION).abstained
    assert all("HER FACTS" not in prompt for prompt in brain.prompts)


def test_the_judge_sees_her_resume_profile_answers_and_the_job(tmp_path):
    brain = _Brain(_judged("0"))
    engine = _engine(tmp_path, brain)

    engine.resolve(QUESTION)

    prompt = brain.prompts[-1]
    assert "Built LangChain pipelines" in prompt
    assert "total_experience_years: 2.5" in prompt
    assert "Have you worked at Info Edge before?" in prompt
    assert "company: Acme" in prompt
    assert json.dumps(QUESTION) in prompt


@pytest.mark.parametrize(
    "answer, nothing",
    [("0", True), ("0 years", True), ("0-1 years", True), ("None", True), ("N/A", True),
     ("No", True), ("Other", True), ("Less than 1 year", True), ("2.5", False), ("Yes", False),
     ("Noida", False), ("1-3 years", False)],
)
def test_claims_nothing(answer, nothing):
    assert llm.claims_nothing(answer) is nothing


def test_the_report_lists_judged_answers(tmp_path):
    engine = _engine(tmp_path, _Brain(_judged("0"), _judged("Other", reason="Indore is not listed")),
                     course_dir=str(tmp_path / "no-course"))
    engine.resolve(QUESTION)
    engine.resolve("Current location", options=["Pune", "Other"])

    now = datetime.now()
    text = report.write_daily_report(engine.settings, now.date(), now).read_text(encoding="utf-8")

    assert "### Answered by judgement" in text
    assert "%s: **0** (CrewAI is named nowhere in her files; saved in answers.txt)" % QUESTION in text
    assert "Current location: **Other** (Indore is not listed; this application only)" in text


def test_the_book_reads_the_judged_answer_like_any_other(tmp_path):
    engine = _engine(tmp_path, _Brain(_judged("0")))
    engine.resolve(QUESTION)

    assert AnswerBook(engine.book.path).answer_for(QUESTION) == "0"
