"""Saved model answers cannot become evidence for another model's claims."""
from pathlib import Path

import pytest

from common import assist
from common.answer_learning import annotation
from common.answers import AnswerBook
from common.models import Profile, Settings
from sites_bot import browser_agent


def _files(tmp_path, options=None):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    question, answer = "How long have you used Rust?", "Nine years of Rust"
    record = annotation(question, answer, "test-facts", options=options)
    path = inputs / "answers.txt"
    path.write_text(
        "Q: What is your notice period?\nA: 15 days\n\n"
        + record + "\nQ: " + question + "\nA: " + answer + "\n\n"
        "Q: Can you work with Rust?\nA:\n",
        encoding="utf-8",
    )
    profile_path = inputs / "profile.yaml"
    profile_path.write_text("full_name: Test Candidate\nnotice_period_days: 15\n", encoding="utf-8")
    return (Settings(data_dir=str(inputs), profile_path=str(profile_path), report_dir=str(tmp_path / "reports")),
            Profile(full_name="Test Candidate", notice_period_days=15, resume_text="Python engineer."),
            question, answer)


@pytest.mark.parametrize("options", [None, ["Nine years of Rust", "None"]])
def test_automatically_learned_answers_are_not_evidence_for_other_models(tmp_path, options):
    settings, profile, question, answer = _files(tmp_path, options)
    book = AnswerBook(str(Path(settings.data_dir) / "answers.txt"))

    assert ([question], answer) in book.entries, "The saved answer stays editable and reportable"
    evidence = assist.sources(settings, profile, book)["answers"]
    browser_facts = browser_agent.facts_text(profile, settings)
    assert answer not in evidence and question not in evidence
    assert answer not in browser_facts and question not in browser_facts
    assert "15 days" in evidence and "15 days" in browser_facts


def test_fill_blanks_rejects_a_quote_that_exists_only_in_a_learned_answer(tmp_path):
    settings, profile, _, answer = _files(tmp_path)

    class Client:
        prompts = []

        def available(self):
            return True

        def complete_json(self, prompt, schema):
            self.prompts.append(prompt)
            return {"items": [{"id": "q:can you work with rust", "answer": "Yes",
                               "source": "answers", "evidence": "A: " + answer}]}

    client = Client()
    assert assist.fill_blanks(settings, profile, client, write=False) == []
    assert len(client.prompts) == 1 and answer not in client.prompts[0]


def test_editing_a_learned_answer_makes_the_new_value_user_evidence(tmp_path):
    settings, profile, question, answer = _files(tmp_path)
    path = Path(settings.data_dir) / "answers.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("A: " + answer, "A: One year of Rust"), encoding="utf-8")
    book = AnswerBook(str(path))

    evidence = assist.sources(settings, profile, book)["answers"]
    browser_facts = browser_agent.facts_text(profile, settings)
    assert "One year of Rust" in evidence and question in evidence
    assert "One year of Rust" in browser_facts and question in browser_facts
    assert answer not in evidence and answer not in browser_facts
