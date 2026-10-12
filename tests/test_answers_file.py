"""data/answers.txt: the user's own words win, and unknown questions are left there to fill.

The file is the one place a person edits between runs, so a question answered
there must beat the cache, the profile and the model; a question the bot could
not answer must land in the same file with an empty A: and be used once filled.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.answers import (
    AnswerBook,
    AnswerEngine,
    facts_fingerprint,
    match_option,
    match_options,
    parse_answers,
)
from common.ledger import Ledger
from common.models import Answer, AnswerSource, JobPosting, Profile, Settings


SAMPLE = """# a comment line
Q: What is your notice period?
Q: Notice period (in days)
A: 30 days

Q: Expected CTC
A:

Q: Tell us about yourself
A: I build evaluation
   pipelines for agents.

Q: Which skills do you have?
A: Python, React
"""


def test_parse_blocks_aliases_blank_and_multiline_answers():
    assert parse_answers(SAMPLE) == [
        (["What is your notice period?", "Notice period (in days)"], "30 days"),
        (["Expected CTC"], ""),
        (["Tell us about yourself"], "I build evaluation pipelines for agents."),
        (["Which skills do you have?"], "Python, React"),
    ]


def _write(tmp_path, text):
    path = tmp_path / "data" / "answers.txt"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_matching_ignores_case_punctuation_and_small_typos(tmp_path):
    book = AnswerBook(str(_write(tmp_path, SAMPLE)))
    assert book.answer_for("notice period (in days)?") == "30 days"
    assert book.answer_for("NOTICE PERIOD, in days") == "30 days"
    assert book.answer_for("What is your notice periods?") == "30 days"
    assert book.answer_for("What is your current CTC?") is None


def test_a_blank_answer_means_unknown(tmp_path):
    book = AnswerBook(str(_write(tmp_path, SAMPLE)))
    assert book.answer_for("Expected CTC") is None
    assert book.blank_questions() == ["Expected CTC"]


def test_missing_file_is_an_empty_book(tmp_path):
    book = AnswerBook(str(tmp_path / "data" / "answers.txt"))
    assert book.answer_for("anything") is None
    assert book.add_blank("Do you drive?", "profile_fact_missing")
    assert (tmp_path / "data" / "answers.txt").read_text().endswith("Q: Do you drive?\nA:\n")


def test_add_blank_appends_once_with_context_and_survives_reload(tmp_path):
    path = _write(tmp_path, SAMPLE)
    book = AnswerBook(str(path))
    assert book.add_blank(
        "Are you ok with a 6 day week?", "llm_abstained", ["Yes", "No"],
        {"title": "Developer", "company": "Acme"},
    )
    assert not book.add_blank("Are you ok with a 6 day week?", "llm_abstained")
    assert not book.add_blank("are you OK with a 6-day week", "llm_abstained")
    text = path.read_text(encoding="utf-8")
    assert text.count("Q: Are you ok with a 6 day week?") == 1
    assert "Q: Are you ok with a 6 day week?\nA:\n" in text
    assert "while applying to Developer at Acme" in text
    assert "options: ['Yes', 'No']" in text
    assert AnswerBook(str(path)).blank_questions() == [
        "Expected CTC",
        "Are you ok with a 6 day week?",
    ]


def test_edits_made_between_questions_are_picked_up(tmp_path):
    path = _write(tmp_path, SAMPLE)
    book = AnswerBook(str(path))
    assert book.answer_for("Expected CTC") is None
    path.write_text(SAMPLE.replace("Q: Expected CTC\nA:\n", "Q: Expected CTC\nA: 14 LPA\n"), encoding="utf-8")
    later = os.path.getmtime(path) + 5
    os.utime(path, (later, later))
    assert book.answer_for("Expected CTC") == "14 LPA"


@pytest.mark.parametrize(
    "answer,options,expected",
    [
        ("30 days", ["15 days", "30 days", "60 days"], "30 days"),
        ("Yes", ["Yes", "No"], "Yes"),
        ("No, none at the moment", ["Yes", "No"], "No"),
        ("Immediate joiner", ["Immediate", "15 Days", "30 Days"], "Immediate"),
        ("Indore", ["Indore, Madhya Pradesh", "Pune"], "Indore, Madhya Pradesh"),
        ("Flexible, office or remote", ["Office", "Remote", "Hybrid"], None),
        ("Bengaluru", ["Pune", "Hyderabad"], None),
        ("", ["Yes", "No"], None),
    ],
)
def test_match_option(answer, options, expected):
    assert match_option(answer, options) == expected


def test_match_options_keeps_the_rendered_order_and_refuses_partial_matches():
    options = ["SQL", "Python", "Java", "React"]
    assert match_options("Python, React and SQL", options) == ["SQL", "Python", "React"]
    assert match_options("Python, Rust", options) is None
    assert match_options("", options) is None


class _NoLLM:
    def available(self):
        return False


def _engine(tmp_path, text=SAMPLE):
    _write(tmp_path, text)
    settings = Settings(email="t@example.com", password="secret")
    profile = Profile(full_name="T", notice_period_days=60)
    return AnswerEngine(Ledger(":memory:"), _NoLLM(), profile, settings)


def test_the_file_beats_the_cache_and_the_profile(tmp_path):
    engine = _engine(tmp_path)
    engine.ledger.save_answer(
        "What is your notice period?",
        Answer(text="45 days", grounded_in="x", source=AnswerSource.LLM, confidence=1.0),
        "text",
        engine.profile_fingerprint,
    )
    resolution = engine.resolve("What is your notice period?")
    assert not resolution.abstained
    assert resolution.answer.text == "30 days"
    assert resolution.answer.source == AnswerSource.DATA
    assert engine.answered == 1


def test_the_file_answer_is_mapped_onto_the_rendered_options(tmp_path):
    engine = _engine(tmp_path)
    resolution = engine.resolve("Notice period (in days)?", options=["15 days", "30 days", "60 days"])
    assert resolution.answer.text == "30 days"


def test_an_answer_fitting_no_option_falls_through_to_the_other_sources(tmp_path):
    engine = _engine(tmp_path)
    resolution = engine.resolve("Notice period (in days)?", options=["Immediate", "60 days"])
    # The profile says 60 days, and that is the only remaining grounded source.
    assert resolution.answer.text == "60 days"
    assert resolution.answer.source == AnswerSource.PROFILE


def test_an_unanswered_question_is_left_in_the_file_for_the_user(tmp_path):
    engine = _engine(tmp_path)
    engine.set_job_context(JobPosting(job_id="1", url="u", title="Developer", company="Acme"))
    resolution = engine.resolve("Do you own a two wheeler?")
    assert resolution.abstained
    text = (tmp_path / "data" / "answers.txt").read_text(encoding="utf-8")
    assert "Q: Do you own a two wheeler?\nA:\n" in text
    assert "while applying to Developer at Acme" in text
    assert "Do you own a two wheeler?" in (tmp_path / "unanswered_questions.md").read_text()


def test_a_filled_in_answer_is_used_on_the_next_question(tmp_path):
    engine = _engine(tmp_path)
    assert engine.resolve("Do you own a two wheeler?").abstained
    path = tmp_path / "data" / "answers.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("Q: Do you own a two wheeler?\nA:\n", "Q: Do you own a two wheeler?\nA: Yes\n"), encoding="utf-8")
    later = os.path.getmtime(path) + 5
    os.utime(path, (later, later))
    resolution = engine.resolve("Do you own a two wheeler?", options=["Yes", "No"])
    assert resolution.answer.text == "Yes"


def test_multi_select_questions_read_the_file_too(tmp_path):
    engine = _engine(tmp_path)
    assert engine.resolve_many("Which skills do you have?", ["Java", "Python", "React"]) == (
        ["Python", "React"],
        "",
    )
    selections, reason = engine.resolve_many("Which skills do you have?", ["Java", "Go"])
    assert selections is None and reason == "llm_unavailable"


def test_a_long_option_list_is_shortened_in_the_file(tmp_path):
    book = AnswerBook(str(tmp_path / "answers.txt"))
    book.add_blank("Which university did you attend?", "llm_abstained", ["University %d" % n for n in range(3000)])

    text = (tmp_path / "answers.txt").read_text(encoding="utf-8")
    assert "'University 11'] and 2988 more" in text
    assert "University 12'" not in text
    assert len(text) < 600


def test_the_facts_fingerprint_ignores_blank_questions_but_not_answers(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    profile = Profile(full_name="Jane", notice_period_days=None)
    path = tmp_path / "data" / "answers.txt"
    path.parent.mkdir()
    path.write_text("Q: Why us?\nA:\n")
    first = facts_fingerprint(profile, settings)

    AnswerBook(str(path)).add_blank("What is your expected CTC?", "llm_abstained")
    assert facts_fingerprint(profile, settings) == first

    path.write_text(path.read_text().replace("Q: Why us?\nA:", "Q: Why us?\nA: The evaluation work."))
    assert facts_fingerprint(profile, settings) != first
    assert facts_fingerprint(Profile(full_name="Jane", notice_period_days=30), settings) != first


def test_a_date_typed_into_profile_yaml_reaches_the_model_as_text(tmp_path):
    import json

    from common.profile import load_profile

    (tmp_path / "resume.txt").write_text("Python engineer", encoding="utf-8")
    (tmp_path / "profile.yaml").write_text(
        "full_name: Jane Doe\nextra_facts:\n  date_of_birth: 2003-04-05\n",
        encoding="utf-8",
    )
    profile = load_profile(
        Settings(profile_path=str(tmp_path / "profile.yaml"), resume_path=str(tmp_path / "resume.txt"))
    )
    assert profile.extra_facts["date_of_birth"] == "2003-04-05"
    json.dumps(profile.known_facts())
