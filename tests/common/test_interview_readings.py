"""Public guides must not present a nearby chapter as a different day's lesson."""
from pathlib import Path

from common import interview_course, interview_lessons


PUBLIC = Path(__file__).parents[2] / 'database/course'


def reading(day, key):
    spec = interview_course.day_spec(day)
    folder = next(folder for name, _, folder in interview_lessons._TRACKS if name == key)
    return interview_lessons._reading(spec, key, folder, PUBLIC)


def test_topic_search_can_leave_the_weeks_suggested_chapter():
    # Week three used to restrict system design to scalability patterns, whose
    # first section is microservices. The actual load-balancing explanation is
    # in the fundamentals chapter.
    result = reading(15, 'system_design')
    assert result['title'] == 'Load Balancers'
    assert result['path'] == '01-system-design/01-fundamentals.md'
    assert result['match'] == 'topic'
    assert 'Microservices vs Monolith' not in result['text']


def test_uncertainty_review_teaches_quality_and_uncertainty_instead_of_learning_types():
    result = reading(14, 'ai_ml')
    assert result['match'] == 'primer'
    assert 'duplicate replies' in result['text'] and 'small sample' in result['text']
    assert 'Cleaning data does not remove all uncertainty' in result['text']
    assert 'Supervised vs. Unsupervised Learning' not in result['text']


def test_deployment_environment_guide_explains_separation_instead_of_service_metrics():
    result = reading(29, 'system_design')
    assert result['match'] == 'primer'
    assert 'staging' in result['text'] and 'production' in result['text']
    assert 'separate credentials' in result['text']
    assert result['path'] == '03-fullstack-mern-kubernetes/05-fullstack-project-architecture.md'
    assert 'SLI, SLO, SLA' not in result['text']


def test_application_dashboard_is_not_substituted_with_infrastructure_monitoring():
    result = reading(14, 'full_stack')
    assert result['match'] == 'primer'
    assert 'weekly total should be 50' in result['text']
    assert 'Prometheus' not in result['text'] and 'Grafana' not in result['text']


def test_sql_guide_is_not_substituted_with_mongodb_aggregation():
    result = reading(9, 'full_stack')
    assert result['match'] == 'primer'
    assert 'GROUP BY' in result['text'] and 'LEFT JOIN' in result['text']
    assert 'SQL vs NoSQL' not in result['text']  # Linked as background, not copied as the lesson.
    assert '$group' not in result['text']


def test_missing_topic_is_explicit_and_does_not_embed_an_unrelated_section():
    result = reading(50, 'system_design')
    assert result['topic'] == 'Workflow state machines'
    assert result['match'] == 'related'
    assert result['title'].startswith('Related background:')
    assert 'does not yet contain a dedicated explanation' in result['text']
    assert 'not a full lesson on this topic' in result['text']
    assert '### SLI' not in result['text']


def test_reference_demoting_does_not_rewrite_heading_text_inside_code(tmp_path):
    folder = tmp_path / '01-system-design'
    folder.mkdir()
    (folder / '01-fundamentals.md').write_text(
        '# Fundamentals\n\n## Load Balancers\nA useful explanation.\n\n```python\n## keep this comment\n```\n')
    spec = interview_course.day_spec(15)
    result = interview_lessons._reading(spec, 'system_design', '01-system-design', tmp_path)
    assert '### Load Balancers' in result['text']
    assert '```python\n## keep this comment\n```' in result['text']


def test_generic_word_overlap_is_not_enough_to_claim_a_topic_match(tmp_path):
    folder = tmp_path / '04-ml-genai-agents'
    folder.mkdir()
    (folder / '01-ml-fundamentals.md').write_text(
        '# Fundamentals\n\n## Data storage\nRows on disk.\n\n## Model output\nA prediction.\n')
    spec = {**interview_course.day_spec(10), 'ai_ml': 'Data uncertainty and confidence'}
    result = interview_lessons._reading(spec, 'ai_ml', '04-ml-genai-agents', tmp_path)
    assert result['match'] == 'related'
    assert 'Rows on disk' not in result['text'] and 'A prediction' not in result['text']
