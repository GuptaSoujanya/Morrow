"""The skill component scores what a posting names, not the whole profile list.

Dividing matched skills by all 41 profile skills gave five matches about 5 of
40 points. Of 5,999 scored jobs the best reached 76.7 and none 80, so the
STRONG verdict at 75 was unreachable and MIN_SCORE could not separate a good
fit from a weak one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import JobPosting, Profile
from naukri_bot import ranking


FORTY_ONE = ["Python", "FastAPI", "React", "Docker", "AWS Bedrock", "LangChain", "RAG", "TypeScript"] + [
    "Skill%d" % n for n in range(33)
]


def _job(description, title="Software Engineer"):
    return JobPosting(job_id="j1", url="https://example.test/1", title=title, company="Acme",
                      description=description, posted_days_ago=0.5, experience="2-4 Yrs", location="Pune")


def _profile(skills):
    return Profile(full_name="T", skills=skills, titles=["Software Engineer"], total_experience_years=2.9,
                   preferred_locations=["Pune"])


def _skill_component(skills, description):
    scored, _ = ranking.lexical_score(_profile(skills), _job(description))
    bare, _ = ranking.lexical_score(_profile(skills), _job("nothing the profile lists"))
    return round(scored - bare, 2)


def test_five_of_forty_one_skills_earn_well_over_half_the_component():
    assert _skill_component(FORTY_ONE, "Python FastAPI React Docker LangChain") == 25.0


def test_eight_matches_fill_the_component_whatever_the_profile_length():
    assert _skill_component(FORTY_ONE, " ".join(FORTY_ONE[:8])) == 40.0
    assert _skill_component(FORTY_ONE, " ".join(FORTY_ONE[:20])) == 40.0


def test_no_match_still_scores_nothing():
    assert _skill_component(FORTY_ONE, "Java Spring Boot Kafka") == 0.0


def test_a_short_profile_is_unchanged():
    three = ["Python", "FastAPI", "React"]
    assert _skill_component(three, "Python FastAPI React") == 40.0
    assert _skill_component(three, "Python") == pytest.approx(40.0 / 3, abs=0.01)


def test_a_well_matched_posting_can_now_reach_the_strong_verdict_lexically():
    scored, reasons = ranking.lexical_score(_profile(FORTY_ONE), _job(" ".join(FORTY_ONE[:8])))
    assert scored >= 75.0, reasons
    assert any(reason.startswith("8 skill matches") for reason in reasons)
