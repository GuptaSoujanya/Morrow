"""Spaced review: grades book the next date, weak questions come back, saved state is checked."""
import datetime as dt
import json
from pathlib import Path

import pytest

from common import interview_course, interview_practice, interview_review, learning_memory

TODAY = dt.date(2026, 1, 10)


def _days(entry):
    return (dt.date.fromisoformat(entry['due']) - TODAY).days


@pytest.mark.parametrize('rating, days', [('again', 1), ('hard', 1), ('good', 4), ('easy', 14)])
def test_a_first_grade_books_the_fsrs_starting_interval(rating, days):
    data = {}
    entry = interview_review.grade(data, 'full_stack-1-1', rating, TODAY)
    assert _days(entry) == days
    assert entry['s'] == pytest.approx(interview_review.W[interview_review.RATINGS[rating] - 1], abs=1e-3)
    assert data['review_log'][-1] == {'at': TODAY.isoformat(), 'id': 'full_stack-1-1', 'rating': rating,
                                      'interval_days': days, 'retrievability': None}


def test_the_relearning_dose_caps_the_next_two_reviews_at_3_then_9_days():
    data = {}
    interview_review.grade(data, 'q', 'easy', TODAY)
    second = interview_review.grade(data, 'q', 'easy', TODAY + dt.timedelta(days=14))
    assert data['review_log'][-1]['interval_days'] == 3
    interview_review.grade(data, 'q', 'easy', dt.date.fromisoformat(second['due']))
    assert data['review_log'][-1]['interval_days'] == 9
    interview_review.grade(data, 'q', 'easy', TODAY + dt.timedelta(days=40))
    assert data['review_log'][-1]['interval_days'] > 9


def test_a_lapse_shrinks_stability_and_brings_the_question_back_sooner():
    data = {}
    interview_review.grade(data, 'q', 'good', TODAY)
    good = interview_review.grade(dict(data, reviews=dict(data['reviews'])), 'q', 'good', TODAY + dt.timedelta(days=4))
    lapsed = interview_review.grade(data, 'q', 'again', TODAY + dt.timedelta(days=4))
    assert lapsed['s'] < interview_review.W[2] < good['s']
    assert lapsed['due'] < good['due'] and lapsed['lapses'] == 1


def test_the_rubric_scores_map_to_grades():
    assert [interview_review.rating_of(n) for n in (0, 1, 2)] == ['again', 'hard', 'good']
    with pytest.raises(ValueError):
        interview_review.rating_of('perfect')


def test_due_takes_the_most_overdue_first_and_alternates_tracks():
    data = {'reviews': {}}
    for item_id, due in (('ai_ml-1-1', '2026-01-08'), ('ai_ml-2-1', '2026-01-05'), ('ai_ml-3-1', '2026-01-09'),
                         ('dsa:two-sum', '2026-01-07'), ('full_stack-4-1', '2026-01-20')):
        data['reviews'][item_id] = {'s': 2.0, 'd': 5.0, 'last': '2026-01-01', 'due': due, 'reps': 1, 'lapses': 0}
    assert interview_review.due(data, TODAY) == ['ai_ml-2-1', 'dsa:two-sum', 'ai_ml-1-1', 'ai_ml-3-1']
    assert interview_review.due(data, TODAY, limit=2) == ['ai_ml-2-1', 'dsa:two-sum']


def test_seeding_registers_new_items_for_tomorrow_and_leaves_scheduled_ones():
    data = {}
    interview_review.grade(data, 'old', 'easy', TODAY)
    before = dict(data['reviews']['old'])
    interview_review.seed(data, ['old', 'new'], TODAY)
    assert data['reviews']['old'] == before
    assert data['reviews']['new']['due'] == '2026-01-11' and data['reviews']['new']['reps'] == 0
    assert interview_review.grade(data, 'new', 'good', TODAY)['reps'] == 1


def test_completing_a_course_day_seeds_its_questions_and_survives_a_save(tmp_path):
    saved = learning_memory.transact(
        tmp_path, lambda data: interview_course.record_completion(data, 3, True, at='2026-01-10T09:00:00+05:30'))
    ids = interview_practice.day_question_ids(3)
    assert len(ids) == 6 and set(ids) <= set(saved['reviews'])
    assert interview_review.due(saved, TODAY + dt.timedelta(days=1), limit=10)
    learning_memory.transact(tmp_path, lambda data: interview_review.grade(data, ids[0], 'good', TODAY))
    assert learning_memory.transact(tmp_path)['reviews'][ids[0]]['reps'] == 1


@pytest.mark.parametrize('bad', [{'reviews': []}, {'reviews': {'q': {'due': 'soon', 'reps': 0, 'lapses': 0}}},
                                 {'reviews': {'q': {'due': '2026-01-01', 'reps': -1, 'lapses': 0}}},
                                 {'review_log': [{'at': '2026-01-01', 'id': 'q', 'rating': 'meh'}]}])
def test_malformed_review_state_is_refused(bad):
    data = {'version': 1, 'course': {}, 'documents': {}, 'plan': {}, 'history': [], **bad}
    with pytest.raises(ValueError):
        learning_memory._validate(data)


def test_the_react_bank_is_attributed_and_joins_the_full_stack_track():
    path = Path(interview_practice.__file__).parent / 'data' / 'react_interview_questions.json'
    items = json.loads(path.read_text(encoding='utf-8'))
    assert len(items) == 24 and len({item['id'] for item in items}) == 24
    for item in items:
        assert item['id'].startswith('react-') and item['license'] == 'MIT'
        assert item['source_url'].startswith('https://github.com/sudheerj/reactjs-interview-questions#')
        assert all(item[key].strip() for key in ('question', 'answer', 'follow_up', 'follow_up_answer', 'topic'))
        assert '<img' not in item['answer'] and '<details' not in item['answer'] and '—' not in item['answer']
    rows = [row for row in interview_practice.bank_rows() if row['id'].startswith('react-')]
    assert len(rows) == 24 and {row['track'] for row in rows} == {'full_stack'}
    assert len({row['id'] for row in interview_practice.bank_rows()}) == len(interview_practice.bank_rows())
    assert interview_review.question_text('react-jsx') == 'What is JSX?'
    found = interview_practice.question_bank({'q': 'useOptimistic'})
    assert found['total'] >= 1
