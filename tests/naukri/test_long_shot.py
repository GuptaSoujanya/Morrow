"""A posting above the profile's level is still applied to, but it is named a long shot.

On 2026-11-11 the user widened the net to roles asking 3 to 5 years and to senior
titles. The report must say which applications those were, so a silence from them
is read as expected and a call back from one is read as a reason to widen further.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import JobPosting
from naukri_bot.ranking import long_shot_reason


def _job(title="Backend Developer", experience="", description=""):
    return JobPosting(job_id="j1", url="https://x/j1", title=title, experience=experience, description=description)


def test_a_posting_within_range_is_not_a_long_shot():
    assert long_shot_reason(_job(experience="2-4 Yrs"), 2.9) == ""


def test_more_years_than_the_profile_has_is_named():
    assert long_shot_reason(_job(experience="5-8 Yrs"), 2.9) == "asks 5+ years, profile has 2.9"


def test_years_stated_only_in_the_description_count_too():
    job = _job(description="You bring 4+ years of experience with Python services.")
    assert long_shot_reason(job, 2.9) == "asks 4+ years, profile has 2.9"


@pytest.mark.parametrize("title, word", [
    ("Senior Software Engineer", "Senior"),
    ("Sr. Backend Developer", "Sr"),
    ("Tech Lead - Platform", "Lead"),
    ("Staff Engineer", "Staff"),
    ("Principal Engineer", "Principal"),
    ("Head of Engineering", "Head"),
    ("Solutions Architect", "Architect"),
    ("Director of Engineering", "Director"),
])
def test_a_senior_title_is_named(title, word):
    assert long_shot_reason(_job(title=title, experience="2-4 Yrs"), 2.9) == "senior title (%s)" % word


def test_both_reasons_are_joined():
    assert long_shot_reason(_job(title="Senior Engineer", experience="6-9 Yrs"), 2.9) == (
        "asks 6+ years, profile has 2.9; senior title (Senior)"
    )


def test_without_a_profile_figure_only_the_title_can_speak():
    assert long_shot_reason(_job(experience="6-9 Yrs"), None) == ""
    assert long_shot_reason(_job(title="Senior Engineer", experience="6-9 Yrs"), None) == "senior title (Senior)"


def test_a_word_inside_another_word_does_not_match():
    # "Leadership", "Headless": not the Lead/Head of a senior title.
    assert long_shot_reason(_job(title="Leadership Program Engineer, Headless CMS"), 2.9) == ""
