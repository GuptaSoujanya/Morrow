"""Scoring must not destroy relevant jobs, and the worklist must not lose rows.

Both defects were found by inspecting a real run on 5 October.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import cli, ranking
from naukri_bot.models import JobPosting, Profile, ScoredJob, Settings

DESC = ("Build agentic AI with Python, LangGraph, RAG, embeddings, vector "
        "search, prompt engineering and LLM evaluation.")


def _profile():
    return Profile(
        full_name="T",
        total_experience_years=3,
        skills=["Python", "RAG", "agentic AI", "embeddings", "vector search",
                "prompt engineering", "LLM evaluation"],
        titles=["AI Engineer", "Agentic AI Engineer", "Data Scientist"],
        preferred_locations=["Gurugram"],
    )


def _job(title):
    return JobPosting(job_id="x", url="u", title=title, company="A",
                      location="Gurugram", experience="2-5 Yrs",
                      posted_days_ago=1, description=DESC)


@pytest.mark.parametrize("title", [
    "Senior AI Engineer (Insurance Domain)",
    "AI Engineer - HR Tech",
    "Field Applications AI Engineer",
    "Data Scientist - Field Ops",
])
def test_a_domain_word_does_not_sink_a_matching_role(title):
    """These are the jobs the penalty was destroying.

    "Senior AI Engineer (Insurance Domain)" scored 17.2 against 67.2 for the
    same job titled "AI Engineer", and was rejected even at an LLM score of 80,
    because the penalty fired and the title bonus was skipped.
    """
    clean, _ = ranking.lexical_score(_profile(), _job("AI Engineer"))
    scored, reasons = ranking.lexical_score(_profile(), _job(title))
    assert scored == clean, (
        "%r scored %.1f against %.1f for the same job without the domain word"
        % (title, scored, clean)
    )


@pytest.mark.parametrize("title", [
    "Telecaller", "Sales Executive", "Field Sales Manager",
    "HR Recruiter", "Manual Testing Engineer",
])
def test_genuinely_wrong_roles_are_still_penalised(title):
    """The penalty must keep working where no preferred title matches."""
    scored, _ = ranking.lexical_score(_profile(), _job(title))
    clean, _ = ranking.lexical_score(_profile(), _job("AI Engineer"))
    assert scored < clean - 30, "%r was not penalised (%.1f)" % (title, scored)


def test_near_misses_are_reported(caplog):
    """A run that rejects most of its pool must say what it nearly took."""
    settings = Settings(email="t@e.com", password="p", min_score=55.0,
                        min_score_floor=0.0)
    ranked = [
        ScoredJob(job=JobPosting(job_id="hit", url="u", title="Taken",
                                 company="C"), score=60.0),
        ScoredJob(job=JobPosting(job_id="near", url="u", title="Near Miss",
                                 company="C"), score=51.0, reasons=["no preferred title match"]),
        ScoredJob(job=JobPosting(job_id="far", url="u", title="Far Off",
                                 company="C"), score=20.0),
    ]
    with caplog.at_level("INFO"):
        ranking.select_for_application(ranked, settings, lambda jid: False)

    text = caplog.text
    assert "Near Miss" in text, "a job just below the bar was not reported"
    assert "Far Off" not in text, "a job far below the bar should not be listed"


def test_a_piped_title_survives_the_worklist_round_trip(tmp_path, monkeypatch):
    """Naukri titles contain pipes; three saved roles were lost to this."""
    monkeypatch.chdir(tmp_path)
    job = JobPosting(job_id="1", url="https://naukri.com/job-listings-walkin",
                     title="Walk-in || GenAI Developer", company="TCS")
    cli._write_external_jobs([ScoredJob(job=job, score=70.0)], announce=False)

    # A second run must find it already present and not drop it.
    other = JobPosting(job_id="2", url="https://naukri.com/job-listings-other",
                       title="AI Engineer", company="Acme")
    cli._write_external_jobs([ScoredJob(job=other, score=65.0)], announce=False)

    written = (tmp_path / "external_jobs.md").read_text()
    rows = [l for l in written.splitlines() if l.startswith("| ") and not l.startswith("| score")]
    assert len(rows) == 2, "a row was lost on the second write:\n%s" % written
    assert "job-listings-walkin" in written
    assert "GenAI Developer" in written


def test_a_legacy_row_with_raw_pipes_is_not_dropped(tmp_path, monkeypatch):
    """Rows written before pipes were escaped must still survive a merge.

    This is the actual 5 October loss: external_jobs.md went from 17 rows to 14
    while reporting "0 new", because titles like "Walk-in || GenAI Developer"
    split into seven fields and were silently discarded on read-back. Escaping
    on write fixes new rows; only splitting from the right rescues the old ones.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "external_jobs.md").write_text(
        "# Roles that apply on the company site\n\n"
        "| score | role | company | posted | link |\n"
        "|---|---|---|---|---|\n"
        "| 74.9 | AI Engineer | Snowrelic | - | https://naukri.com/job-listings-keep1 |\n"
        "| 70.2 | Walk-in || GenAI Developer | TCS | - | https://naukri.com/job-listings-piped |\n"
        "| 68.0 | Lead | Acme || Labs | - | https://naukri.com/job-listings-piped2 |\n"
    )

    fresh = JobPosting(job_id="n", url="https://naukri.com/job-listings-new",
                       title="New Role", company="NewCo")
    cli._write_external_jobs([ScoredJob(job=fresh, score=60.0)], announce=False)

    written = (tmp_path / "external_jobs.md").read_text()
    for marker in ("job-listings-keep1", "job-listings-piped",
                   "job-listings-piped2", "job-listings-new"):
        assert marker in written, "%s was dropped:\n%s" % (marker, written)


def test_repeated_writes_never_lose_rows(tmp_path, monkeypatch):
    """The 5 October symptom: 17 rows became 14 while reporting '0 new'."""
    monkeypatch.chdir(tmp_path)
    jobs = [
        ScoredJob(
            job=JobPosting(job_id=str(i), url="https://naukri.com/job-listings-%d" % i,
                           title="Walk-in || Role %d" % i if i % 2 else "Role %d" % i,
                           company="Co"),
            score=70.0 - i,
        )
        for i in range(8)
    ]
    for _ in range(3):  # three runs over the same roles
        cli._write_external_jobs(jobs, announce=False)

    written = (tmp_path / "external_jobs.md").read_text()
    rows = [l for l in written.splitlines() if l.startswith("| ") and not l.startswith("| score")]
    assert len(rows) == 8, "expected 8 unique rows, got %d" % len(rows)
