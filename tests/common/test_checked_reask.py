"""A refused reply is asked again with its exact errors, once, instead of being dropped.

The validate-then-reask loop of instructor (567-labs/instructor). Before it, an
option the model paraphrased or a job it left out of a batch cost the question
or the job outright.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import llm
from common.models import JobPosting, Profile


class _Scripted:
    """Answers each complete_json call with the next reply, and keeps the prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


def _profile():
    return Profile(full_name="A B", notice_period_days=30, skills=["Python"])


def test_a_paraphrased_option_is_corrected_on_the_second_try():
    client = _Scripted(
        {"can_answer": True, "answer": "thirty days", "grounded_in": "notice_period_days", "confidence": 0.9},
        {"can_answer": True, "answer": "30 days", "grounded_in": "notice_period_days", "confidence": 0.9},
    )
    resolution = llm.resolve_answer(client, _profile(), "Notice period?", options=["15 days", "30 days"])
    assert resolution.answer is not None and resolution.answer.text == "30 days"
    assert len(client.prompts) == 2
    assert "copy one of these options exactly" in client.prompts[1]
    assert "thirty days" in client.prompts[1]


def test_an_abstention_is_accepted_without_asking_again():
    client = _Scripted({"can_answer": False, "answer": "not in facts", "grounded_in": "", "confidence": 0})
    resolution = llm.resolve_answer(client, _profile(), "Blood group?")
    assert resolution.answer is None
    assert len(client.prompts) == 1


def test_a_reply_still_wrong_after_the_retry_is_refused_by_the_usual_checks():
    wrong = {"can_answer": True, "answer": "45", "grounded_in": "made_up_key", "confidence": 0.9}
    client = _Scripted(dict(wrong), dict(wrong))
    resolution = llm.resolve_answer(client, _profile(), "Notice period?")
    assert resolution.answer is None
    assert len(client.prompts) == 2


def test_a_job_left_out_of_a_batch_is_asked_for_again():
    jobs = [JobPosting(job_id=i, url="", title="Engineer", company="X") for i in ("j1", "j2")]
    client = _Scripted(
        {"jobs": [{"job_id": "j1", "score": 80, "verdict": "strong", "reasons": []}]},
        {"jobs": [{"job_id": "j1", "score": 80, "verdict": "strong", "reasons": []},
                  {"job_id": "j2", "score": 40, "verdict": "weak", "reasons": []}]},
    )
    scores = llm.score_jobs(client, _profile(), jobs)
    assert set(scores) == {"j1", "j2"}
    assert "j2" in client.prompts[1]


def test_a_stray_selection_is_corrected():
    client = _Scripted(
        {"selected": ["python"], "grounded_in": "skills", "confidence": 0.9},
        {"selected": ["Python"], "grounded_in": "skills", "confidence": 0.9},
    )
    chosen, _ = llm.resolve_selection(client, _profile(), "Which do you use?", ["Python 3", "Java"])
    assert len(client.prompts) == 2
    assert chosen is None  # "Python" is still not an option; the caller's checks keep refusing it
