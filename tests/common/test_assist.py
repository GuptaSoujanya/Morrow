"""AI assist: blanks are filled only with a quote that is really in the user's own files."""

import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import assist
from common.answers import AnswerBook
from common.models import Profile, Settings


ANSWERS = """# Your answers

Q: What is your notice period?
Q: Notice period (in days)
A:

Q: Do you have a valid passport?
A:

Q: Why do you want to work with us?
A:

Q: Are you open to contract roles?
A: Yes, open to contract roles of 12 months or more

# ----- questions the bot could not answer are added below this line ---------

# 2026-10-10 23:29 | while applying to AI Engineer at Acme | llm_abstained
Q: How many years of experience do you have in CrewAI or LangGraph or AutoGen?
A:

# 2026-10-10 23:30 | while applying to SRE at Beta | llm_abstained
Q: Do you know Kubernetes?
A:
"""

PROFILE_YAML = """full_name: "Jane Doe"
notice_period_days: 15                 # FILL, e.g. 30
has_passport: true                     # FILL
expected_ctc_lpa: 18
extra_facts:
  pan_number: null                     # FILL only if forms keep asking
  contract_roles: null                 # FILL, e.g. "Yes, comfortable with a 12 month contract role"
"""

RESUME = "Software Engineer at Acme. Built LangChain pipelines in Python for evaluating agents."


class _Client:
    def __init__(self, items):
        self.items = items
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return {"items": self.items}


def _setup(tmp_path, answers=ANSWERS, profile_yaml=PROFILE_YAML):
    data = tmp_path / "data" / "inputs"
    data.mkdir(parents=True)
    (data / "answers.txt").write_text(answers, encoding="utf-8")
    (data / "profile.yaml").write_text(profile_yaml, encoding="utf-8")
    settings = Settings(
        profile_path=str(data / "profile.yaml"),
        data_dir=str(data),
        report_dir=str(tmp_path / "reports"),
    )
    profile = Profile(full_name="Jane Doe", notice_period_days=15, has_passport=True, expected_ctc_lpa=18, resume_text=RESUME)
    return settings, profile


GOOD = [
    {"id": "q:what is your notice period", "answer": "15 days", "source": "profile", "evidence": "notice_period_days: 15"},
    {"id": "q:do you have a valid passport", "answer": "Yes", "source": "profile", "evidence": "has_passport: True"},
    {"id": "f:extra_facts.contract_roles", "answer": "Yes, open to contract roles of 12 months or more",
     "source": "answers", "evidence": "A: Yes, open to contract roles of 12 months or more"},
    {"id": "q:do you know kubernetes", "answer": "Yes", "source": "resume", "evidence": "five years of Kubernetes in production"},
]


def test_a_quote_must_really_be_in_the_source():
    assert assist.quote_found("built  LangChain pipelines", RESUME)
    assert not assist.quote_found("built Kubernetes clusters", RESUME)
    assert not assist.quote_found("Python", RESUME)


def test_blanks_are_filled_from_quoted_lines_and_marked(tmp_path):
    settings, profile = _setup(tmp_path)
    client = _Client(GOOD)

    changes = assist.fill_blanks(settings, profile, client)

    assert [change.item for change in changes] == [
        "What is your notice period?",
        "Do you have a valid passport?",
        "extra_facts.contract_roles",
    ]
    book = AnswerBook(str(tmp_path / "data" / "inputs" / "answers.txt"))
    assert book.answer_for("Notice period (in days)") == "15 days"
    assert book.answer_for("Do you have a valid passport?") == "Yes"
    assert book.answer_for("Do you know Kubernetes?") is None
    text = (tmp_path / "data" / "inputs" / "answers.txt").read_text(encoding="utf-8")
    assert '# AI filled this on' in text and 'from your profile: "notice_period_days: 15"' in text
    facts = yaml.safe_load((tmp_path / "data" / "inputs" / "profile.yaml").read_text(encoding="utf-8"))
    assert facts["extra_facts"]["contract_roles"] == "Yes, open to contract roles of 12 months or more"
    assert facts["extra_facts"]["pan_number"] is None
    backups = sorted(path.name.split(".")[0] for path in (tmp_path / "data" / "inputs" / "backups").iterdir())
    assert backups == ["answers", "profile"]
    recorded = assist.changes_on(settings, changes[0].at[:10])
    assert [record["value"] for record in recorded] == ["15 days", "Yes", "Yes, open to contract roles of 12 months or more"]


def test_what_the_model_is_never_asked(tmp_path):
    settings, profile = _setup(tmp_path)
    client = _Client([])

    assist.fill_blanks(settings, profile, client)

    items = json.loads(client.prompts[0].split("ITEMS:\n", 1)[1].split("\n\nRESUME:", 1)[0])
    asked = [item["text"] for item in items]
    assert "Why do you want to work with us?" not in asked
    assert not any("CrewAI" in text for text in asked)
    assert "extra_facts.pan_number" not in asked
    assert "Do you know Kubernetes?" in asked


def test_a_dry_run_changes_no_file(tmp_path):
    settings, profile = _setup(tmp_path)

    changes = assist.fill_blanks(settings, profile, _Client(GOOD), write=False)

    assert len(changes) == 3
    assert (tmp_path / "data" / "inputs" / "answers.txt").read_text(encoding="utf-8") == ANSWERS
    assert (tmp_path / "data" / "inputs" / "profile.yaml").read_text(encoding="utf-8") == PROFILE_YAML
    assert not (tmp_path / "reports").exists()


def test_a_blank_the_model_could_not_answer_is_not_asked_again_until_a_file_changes(tmp_path):
    settings, profile = _setup(tmp_path)
    client = _Client(GOOD)
    assist.fill_blanks(settings, profile, client)

    assist.fill_blanks(settings, profile, client)
    assert len(client.prompts) == 1

    with open(tmp_path / "data" / "inputs" / "answers.txt", "a", encoding="utf-8") as handle:
        handle.write("\nQ: Kubernetes experience\nA: Three years of Kubernetes in production\n")
    assist.fill_blanks(settings, profile, client)
    assert len(client.prompts) == 2


def test_a_quote_cannot_vouch_for_a_different_number():
    assert assist.numbers_backed("15 days", "notice_period_days: 15")
    assert not assist.numbers_backed("30 days", "notice_period_days: 15")
    assert assist.numbers_backed("Yes", "has_passport: True")


def test_fill_answer_only_touches_a_blank_answer():
    assert assist.fill_answer("Q: A?\nA: no\n", "A?", "yes", "note") is None
    filled = assist.fill_answer("# head\n\nQ: One?\nQ: Two?\nA:\n\nQ: Three?\nA:\n", "Two?", "42", "AI note")
    assert filled == "# head\n\n# AI note\nQ: One?\nQ: Two?\nA: 42\n\nQ: Three?\nA:\n"


def test_fill_fact_refuses_an_ambiguous_key():
    text = "a:\n  name: null\nb:\n  name: null\n"
    assert assist.fill_fact(text, "a.name", "x", "note") is None


def test_disagreements_between_the_two_files_are_named(tmp_path):
    answers = (
        "Q: What is your expected CTC?\nA: 20 LPA\n\n"
        "Q: Can your notice period be bought out?\nA: 7 days\n\n"
        "Q: Are you serving your notice period?\nA: No\n\n"
        "Q: Date of birth\nA: 05/0/2003\n\n"
        "Q: What is your last working day?\nA: yes\n\n"
        "Q: Notice period (in days)\nA: 15\n"
    )
    settings, _ = _setup(tmp_path, answers=answers)
    profile = Profile(expected_ctc_lpa=18, notice_period_days=15, serving_notice=True)

    found = assist.disagreements(profile, AnswerBook(str(tmp_path / "data" / "inputs" / "answers.txt")))

    assert [(item.topic, item.in_answers, item.in_profile) for item in found] == [
        ("expected CTC", "20 LPA", "expected_ctc_lpa: 18"),
        ("serving notice", "No", "serving_notice: true"),
        ("date of birth", "05/0/2003", "not a real date"),
        ("last working day", "yes", "not a real date"),
    ]


def test_shift_answers_that_disagree_with_the_profile_facts_are_named(tmp_path):
    answers = (
        "Q: Are you comfortable with night shifts?\nQ: Are you open to working in US shift timings?\nA: No\n\n"
        "Q: Are you comfortable with rotational shifts?\nA: No\n"
    )
    settings, _ = _setup(tmp_path, answers=answers)
    profile = Profile(extra_facts={"willing_night_shifts": "false", "willing_rotational_shifts": True})

    found = assist.disagreements(profile, AnswerBook(str(tmp_path / "data" / "inputs" / "answers.txt")))

    assert [(item.topic, item.in_answers, item.in_profile) for item in found] == [
        ("rotational shifts", "No", "extra_facts.willing_rotational_shifts: true"),
    ]
