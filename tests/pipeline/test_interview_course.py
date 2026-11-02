"""A fixed course with private, completion-driven daily generation."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest

from common import ai_cli, interview_course as course, learning_memory
from pipeline import briefing, content, learning


def day_text(day, label='An explained example'):
    small = '\n\n'.join('### ' + title + '\n' + label for title in
                          ('Words you need', 'The idea', 'A small example', 'Your turn', 'Check your answer')) + '\n\n---'
    return ('## Day %d: %s\n\n' % (day, course.day_spec(day)['title'])
            + '\n\n'.join('**%s: topic**\n%s' % (part, small)
                          for part in ('ML / GenAI', 'System Design', 'Full-stack', 'DSA'))
            + '\n\n**Recall**\nExplain the example.\n\n**Go deeper**\n- [Python](https://docs.python.org/3/)\n')


def week_text(week, label='An explained example'):
    return '# Week %d: course\n\n' % week + '\n'.join(day_text(day, label) for day in learning.days_of(week))


def test_syllabus_has_exactly_90_complete_days_and_no_account_input():
    weeks = course.syllabus()
    days = [day for week in weeks for day in week['days']]
    assert [day['day'] for day in days] == list(range(1, 91))
    assert len(weeks) == 13 and len(weeks[-1]['days']) == 6
    assert sum(part['minutes'] for part in course.course_info()['daily_session']) == 120
    assert all(len(day['topics']) == 4 and day['practice'] and day['explanation'] and day['example'] for day in days)
    root = Path(__file__).parents[2] / 'database/course'
    assert all((root / path).is_file() for day in days for path in day['reading_paths'].values())
    for invalid in (0, 91, True, '1'):
        with pytest.raises(ValueError):
            course.day_spec(invalid)


def test_legacy_completion_is_preserved_and_does_not_complete_shared_course():
    data = {'plan': {'done': [1, 2], 'marked': {'2026-10-01': 2}},
            'documents': {'plan/day-1': {'done': True}}, 'history': []}
    before = deepcopy(data)
    assert course.completed_days(data) == [] and course.next_day(data) == 1
    assert data == before  # Reading does not migrate or reset old progress.
    course.record_completion(data, 1, True, at='2026-11-02T10:00:00+05:30')
    assert data['plan'] == before['plan']
    assert data['documents']['plan/day-1'] == before['documents']['plan/day-1']
    assert course.completed_days(data) == [1] and course.next_day(data) == 2
    course.record_completion(data, 1, False, at='2026-11-02T10:01:00+05:30')
    assert course.next_day(data) == 1 and not data['interview_course']['marked']


def test_repeated_completion_does_not_move_today_back_or_add_history():
    data = {'documents': {}, 'history': []}
    course.record_completion(data, 1, True, at='2026-11-02T10:00:00+05:30')
    course.record_completion(data, 2, True, at='2026-11-02T11:00:00+05:30')
    before = deepcopy(data)
    course.record_completion(data, 1, True, at='2026-11-02T12:00:00+05:30')
    assert data == before


def test_invalid_course_progress_is_reported_not_reset(tmp_path):
    data = learning_memory.transact(tmp_path)
    data['interview_course'] = {'course_id': course.COURSE_ID, 'course_version': 1, 'done': [91]}
    path = tmp_path / 'user/memory/learning.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='not been reset'):
        learning_memory.transact(tmp_path)
    assert json.loads(path.read_text())['interview_course']['done'] == [91]


def test_daily_fetch_is_one_next_day_and_does_not_skip_missed_dates(tmp_path, monkeypatch):
    monkeypatch.setenv('RESUME_PATH', str(tmp_path / 'missing-resume.pdf'))
    prompts = []
    def ask(prompt):
        prompts.append(prompt)
        return day_text(1)
    day, path = learning.write_today(ask, tmp_path, date(2026, 11, 2))
    assert day == 1 and path == tmp_path / 'interview-90/daily/2026-11-02.md'
    assert set(learning.split_days(learning.week_path(1, tmp_path).read_text())) == {1}
    assert 'simple, clear English' in prompts[0] and 'same fixed course for everyone' in prompts[0]
    assert not learning.load_progress(tmp_path)['done']
    day, later = learning.write_today(lambda prompt: pytest.fail('Unfinished lesson is reusable'), tmp_path, date(2026, 11, 7))
    assert day == 1 and later.exists()
    assert not (tmp_path / 'progress.json').exists()


def test_new_teaching_style_replaces_only_unfinished_old_lessons(tmp_path):
    path = learning.ensure_week(1, lambda prompt: week_text(1, 'Old reference text'), tmp_path)
    metadata = learning._read_metadata(path)
    for source in metadata['day_sources'].values():
        source.pop('teaching_version')
    learning._write_metadata(path, metadata)
    learning.save_progress({'done': [1]}, tmp_path)
    completed = learning.split_days(path.read_text())[1]
    prompts = []
    learning.ensure_day(2, lambda prompt: prompts.append(prompt) or day_text(2, 'Small steps'), tmp_path)
    assert 'VERY SIMPLE ENGLISH' in prompts[0] and 'explain every line' in prompts[0]
    sections = learning.split_days(path.read_text())
    assert sections[1] == completed and 'Small steps' in sections[2]
    assert learning.load_progress(tmp_path)['done'] == [1]
    assert learning._read_metadata(path)['day_sources']['2']['teaching_version'] == course.TEACHING_VERSION


def test_dense_generated_chapter_cannot_replace_a_small_lesson(tmp_path):
    path = learning.ensure_day(1, lambda prompt: day_text(1), tmp_path)
    before = path.read_text()
    dense = day_text(2).replace('### A small example', '**More terminology**')
    with pytest.raises(ai_cli.AIError, match='beginner lesson steps'):
        learning.ensure_day(2, lambda prompt: dense, tmp_path)
    assert path.read_text() == before and not learning.load_progress(tmp_path)['done']


@pytest.mark.parametrize('text', [day_text(1, ''), day_text(1).replace('topic**', 'topic'),
                                 day_text(1).replace('### Words you need', '### A small example')])
def test_empty_or_malformed_teaching_steps_are_rejected(text):
    with pytest.raises(ai_cli.AIError):
        learning._checked_sections(text, [1])


def test_core_prompt_and_cache_do_not_change_with_resume(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('SecretEmployer COBOL')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    prompt = learning.day_prompt(1, tmp_path)
    path = learning.ensure_day(1, lambda value: day_text(1), tmp_path)
    original = path.read_text()
    selected.write_text('OtherEmployer Rust')
    assert learning.day_prompt(1, tmp_path) == prompt
    assert 'SecretEmployer' not in prompt and 'OtherEmployer' not in prompt
    assert learning.ensure_day(1, lambda value: pytest.fail('Resume must not invalidate course'), tmp_path) == path
    assert path.read_text() == original


def test_next_generation_uses_only_completed_prior_material(tmp_path):
    learning.ensure_week(1, lambda value: week_text(1, 'Saved reading'), tmp_path)
    path = learning.week_path(1, tmp_path)
    text = path.read_text().replace('## Day 2:', '## Day 2: UNREAD SECRET').replace('## Day 7:', '## Day 7: FUTURE SECRET')
    path.write_text(text)
    learning.save_progress({'done': [1, 7]}, tmp_path)
    prompt = learning.day_prompt(3, tmp_path)
    assert 'Completed earlier course days: 1' in prompt
    assert 'Saved reading' in prompt
    assert 'UNREAD SECRET' not in prompt and 'FUTURE SECRET' not in prompt


def test_completed_bundled_reading_is_used_when_no_generated_week_exists(tmp_path):
    learning.save_progress({'done': [1]}, tmp_path)
    prompt = learning.day_prompt(2, tmp_path)
    assert 'Completed earlier course days: 1' in prompt
    assert 'Previously completed material' in prompt and 'Start here' in prompt
    assert not learning.week_path(1, tmp_path).exists()


def test_next_day_refreshes_prebuilt_content_after_prior_lesson_completion(tmp_path):
    path = learning.ensure_week(1, lambda value: week_text(1, 'Initial explanation'), tmp_path)
    previous = learning.split_days(path.read_text())[1]
    learning.mark_done(tmp_path, date(2026, 11, 2))
    prompts = []
    day, _ = learning.write_today(lambda value: prompts.append(value) or day_text(2, 'Build on day one'), tmp_path,
                                 date(2026, 11, 3))
    sections = learning.split_days(path.read_text())
    assert day == 2 and sections[1] == previous
    assert 'Build on day one' in sections[2] and 'Completed earlier course days: 1' in prompts[0]
    assert learning.load_progress(tmp_path)['done'] == [1]
    source = learning._read_metadata(path)['day_sources']['2']
    assert source['completed_days'] == [1]
    assert list((path.parent / 'archive/week-01').glob('*.md'))


def test_failed_daily_answer_keeps_saved_material_and_progress(tmp_path):
    path = learning.ensure_week(1, lambda value: week_text(1), tmp_path)
    learning.mark_done(tmp_path, date(2026, 11, 2))
    before = path.read_text(), path.with_suffix('.meta.json').read_text(), learning.load_progress(tmp_path)
    with pytest.raises(ai_cli.AIError, match='missing'):
        learning.ensure_day(2, lambda value: '## Day 2: missing teaching blocks\n', tmp_path)
    assert (path.read_text(), path.with_suffix('.meta.json').read_text(), learning.load_progress(tmp_path)) == before


def test_generation_rejects_new_progress_and_never_overwrites_completion(tmp_path):
    learning.ensure_day(1, lambda value: day_text(1), tmp_path)
    def ask(prompt):
        learning.mark_done(tmp_path, date(2026, 11, 2))
        return day_text(2)
    with pytest.raises(ai_cli.AIError, match='completed reading changed'):
        learning.ensure_day(2, ask, tmp_path)
    assert learning.load_progress(tmp_path)['done'] == [1]
    assert set(learning.split_days(learning.week_path(1, tmp_path).read_text())) == {1}


def test_completed_bundled_day_is_preserved_without_an_ai_call(tmp_path):
    learning.save_progress({'done': [1]}, tmp_path)
    path = learning.ensure_day(1, lambda prompt: pytest.fail('Never rewrite completed public reading'), tmp_path)
    assert learning.split_days(path.read_text())[1] == learning._bundled_section(1)
    assert learning._read_metadata(path)['day_sources']['1']['source'] == 'bundled'
    assert learning.load_progress(tmp_path)['done'] == [1]


def test_week_generation_targets_only_unfinished_days(tmp_path):
    learning.save_progress({'done': [1, 2]}, tmp_path)
    prompts = []
    path = learning.ensure_week(1, lambda prompt: prompts.append(prompt) or '# Week 1: course\n\n' +
                               '\n'.join(day_text(day) for day in range(3, 8)), tmp_path)
    assert 'Output exactly these day sections: Day 3, Day 4, Day 5, Day 6, Day 7.' in prompts[0]
    assert 'Do not output completed days.' in prompts[0]
    assert learning.split_days(path.read_text())[1] == learning._bundled_section(1)
    assert learning.split_days(path.read_text())[2] == learning._bundled_section(2)
    assert learning.load_progress(tmp_path)['done'] == [1, 2]


def test_all_complete_does_not_call_ai(tmp_path):
    learning.save_progress({'done': list(range(1, 91))}, tmp_path)
    day, path = learning.write_today(lambda prompt: pytest.fail('Course is already complete'), tmp_path, date(2026, 11, 2))
    assert day == 90 and 'Course complete' in path.read_text()
    assert learning.load_progress(tmp_path)['done'] == list(range(1, 91))


def test_briefing_uses_course_context_without_resume_and_preserves_freshness_rules(tmp_path, monkeypatch):
    monkeypatch.setenv('RESUME_PATH', str(tmp_path / 'missing.pdf'))
    context = briefing.context(date(2026, 11, 2), tmp_path)
    assert 'day 1 of the shared 90-day interview course' in context
    assert 'What is machine learning?' in context
    for key in ('papers', 'tech-news', 'repositories'):
        prompt = briefing.prompt_for(briefing.by_key(key), context, date(2026, 11, 2))
        assert 'simple English' in prompt
        assert "resume's skills" not in prompt
    assert 'within the last 30 days' in briefing.prompt_for(briefing.by_key('papers'), context, date(2026, 11, 2))


def test_incremental_generated_week_passes_content_check(tmp_path):
    learning.ensure_day(1, lambda value: day_text(1), tmp_path)
    assert content.week_problems(1, tmp_path) == []
    learning.write_today(lambda prompt: pytest.fail('Already saved'), tmp_path, date(2026, 11, 2))
    assert content.day_problems(date(2026, 11, 2), tmp_path, tmp_path / 'briefing', required_agents=set()) == []
