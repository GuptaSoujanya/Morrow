"""The AI course must teach a complete path before linking advanced reading."""
import pytest

from common.interview_ai_basics import lesson
from common.interview_course import TOTAL_DAYS, day_spec


def test_every_shared_course_day_has_a_complete_self_contained_lesson():
    required = {'title', 'idea', 'example', 'steps', 'task', 'answer', 'words'}
    lessons = [lesson(day) for day in range(1, TOTAL_DAYS + 1)]

    assert TOTAL_DAYS == 90
    assert len({item['title'] for item in lessons}) == TOTAL_DAYS
    assert len({item['task'] for item in lessons}) == TOTAL_DAYS
    for day, item in enumerate(lessons, 1):
        assert day_spec(day)['ai_ml']
        assert set(item) == required
        assert all(isinstance(item[key], str) and item[key].strip()
                   for key in ('title', 'idea', 'example', 'task', 'answer'))
        assert 2 <= len(item['steps']) <= 4
        assert all(isinstance(step, str) and step.strip() for step in item['steps'])
        assert 2 <= len(item['words']) <= 5
        assert all(term.strip() and meaning.strip()
                   for term, meaning in item['words'].items())
        # A lesson must be usable without opening research papers or code blocks.
        content = ' '.join((item['idea'], item['example'], item['task'], item['answer']))
        assert 'http://' not in content and 'https://' not in content
        assert '```' not in content


@pytest.mark.parametrize('day', [0, 91, -1, 1.0, True, False, None, '1'])
def test_invalid_days_do_not_silently_choose_a_different_lesson(day):
    with pytest.raises(ValueError, match='1 to 90'):
        lesson(day)


def test_returned_lessons_cannot_mutate_the_shared_course():
    changed = lesson(1)
    original = lesson(1)
    changed['title'] = 'Changed'
    changed['steps'].append('An unrelated instruction')
    changed['words']['model'] = 'An incorrect meaning'
    assert lesson(1) == original
    assert lesson(2)['title'] != 'Changed'


def test_first_day_starts_with_examples_and_a_checkable_small_guess():
    first = lesson(1)
    assert {'machine learning', 'model', 'prediction'} <= first['words'].keys()
    assert '1 hour' in first['example'] and '2 hours' in first['example']
    assert '4 hours' in first['task']
    assert '8 exercises' in first['answer']
    assert 'guess' in first['answer'] and 'promise' in first['answer']
    assert 'gradient' not in first['idea'] and 'transformer' not in first['idea']


def test_learning_and_using_a_model_are_explained_separately():
    item = lesson(3)
    assert {'training', 'inference'} <= item['words'].keys()
    assert 'inference' in item['answer']
    assert 'adjust' in item['answer']
    assert 'does not normally train' in item['idea']


def test_precision_and_recall_have_different_denominators():
    item = lesson(18)
    assert {'precision', 'recall', 'false positive'} <= item['words'].keys()
    assert '3 out of 4' in item['example'] and '3 out of 5' in item['example']
    assert '4/5 = 80%' in item['answer']
    assert '4/8 = 50%' in item['answer']


def test_rare_positive_example_exposes_misleading_accuracy():
    item = lesson(24)
    assert '1,000' in item['task']
    assert '99%' in item['answer'] and '0%' in item['answer']
    assert 'flags nothing' in item['task']


def test_later_topics_are_real_lessons_in_their_syllabus_positions():
    expected_definitions = {
        8: 'vector', 15: 'regression', 22: 'random forest',
        29: 'neuron', 36: 'token', 43: 'RAG', 50: 'agent',
        57: 'training-serving skew', 64: 'recommender', 71: 'product goal',
    }
    for day, term in expected_definitions.items():
        assert term in lesson(day)['words'], (day, day_spec(day)['ai_ml'])


def test_search_evidence_does_not_license_an_unsupported_answer():
    item = lesson(43)
    assert 'parking' in item['task']
    assert item['answer'].startswith('No.')
    assert 'does not answer' in item['answer']
    grounded = lesson(41)
    assert 'carry-over' in grounded['answer']
    assert 'does not cover' in grounded['answer']


def test_live_input_example_preserves_units():
    item = lesson(57)
    assert '3,000 metres' in item['task']
    assert '3 kilometres' in item['answer']
    assert 'training-serving skew' in item['words']


def test_review_days_include_specific_practice_and_corrected_reasoning():
    precision_review = lesson(84)
    assert '2/5 = 40%' in precision_review['answer']
    assert '2/4 = 50%' in precision_review['answer']
    training_review = lesson(89)
    assert 'two examples' in training_review['task']
    assert 'weights' in training_review['answer']
    assert 'prompting' in training_review['answer']
    final = lesson(90)
    assert 'closing time' in final['task']
    assert 'not available' in final['answer']
    assert 'next practice task' in final['answer']
