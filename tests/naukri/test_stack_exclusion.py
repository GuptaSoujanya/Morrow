"""EXCLUDE_SKILLS drops postings built on a stack the profile does not list.

Generic KEYWORDS such as "Software Engineer" return every stack. On
2026-11-03, 310 of the 892 applied jobs with gaps were Java, Spring, .NET,
Go, Angular or Django shops that cleared MIN_SCORE on Git, REST, SQL and
Docker plus title and freshness.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import config
from common.models import DEFAULT_EXCLUDE_SKILLS, JobPosting, Profile, Settings
from naukri_bot import ranking


class _NoLLM:
    def available(self):
        return False


def _job(number, title="Software Engineer", tags=(), description="python fastapi react"):
    return JobPosting(job_id="j%d" % number, url="https://example.test/%d" % number, title=title,
                      company="Acme", tags=list(tags), description=description)


def _profile(skills=("Python", "FastAPI", "React", "Docker")):
    return Profile(full_name="T", skills=list(skills), titles=["Software Engineer"])


@pytest.mark.parametrize("title,tags,expected", [
    ("Java Developer", (), "Java"),
    ("Software Engineer", ("Spring Boot", "Microservices"), "Spring"),
    (".NET Developer", (), ".NET"),
    ("Software Engineer", ("C#", "Azure"), "C#"),
    ("Golang Engineer", (), "Golang"),
    ("Go Developer", (), "Go"),
    ("Angular Developer", (), "Angular"),
    ("Backend Developer", ("Django", "PostgreSQL"), "Django"),
    ("Software Engineer", ("Python", "FastAPI"), None),
    ("Software Engineer", ("JavaScript", "Mongodb"), None),
    ("Django Developer", (), "Django"),
])
def test_the_title_or_the_tags_name_the_stack(title, tags, expected):
    assert ranking.foreign_stack(_job(1, title, tags), _profile(), Settings()) == expected


def test_a_description_only_mention_does_not_cut():
    job = _job(1, description="python fastapi; Java a plus")
    assert ranking.foreign_stack(job, _profile(), Settings()) is None


def test_whole_terms_only():
    assert ranking.foreign_stack(_job(1, "JavaScript Engineer"), _profile(), Settings()) is None
    assert ranking.foreign_stack(_job(1, "Software Engineer", ("Golang",)), _profile(), Settings(exclude_skills=["Go"])) is None
    assert ranking.foreign_stack(_job(1, "Swift Delivery Engineer"), _profile(), Settings()) == "Swift"


@pytest.mark.parametrize("title,tags,skills,expected", [
    ("Solutions Engineer (Go-to-Market)", (), ("Python",), None),
    ("AI Engineer, GTM / go-to-market", (), ("Python",), None),
    ("Go Developer", (), ("Golang",), None),
    ("Software Engineer", ("Go",), ("Golang",), None),
    ("Golang Engineer", (), ("Go",), None),
    ("Go Developer", (), ("Python",), "Go"),
    (".NET Developer", (), ("ASP.NET Core", "C#"), None),
    ("ASP.NET Developer", (), ("Python",), ".NET"),
    ("VB.NET Developer", (), ("Python",), ".NET"),
    ("Software Engineer", ("C#",), ("C#", ".NET"), None),
    ("Django-based Backend Developer", (), ("Python",), None),
])
def test_issue_12_cases(title, tags, skills, expected):
    """Hyphens join words, Go and Golang are one stack, and .NET is inside ASP.NET."""
    assert ranking.foreign_stack(_job(1, title, tags), _profile(skills), Settings()) == expected


def test_the_log_names_the_dropped_postings(caplog):
    jobs = [_job(1, "Java Backend Developer"), _job(2, "Go Developer")]
    with caplog.at_level("INFO"):
        ranking.drop_foreign_stacks(jobs, _profile(), Settings())
    assert "Java Backend Developer (Java); Go Developer (Go)" in caplog.text


def test_a_stack_the_profile_lists_is_not_foreign():
    profile = _profile(("Python", "Java", "Spring Boot"))
    assert ranking.foreign_stack(_job(1, "Java Developer"), profile, Settings()) is None
    assert ranking.foreign_stack(_job(1, "Software Engineer", ("Spring",)), profile, Settings()) is None
    assert ranking.foreign_stack(_job(1, "Software Engineer", ("Angular",)), profile, Settings()) == "Angular"


def test_rank_drops_foreign_stacks_before_scoring(caplog):
    jobs = [_job(1), _job(2, "Java Backend Developer"), _job(3, tags=("Angular", "TypeScript")),
            _job(4, description="Java a plus")]
    with caplog.at_level("INFO"):
        ranked = ranking.rank(_profile(), jobs, _NoLLM(), Settings(llm_rank_top_n=10))
    assert sorted(item.job.job_id for item in ranked) == ["j1", "j4"]
    assert "dropped 2 of 4 postings for EXCLUDE_SKILLS the profile does not list (Angular 1, Java 1)" in caplog.text


def test_exclude_skills_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("EXCLUDE_SKILLS", "Rust, Scala")
    settings = config.load_settings(overrides={"email": "t@example.com", "password": "x"})
    assert settings.exclude_skills == ["Rust", "Scala"]
    assert ranking.foreign_stack(_job(1, "Scala Developer"), _profile(), settings) == "Scala"
    assert ranking.foreign_stack(_job(1, "Java Developer"), _profile(), settings) is None
    monkeypatch.setenv("EXCLUDE_SKILLS", "")
    assert config.load_settings(overrides={"email": "t@example.com", "password": "x"}).exclude_skills == []
    assert list(DEFAULT_EXCLUDE_SKILLS) == Settings().exclude_skills
