"""Long answers on company-site forms: hers from answers.txt first, else written from the resume.

A required "Why this role?" box used to send the whole application to her
worklist. Now one is written for the job, but only from the resume and the
posting, linted like the resume summary, and kept in the job's folder to read.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes

from common import assist
from sites_bot import external as ext
from common import resume as rs
from common.answers import AnswerEngine
from common.ledger import Ledger
from common.models import AnswerMode, JobPosting, Profile, Settings


TEX = """\\documentclass{article}
\\begin{document}
\\begin{center}
  {\\LARGE\\bfseries\\color{ink} JANE DOE}\\\\[3pt]
  {\\normalsize\\color{muted} Software Engineer \\;$\\cdot$\\; AI Agent Evaluation}\\\\[5pt]
\\end{center}

\\section{Summary}
I build evaluation pipelines for AI agents at Ethara AI, with LangChain and FastAPI services.

\\section{Skills}
{\\bfseries Languages:} Python, TypeScript\\par\\vspace{2pt}

\\end{document}
"""

GOOD = (
    "I build evaluation pipelines for AI agents at Ethara AI, mostly in Python with LangChain "
    "and FastAPI. Acme is hiring a LangChain Engineer to build agents, which is the work I do every day."
)
QUESTION = "Why do you want to join Acme?"


class _Writer:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else None


def _job():
    return JobPosting(job_id="j1", url="https://www.naukri.com/job-listings-j1", title="LangChain Engineer",
                      company="Acme", description="Build LangChain agents in Python.")


@pytest.fixture
def base(tmp_path):
    path = tmp_path / "base.tex"
    path.write_text(TEX, encoding="utf-8")
    return rs.load_base(str(path))


def test_a_grounded_answer_is_accepted(base):
    client = _Writer({"can_answer": True, "answer": GOOD})

    assert rs.write_long_answer(client, base, _job(), QUESTION) == GOOD
    assert "QUESTION\n%s" % QUESTION in client.prompts[0]
    assert "Build LangChain agents in Python." in client.prompts[0]


def test_an_invented_claim_is_sent_back_once_then_dropped(base):
    invented = GOOD + " I also led the Kubernetes migration at Google."
    client = _Writer({"can_answer": True, "answer": invented}, {"can_answer": True, "answer": GOOD})

    assert rs.write_long_answer(client, base, _job(), QUESTION) == GOOD
    assert "Kubernetes" in client.prompts[1] and "neither the resume nor the posting" in client.prompts[1]


@pytest.mark.parametrize(
    "answer",
    [
        GOOD + " I am passionate about agents.",
        GOOD.replace(", mostly", " \u2014 mostly"),
        GOOD + " Kubernetes!",
        "I like it here a lot.",
        GOOD * 4,
    ],
)
def test_slop_and_invention_twice_give_nothing(base, answer):
    client = _Writer({"can_answer": True, "answer": answer}, {"can_answer": True, "answer": answer})

    assert rs.write_long_answer(client, base, _job(), QUESTION) is None


def test_a_question_the_resume_cannot_answer_is_declined(base):
    assert rs.write_long_answer(_Writer({"can_answer": False, "answer": ""}), base, _job(), "Name a reference") is None


# --- in the form ------------------------------------------------------------------


def _engine(tmp_path, client, **overrides):
    (tmp_path / "user" / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user" / "inputs" / "answers.txt").write_text("Q: Tell us about yourself\nA: My own words.\n", encoding="utf-8")
    (tmp_path / "base.tex").write_text(TEX, encoding="utf-8")
    values = dict(email="t@example.com", password="secret", resume_path=str(tmp_path / "base.tex"),
                  resume_out_dir=str(tmp_path / "out"), report_dir=str(tmp_path / "reports"))
    values.update(overrides)
    return AnswerEngine(Ledger(":memory:"), client, Profile(full_name="T"), Settings(**values))


def test_her_own_answer_beats_the_writer(tmp_path):
    called = []
    engine = _engine(tmp_path, _Writer())

    answer = ext._own_words(engine, "Tell us about yourself", True, lambda q: called.append(q) or "written")

    assert answer == "My own words." and called == []


def test_a_required_box_she_has_not_answered_is_written(tmp_path):
    engine = _engine(tmp_path, _Writer())

    assert ext._own_words(engine, QUESTION, True, lambda q: "written for " + q) == "written for " + QUESTION
    assert QUESTION not in (tmp_path / "user" / "inputs" / "answers.txt").read_text(encoding="utf-8")


def test_an_optional_box_is_never_written(tmp_path):
    engine = _engine(tmp_path, _Writer())

    assert ext._own_words(engine, "Anything else?", False, lambda q: "written") is None


def test_a_box_nobody_could_write_is_left_in_answers_txt(tmp_path):
    engine = _engine(tmp_path, _Writer())

    assert ext._own_words(engine, QUESTION, True, lambda q: None) is None
    assert "Q: %s\nA:\n" % QUESTION in (tmp_path / "user" / "inputs" / "answers.txt").read_text(encoding="utf-8")


def test_the_writer_keeps_each_answer_in_the_jobs_folder(tmp_path):
    engine = _engine(tmp_path, _Writer({"can_answer": True, "answer": GOOD}))
    write = ext.long_answer_writer(engine.settings, engine, _job())

    assert write(QUESTION) == GOOD

    kept = rs.tailored_dir(engine.settings, _job()) / "answers.md"
    assert kept.read_text(encoding="utf-8") == "## %s\n\n%s\n\n" % (QUESTION, GOOD)
    [record] = [r for r in assist.read_changes(engine.settings) if r["kind"] == "written"]
    assert record["file"] == str(kept) and record["item"] == QUESTION


def test_legal_questions_are_not_written(tmp_path):
    client = _Writer({"can_answer": True, "answer": GOOD})
    write = ext.long_answer_writer(_engine(tmp_path, client).settings, _engine(tmp_path, client), _job())

    assert write("Describe any criminal convictions") is None
    assert client.prompts == []


@pytest.mark.parametrize("overrides", [{"judge_answers": False}, {"answer_mode": AnswerMode.PROPOSE}])
def test_the_writer_can_be_switched_off(tmp_path, overrides):
    engine = _engine(tmp_path, _Writer(), **overrides)

    assert ext.long_answer_writer(engine.settings, engine, _job()) is None


def test_no_resume_means_no_writer(tmp_path):
    engine = _engine(tmp_path, _Writer(), resume_path=str(tmp_path / "missing.tex"))

    assert ext.long_answer_writer(engine.settings, engine, _job()) is None


def test_pdf_resume_supports_grounded_long_answers_without_tailoring(tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(pdf_bytes("I build evaluation pipelines for AI agents at Ethara AI, with LangChain and FastAPI services. Python TypeScript."))
    client = _Writer({"can_answer": True, "answer": GOOD})
    engine = _engine(tmp_path, client, resume_path=str(pdf))
    writer = ext.long_answer_writer(engine.settings, engine, _job())
    assert writer is not None and writer(QUESTION) == GOOD
    assert "Ethara AI" in client.prompts[0] and "%PDF" not in client.prompts[0]
    source = rs.load_source(str(pdf))
    assert isinstance(source, rs.ResumeSource) and not hasattr(source, "sections")
    with pytest.raises(rs.ResumeError, match="tailoring requires"):
        rs.load_base(str(pdf))


def test_pdf_grounding_rejects_fabricated_claims(tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(pdf_bytes("I build evaluation pipelines for AI agents at Ethara AI, with LangChain and FastAPI services. Python TypeScript."))
    invented = GOOD + " I also led the Kubernetes migration at Google."
    client = _Writer({"can_answer": True, "answer": invented}, {"can_answer": True, "answer": invented})
    assert rs.write_long_answer(client, rs.load_source(str(pdf)), _job(), QUESTION) is None
    assert len(client.prompts) == 2 and "Kubernetes" in client.prompts[1]


# ---------------------------------------------------------------------------
# Answers marked "[AI writes this for each job]" in answers.txt
# ---------------------------------------------------------------------------

WHY_US = "Why do you want to work with us?"
SHORT = "I build LangChain agent evaluation in Python, the work Acme hires for."


def _per_job_engine(tmp_path, client):
    engine = _engine(tmp_path, client)
    with open(engine.book.path, "a", encoding="utf-8") as handle:
        handle.write("\nQ: %s\nQ: Why do you want to join us?\nA: [AI writes this for each job]\n" % WHY_US)
    engine.book.reload()
    return engine


def test_a_per_job_answer_is_never_sent_as_written(tmp_path):
    engine = _per_job_engine(tmp_path, _Writer())

    assert engine.book.answer_for(WHY_US) is None
    assert engine.book.per_job(WHY_US) and engine.book.per_job("Why do you want to join us?")
    assert WHY_US not in engine.book.blank_questions()
    assert engine.own_answer(WHY_US) is None


def test_a_chat_question_marked_per_job_gets_one_short_sentence_for_this_posting(tmp_path):
    client = _Writer({"can_answer": True, "answer": SHORT})
    engine = _per_job_engine(tmp_path, client)
    engine.set_job_context(_job())

    resolution = engine.resolve(WHY_US)

    assert not resolution.abstained and resolution.answer.text == SHORT
    assert "one sentence, under 90 characters" in client.prompts[0]
    assert "Build LangChain agents in Python." in client.prompts[0]
    assert SHORT not in (tmp_path / "user" / "inputs" / "answers.txt").read_text(encoding="utf-8")
    [record] = [r for r in assist.read_changes(engine.settings) if r["kind"] == "written"]
    assert record["file"] == "this application only" and record["value"] == SHORT


def test_per_job_chat_answer_uses_selected_pdf_facts(tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    client = _Writer({"can_answer": True, "answer": SHORT})
    engine = _per_job_engine(tmp_path, client)
    selected = tmp_path / "selected.pdf"
    selected.write_bytes(pdf_bytes("I build LangChain agent evaluation pipelines in Python at Ethara AI."))
    engine.settings.resume_path = str(selected)
    engine.set_job_context(_job())
    result = engine.resolve(WHY_US)
    assert not result.abstained and result.answer.text == SHORT
    assert "Ethara AI" in client.prompts[0] and "%PDF" not in client.prompts[0]


def test_each_posting_gets_its_own_answer(tmp_path):
    other = "I evaluate AI agents in Python and FastAPI, which Beta builds on."
    client = _Writer({"can_answer": True, "answer": SHORT}, {"can_answer": True, "answer": other})
    engine = _per_job_engine(tmp_path, client)

    engine.set_job_context(_job())
    first = engine.resolve(WHY_US).answer.text
    engine.set_job_context(JobPosting(job_id="j2", url="u", title="AI Engineer", company="Beta",
                                      description="Python and FastAPI services for AI agents."))
    second = engine.resolve(WHY_US).answer.text

    assert (first, second) == (SHORT, other)
    assert "Beta" in client.prompts[1]


def test_no_posting_or_a_declining_model_leaves_it_unanswered(tmp_path):
    engine = _per_job_engine(tmp_path, _Writer({"can_answer": False, "answer": ""}))
    assert engine.resolve(WHY_US).abstained

    engine.set_job_context(_job())
    assert engine.resolve(WHY_US).abstained
    assert "[AI writes this for each job]" in (tmp_path / "user" / "inputs" / "answers.txt").read_text(encoding="utf-8")


def test_an_optional_box_marked_per_job_is_written_on_company_forms(tmp_path):
    engine = _per_job_engine(tmp_path, _Writer())

    assert ext._own_words(engine, WHY_US, False, lambda q: "written for " + q) == "written for " + WHY_US
