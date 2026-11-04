"""MAX_YEARS_OVER is a hard cut on required experience, before and after the model.

On 2026-11-03 the bot applied to 218 jobs wanting more than 3 years against a
2.9-year profile: the lexical penalty was 10 points and the model was only told
to "penalise", so skill overlap carried them over MIN_SCORE anyway.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import config, llm
from common.models import JobPosting, Profile, Settings
from naukri_bot import ranking


class _NoLLM:
    def available(self):
        return False


class _Model:
    """Scores every job 90 and reports the gaps it is given."""

    def __init__(self, gaps):
        self.gaps = gaps
        self.settings = Settings()

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        import json
        jobs = json.loads(prompt.split("Jobs: ", 1)[1])
        return {"jobs": [
            {"job_id": job["job_id"], "score": 90, "verdict": "strong", "reasons": [],
             "gaps": self.gaps.get(job["job_id"], [])}
            for job in jobs
        ]}


def _job(number, experience="", description="python fastapi react", title="Software Engineer"):
    return JobPosting(job_id="j%d" % number, url="https://example.test/%d" % number, title=title,
                      company="Acme", experience=experience, description=description)


def _profile(years=2.9):
    return Profile(full_name="T", skills=["Python", "FastAPI", "React"], titles=["Software Engineer"],
                   total_experience_years=years)


@pytest.mark.parametrize("experience,description,expected", [
    ("4-7 Yrs", "", 4.0),
    ("2-5 Yrs", "8+ years of experience", 2.0),
    ("", "5+ years of experience in Python", 5.0),
    ("", "Minimum 4 years of professional software engineering experience", 4.0),
    ("", "3 to 6 years of relevant experience", 3.0),
    ("", "0-3 years of experience", 0.0),
    ("", "a company with 36 years of experience in banking; 6+ years of experience required", 6.0),
    ("", "We have 20 years of experience serving clients", None),
    ("", "built 3 years ago", None),
    ("Not Disclosed", "", None),
    # #21: a company's, founders' or team's years come first and are not the requirement.
    ("", "With over 12 years of experience in fintech, Acme is hiring. 0-2 years experience required.", 0.0),
    ("", "Our founders bring 10+ years of experience at Google. You: 2+ years of experience with Python.", 2.0),
    ("", "Experience: 1 to 3 years. Our team has 8 years of combined experience.", 1.0),
    ("", "Acme has 9 years of experience serving banks. We need an engineer with 2 years of experience.", 2.0),
    ("", "Experience Required: 2-4 Yrs", 2.0),
    ("", "Experience - 5+ years in backend development", 5.0),
])
def test_required_years_reads_the_card_first_then_the_description(experience, description, expected):
    assert ranking.required_years(_job(1, experience, description)) == expected


def test_postings_over_the_bound_are_dropped_before_scoring(caplog):
    jobs = [_job(1, "2-4 Yrs"), _job(2, "4-7 Yrs"), _job(3, "", "5+ years of experience"),
            _job(4, "", "3+ years of experience"), _job(5, "Not Disclosed", "no years stated")]
    with caplog.at_level("INFO"):
        ranked = ranking.rank(_profile(), jobs, _NoLLM(), Settings(llm_rank_top_n=10))
    assert sorted(item.job.job_id for item in ranked) == ["j1", "j4", "j5"]
    assert "dropped 2 of 5 postings asking for more than 3.9 years" in caplog.text


def test_unknown_candidate_years_or_a_negative_bound_disable_the_gate():
    jobs = [_job(1, "8-12 Yrs")]
    assert len(ranking.rank(_profile(years=None), jobs, _NoLLM(), Settings(llm_rank_top_n=10))) == 1
    assert len(ranking.rank(_profile(), jobs, _NoLLM(), Settings(llm_rank_top_n=10, max_years_over=-1))) == 1


def test_the_gate_is_a_cut_not_a_penalty():
    jobs = [_job(1, "6-9 Yrs")]
    assert ranking.rank(_profile(), jobs, _NoLLM(), Settings(llm_rank_top_n=10, min_score=0)) == []


@pytest.mark.parametrize("gaps,expected", [
    (["5+ years of Java"], "5+ years of Java"),
    (["4-7 years of experience"], "4-7 years of experience"),
    (["Senior-level experience"], "Senior-level experience"),
    (["staff level engineering experience"], "staff level engineering experience"),
    (["Kubernetes", "3+ years of Python"], None),
    (["Kafka"], None),
    ([], None),
])
def test_experience_gap_names_the_disqualifying_gap(gaps, expected):
    assert ranking.experience_gap(gaps, 3.9) == expected


def test_experience_gap_is_ignored_without_a_bound():
    assert ranking.experience_gap(["10+ years of experience"], None) is None


def test_model_reported_gaps_rule_a_high_scoring_job_out(caplog):
    jobs = [_job(1), _job(2), _job(3)]
    model = _Model({"j2": ["6+ years of backend experience"], "j3": ["Senior-level experience", "Go"]})
    with caplog.at_level("INFO"):
        ranked = ranking.rank(_profile(), jobs, model, Settings(llm_rank_top_n=10))
    assert [item.job.job_id for item in ranked] == ["j1"]
    assert ranked[0].llm_score == 90
    assert "dropped 2 of 3 ranked jobs whose reported gaps exceed 3.9 years" in caplog.text


def test_a_survivable_gap_keeps_the_job():
    jobs = [_job(1)]
    ranked = ranking.rank(_profile(), jobs, _Model({"j1": ["Kubernetes", "2+ years of Go"]}), Settings(llm_rank_top_n=10))
    assert [item.job.job_id for item in ranked] == ["j1"]
    assert ranked[0].gaps == ["Kubernetes", "2+ years of Go"]


def test_max_years_over_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_YEARS_OVER", "2.5")
    settings = config.load_settings(overrides={"email": "t@example.com", "password": "x"})
    assert settings.max_years_over == 2.5
    assert ranking.years_bound(_profile(), settings) == pytest.approx(5.4)
    assert Settings().max_years_over == 1.0


def test_the_model_is_told_the_candidate_years_not_a_hardcoded_figure():
    captured = {}

    class _Recorder:
        settings = Settings()

        def available(self):
            return True

        def complete_json(self, prompt, schema):
            captured["prompt"] = prompt
            return {"jobs": []}

    llm.score_jobs(_Recorder(), _profile(years=2.9), [_job(1)])
    assert "a roughly 2.9-year candidate" in captured["prompt"]
    assert "2.5-year" not in captured["prompt"]
    llm.score_jobs(_Recorder(), _profile(years=None), [_job(1)])
    assert "more years than this candidate has" in captured["prompt"]


def test_a_company_describing_its_own_experience_does_not_cut_a_junior_posting():
    job = _job(1, description="Acme has 9 years of experience serving banks. We need an engineer with 2 years of experience.")
    kept, dropped = ranking.drop_over_experienced([job], _profile(2.9), Settings())
    assert (kept, dropped) == ([job], 0)
