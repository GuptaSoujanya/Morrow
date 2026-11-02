"""A follow-up question sees the form's earlier answers; a refused answer is corrected from the site's error.

Both from beatwad/LinkedIn-AI-Job-Applier-Ultimate. "If yes, please name it." means
nothing without the question before it, and "Enter a whole number between 0 and
30" says exactly what shape "30 days" should have been.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import answers as answers_module
from common.models import JobPosting, Profile, Settings


class _Ledger:
    def get_answer(self, question, fingerprint):
        return None

    def save_answer(self, *args, **kwargs):
        pass


class _Client:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.settings = Settings(email="t@example.com", password="p")

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _engine(client, tmp_path):
    settings = Settings(email="t@example.com", password="p")
    profile = Profile(full_name="T", extra_facts={"github_project": "Yes, a RAG evaluation harness", "notice": "30 days"})
    engine = answers_module.AnswerEngine(_Ledger(), client, profile, settings)
    engine.set_job_context(JobPosting(job_id="1", url="u", title="Engineer", company="Acme"))
    return engine


def _request(prompt):
    return json.loads(prompt.split("Input: ", 1)[1].split("\n", 1)[0])


def test_a_follow_up_is_shown_the_answers_before_it(tmp_path):
    client = _Client(
        {"can_answer": True, "answer": "Yes", "grounded_in": "github_project", "confidence": 0.9},
        {"can_answer": True, "answer": "A RAG evaluation harness", "grounded_in": "github_project", "confidence": 0.9},
    )
    engine = _engine(client, tmp_path)
    engine.resolve("Have you published an open-source project?", ["Yes", "No"], "radio")
    engine.resolve("If yes, please name it.")
    assert "prior_answers" not in _request(client.prompts[0])
    assert _request(client.prompts[1])["prior_answers"] == {"Have you published an open-source project?": "Yes"}


def test_a_new_job_starts_with_no_earlier_answers(tmp_path):
    client = _Client({"can_answer": True, "answer": "Yes", "grounded_in": "github_project", "confidence": 0.9})
    engine = _engine(client, tmp_path)
    engine.resolve("Have you published an open-source project?", ["Yes", "No"], "radio")
    engine.set_job_context(JobPosting(job_id="2", url="u", title="Engineer", company="Beta"))
    assert engine.form_answers == {}


def test_a_refused_answer_is_rewritten_in_the_shape_the_error_asks(tmp_path):
    client = _Client({"can_answer": True, "answer": "30", "grounded_in": "notice", "confidence": 0.9})
    engine = _engine(client, tmp_path)
    assert engine.correct("Notice period", "30 days", "Enter a whole number between 0 and 90") == "30"
    sent = _request(client.prompts[0])
    assert sent["site_rejected"] == {"answer": "30 days", "error": "Enter a whole number between 0 and 90"}


def test_no_correction_when_the_model_repeats_the_refused_answer(tmp_path):
    client = _Client({"can_answer": True, "answer": "30 days", "grounded_in": "notice", "confidence": 0.9})
    assert _engine(client, tmp_path).correct("Notice period", "30 days", "Invalid") is None
