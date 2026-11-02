"""Public content coverage, question bank search, and closed interview answers."""
from pathlib import Path

import pytest

from common import interview_course, interview_lessons, interview_practice


def test_all_subjects_add_specific_interview_depth_without_mutable_shared_state():
    for track, _, _ in interview_practice.TRACKS:
        questions = []
        for day in range(1, 91):
            entry = interview_practice.subject(day, track)
            assert all(entry[key].strip() for key in ('explanation', 'scenario', 'mistake', 'drill'))
            assert len(entry['checks']) >= 2 and all(entry['checks'])
            assert len(entry['questions']) == 2
            for question in entry['questions']:
                assert all(question[key].strip() for key in ('question', 'answer', 'follow_up', 'follow_up_answer'))
                questions.append(question['question'])
            entry['questions'][0]['answer'] = 'mutated'
            assert interview_practice.subject(day, track)['questions'][0]['answer'] != 'mutated'
        assert len(set(questions)) == 180, f'Repeated question in {track}'
    for invalid in (0, 91, True, '1'):
        with pytest.raises(ValueError):
            interview_practice.subject(invalid, 'ai_ml')


def test_bank_filters_pages_and_routes_retain_the_selected_collection():
    bank = interview_practice.question_bank()
    assert bank['bank_total'] == bank['total'] == 540
    assert sum(item['count'] for item in bank['tracks']) == 540
    assert len(bank['items']) == 12 and bank['pages'] == 45
    other = interview_practice.question_bank({'page': '2'})
    assert not {item['id'] for item in bank['items']} & {item['id'] for item in other['items']}
    filtered = interview_practice.question_bank({'track': 'system_design', 'week': '13', 'q': 'design'})
    assert filtered['total'] and all(item['track'] == 'system_design' and item['week'] == 13 for item in filtered['items'])
    assert all('stage=interview' in item['route'] and 'from=weekly' in item['route'] and 'view=questions' in item['route'] for item in filtered['items'])
    assert interview_practice.question_bank({'q': 'unlikelytermxyz'})['total'] == 0
    assert interview_practice.question_bank({'page': '9999'})['page'] == 45
    for query in ({'track': 'private'}, {'week': '14'}, {'page': '0'}, {'q': 'x' * 161}):
        with pytest.raises(ValueError):
            interview_practice.question_bank(query)


def test_each_day_exposes_interviews_without_leaking_answers_into_the_task():
    from bs4 import BeautifulSoup
    course_root = Path(__file__).parents[2] / 'database/course'
    for day in range(1, 91):
        soup = BeautifulSoup(interview_lessons.render(interview_lessons.lesson(day, course_root)['text']), 'html.parser')
        interviews = [node for node in soup.find_all('h3') if node.text == 'Interview practice']
        assert len(interviews) == 3 and all(node.find_parent('details') is None for node in interviews)
        answers = [node for node in soup.find_all('details') if node.summary.text == 'Show answer']
        expected = 7 if interview_course.day_spec(day)['review'] else 6
        assert len(answers) == expected and all(not node.has_attr('open') for node in answers)
        followups = [node for node in soup.find_all('details') if node.summary.text == 'Show follow-up answer']
        assert len(followups) == 6 and all(not node.has_attr('open') for node in followups)
        assert not soup.find('script')
    assert len({interview_practice.weekly_assessment(week)['mock_question'] for week in range(1, 14)}) == 13


def test_bank_rows_are_copies_and_sources_are_public_links():
    result = interview_practice.question_bank()
    result['items'][0]['question'] = 'changed'
    assert interview_practice.question_bank()['items'][0]['question'] != 'changed'
    assert result['sources'] and all(source['url'].startswith('https://') for source in result['sources'])
