import re

import pytest

from common.interview_course import day_spec
from common.interview_fullstack_basics import lesson


def _text(item):
    return ' '.join([
        item['title'], item['idea'], item['example'], *item['steps'],
        item['task'], item['answer'], *item['words'].values(),
    ])


def test_every_syllabus_day_has_a_complete_short_lesson():
    titles = set()
    exercises = set()
    for day in range(1, 91):
        assert day_spec(day)['full_stack']
        item = lesson(day)
        assert set(item) == {'title', 'idea', 'example', 'steps', 'task', 'answer', 'words'}
        for field in ('title', 'idea', 'example', 'task', 'answer'):
            assert isinstance(item[field], str) and item[field].strip(), (day, field)
        assert 2 <= len(item['steps']) <= 4
        assert all(isinstance(step, str) and step.strip() for step in item['steps'])
        assert 2 <= len(item['words']) <= 5
        assert all(term.strip() and definition.strip() for term, definition in item['words'].items())
        assert 100 <= len(_text(item).split()) <= 180, day
        assert 2 <= len(re.findall(r'[.!?](?:\s|$)', item['idea'])) <= 4, day
        titles.add(item['title'])
        exercises.add(item['task'])
    assert len(titles) == 90
    assert len(exercises) == 90


@pytest.mark.parametrize('day', [0, -1, 91, 900, True, False, '1', 1.0, None, []])
def test_invalid_days_are_rejected(day):
    with pytest.raises(ValueError, match='1 to 90'):
        lesson(day)


def test_callers_cannot_change_the_shared_course():
    original = lesson(1)
    changed = lesson(1)
    changed['title'] = 'Changed'
    changed['steps'].append('Extra step')
    changed['words']['input'] = 'Changed'
    assert lesson(1) == original


def test_first_day_teaches_and_runs_a_small_python_function(capsys):
    item = lesson(1)
    assert 'Python is a language' in item['idea']
    assert 'A function is' in item['idea']
    code = re.search(r'```python\n(.*?)\n```', item['example'], re.S).group(1)
    namespace = {}
    exec(compile(code, '<day-one-example>', 'exec'), namespace)
    assert capsys.readouterr().out == '25\n'
    assert namespace['add_five'](10) == 15
    assert '15' in item['answer']
    assert len(code.splitlines()) == 3
    assert all(f'Line {number}' in item['example'] for number in (1, 2, 3))
    assert 'starting spaces' in item['example']


@pytest.mark.parametrize(('day', 'terms'), [
    (2, ('HTML', 'CSS', 'Tab')),
    (4, ('JSON', '30')),
    (9, ('join', '35', '15')),
    (11, ('transaction', '30 and 20')),
    (17, ('password hash', 'reset')),
    (18, ('server', 'ownership')),
    (24, ('save-7', 'One.', 'rejected')),
    (29, ('image', 'container', 'persistent')),
    (36, ('pieces', 'incomplete', 'finished')),
    (37, ('python', 'older', 'request id')),
    (40, ('schema', '-5', 'rejects')),
    (47, ('source', 'No.', 'end time')),
    (54, ('approval', 'changed recipient')),
    (60, ('20, 20 and 5', 'memory')),
    (67, ('6.', 'A', 'B', 'twice')),
    (74, ('permission', 'saved state')),
    (80, ('Two seconds', 'database')),
    (86, ('25 minutes', 'database')),
    (90, ('index', 'next', 'not a guarantee')),
])
def test_progression_contains_relevant_examples_and_real_answers(day, terms):
    text = _text(lesson(day)).lower()
    for term in terms:
        assert term.lower() in text, (day, term)


def test_lessons_do_not_require_raw_advanced_reference_chapters():
    forbidden = ('04-ml-genai-agents/', '03-fullstack-mern-kubernetes/',
                 'read the full chapter', 'consult the advanced reference',
                 'senior-level', 'kubernetes')
    for day in range(1, 91):
        text = _text(lesson(day)).lower()
        assert not any(term in text for term in forbidden), day
        assert len(lesson(day)['example'].split()) >= 30, day
        assert len(lesson(day)['answer'].split()) >= 10, day
