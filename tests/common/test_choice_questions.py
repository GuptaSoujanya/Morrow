"""Single-choice and multi-choice screening questions must both work.

From the run of 5 October: "Will you attend the walk-in?" and "Salutation"
abstained with llm_answer_not_in_options although the facts were present, and
an Ai ML Engineer role stalled for thirty seconds with no record of what the
drawer contained. _handle_checkbox could also only ever tick one box, so a
genuine select-all-that-apply question was unanswerable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import llm
from common.answers import AnswerEngine
from common.ledger import Ledger
from common.models import Profile, Settings


class _Client:
    """Returns a canned JSON payload, like the CLI backend would."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.payload


def _profile():
    return Profile(full_name="T", total_experience_years=3,
                   current_location="Gurugram", skills=["Python", "SQL"])


# ---------- the empty-options bug ----------

def test_an_empty_options_list_does_not_block_every_answer():
    """The walk-in failure: options scraped empty, so nothing could match."""
    client = _Client({"can_answer": True, "answer": "No, cannot attend walk-in drives",
                      "grounded_in": "current_location", "confidence": 0.9})
    resolution = llm.resolve_answer(client, _profile(),
                                    "Will you attend the walk-in?", options=[])
    assert not resolution.abstained, "abstained with reason %r" % resolution.reason
    assert resolution.answer.text.startswith("No")


@pytest.mark.parametrize("blank", [["", ""], [" ", "  "], [""]])
def test_blank_option_labels_count_as_no_options(blank):
    """handle_radio builds options from label text, which paints late.

    A list of blank strings is truthy, so it passed the empty-list guard: the
    model was handed two blank choices, answered in prose, and nothing matched.
    Three applications were abandoned this way on 7 October with answers that
    plainly meant one of the choices.
    """
    client = _Client({"can_answer": True, "answer": "No, cannot attend walk-in drives",
                      "grounded_in": "current_location", "confidence": 0.9})
    resolution = llm.resolve_answer(client, _profile(),
                                    "Will you attend the walk-in?", options=blank)
    assert not resolution.abstained, "abstained with %r" % resolution.reason
    assert '"options"' not in client.prompts[0], (
        "blank choices were still offered to the model"
    )


def test_real_options_are_still_matched_exactly():
    client = _Client({"can_answer": True, "answer": "Gurugram",
                      "grounded_in": "current_location", "confidence": 0.9})
    resolution = llm.resolve_answer(client, _profile(), "Where do you live?",
                                    options=["Pune", "Gurugram"])
    assert resolution.answer.text == "Gurugram"


def test_an_answer_outside_real_options_still_abstains():
    client = _Client({"can_answer": True, "answer": "Mumbai",
                      "grounded_in": "current_location", "confidence": 0.9})
    resolution = llm.resolve_answer(client, _profile(), "Where do you live?",
                                    options=["Pune", "Gurugram"])
    assert resolution.abstained
    assert resolution.reason == "llm_answer_not_in_options"


# ---------- multi-select ----------

def test_several_options_can_be_selected():
    client = _Client({"selected": ["Python", "SQL"],
                      "grounded_in": "skills", "confidence": 0.9})
    chosen, reason = llm.resolve_selection(
        client, _profile(), "Which do you know?", ["Python", "Java", "SQL"])
    assert chosen == ["Python", "SQL"], reason


def test_selections_come_back_exactly_as_rendered():
    """The caller matches these against controls, so casing must be the page's."""
    client = _Client({"selected": ["python", "sql"],
                      "grounded_in": "skills", "confidence": 0.9})
    chosen, _ = llm.resolve_selection(
        client, _profile(), "Which do you know?", ["Python", "SQL", "Java"])
    assert chosen == ["Python", "SQL"]


def test_invented_selections_are_rejected():
    client = _Client({"selected": ["Rust", "COBOL"],
                      "grounded_in": "skills", "confidence": 0.9})
    chosen, reason = llm.resolve_selection(
        client, _profile(), "Which do you know?", ["Python", "SQL"])
    assert chosen is None
    assert reason == "llm_selection_not_in_options"


def test_choosing_nothing_is_reported_separately():
    client = _Client({"selected": [], "grounded_in": "skills", "confidence": 0.9})
    chosen, reason = llm.resolve_selection(
        client, _profile(), "Which do you know?", ["Haskell", "Erlang"])
    assert chosen is None
    assert reason == "llm_selected_nothing"


def test_an_ungrounded_selection_is_rejected():
    client = _Client({"selected": ["Python"], "grounded_in": "", "confidence": 0.9})
    chosen, reason = llm.resolve_selection(
        client, _profile(), "Which do you know?", ["Python"])
    assert chosen is None
    assert reason == "ungrounded"


def test_no_options_means_no_selection_attempt():
    client = _Client({"selected": ["x"], "grounded_in": "skills", "confidence": 1.0})
    chosen, reason = llm.resolve_selection(client, _profile(), "Which?", [])
    assert chosen is None
    assert reason == "no_options_rendered"
    assert client.prompts == [], "should not call the model with nothing to choose from"


# ---------- the engine records both kinds of failure ----------

def test_resolve_many_records_an_unanswerable_question(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(email="t@e.com", password="p")
    engine = AnswerEngine(Ledger(":memory:"),
                          _Client({"selected": [], "grounded_in": "skills",
                                   "confidence": 0.9}),
                          _profile(), settings)
    chosen, reason = engine.resolve_many("Which apply?", ["Haskell"])
    assert chosen is None and reason == "llm_selected_nothing"
    written = (tmp_path / "data/worklists/unanswered_questions.md").read_text()
    assert "Which apply?" in written
    assert "llm_selected_nothing" in written


def test_an_option_mismatch_is_recorded_as_such_not_as_an_abstain(tmp_path, monkeypatch):
    """"Could not answer" and "answer did not match the page" are different."""
    monkeypatch.chdir(tmp_path)
    engine = AnswerEngine(Ledger(":memory:"), _Client({}), _profile(),
                          Settings(email="t@e.com", password="p"))
    engine.record_option_mismatch("Salutation", "Mr", ["Mr.", "Ms."])
    written = (tmp_path / "data/worklists/unanswered_questions.md").read_text()
    assert "Salutation" in written
    assert "not_among_rendered_options" in written
    assert "options: ['Mr.', 'Ms.']" in written


def test_the_apply_wait_requires_a_visible_control():
    """A hidden duplicate must not satisfy the wait.

    A live PwC posting reported "no actionable apply control" because the page
    ships two #apply-button elements, one of them hidden. _apply_controls_present
    checked DOM presence, so it matched instantly and the wait never waited;
    classification then looked for a visible control and found only the footer.
    """
    import inspect

    from naukri_bot import apply as apply_module

    source = inspect.getsource(apply_module._apply_controls_present)
    assert "_find_visible" in source, (
        "the wait must require visibility, or a hidden element ends it early"
    )
    assert "driver.find_elements" not in source, (
        "a bare presence check reintroduces the bug"
    )
