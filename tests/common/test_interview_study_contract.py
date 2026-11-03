"""Course purpose, observable tasks and executable examples stay in sync."""
from copy import deepcopy
from pathlib import Path
import sqlite3

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
import pytest

from common import interview_course, interview_engineering, interview_lessons

PUBLIC = Path(__file__).parents[2] / 'database/course'
TRACKS = ('ai_ml', 'system_design', 'full_stack', 'dsa')


def python_lab(day):
    code = '\n'.join(token.content for token in MarkdownIt().parse(interview_engineering.implementation_lab(day))
                     if token.type == 'fence' and token.info == 'python')
    namespace = {}
    exec(compile(code, f'<week-{(day - 1) // 7 + 1}-lab>', 'exec'), namespace)
    return namespace


def test_every_day_has_a_topic_specific_work_and_practice_contract():
    relevance = {key: set() for key in TRACKS[:3]}
    for day in range(1, 91):
        spec = interview_course.day_spec(day)
        assert [item['key'] for item in spec['learning_path']] == list(TRACKS)
        assert spec['project'] and spec['deliverable'] and '3–4' in spec['session_label']
        for item in spec['learning_path']:
            assert item['topic'] == spec[item['key']]
            assert item['outcome'] and item['task'] and len(item['checks']) >= 2
            assert item['job_use'] == spec['job_relevance'][item['key']]
            if item['key'] in relevance:
                relevance[item['key']].add(item['job_use'])
    assert all(len(items) == 90 for items in relevance.values())
    # Metadata is copied: a consumer cannot change the next learner's brief.
    spec['learning_path'][0]['checks'].clear()
    assert interview_course.day_spec(90)['learning_path'][0]['checks']
    for week in interview_course.syllabus():
        assert len(week['milestones']) == len(week['days'])
        assert [item['day'] for item in week['milestones']] == [item['day'] for item in week['days']]


def test_checks_stay_visible_before_answers_and_finish_has_its_own_boundary():
    for day in range(1, 91):
        soup = BeautifulSoup(interview_lessons.render(interview_lessons.lesson(day, PUBLIC)['text']), 'html.parser')
        checks = [node for node in soup.find_all('h4') if node.text == 'Your task is ready when']
        assert len(checks) == 3 and all(node.find_parent('details') is None for node in checks)
        assert all(node.find_next_sibling('ul').find_all('li') for node in checks)
        finish = next(node for node in soup.find_all('h2') if node.text == 'Review and finish')
        assert finish.find_parent('details') is None
        assert finish.find_next_sibling('ul').find_all('li')


def test_day_one_connects_all_four_tracks_and_keeps_state_unchanged():
    saved = {'version': 1, 'course': {}, 'documents': {}, 'plan': {}, 'history': []}
    before = deepcopy(saved)
    text = interview_lessons.lesson(1, PUBLIC)['text']
    assert 'add_five' not in text
    assert 'POST /api/study-summary' in text and 'summarise_sessions' in text
    assert '8.33' in text and 'O(n)' in text and 'O(1)' in text
    assert 'after visiting the first k values' in text
    assert interview_course.next_day(saved) == 1 and saved == before
    assert 'production quality' in text  # Tiny data is not offered as proof.


def test_baseline_error_calculation_matches_the_worked_case():
    code = next(t.content for t in MarkdownIt().parse(interview_lessons._DAY_ONE['ai_ml']['example'])
                if t.type == 'fence' and t.info == 'python')
    namespace = {}
    exec(compile(code, '<day-one-evaluation>', 'exec'), namespace)
    error = namespace['mean_absolute_error']
    assert error([20, 30, 40], [25, 25, 25]) == pytest.approx(25 / 3)
    assert error([20, 30, 40], [22, 28, 35]) == 3
    for actual, predicted in (([], []), ([1], [1, 2])):
        with pytest.raises(ValueError):
            error(actual, predicted)


def test_query_lab_keeps_empty_learners_and_excludes_the_end_boundary():
    sql = next(t.content for t in MarkdownIt().parse(interview_engineering.implementation_lab(8))
               if t.type == 'fence' and t.info == 'sql')
    with sqlite3.connect(':memory:') as db:
        db.executescript('''CREATE TABLE learners(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE sessions(id INTEGER PRIMARY KEY, learner_id INTEGER, minutes INTEGER, started_at TEXT);
            INSERT INTO learners VALUES(1, 'Same'), (2, 'Same');
            INSERT INTO sessions VALUES(1, 1, 20, '2026-11-03'), (2, 1, 30, '2026-11-04'), (3, 1, 99, '2026-11-05');''')
        rows = db.execute(sql, {'start': '2026-11-03', 'end': '2026-11-05'}).fetchall()
    assert rows == [(1, 'Same', 50), (2, 'Same', 0)]


def test_later_labs_have_working_boundaries_and_traceable_outputs():
    confusion = python_lab(15)['confusion']
    assert confusion([1, 0, 1, 0], [.9, .7, .4, .1], .8) == {'tp': 1, 'fp': 0, 'tn': 2, 'fn': 1}
    with pytest.raises(ValueError):
        confusion([1], [.9], True)
    config = python_lab(29)['serving_config']
    for limit in ('0', '-1', '129', 'bad'):
        with pytest.raises(ValueError):
            config({'MODEL_VERSION': 'v3', 'MAX_IN_FLIGHT': limit})
    chunks = python_lab(43)['word_chunks']
    assert chunks('') == []
    assert chunks('a b c d e f')[1] == {'start_word': 3, 'end_word': 6, 'text': 'd e f'}
    with pytest.raises(ValueError):
        chunks('a b c', 2, 2)
    transition = python_lab(50)['transition']
    assert transition('running', 'unknown') == 'unknown'
    with pytest.raises(ValueError):
        transition('unknown', 'queued')
    vector = python_lab(57)['serving_vector']
    assert vector({'stops': 2, 'distance_km': 4}, 'delivery-features-v1') == [4., 2.]
    with pytest.raises(ValueError):
        vector({'stops': 2, 'distance_km': 4}, 'v2')
    assign = python_lab(64)['experiment_group']
    assert assign('user-7', 'rank-v2') in ('control', 'treatment')
    with pytest.raises(ValueError):
        assign('user\0other', 'rank-v2')
    percentile = python_lab(71)['p95_ms']
    assert percentile(list(range(1, 101))) == 95
    with pytest.raises(ValueError):
        percentile([float('nan')])


def test_dsa_mock_contains_real_questions_before_linking_solutions():
    text = interview_lessons._dsa_material(interview_course.day_spec(90), PUBLIC)
    assert 'Timed coding practice' in text and text.count('**Statement:**') == 2
    assert '**Approach:**' not in text and 'compare the worked solutions' in text


def test_bank_and_chapter_share_day_one_questions_without_changing_ids():
    from common import interview_practice
    rows = interview_practice.bank_rows()
    assert interview_course.course_info()['interview_questions'] == len(rows)
    assert len({row['id'] for row in rows}) == len(rows)
    text = interview_lessons.lesson(1, PUBLIC)['text']
    for track in TRACKS[:3]:
        expected = interview_engineering.kickoff_questions(track)
        actual = [row for row in rows if row['day'] == 1 and row['track'] == track]
        assert [row['id'] for row in actual] == [f'{track}-1-1', f'{track}-1-2']
        assert [row['question'] for row in actual] == [row['question'] for row in expected]
        assert all(row['question'] in text and row['answer'] in text for row in actual)
