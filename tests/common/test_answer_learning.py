"""Learning reduces calls while preserving source, option, and job boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from common import answer_events, answer_learning, llm
from common.answers import AnswerBook, AnswerEngine, PER_JOB, parse_answers
from common.ledger import Ledger
from common.models import AnswerMode, AnswerSource, JobPosting, Profile, Settings


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.calls += 1
        return self.responses.pop(0) if self.responses else None


def response(answer="30 days", grounding="notice_period_days"):
    return dict(can_answer=True, answer=answer, grounded_in=grounding, confidence=.95)


def engine(tmp_path, client, **overrides):
    values = dict(data_dir=str(tmp_path / "inputs"), judge_answers=False)
    values.update(overrides)
    profile = Profile(full_name="Test", notice_period_days=30,
                      extra_facts={"editor": "Emacs", "languages": "Python, SQL"})
    return AnswerEngine(Ledger(":memory:"), client, profile, Settings(**values))


def test_new_answer_is_saved_then_reused_for_a_paraphrase_without_model(tmp_path):
    client = Client(response())
    first = engine(tmp_path, client)
    assert first.resolve("How soon can you join?").answer.text == "30 days"
    text = Path(first.book.path).read_text()
    assert "Q: How soon can you join?\nA: 30 days" in text
    assert "# Morrow learned:" in text
    second = engine(tmp_path, client)
    result = second.resolve("What is your notice period?")
    assert result.answer.text == "30 days"
    assert result.answer.source == AnswerSource.DATA
    assert second.book.last_match.matched_question == "How soon can you join?"
    assert client.calls == 1


def test_same_answer_reused_across_runs_without_duplicate_entries(tmp_path):
    client = Client(response())
    first = engine(tmp_path, client)
    first.resolve("How soon can you join?")
    engine(tmp_path, client).resolve("How soon can you join?")
    assert client.calls == 1
    assert Path(first.book.path).read_text().count("Q: How soon can you join?") == 1


def test_choice_answer_never_replays_as_typed_value_or_different_choices(tmp_path):
    client = Client(response("Other", "editor"), response("Emacs", "editor"))
    subject = engine(tmp_path, client)
    question = "Which editor do you use?"
    assert subject.resolve(question, ["Other", "VSCode"]).answer.text == "Other"
    # Choice ordering is irrelevant, but the actual available values are not.
    assert subject.resolve(question, ["VSCode", "Other"]).answer.text == "Other"
    assert subject.resolve(question).answer.text == "Emacs"
    assert client.calls == 2
    assert len(parse_answers(Path(subject.book.path).read_text())) == 2


def test_human_edit_wins_immediately_and_remains_a_source(tmp_path):
    client = Client(response())
    subject = engine(tmp_path, client)
    subject.resolve("How soon can you join?")
    path = Path(subject.book.path)
    path.write_text(path.read_text().replace("A: 30 days", "A: 15 days"))
    assert subject.resolve("How soon can you join?").answer.text == "15 days"
    assert subject.book.source_entries == [(["How soon can you join?"], "15 days")]
    assert client.calls == 1


def test_profile_or_manual_source_change_invalidates_learned_and_ledger_answers(tmp_path):
    client = Client(response(), response("20 days"), response("10 days"))
    subject = engine(tmp_path, client)
    subject.resolve("How soon can you join?")
    subject.profile.notice_period_days = 20
    assert subject.resolve("How soon can you join?").answer.text == "20 days"
    path = Path(subject.book.path)
    path.write_text(path.read_text() + "\nQ: Availability note\nA: Early release agreed\n")
    assert subject.resolve("How soon can you join?").answer.text == "10 days"
    assert client.calls == 3


@pytest.mark.parametrize("value", ["", PER_JOB])
def test_exact_user_blank_or_per_job_blocks_a_similar_saved_answer(tmp_path, value):
    path = tmp_path / "answers.txt"
    path.write_text("Q: What is your notice period?\nA: 30 days\n\nQ: How soon can you join?\nA: " + value + "\n")
    book = AnswerBook(str(path))
    assert book.answer_for("How soon can you join?") is None


@pytest.mark.parametrize("saved,other", [
    ("Years of experience in C++?", "Years of experience in C#?"),
    ("Years of experience in C++?", "Years of experience in C?"),
    ("Do you have 3+ years of Python experience?", "Do you have 3 years of Python experience?"),
    ("Current salary in $?", "Current salary in ₹?"),
    ("Current salary in ¥?", "Current salary in $?"),
    ("Current salary in ¥?", "Current salary in?"),
    ("Is your bonus 3%?", "Is your bonus 3?"),
    ("Do you have 3.5 years of experience?", "Do you have 3-5 years of experience?"),
    ("Do you have .5 years of experience?", "Do you have 5 years of experience?"),
    ("Do you have -3 years of experience?", "Do you have 3 years of experience?"),
])
def test_exact_normalization_preserves_meaningful_symbols(tmp_path, saved, other):
    path = tmp_path / "answers.txt"
    path.write_text(f"Q: {saved}\nA: 2\n")
    book = AnswerBook(str(path))
    assert book.answer_for(saved) == "2"
    assert book.answer_for(other) is None


def test_blank_followed_by_comment_is_filled_in_place_and_reusable(tmp_path):
    subject = engine(tmp_path, Client(response()))
    path = Path(subject.book.path)
    path.parent.mkdir(parents=True)
    path.write_text("Q: How soon can you join?\nA:\n# Next answer\nQ: Favorite editor\nA: Emacs\n")
    assert subject.resolve("How soon can you join?").answer.text == "30 days"
    assert subject.resolve("How soon can you join?").answer.text == "30 days"
    assert subject.client.calls == 1
    assert path.read_text().count("Q: How soon can you join?") == 1


@pytest.mark.parametrize("mode", [AnswerMode.ASK, AnswerMode.PROPOSE])
def test_non_auto_model_result_does_not_become_a_saved_answer(tmp_path, mode):
    subject = engine(tmp_path, Client(response()), answer_mode=mode)
    assert subject.resolve("How soon can you join?").abstained
    assert all(not answer for _, answer in subject.book.entries)


def test_job_grounded_model_answer_is_not_learned_or_cached(tmp_path):
    client = Client(response("Yes", "notice_period_days, job_location"), response("No", "notice_period_days, job_location"))
    subject = engine(tmp_path, client)
    subject.set_job_context(JobPosting(job_id="1", url="x", title="Engineer", company="A", location="Pune"))
    assert subject.resolve("Will you attend the walk-in?", ["Yes", "No"]).answer.text == "Yes"
    subject.set_job_context(JobPosting(job_id="2", url="y", title="Engineer", company="B", location="Chennai"))
    assert subject.resolve("Will you attend the walk-in?", ["Yes", "No"]).answer.text == "No"
    assert subject.book.entries == []
    assert client.calls == 2


def test_user_value_arriving_during_model_request_is_not_overwritten(tmp_path):
    client = Client(response())
    subject = engine(tmp_path, client)
    def reply(prompt, schema):
        path = Path(subject.book.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Q: How soon can you join?\nA: 45 days\n")
        return response()
    client.complete_json = reply
    assert subject.resolve("How soon can you join?").answer.text == "45 days"
    assert Path(subject.book.path).read_text() == "Q: How soon can you join?\nA: 45 days\n"


def test_saved_answer_event_emitted_once_after_successful_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MORROW_ANSWER_EVENT_TOKEN", "test-token")
    subject = engine(tmp_path, Client(response()))
    subject.resolve("How soon can you join?")
    subject.resolve("How soon can you join?")
    lines = capsys.readouterr().out.splitlines()
    events = [json.loads(line.removeprefix(answer_events.PREFIX)) for line in lines if line.startswith(answer_events.PREFIX)]
    assert len(events) == 1
    assert events[0]["question"] == "How soon can you join?"
    assert events[0]["answer"] == "30 days"
    assert events[0]["token"] == "test-token"


def test_failed_save_does_not_emit_a_success_event(tmp_path, monkeypatch, capsys):
    from common import answers
    monkeypatch.setenv("MORROW_ANSWER_EVENT_TOKEN", "test-token")
    def fail(*args):
        raise OSError("write unavailable")
    monkeypatch.setattr(answers, "atomic_write_text", fail)
    subject = engine(tmp_path, Client(response()))
    assert subject.resolve("How soon can you join?").answer.text == "30 days"
    assert answer_events.PREFIX not in capsys.readouterr().out


@pytest.mark.parametrize("mode", [AnswerMode.ASK, AnswerMode.PROPOSE])
def test_multi_select_respects_answer_mode_without_learning(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(llm, "resolve_selection", lambda *args: (["Python"], ""))
    subject = engine(tmp_path, Client(), answer_mode=mode)
    values, reason = subject.resolve_many("Which languages do you know?", ["Python", "SQL"])
    assert values is None
    assert reason in ("propose_mode", "ask_mode_llm_answer")
    assert all(not answer for _, answer in subject.book.entries)


def test_learned_selection_is_not_applied_in_propose_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "resolve_selection", lambda *args: (["Python"], ""))
    subject = engine(tmp_path, Client())
    assert subject.resolve_many("Which languages do you know?", ["Python", "SQL"])[0] == ["Python"]
    subject.settings.answer_mode = AnswerMode.PROPOSE
    assert subject.resolve_many("Which languages do you know?", ["Python", "SQL"]) == (None, "propose_mode")


def test_choice_labels_with_separators_are_not_learned_as_different_selections(tmp_path, monkeypatch):
    calls = []
    def select(*args):
        calls.append(True)
        return ["Python, SQL"], ""
    monkeypatch.setattr(llm, "resolve_selection", select)
    subject = engine(tmp_path, Client())
    options = ["Python, SQL", "Python", "SQL"]
    for _ in range(2):
        assert subject.resolve_many("Which languages do you know?", options)[0] == ["Python, SQL"]
    assert len(calls) == 2
    assert subject.book.entries == []


def test_multi_select_uses_human_answer_arriving_during_request(tmp_path, monkeypatch):
    subject = engine(tmp_path, Client())
    def select(*args):
        path = Path(subject.book.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Q: Which languages do you know?\nA: SQL\n")
        return ["Python"], ""
    monkeypatch.setattr(llm, "resolve_selection", select)
    assert subject.resolve_many("Which languages do you know?", ["Python", "SQL"])[0] == ["SQL"]


@pytest.mark.parametrize("missing", ["options", "source", "profile", "multi", "version"])
def test_incomplete_metadata_cannot_broaden_learned_scope(tmp_path, missing):
    question = "Which editor do you use?"
    marker = answer_learning.annotation(question, "Other", "source-fingerprint", ["Other", "VSCode"])
    head, body = marker.split("{", 1)
    metadata = json.loads("{" + body)
    del metadata[missing]
    path = tmp_path / "answers.txt"
    path.write_text(f"Q: {question}\nA: Other\n" + head + json.dumps(metadata) + "\n")
    book = AnswerBook(str(path))
    book.profile_fingerprint = "source-fingerprint"
    assert book.answer_for(question) is None
    assert book.source_entries == []


def test_indented_metadata_keeps_profile_and_option_scope(tmp_path):
    question = "Which editor do you use?"
    path = tmp_path / "answers.txt"
    annotation = answer_learning.annotation(question, "Other", "old-profile", ["Other", "VSCode"])
    path.write_text(f"Q: {question}\nA: Other\n  {annotation}\n")
    book = AnswerBook(str(path))
    book.profile_fingerprint = "new-profile"
    assert book.answer_for(question) is None
    assert book.source_entries == []


def test_parallel_agents_share_one_model_request_for_the_same_question(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = '''
import os, time
from pathlib import Path
from common.answers import AnswerEngine
from common.ledger import Ledger
from common.models import Profile, Settings
class Client:
    def available(self): return True
    def complete_json(self, prompt, schema):
        with open('model-calls', 'a') as out: out.write(str(os.getpid()) + '\\n')
        time.sleep(.15)
        return dict(can_answer=True, answer='30 days', grounded_in='notice_period_days', confidence=.95)
engine = AnswerEngine(Ledger(':memory:'), Client(), Profile(full_name='Test', notice_period_days=30), Settings(data_dir='inputs', judge_answers=False))
assert engine.resolve('How soon can you join?').answer.text == '30 days'
'''
    environment = dict(os.environ, PYTHONPATH=str(root))
    environment.pop("MORROW_ANSWER_EVENT_TOKEN", None)
    children = [subprocess.Popen([sys.executable, "-c", script], cwd=tmp_path, env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    for child in children:
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr.decode()
    assert len((tmp_path / "model-calls").read_text().splitlines()) == 1
    assert (tmp_path / "inputs/answers.txt").read_text().count("Q: How soon can you join?") == 1
