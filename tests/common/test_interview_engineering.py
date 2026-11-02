"""The main course must contain engineering detail, not only optional links."""
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
import pytest

from common import interview_course, interview_engineering, interview_lessons


PUBLIC = Path(__file__).parents[2] / 'database/course'


def test_all_days_have_visible_technical_notebooks_and_diagrams():
    for day in range(1, 91):
        text = interview_lessons.lesson(day, PUBLIC)['text']
        soup = BeautifulSoup(interview_lessons.render(text), 'html.parser')
        notebooks = [node for node in soup.find_all('h4') if 'Engineering notebook' in node.text]
        assert len(notebooks) == 3
        assert all(node.find_parent('details') is None for node in notebooks)
        graphs = soup.select('pre > code.language-mermaid')
        assert len(graphs) >= 3
        assert all(graph.find_parent('details') is None for graph in graphs)
        # Protect the order expected by the guided reader: depth is part of
        # Understand, followed by the example, exercise and interview stages.
        subjects = text.split('**Subject: ')[1:]
        for subject in subjects:
            assert subject.index('### The idea') < subject.index('#### Engineering notebook') < subject.index('### A small example')
            assert subject.index('### A small example') < subject.index('### Your turn') < subject.index('### Interview practice')


def test_weekly_notebooks_are_honestly_shared_but_subjects_and_weeks_are_distinct():
    entries = [interview_engineering.notebook(day, track)
               for day in range(1, 91, 7)
               for track in ('ai_ml', 'system_design', 'full_stack')]
    assert len({entry['text'] for entry in entries}) == 39
    for entry in entries:
        fences = [token for token in MarkdownIt().parse(entry['text']) if token.type == 'fence' and token.info == 'mermaid']
        assert len(fences) == 1 and 'accTitle:' in fences[0].content
    first = interview_engineering.notebook(1, 'ai_ml')
    second = interview_engineering.notebook(2, 'ai_ml')
    assert first['text'] == second['text'] and first['focus'] != second['focus']
    assert 'This case connects the week’s topics' in interview_lessons.lesson(2, PUBLIC)['text']
    with pytest.raises(ValueError):
        interview_engineering.notebook(1, 'private')
    with pytest.raises(ValueError):
        interview_engineering.notebook(True, 'ai_ml')


def test_main_reading_embeds_only_matched_technical_sections():
    text = interview_lessons.lesson(15, PUBLIC)['text']
    assert '#### Technical detail' in text and 'Load Balancers' in text
    # This day has no dedicated workflow-state chapter. Its own engineering
    # notebook teaches recovery, without presenting an unrelated SLI as it.
    text = interview_lessons.lesson(50, PUBLIC)['text'].split('**Subject: System design**')[1].split('**Subject: Full-stack')[0]
    assert 'Outcome unknown' in text and 'Reconcile using operation ID' in text
    assert '### SLI' not in text
    # Missing reference files do not remove the authored explanation or flow.
    text = interview_lessons.lesson(1, PUBLIC / 'not-present')['text']
    assert text.count('Engineering notebook') == 3 and text.count('```mermaid') == 3


def test_first_implementation_example_runs_and_rejects_boundary_errors():
    text = interview_engineering.notebook(1, 'full_stack')['text']
    code = next(token.content for token in MarkdownIt().parse(text) if token.type == 'fence' and token.info == 'python')
    namespace = {}
    exec(compile(code, '<authored-course-example>', 'exec'), namespace)
    predict = namespace['baseline_minutes']
    assert predict(5) == 10 and predict(3, 60) == 3
    for bad in (True, '5', -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            predict(bad)
    for bad in (True, '30', 0, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            predict(5, bad)


def test_deeper_teaching_changes_neither_syllabus_identity_nor_progress():
    progress = {}
    interview_course.record_completion(progress, 1, True)
    before = interview_course.completed_days(progress)
    info = interview_course.course_info()
    assert info['version'] == 1 and interview_course.TEACHING_VERSION == 4
    assert info['daily_minutes'] == sum(item['minutes'] for item in info['daily_session']) == 240
    assert '3 years' in info['audience'] and 'not a limit' in info['study_note']
    interview_lessons.lesson(1, PUBLIC)
    assert interview_course.completed_days(progress) == before == [1]
