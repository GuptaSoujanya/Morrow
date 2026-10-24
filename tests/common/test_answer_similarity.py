"""Local screening paraphrases must preserve the meaning of a saved answer."""
import pytest

from common.answer_similarity import SimilarityMatch, is_job_dependent, match


def saved(question, answer="saved answer"):
    return [([question], answer)]


@pytest.mark.parametrize("stored,question,answer", [
    ("What is your notice period?", "How soon can you join?", "30 days"),
    ("Notice period", "Please mention your notice periods", "30 days"),
    ("What is your total experience?", "How many years have you worked?", "2.5"),
    ("Total professional experience in years", "Years of overall work experience", "2.5"),
    ("How many years of experience do you have in Python?", "How long have you used Python?", "2"),
    ("Years of experience with PySpark", "Please specify your total years using PySpark", "1"),
    ("Current CTC", "What is your current compensation?", "6 LPA"),
    ("Expected CTC", "Please state your salary expectation", "10 LPA"),
    ("What is your current annual salary in INR?", "Current compensation per annum in INR", "600000"),
    ("Are you willing to relocate?", "Would you be open to relocating?", "Yes"),
    ("Are you willing to relocate to Pune?", "Would you relocate to Pune?", "Yes"),
    ("Are you comfortable with rotational shifts?", "Would you be willing to work rotational shifts?", "No"),
    ("Do you have experience with C++?", "Have you used C++?", "Yes"),
    ("What is your current location?", "Where are you currently based?", "Indore"),
])
def test_known_paraphrases_reuse_only_the_saved_answer(stored, question, answer):
    result = match(question, saved(stored, answer))
    assert isinstance(result, SimilarityMatch)
    assert result.answer == answer
    assert result.matched_question == stored
    assert result.method == "intent_tfidf"
    assert 0.85 <= result.score <= 1.0


@pytest.mark.parametrize("stored,question", [
    ("What is your current CTC?", "What is your expected CTC?"),
    ("Current CTC", "What is your CTC?"),
    ("Current annual salary", "Current monthly salary"),
    ("Current salary in INR", "Current salary in USD"),
    ("Current salary in £", "Current salary in $"),
    ("Current salary in £", "Current salary"),
    ("Current salary in ₩", "Current salary"),
    ("Current salary in ₩", "Current salary in ₽"),
    ("Current gross salary", "Current net salary"),
    ("Current fixed compensation", "Current variable compensation"),
    ("Current salary", "Current take-home salary"),
    ("How many years of Python experience?", "How many years of PySpark experience?"),
    ("How many years of Java experience?", "How many years of JavaScript experience?"),
    ("How many years of C experience?", "How many years of C++ experience?"),
    ("How many years of C++ experience?", "How many years of C# experience?"),
    ("How many years of total experience?", "How many years of Python experience?"),
    ("How many years have you worked?", "How many years will you work?"),
    ("How many years of Python experience?", "How many months of Python experience?"),
    ("How many years of Python experience?", "Do you have Python experience?"),
    ("How many years of Python experience?", "How many years of professional Python experience?"),
    ("How many years of Python experience?", "How many years of production Python experience?"),
    ("How many years of Python experience?", "How many years of Python and Java experience?"),
    ("How many years of Python experience?", "How many years of Python 3 experience?"),
    ("Are you willing to relocate to India?", "Are you willing to relocate to Canada?"),
    ("Are you willing to relocate?", "Are you willing to relocate to Mumbai?"),
    ("Are you willing to relocate?", "Have you relocated previously?"),
    ("Are you willing to work night shifts?", "Have you worked night shifts?"),
    ("Have you worked night shifts?", "Do you work night shifts?"),
    ("Have you worked?", "Are you working?"),
    ("Are you comfortable with night shifts?", "Have you been comfortable with night shifts?"),
    ("Are you willing to work remotely?", "Are you willing to work onsite?"),
    ("Are you willing to relocate?", "Are you not willing to relocate?"),
    ("Can you relocate?", "Can't you relocate?"),
    ("Can you relocate?", "You cannot relocate?"),
    ("Do you have Python experience?", "Do you have no Python experience?"),
    ("Do you have at least 3 years of Python experience?", "Do you have at least 5 years of Python experience?"),
    ("Do you have at least 3 years of Python experience?", "Do you have more than 3 years of Python experience?"),
    ("Do you have 3 years of Python experience?", "Do you have 3+ years of Python experience?"),
    ("Do you expect a 3% salary increase?", "Do you expect a 3 salary increase?"),
    ("Do you have 3-5 years of Python experience?", "Do you have 3 or 5 years of Python experience?"),
    ("Do you have .5 years of Python experience?", "Do you have 5 years of Python experience?"),
    ("What is your notice period?", "Are you serving your notice period?"),
    ("What is your notice period?", "Can you join immediately?"),
    ("What is your notice period?", "What is your last working date?"),
    ("What is your notice period?", "How many days are left in your notice period?"),
    ("What is your notice period in days?", "What is your notice period in months?"),
    ("What is your current location?", "What is your preferred location?"),
    ("What is your current location?", "Where have you been based?"),
    ("What is your current location?", "Where will you be based?"),
    ("What is your current city?", "What is your current country?"),
    ("Are you currently based in India?", "Are you currently based in Canada?"),
    ("Are you currently based in the US?", "Are you currently based?"),
    ("Are you currently based in the US?", "Are you currently based in the UK?"),
    ("What is your notice period?", "What are your notice period and current CTC?"),
])
def test_distinct_facts_must_never_share_an_answer(stored, question):
    assert match(question, saved(stored)) is None


@pytest.mark.parametrize("question", [
    "Why should we hire you for this role?", "Why do you want to join our company?",
    "What makes you a good fit for this position?", "What is your relevant experience?",
    "What salary do you expect for this role?", "Write a cover letter for this job",
    "What is your motivation for relocation?", "Explain your experience with the job requirements",
    "What is your favorite programming language?", "Are you a great candidate?", "", " " * 20,
])
def test_unknown_or_job_dependent_prompts_abstain_even_if_saved(question):
    assert match(question, saved(question)) is None


@pytest.mark.parametrize("answer", ["", "  ", "[AI writes this for each job]", "[ai  writes this for each job]"])
def test_blank_and_per_job_answers_are_never_reused(answer):
    assert match("How soon can you join?", saved("Notice period", answer)) is None


def test_conflicting_saved_answers_abstain_regardless_of_entry_order():
    entries = [(["Notice period"], "30 days"), (["How soon can you join?"], "60 days")]
    assert match("What is your notice period?", entries) is None
    assert match("What is your notice period?", list(reversed(entries))) is None


def test_equivalent_saved_answers_and_multiple_aliases_are_unambiguous():
    entries = [(["Notice period", "How soon can you join?"], "30 days"),
               (["Please state your notice period"], "30 DAYS")]
    result = match("What is your notice period?", entries)
    assert result.answer == "30 days"


def test_incompatible_answer_cannot_conflict_with_the_matching_skill():
    entries = [(["Years of Python experience"], "2"), (["Years of Java experience"], "5")]
    assert match("How long have you used Python?", entries).answer == "2"


def test_unknown_skill_names_are_protected_without_a_skill_dictionary():
    assert match("How many years using SyntheticToolAlpha?", saved("Years of SyntheticToolBeta experience")) is None
    assert match("How many years using SyntheticToolAlpha?", saved("Years of SyntheticToolAlpha experience", "1")).answer == "1"


def test_threshold_paraphrase_requires_identical_entity_number_and_comparator():
    result = match("Have you used Python for a minimum of 3 years?",
                   saved("Do you have at least 3 years of Python experience?", "Yes"))
    assert result.answer == "Yes"


@pytest.mark.parametrize("question", [
    "Are you willing to relocate to this location?",
    "Can you attend a walk-in interview?",
    "Can you attend a walkin interview in Pune?",
    "Can you start tomorrow?",
    "What is your expected CTC for this role?",
    "How many years of relevant experience do you have?",
])
def test_exported_job_dependent_guard_rejects_posting_and_event_facts(question):
    assert is_job_dependent(question)
    assert match(question, saved(question)) is None


@pytest.mark.parametrize("question", ["What is your notice period?", "Years of Python experience", "Expected CTC", "Are you willing to relocate to Pune?"])
def test_exported_guard_does_not_label_stable_personal_facts_as_posting_specific(question):
    assert not is_job_dependent(question)
