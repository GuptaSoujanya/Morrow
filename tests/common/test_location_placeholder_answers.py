"""A location dropdown that names the person's city is never answered 'Others'.

The 2026-11-14 audit found the saved Naukri answer for 'What is your current
location?' was 'Others' against a Gurugram profile, and that it went out with
every Naukri apply, failing each recruiter's city filter.
"""
from common.answers import AnswerEngine, real_location_names
from common.ledger import Ledger
from common.models import Answer, AnswerResolution, AnswerSource, Profile, Settings


class Client:
    def available(self):
        return True

    def complete_json(self, prompt, schema):
        return None


def engine(tmp_path, **profile_kwargs):
    values = dict(current_location="Gurugram, India",
                  preferred_locations=["Pune", "Remote"],
                  extra_facts={"hometown": "Indore"})
    values.update(profile_kwargs)
    profile = Profile(full_name="Test", **values)
    return AnswerEngine(Ledger(":memory:"), Client(), profile,
                        Settings(data_dir=str(tmp_path / "inputs"), judge_answers=False))


def placeholder(engine_, question, options):
    engine_._current_options = options
    engine_._cache_fingerprint = "fp"
    return engine_._accept(
        question,
        AnswerResolution.resolved(Answer(text="Others", source=AnswerSource.LLM)),
        "select",
        persist=False,
    )


def test_the_current_city_is_offered_as_a_name_to_match(tmp_path):
    assert "Gurugram, India" in real_location_names(engine(tmp_path).profile)


def test_a_city_written_with_a_country_matches_the_boards_own_wording(tmp_path):
    for rendered in ("Gurgaon", "Gurgaon / Gurugram", "Gurugram"):
        result = placeholder(engine(tmp_path), "What is your current location?",
                             ["Bengaluru", rendered, "Others"])
        assert result.answer.text == rendered, rendered


def test_remote_is_not_offered_as_a_real_city(tmp_path):
    assert "Remote" not in real_location_names(engine(tmp_path).profile)


def test_current_city_is_preferred_over_a_preferred_location(tmp_path):
    names = real_location_names(engine(tmp_path).profile)
    assert names.index("Gurugram, India") < names.index("Pune")


def test_the_current_city_wins_when_the_list_offers_both(tmp_path):
    result = placeholder(engine(tmp_path), "Current city", ["Pune", "Gurgaon", "Others"])
    assert result.answer.text == "Gurgaon"


def test_dropdown_offering_the_city_is_answered_with_the_city(tmp_path):
    result = placeholder(engine(tmp_path), "What is your current location?",
                         ["Bengaluru", "Gurugram", "Others"])
    assert not result.abstained
    assert result.answer.text == "Gurugram"
    assert result.answer.source == AnswerSource.PROFILE
    assert result.answer.grounded_in == "current_location"


def test_dropdown_falls_back_to_a_preferred_city_then_the_hometown(tmp_path):
    assert placeholder(engine(tmp_path), "Current city",
                       ["Pune", "Others"]).answer.text == "Pune"
    assert placeholder(engine(tmp_path), "Current city",
                       ["Indore", "Others"]).answer.text == "Indore"


def test_dropdown_without_any_of_the_cities_keeps_the_only_honest_pick(tmp_path):
    result = placeholder(engine(tmp_path), "What is your current location?",
                         ["Bengaluru", "Chennai", "Others"])
    assert not result.abstained
    assert result.answer.text == "Others"


def test_a_list_whose_only_match_is_itself_a_placeholder_keeps_it(tmp_path):
    result = placeholder(engine(tmp_path, preferred_locations=["Remote"]),
                         "Which city do you currently live in?", ["Remote", "Others"])
    assert not result.abstained
    assert result.answer.text == "Others"


def test_a_free_text_location_question_is_unchanged(tmp_path):
    subject = engine(tmp_path)
    subject._current_options = None
    subject._cache_fingerprint = "fp"
    result = subject._accept(
        "What is your current location?",
        AnswerResolution.resolved(Answer(text="Others", source=AnswerSource.LLM)),
        "text",
        persist=False,
    )
    assert result.abstained


def test_a_relocation_question_is_not_treated_as_a_location_question(tmp_path):
    result = placeholder(engine(tmp_path), "Are you willing to relocate?",
                         ["Yes", "No", "Others"])
    assert not result.abstained
    assert result.answer.text == "Others"
