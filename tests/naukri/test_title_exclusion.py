"""EXCLUDE_TITLES is a hard cut before ranking, not a penalty a good skills match can outscore.

The 2026-11-03 run applied to Senior, Lead and QA postings that cleared MIN_SCORE
on skill overlap alone.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import config
from common.models import DEFAULT_EXCLUDE_TITLES, JobPosting, Profile, Settings
from naukri_bot import ranking


class _NoLLM:
    def available(self):
        return False


def _job(number, title):
    return JobPosting(job_id="j%d" % number, url="https://example.test/%d" % number, title=title, company="Acme",
                      description="python fastapi react")


@pytest.mark.parametrize("title", [
    "Senior Software Engineer", "Sr. Backend Developer", "Tech Lead - Python", "Staff Engineer",
    "Principal Engineer", "Head of Engineering", "Solutions Architect", "Software Engineering Intern",
    "QA Engineer", "SDET II", "Data Analyst",
])
def test_every_default_word_excludes_the_title(title):
    assert ranking.excluded_title(title, Settings()) is not None


@pytest.mark.parametrize("title", [
    "Software Engineer", "Backend Developer (Python)", "Full Stack Developer", "Seniority Platform Engineer",
    "Leadership Platform Engineer", "Internal Tools Engineer",
])
def test_whole_words_only(title):
    assert ranking.excluded_title(title, Settings()) is None


def test_rank_drops_excluded_titles_before_scoring(caplog):
    jobs = [_job(1, "Software Engineer"), _job(2, "Senior Software Engineer"), _job(3, "QA Engineer")]
    profile = Profile(full_name="T", skills=["Python", "FastAPI", "React"], titles=["Software Engineer"])
    with caplog.at_level("INFO"):
        ranked = ranking.rank(profile, jobs, _NoLLM(), Settings(llm_rank_top_n=10))
    assert [item.job.job_id for item in ranked] == ["j1"]
    assert "dropped 2 of 3 postings for EXCLUDE_TITLES" in caplog.text


def test_exclude_titles_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("EXCLUDE_TITLES", "Manager, Intern")
    settings = config.load_settings(overrides={"email": "t@example.com", "password": "x"})
    assert settings.exclude_titles == ["Manager", "Intern"]
    assert ranking.excluded_title("Engineering Manager", settings) == "Manager"
    assert ranking.excluded_title("Senior Engineer", settings) is None
    monkeypatch.setenv("EXCLUDE_TITLES", "")
    assert config.load_settings(overrides={"email": "t@example.com", "password": "x"}).exclude_titles == []
    assert list(DEFAULT_EXCLUDE_TITLES) == Settings().exclude_titles
