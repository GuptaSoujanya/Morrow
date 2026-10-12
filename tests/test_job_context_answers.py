"""A question with no place in it still has one: the posting's.

"Will you attend the walk-in?" cost three applications in one run. The
candidate attends walk-ins in Delhi-NCR only, so neither Yes nor No is
groundable in the profile alone and the model rightly abstained -- but the
walk-in is at the employer's location, which the bot knew all along and never
passed on.

The trap this opens is the answer cache. It is keyed on the question text and
the profile fingerprint, neither of which changes between jobs, so "Yes" cached
for a Noida employer would be replayed to a Chennai one. An answer that leaned
on the posting must not be cached.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import answers as answers_module
from common import llm
from common.models import (
    Answer,
    AnswerResolution,
    ApplyStatus,
    JobPosting,
    Profile,
    Settings,
)

QUESTION = "Will you attend the walk-in?"


class _Ledger:
    def __init__(self):
        self.saved = []
        self.cached = None

    def get_answer(self, question, fingerprint):
        return self.cached

    def save_answer(self, *args, **kwargs):
        self.saved.append((args, kwargs))


class _Client:
    """Records the prompt and answers with whatever it is told to."""

    def __init__(self, response):
        self.response = response
        self.prompts = []
        self.settings = Settings(email="t@example.com", password="p")

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.response


def _profile():
    return Profile(
        full_name="T",
        email="t@example.com",
        phone="0",
        extra_facts={"attend_walk_in": "Yes only in Delhi-NCR"},
    )


def _engine(client, ledger=None):
    return answers_module.AnswerEngine(
        ledger or _Ledger(),
        client,
        _profile(),
        Settings(email="t@example.com", password="p"),
    )


def _job(location="Noida", title="AI Engineer", company="Acme"):
    return JobPosting(
        job_id="1", url="u", title=title, company=company, location=location
    )


def test_the_posting_location_reaches_the_model():
    """Without it the model has nothing to resolve an unnamed city against."""
    client = _Client({"can_answer": True, "answer": "Yes",
                      "grounded_in": "attend_walk_in, job_location",
                      "confidence": 0.9})
    engine = _engine(client)
    engine.set_job_context(_job(location="Noida"))

    engine.resolve(QUESTION, options=["Yes", "No"])

    # The quoted form is the JSON key in the request payload; the bare word
    # also appears in the standing instruction, so it proves nothing.
    assert '"job_location"' in client.prompts[0]
    assert "Noida" in client.prompts[0]


def test_an_answer_resting_on_the_posting_is_not_cached():
    """Cached, a Noida yes would be replayed to a Chennai walk-in."""
    ledger = _Ledger()
    client = _Client({"can_answer": True, "answer": "Yes",
                      "grounded_in": "attend_walk_in, job_location",
                      "confidence": 0.9})
    engine = _engine(client, ledger)
    engine.set_job_context(_job(location="Noida"))

    resolution = engine.resolve(QUESTION, options=["Yes", "No"])

    assert resolution.answer.text == "Yes"
    assert ledger.saved == [], "cached a per-posting answer"


def test_an_answer_from_the_profile_alone_is_still_cached():
    """Only posting-dependent answers lose caching, not every answer."""
    ledger = _Ledger()
    client = _Client({"can_answer": True, "answer": "Yes",
                      "grounded_in": "attend_walk_in", "confidence": 0.9})
    engine = _engine(client, ledger)
    engine.set_job_context(_job())

    engine.resolve("Do you attend walk-ins in Delhi?", options=["Yes", "No"])

    assert len(ledger.saved) == 1


def test_the_model_is_told_job_facts_are_not_about_the_candidate():
    """Otherwise the posting's city reads as where the candidate lives."""
    client = _Client({"can_answer": False, "answer": "", "grounded_in": "",
                      "confidence": 0.0})
    llm.resolve_answer(client, _profile(), QUESTION,
                       job_context={"location": "Chennai"})

    prompt = client.prompts[0]
    assert "describes the JOB, not the" in prompt


def test_a_posting_without_a_location_says_so():
    """Leaving the key out makes the question ungroundable and it abstains.

    The candidate answers these by city, so with no city in the question and
    none from the posting the model has nothing to ground on. Stated as a
    value, "not stated" is something the profile can answer about -- and the
    profile answers No, since an unknown city is not Delhi-NCR. Saying it in
    prose instead ("never assume a location") pulled the in-region answers to
    No as well, which is why it is a value and not an instruction.
    """
    client = _Client({"can_answer": True, "answer": "No",
                      "grounded_in": "attend_walk_in, job_location",
                      "confidence": 0.9})

    llm.resolve_answer(client, _profile(), QUESTION,
                       job_context={"title": "AI Engineer"})

    assert llm._LOCATION_NOT_STATED in client.prompts[0]


def test_an_empty_context_also_says_not_stated():
    """apply_to_job sets a context for every job; a bare one still means no city."""
    client = _Client({"can_answer": True, "answer": "No",
                      "grounded_in": "attend_walk_in, job_location",
                      "confidence": 0.9})

    llm.resolve_answer(client, _profile(), QUESTION, job_context={})

    assert llm._LOCATION_NOT_STATED in client.prompts[0]


def test_a_real_location_is_not_overwritten():
    client = _Client({"can_answer": True, "answer": "Yes",
                      "grounded_in": "attend_walk_in, job_location",
                      "confidence": 0.9})

    llm.resolve_answer(client, _profile(), QUESTION,
                       job_context={"location": "Noida"})

    assert "Noida" in client.prompts[0]
    assert llm._LOCATION_NOT_STATED not in client.prompts[0]


def test_no_job_context_adds_no_job_facts():
    """Nothing changes for callers that do not set a posting."""
    client = _Client({"can_answer": False, "answer": "", "grounded_in": "",
                      "confidence": 0.0})
    llm.resolve_answer(client, _profile(), QUESTION)

    assert '"job_location"' not in client.prompts[0]


def test_grounding_in_a_job_fact_verifies():
    """job_* keys must count as named facts or every such answer abstains."""
    client = _Client({"can_answer": True, "answer": "No",
                      "grounded_in": "job_location", "confidence": 0.9})

    resolution = llm.resolve_answer(
        client, _profile(), QUESTION, job_context={"location": "Chennai"}
    )

    assert not resolution.abstained, resolution.reason


def test_apply_tells_the_engine_which_job_it_is_answering_for():
    """The hook is useless if the apply path never calls it."""
    from naukri_bot import apply as apply_module

    seen = []

    class _Engine:
        def set_job_context(self, job):
            seen.append(job.location)

        def resolve(self, question, options=None, field_type="text"):
            return AnswerResolution.resolved(Answer(text="Yes"))

    settings = Settings(email="t@example.com", password="p", dry_run=False)
    job = _job(location="Chennai")

    class _Driver:
        def get(self, url):
            raise RuntimeError("navigation should not be reached in this test")

    apply_module.safe_get = lambda driver, url: False
    result = apply_module.apply_to_job(
        _Driver(), job, _profile(), _Engine(), settings
    )

    assert seen == ["Chennai"]
    assert result.status == ApplyStatus.ERROR
