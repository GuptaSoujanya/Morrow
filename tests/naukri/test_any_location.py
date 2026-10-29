"""ANY_LOCATION must make every city score alike, and search the whole country.

The preferred cities run dry long before Naukri's own daily apply cap, so a day
can end with quota left and nothing eligible to spend it on.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import auth, cli, ranking, sources
from common import browser, llm
from common.models import JobPosting, LoginResult, Profile, Settings

DESC = ("Build agentic AI with Python, LangGraph, RAG, embeddings and LLM "
        "evaluation.")


def _profile():
    return Profile(
        full_name="T",
        total_experience_years=3,
        skills=["Python", "RAG", "agentic AI", "embeddings", "LLM evaluation"],
        titles=["AI Engineer"],
        preferred_locations=["Gurugram"],
    )


def _job(location):
    return JobPosting(job_id=location, url="u", title="AI Engineer",
                      company="A", location=location, experience="2-5 Yrs",
                      posted_days_ago=1, description=DESC)


def _settings(**kwargs):
    return Settings(min_score=40, llm_rank_top_n=50, **kwargs)


def _ranked(settings):
    jobs = [_job("Gurugram"), _job("Hyderabad")]
    return {
        item.job.location: item.score
        for item in ranking.rank(_profile(), jobs, llm.NullClient(), settings)
    }


def test_an_unlisted_city_is_scored_like_a_preferred_one():
    scores = _ranked(_settings(any_location=True))
    assert scores["Hyderabad"] == scores["Gurugram"]


def test_without_it_an_unlisted_city_still_loses_points():
    scores = _ranked(_settings())
    assert scores["Hyderabad"] < scores["Gurugram"]


def test_turning_it_on_says_so(caplog):
    with caplog.at_level("INFO"):
        _ranked(_settings(any_location=True))
    assert "ANY_LOCATION is on" in caplog.text
    assert "Gurugram" in caplog.text


def test_the_judge_is_told_to_ignore_location_when_no_city_is_preferred():
    asked = {}

    class Client:
        def available(self):
            return True

        def complete_json(self, prompt, schema):
            asked["prompt"] = prompt
            return {"jobs": []}

    open_profile = Profile(full_name="T", titles=["AI Engineer"])
    llm.score_jobs(Client(), open_profile, [_job("Hyderabad")])
    assert '"open_to_any_location": true' in asked["prompt"]
    assert "ignore which city it is in" in asked["prompt"]


def test_a_job_she_could_not_legally_take_is_still_a_poor_match():
    """Searching every location brought up San Francisco roles needing US work authorisation;
    each one reached the browser agent before anybody noticed she cannot take it."""
    asked = {}

    class Client:
        def available(self):
            return True

        def complete_json(self, prompt, schema):
            asked["prompt"] = prompt
            return {"jobs": []}

    open_profile = Profile(
        full_name="T",
        titles=["AI Engineer"],
        work_authorization="Indian citizen, authorised to work in India; no visa sponsorship needed",
    )
    llm.score_jobs(Client(), open_profile, [_job("San Francisco")])

    assert '"work_authorization": "Indian citizen' in asked["prompt"]
    assert "Score 0 for a job the candidate could not legally take" in asked["prompt"]
    assert "visa sponsorship" in asked["prompt"]


def test_a_candidate_with_cities_is_still_judged_on_them():
    asked = {}

    class Client:
        def available(self):
            return True

        def complete_json(self, prompt, schema):
            asked["prompt"] = prompt
            return {"jobs": []}

    llm.score_jobs(Client(), _profile(), [_job("Hyderabad")])
    assert '"open_to_any_location": false' in asked["prompt"]
    assert "Gurugram" in asked["prompt"]


@pytest.mark.parametrize("any_location, searched", [(True, ""), (False, "Pune")])
def test_the_search_drops_the_city_filter_only_when_asked(
    monkeypatch, tmp_path, any_location, searched
):
    monkeypatch.chdir(tmp_path)
    asked = {}

    class Client:
        def available(self):
            return True

    monkeypatch.setattr(llm, "build_client", lambda settings: Client())
    monkeypatch.setattr(browser, "create_driver", lambda settings: object())
    monkeypatch.setattr(
        auth,
        "ensure_logged_in",
        lambda driver, settings: LoginResult(ok=True, reason="session_reused"),
    )

    def _collect(driver, settings, keywords, location=""):
        asked["location"] = location
        return []

    monkeypatch.setattr(sources, "collect_candidates", _collect)

    settings = _settings(any_location=any_location)
    settings.location = "Pune"
    settings.keywords = ["AI Engineer"]
    settings.db_path = str(tmp_path / "t.db")
    cli.run(settings, _profile())

    assert asked["location"] == searched


def test_a_search_with_no_city_filter_asks_naukri_for_the_whole_country():
    everywhere = sources._search_url("AI Engineer", "", 1, True)
    one_city = sources._search_url("AI Engineer", "Pune", 1, True)
    assert "&l=" not in everywhere and "?l=" not in everywhere
    assert "l=Pune" in one_city
