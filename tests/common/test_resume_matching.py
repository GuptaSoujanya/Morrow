"""The posting is read and the resume scored against it before anything is edited.

What must hold: an item's score is the weighted sum of its four axes and its
band follows the fixed cut-offs; a requirement is covered by the best item that
gives evidence for it, otherwise it is a gap; the model's reading is accepted
only where it can be checked (requirements with text, terminology that exists
in both texts, scores clamped) and an item the model skipped is still ranked
by keyword overlap; the ranking, the gaps and the coverage reach the tailoring
prompt, the notes and tailoring.json; and nothing in the profile can add a
claim the resume does not make.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import resume as rs
from common.models import JobPosting, Settings

TEX = """\\documentclass[a4paper,9pt]{extarticle}
\\begin{document}
\\begin{center}
  {\\LARGE\\bfseries JANE DOE}\\\\[3pt]
  {\\normalsize\\color{muted} Software Engineer \\;$\\cdot$\\; AI Agent Evaluation}\\\\[5pt]
\\end{center}

\\section{Summary}
I'm a software engineer who evaluates AI agents and large language models. I grew the WildClawBench benchmark on the OpenClaw harness into a multi-provider evaluation platform with LLM-as-judge grading for Claude on AWS Bedrock. Before that I built Next.js front-ends and LangChain pipelines and wrote FastAPI services for a small team. I like plain code, measured results and short feedback loops, and I would rather show a benchmark run than describe one.

\\section{Professional Experience}
Ethara AI, Gurugram
\\begin{itemize}
  \\item Built LangChain agents in Python with LLM-as-judge grading.
  \\item Wrote FastAPI services for a small team.
  \\item Grew the WildClawBench benchmark to 3 providers.
\\end{itemize}

\\section{Skills}
{\\bfseries Languages:} Python, SQL\\par\\vspace{2pt}
{\\bfseries AI / LLM:} LangChain, RAG\\par\\vspace{2pt}

\\end{document}
"""


@pytest.fixture
def base(tmp_path):
    path = tmp_path / "base.tex"
    path.write_text(TEX, encoding="utf-8")
    return rs.load_base(str(path))


class _Client:
    """Answers the analysis call and the edit call differently, by schema."""

    def __init__(self, profile=None, edit=None, available=True):
        self.profile, self.edit, self._available = profile, edit, available
        self.prompts = []

    def available(self):
        return self._available

    def complete_json(self, prompt, schema_hint):
        self.prompts.append((schema_hint, prompt))
        return self.profile if "requirements" in schema_hint else self.edit


def _job(**overrides):
    values = dict(
        job_id="j1",
        url="https://example.com/j1",
        title="LangChain Engineer",
        company="Acme",
        description="Build LangChain agents in Python. Kubernetes a plus. Orchestration frameworks welcome.",
    )
    values.update(overrides)
    return JobPosting(**values)


PROFILE = {
    "archetype": "individual contributor",
    "requirements": [
        {"text": "LangChain agent development", "must_have": True, "keywords": ["LangChain", "agents"]},
        {"text": "Python", "must_have": True, "keywords": ["Python"]},
        {"text": "Kubernetes", "must_have": False, "keywords": ["Kubernetes"]},
    ],
    "themes": ["agent reliability"],
    "terminology": {
        "orchestration frameworks": "LangChain pipelines",
        "orchestration frameworks ": "Airflow DAGs",
        "made up term": "Python",
    },
    "red_flags": ["Kubernetes never appears on the resume"],
    "matches": [
        {"item": "b0.0", "direct": 100, "transferable": 90, "adjacent": 90, "impact": 80, "covers": [0]},
        {"item": "b0.1", "direct": 20, "transferable": 70, "adjacent": 60, "impact": 50, "covers": []},
        {"item": "s1.0", "direct": 100, "transferable": 100, "adjacent": 100, "impact": 100, "covers": [0]},
        {"item": "s9.9", "direct": 100, "transferable": 100, "adjacent": 100, "impact": 100, "covers": [2]},
    ],
}


# --- scoring ----------------------------------------------------------------------


def test_the_score_is_the_weighted_sum_of_the_four_axes():
    match = rs.ItemMatch("b0.0", "x", direct=100, transferable=80, adjacent=60, impact=40)
    assert match.score == 100 * 0.4 + 80 * 0.3 + 60 * 0.2 + 40 * 0.1 == 80.0
    assert match.band == "TRANSFERABLE"


@pytest.mark.parametrize(
    "score,band",
    [(100, "DIRECT"), (90, "DIRECT"), (89.9, "TRANSFERABLE"), (75, "TRANSFERABLE"), (74, "ADJACENT"), (60, "ADJACENT"), (59, "WEAK"), (45, "WEAK"), (44.9, "GAP"), (0, "GAP")],
)
def test_bands_follow_the_fixed_cut_offs(score, band):
    assert rs.match_band(score) == band


def test_a_requirement_is_covered_by_its_best_item_or_is_a_gap():
    profile = rs.JobProfile(
        requirements=[rs.Requirement("A"), rs.Requirement("B", must_have=False), rs.Requirement("C")],
        matches=[
            rs.ItemMatch("b0.0", "x", 100, 100, 100, 100, covers=[0, 1]),
            rs.ItemMatch("b0.1", "y", 50, 50, 50, 50, covers=[1, 2]),
            rs.ItemMatch("b0.2", "z", 0, 0, 0, 0, covers=[7]),
        ],
    )
    assert profile.requirement_scores() == [100.0, 100.0, 50.0]
    assert [req.text for req in profile.gaps()] == ["C"]
    coverage = profile.coverage()
    assert (coverage["covered"], coverage["requirements"], coverage["percent"]) == (2, 3, 67)
    assert (coverage["must_have_covered"], coverage["must_have"]) == (1, 2)
    assert coverage["bands"] == {"DIRECT": 2, "TRANSFERABLE": 0, "ADJACENT": 0, "WEAK": 1, "GAP": 0}
    assert [m.item for m in profile.ranked()] == ["b0.0", "b0.1", "b0.2"]


def test_every_bullet_and_skill_item_gets_an_id(base):
    items = rs.match_items(base)
    assert items[0] == ("b0.0", "Built LangChain agents in Python with LLM-as-judge grading.")
    assert items[2] == ("b0.2", "Grew the WildClawBench benchmark to 3 providers.")
    assert items[3] == ("s0.0", "Languages: Python")
    assert items[-1] == ("s1.1", "AI / LLM: RAG")


def test_keyword_overlap_alone_never_reaches_direct():
    reqs = [rs.Requirement("a", keywords=["LangChain"]), rs.Requirement("b", keywords=["Python"]), rs.Requirement("c", keywords=["Go"])]
    assert rs.keyword_hits("Built LangChain agents in Python", reqs) == [0, 1]
    one = rs.keyword_match("s0.0", "LangChain", reqs)
    two = rs.keyword_match("b0.0", "LangChain in Python", reqs)
    none = rs.keyword_match("b0.1", "Wrote FastAPI services", reqs)
    assert (one.band, two.band, none.band) == ("ADJACENT", "TRANSFERABLE", "GAP")
    assert (one.covers, two.covers, none.covers) == ([0], [0, 1], [])
    assert rs.keyword_match("x", "LangChain Python Go", reqs).score == 85


# --- reading the model's answer ----------------------------------------------------


def test_the_reading_is_taken_only_where_it_can_be_checked(base):
    profile = rs.analyse_posting(_Client(profile=PROFILE), base, _job())
    assert profile is not None
    assert profile.archetype == "individual contributor"
    assert [(r.text, r.must_have) for r in profile.requirements] == [
        ("LangChain agent development", True),
        ("Python", True),
        ("Kubernetes", False),
    ]
    # Only the pair whose posting term is in the posting and whose resume wording is in the resume.
    assert profile.terminology == {"orchestration frameworks": "LangChain pipelines"}
    assert profile.red_flags == ["Kubernetes never appears on the resume"]

    by_id = {m.item: m for m in profile.matches}
    assert "s9.9" not in by_id, "an id the resume does not have is ignored"
    assert by_id["b0.0"].score == 100 * 0.4 + 90 * 0.3 + 90 * 0.2 + 80 * 0.1
    # The model left Python off its covers; the keyword backfill adds it.
    assert by_id["b0.0"].covers == [0, 1]
    assert by_id["b0.1"].covers == [] and by_id["b0.1"].band == "WEAK"
    # Items the model skipped are scored from keyword overlap.
    assert by_id["s0.0"].covers == [1] and by_id["s0.0"].band == "ADJACENT"
    assert by_id["b0.2"].score == 0 and by_id["b0.2"].band == "GAP"
    assert [req.text for req in profile.gaps()] == ["Kubernetes"]


def test_axis_scores_are_clamped_and_junk_requirements_dropped(base):
    answer = {
        "requirements": [
            {"text": "  Python  ", "must_have": "yes", "keywords": ["Python", 3, "", "Python"]},
            {"text": "", "keywords": []},
            "not a requirement",
            {"keywords": ["x"]},
        ],
        "matches": [{"item": "b0.0", "direct": 250, "transferable": -5, "adjacent": "80", "impact": None, "covers": [0, 1, "a", 99]}],
    }
    profile = rs.analyse_posting(_Client(profile=answer), base, _job())
    assert [(r.text, r.must_have, r.keywords) for r in profile.requirements] == [("Python", True, ["Python"])]
    match = profile.matches[0]
    assert (match.direct, match.transferable, match.adjacent, match.impact) == (100, 0, 80, 0)
    assert match.covers == [0]


@pytest.mark.parametrize("answer", [None, {}, {"requirements": "none"}, {"requirements": []}, {"requirements": [{"text": " "}]}])
def test_no_usable_reading_means_no_profile(base, answer):
    assert rs.analyse_posting(_Client(profile=answer), base, _job()) is None


def test_no_llm_means_no_profile(base):
    assert rs.analyse_posting(_Client(profile=PROFILE, available=False), base, _job()) is None


def test_the_analysis_prompt_carries_the_posting_and_every_item(base):
    client = _Client(profile=PROFILE)
    rs.analyse_posting(client, base, _job())
    schema, prompt = client.prompts[0]
    assert "requirements" in schema and "Orchestration frameworks welcome" in prompt
    assert "b0.2: Grew the WildClawBench benchmark to 3 providers." in prompt
    assert "s1.1: AI / LLM: RAG" in prompt


# --- what reaches the edit ---------------------------------------------------------


def test_the_ranking_and_the_gaps_steer_the_edit(base):
    client = _Client(profile=PROFILE, edit={"bullets": [[0, 2, 1]], "notes": "Led with agents."})
    sections, notes = rs.tailor(client, base, _job())
    assert [schema[:20] for schema, _ in client.prompts] == ['{"archetype": "indiv', '{"subtitle": "...", ']
    edit_prompt = client.prompts[1][1]
    assert "role archetype: individual contributor" in edit_prompt
    assert 'must-have: ["LangChain agent development", "Python"]' in edit_prompt
    assert 'nice-to-have: ["Kubernetes"]' in edit_prompt
    assert '"orchestration frameworks": "LangChain pipelines"' in edit_prompt
    assert '"s1.0 DIRECT AI / LLM: LangChain"' in edit_prompt
    assert 'requirements nothing in the resume covers: ["Kubernetes"]' in edit_prompt
    assert "Reframe, never invent" in edit_prompt
    assert sections.bullets[0][1] == base.sections.bullets[0][2]
    assert notes[0] == (
        "posting read as individual contributor role: 2 must-have and 1 nice-to-have requirements; "
        "2 of 3 covered (67%): 2 direct, 0 transferable, 0 adjacent"
    )
    assert notes[1] == "gaps the resume does not cover: Kubernetes"
    assert notes[2] == "posting flags: Kubernetes never appears on the resume"
    assert notes[-1] == "model: Led with agents."


def test_a_profile_passed_in_is_not_read_again(base):
    client = _Client(profile=PROFILE, edit={})
    profile = rs.analyse_posting(client, base, _job())
    rs.tailor(client, base, _job(), profile, analyse=False)
    assert [schema[:12] for schema, _ in client.prompts] == ['{"archetype"', '{"subtitle":']


def test_without_a_reading_the_edit_runs_on_the_posting_alone(base):
    client = _Client(profile=None, edit={"notes": "nothing to change"})
    sections, notes = rs.tailor(client, base, _job())
    assert sections == base.sections
    assert notes == ["model: nothing to change"]
    assert "What the posting asks for" not in client.prompts[1][1]


def test_the_profile_cannot_add_a_claim(base):
    """A reading that names Kubernetes everywhere still cannot put it in the summary."""
    client = _Client(
        profile=PROFILE,
        edit={"summary": "I run Kubernetes clusters and build LangChain agents in Python. " * 7},
    )
    sections, notes = rs.tailor(client, base, _job())
    assert sections.summary == base.sections.summary
    assert any("Kubernetes" in note and "rejected" in note for note in notes)


def test_no_edit_proposal_still_reports_the_reading(base):
    _, notes = rs.tailor(_Client(profile=PROFILE, edit=None), base, _job())
    assert notes[0].startswith("posting read as individual contributor role")
    assert notes[-1] == "LLM gave no usable proposal; resume left as is"


# --- what tailoring.json keeps -----------------------------------------------------


def test_the_record_keeps_the_reading(base, monkeypatch, tmp_path):
    def _compile(tex_path, out_dir, compiler="", timeout_s=240):
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / (tex_path.stem + ".pdf")
        pdf.write_bytes(tex_path.read_bytes())
        return pdf

    monkeypatch.setattr(rs, "compile_pdf", _compile)
    monkeypatch.setattr(rs, "pdf_page_count", lambda path: 1)
    monkeypatch.setattr(rs, "find_compiler", lambda preferred="": ("tectonic", "/usr/bin/true"))
    settings = Settings(email="e", password="p", resume_path=str(base.path), resume_out_dir=str(tmp_path / "out"))
    client = _Client(profile=PROFILE, edit={"bullets": [[0, 2, 1]]})

    pdf, notes = rs.build_tailored_pdf(settings, client, _job())

    assert len(client.prompts) == 2, "the posting is read once per build"
    record = json.loads((pdf.parent / "tailoring.json").read_text())
    assert record["notes"] == notes
    analysis = record["analysis"]
    assert analysis["archetype"] == "individual contributor"
    assert analysis["gaps"] == ["Kubernetes"]
    assert analysis["coverage"]["percent"] == 67
    assert analysis["requirements"][0] == {
        "text": "LangChain agent development",
        "must_have": True,
        "keywords": ["LangChain", "agents"],
        "best_match": 100.0,
    }
    assert analysis["ranking"][0]["item"] == "s1.0" and analysis["ranking"][0]["band"] == "DIRECT"
    assert analysis["ranking"][-1]["band"] == "GAP"


def test_the_record_without_a_reading_says_so(base, monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "compile_pdf", lambda tex_path, out_dir, compiler="", timeout_s=240: (out_dir.mkdir(parents=True, exist_ok=True), (out_dir / (tex_path.stem + ".pdf")).write_bytes(b"pdf"), out_dir / (tex_path.stem + ".pdf"))[2])
    monkeypatch.setattr(rs, "pdf_page_count", lambda path: 1)
    monkeypatch.setattr(rs, "find_compiler", lambda preferred="": ("tectonic", "/usr/bin/true"))
    settings = Settings(email="e", password="p", resume_path=str(base.path), resume_out_dir=str(tmp_path / "out"))
    pdf, _ = rs.build_tailored_pdf(settings, _Client(profile=None, edit={}), _job())
    assert json.loads((pdf.parent / "tailoring.json").read_text())["analysis"] is None
