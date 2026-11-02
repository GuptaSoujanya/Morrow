"""Beginner lessons must be usable on every scheduled system-design day."""
import pytest

from common.interview_course import TOTAL_DAYS, day_spec
from common.interview_system_basics import lesson


def _text(card):
    return ' '.join([
        card['title'], card['idea'], card['example'], *card['steps'],
        card['task'], card['answer'],
        *(f'{term} {meaning}' for term, meaning in card['words'].items()),
    ])


@pytest.mark.parametrize('day', range(1, TOTAL_DAYS + 1))
def test_every_scheduled_day_has_a_short_complete_teaching_card(day):
    assert day_spec(day)['system_design']
    card = lesson(day)
    assert set(card) == {'title', 'idea', 'example', 'steps', 'task', 'answer', 'words'}
    for field in ('title', 'idea', 'example', 'task', 'answer'):
        assert isinstance(card[field], str) and card[field].strip()
    assert 2 <= len(card['steps']) <= 4
    assert all(isinstance(step, str) and step.strip() for step in card['steps'])
    assert 2 <= len(card['words']) <= 5
    assert all(term.strip() and meaning.strip() for term, meaning in card['words'].items())
    assert 100 <= len(_text(card).split()) <= 180
    assert card['task'] != card['answer']
    assert 'not yet contain' not in _text(card)


def test_request_path_starts_with_a_familiar_worked_action():
    card = lesson(1)
    assert 'browser' in card['idea'].lower()
    assert '20' in card['example']
    assert 'Browser → app → saved data → app → screen' in card['answer']
    assert {'request', 'response'} <= card['words'].keys()


def test_transaction_example_explains_both_success_and_failure():
    card = lesson(11)
    assert 'undone together' in card['idea']
    assert 'A 7, B 13' in card['answer']
    assert 'A 12, B 8' in card['answer']
    assert '20' in card['answer']  # The conserved total is explained to learners.


def test_stateless_does_not_mean_the_application_has_no_saved_state():
    card = lesson(6)
    assert 'shared' in card['idea']
    assert 'database' in card['example']
    assert 'memory' in card['answer']


def test_privacy_checks_are_taught_before_search_results_are_used():
    cache_card = lesson(47)
    assistant_card = lesson(81)
    assert 'different users' in cache_card['answer']
    assert 'access scope' in cache_card['answer']
    assert 'before the passage is used' in assistant_card['answer']


def test_timeout_example_does_not_claim_the_action_was_cancelled():
    card = lesson(52)
    assert 'payment' in card['task']
    assert 'may have completed' in card['answer']
    assert 'identifier' in card['answer']


def test_queue_pressure_is_explained_with_checkable_arithmetic():
    card = lesson(58)
    assert '8 − 5' in card['answer']
    assert '30 jobs' in card['answer']
    assert 'backpressure' in card['words']


def test_final_practice_contains_a_prompt_and_substantive_model_answer():
    mock = lesson(87)
    assert '100 learners' in mock['example']
    assert '25 minutes' in mock['title']
    assert 'owner' in mock['answer']
    assert 'retries' in mock['answer']
    final = lesson(90)
    assert 'job identifier' in final['answer']
    assert 'delayed availability' in final['answer']  # Includes a real trade-off.


def test_callers_cannot_change_lessons_for_other_learners():
    original = lesson(1)
    edited = lesson(1)
    edited['title'] = 'Changed title'
    edited['steps'].append('Changed step')
    edited['words']['request'] = 'Changed definition'
    assert lesson(1) == original


@pytest.mark.parametrize('day', [0, 91, -1, True, False, 1.0, '1', None])
def test_invalid_days_are_rejected_instead_of_getting_a_generic_lesson(day):
    with pytest.raises(ValueError, match='1 to 90'):
        lesson(day)
