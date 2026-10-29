"""A number must pick the band it falls in.

On 29 October a Naukri form offered "Current Salary (LPA)*" as 37 bands. The
saved answer "16" named none of them literally, so the whole application went
to the model and then to the user, for a question the facts already answered.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import answers

LPA_BANDS = [
    "Less than 3 LPA", "3 - 6 LPA", "6 - 9 LPA", "9 - 12 LPA", "12 - 15 LPA",
    "15 - 18 LPA", "18 - 21 LPA", "More than 150 LPA",
]


@pytest.mark.parametrize("given, expected", [
    ("16", "15 - 18 LPA"),
    ("16 LPA", "15 - 18 LPA"),
    ("20", "18 - 21 LPA"),
    ("2.5", "Less than 3 LPA"),
    ("200", "More than 150 LPA"),
    ("6", "6 - 9 LPA"),
])
def test_a_salary_picks_its_band(given, expected):
    assert answers.match_option(given, LPA_BANDS) == expected


@pytest.mark.parametrize("given", [
    "Yes",
    "Immediate",
    "I earn sixteen",
    "Between 10 and 40 depending on the role",
])
def test_an_answer_that_is_not_a_number_is_left_alone(given):
    assert answers.match_option(given, LPA_BANDS) is None


def test_a_number_outside_every_band_matches_nothing():
    assert answers.match_option("100", ["3 - 6 LPA", "6 - 9 LPA"]) is None


def test_years_bands_work_the_same():
    options = ["0-1 years", "1-3 years", "3-5 years", "5+ years"]
    assert answers.match_option("2.9 years", options) == "1-3 years"
    assert answers.match_option("7", options) == "5+ years"


def test_a_notice_period_at_the_edge_of_a_band_still_matches():
    assert answers.match_option("15 days", ["0-15 days", "16-30 days"]) == "0-15 days"


def test_an_exact_option_still_wins_over_a_band():
    assert answers.match_option("3", ["3", "3 - 6 LPA"]) == "3"


def test_a_profile_number_fills_a_banded_dropdown(tmp_path, monkeypatch):
    from common.ledger import Ledger
    from common.models import Profile, Settings

    class NoLLM:
        def available(self):
            return False

    monkeypatch.chdir(tmp_path)
    engine = answers.AnswerEngine(
        Ledger(":memory:"),
        NoLLM(),
        Profile(full_name="T", current_ctc_lpa=16),
        Settings(data_dir=str(tmp_path)),
    )
    resolution = engine.resolve("Current Salary (LPA)*", options=LPA_BANDS)
    assert resolution.answer is not None
    assert resolution.answer.text == "15 - 18 LPA"
    assert resolution.answer.grounded_in == "current_ctc_lpa"


@pytest.mark.parametrize("answer, options, picked", [
    ("2.9", ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"], "3"),
    ("2.9 years", ["0", "1", "2", "3", "4", "5"], "3"),
    ("3", ["0", "1", "2", "3", "4", "5"], "3"),
    ("2.5", ["0", "1", "2", "3", "4"], "3"),
    ("16", ["5", "10", "15", "20", "25"], "15"),
    ("0", ["0", "1", "2"], "0"),
    ("15", ["0", "15", "30", "60", "90"], "15"),
    ("20", ["0", "15", "30", "60", "90"], "15"),
    ("99", ["0", "1", "2"], "2"),
])
def test_a_list_of_plain_numbers_takes_the_closest_one_rounding_a_tie_up(answer, options, picked):
    assert answers.match_band(answer, options) == picked


def test_a_number_never_picks_from_a_list_that_is_not_numeric():
    assert answers.match_band("2.9", ["Fresher", "Experienced", "Student"]) is None
    assert answers.match_band("2.9", ["0", "1", "Not applicable"]) is None
