"""Shared interview cases and project assessments. No learner data or network IO."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from . import interview_course

TRACKS = (('ai_ml', 'AI & ML', 'ai'), ('system_design', 'System design', 'systems'),
          ('full_stack', 'Full-stack', 'build'))


def subject(day, track):
    spec = interview_course.day_spec(day)
    from . import interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews
    modules = dict(zip((key for key, _, _ in TRACKS),
                       (interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews)))
    if track not in modules:
        raise ValueError('Choose AI & ML, system design or full-stack.')
    entry = modules[track].lesson(day)
    if day == 1:
        from .interview_engineering import kickoff_questions
        entry['questions'] = kickoff_questions(track)
        guide = next(item for item in spec['learning_path'] if item['key'] == track)
        entry['drill'], entry['checks'] = guide['task'], guide['checks'][:]
    return entry


def references():
    from . import interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews
    seen, rows = set(), []
    for module in (interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews):
        for row in module.SOURCES:
            if row['url'] not in seen:
                rows.append(dict(row)); seen.add(row['url'])
    react = {'title': 'sudheerj/reactjs-interview-questions (MIT)', 'url': 'https://github.com/sudheerj/reactjs-interview-questions'}
    if react['url'] not in seen:
        rows.append(react)
    return rows


@lru_cache(maxsize=1)
def _questions():
    rows = []
    for day in range(1, 91):
        spec = interview_course.day_spec(day)
        for track, title, part in TRACKS:
            entry = subject(day, track)
            for number, question in enumerate(entry['questions'], 1):
                rows.append({**question, 'id': f'{track}-{day}-{number}', 'day': day, 'week': spec['week'],
                             'track': track, 'track_title': title, 'topic': spec[track],
                             'level': 'Foundations' if day <= 28 else 'Applied' if day <= 70 else 'Mock interview',
                             'part': part})
    rows.extend(_react_rows())
    return rows


# Curated from sudheerj/reactjs-interview-questions (MIT); see data/THIRD_PARTY_NOTICES.md.
# Core questions sit with day 72 (core frontend), React 18/19 with day 78 (frontend state).
_REACT_FILE = Path(__file__).parent / 'data' / 'react_interview_questions.json'
_REACT_DAYS = {'core': 72, 'modern': 78}


def _react_rows():
    rows = []
    for item in json.loads(_REACT_FILE.read_text(encoding='utf-8')):
        day = _REACT_DAYS[item['section']]
        rows.append({key: item[key] for key in ('question', 'answer', 'follow_up', 'follow_up_answer')}
                    | {'id': item['id'], 'day': day, 'week': interview_course.day_spec(day)['week'],
                       'track': 'full_stack', 'track_title': 'Full-stack', 'topic': item['topic'],
                       'level': 'Mock interview', 'part': 'build', 'source_url': item['source_url']})
    return rows


def bank_rows():
    """Every question in the bank, read-only, as question_bank searches it."""
    return _questions()


def day_question_ids(day):
    """The ids of the interview questions taught on a course day, for review seeding."""
    return [row['id'] for row in _questions() if row['day'] == day]


def question_bank(query=None):
    """Bounded, searchable read-only catalog; identical for local and account users."""
    query = query or {}
    track, search = query.get('track', ''), query.get('q', '').strip()
    if track and track not in {key for key, _, _ in TRACKS}:
        raise ValueError('Choose a valid interview subject.')
    if len(search) > 160:
        raise ValueError('Keep your search under 160 characters.')
    def number(key, default, maximum):
        raw = str(query.get(key, default))
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= maximum:
            raise ValueError(f'Choose a valid {key}.')
        return int(raw)
    week = number('week', 1, 13) if query.get('week') else None
    page = number('page', 1, 10000)
    size = 12
    terms = search.casefold().split()
    all_rows = _questions()
    rows = [row for row in all_rows if (not track or row['track'] == track)
            and (not week or row['week'] == week)
            and all(term in (row['topic'] + ' ' + row['question'] + ' ' + row['follow_up']).casefold()
                    for term in terms)]
    pages = max(1, (len(rows) + size - 1) // size)
    page = min(page, pages)
    from .interview_lessons import render
    items = []
    origin = {key: value for key, value in (('view', 'questions'), ('track', track), ('q', search),
                                           ('week', week), ('page', page)) if value}
    for row in rows[(page - 1) * size:page * size]:
        route_query = {**origin, 'from': 'weekly', 'part': row['part'], 'stage': 'interview'}
        items.append({**row, 'answer_html': render(row['answer']),
                      'follow_up_answer_html': render(row['follow_up_answer']),
                      'route': f"#/learning/read/interview%2Fday-{row['day']}?{urlencode(route_query)}"})
    return {'items': items, 'total': len(rows), 'bank_total': len(all_rows), 'page': page, 'pages': pages,
            'page_size': size, 'query': {'q': search, 'track': track, 'week': week},
            'tracks': [{'key': key, 'title': title, 'count': sum(row['track'] == key for row in all_rows)}
                       for key, title, _ in TRACKS], 'sources': references()}


# Each weekly deliverable has observable checks, not just a project name.
_PROJECTS = (
    ('Build a study tracker',
     'Save a topic and minutes studied. Show the total and unfinished lessons. Start with one learner.',
     ('Saving 20 minutes and 30 minutes shows 50 after a reload.', 'Reject negative minutes and an empty topic.',
      'Explain the browser → API → database path.', 'A failed save leaves the old total and offers retry.'),
     'The total becomes 70 after the learner clicks Save twice. Find the cause and explain a fix.',
     'Compare preventing a second click with identifying the same request on the server. A browser-only fix cannot handle a retry after a lost response.'),
    ('Build a data-quality dashboard',
     'Import a small CSV of study sessions. Show valid rows, rejected rows and total minutes per learner.',
     ('Include a missing value, duplicate ID and invalid number in the sample.', 'Explain each rejection without silently inventing a value.',
      'A learner with no sessions appears with zero.', 'Test a join that could accidentally count a session twice.'),
     'Your chart is twice the expected total after a database join. Walk through the rows before changing the code.',
     'Check the relationship on both sides of the join. Aggregate at the intended level and test the report against a small hand-calculated sample.'),
    ('Build a prediction service with sign-in',
     'Train a small baseline on public or invented data. Let a signed-in learner request a prediction.',
     ('Keep training and final test records separate.', 'Compare a simple baseline and a learned model on the same held-out rows.',
      'Reject a request without the required inputs.', 'Test that one learner cannot read another learner’s saved predictions.'),
     'A model scores very well locally but fails on future data. Investigate before choosing a more complex model.',
     'Check leakage, time-based splits, different input distributions and whether the same preprocessing runs in training and serving. Report uncertainty.'),
    ('Build a queued prediction service',
     'Accept a file, return a job ID, and show queued, running, succeeded or failed status.',
     ('Duplicate submission does not create duplicate results.', 'A crashed worker leaves a recoverable job.',
      'A timeout is visible and does not become a false success.', 'Demonstrate one retry and one permanently invalid input.'),
     'A worker finishes the job but crashes before acknowledging the message. What happens next?',
     'Expect possible redelivery. Use a durable job identity and a safe state transition so repeated processing does not repeat an external effect.'),
    ('Ship a reproducible model demo',
     'Package a small model and API so another person can run the same version using your README.',
     ('Pin the model and dependency versions.', 'Record the data split, seed and evaluation results.',
      'Run tests before release; keep credentials outside the repository.', 'Show a health check and a rollback to the previous version.'),
     'Your new container starts but cannot load its model. Decide what health checks and release checks should catch this.',
     'Separate process liveness from readiness to serve. Validate model loading and a representative inference before routing real traffic.'),
    ('Build a streamed assistant',
     'Stream a response to a page. Give users Cancel and a useful error state. Use a stub if you have no model account.',
     ('A new request does not display tokens from an older request.', 'Cancel stops UI updates and requests server cancellation where supported.',
      'Invalid structured output is rejected before saving.', 'Test empty output, a network failure and a slow response.'),
     'An old response finishes after a new request and overwrites it. Explain the race and test your fix.',
     'Give each request an identity. Apply results only to the current request. Cancellation helps with work but does not replace checking identity.'),
    ('Build a document assistant with citations',
     'Index a small set of documents. Answer questions from retrieved passages and show the supporting passages.',
     ('Record document IDs and versions on chunks.', 'Include answerable and unanswerable questions in an evaluation set.',
      'Check retrieval quality separately from answer quality.', 'Do not treat a citation as proof unless its passage supports the answer.'),
     'The answer sounds correct but the citation does not support it. Is this a retrieval problem or a generation problem?',
     'Inspect the retrieved passages first. If support was absent, improve retrieval or abstain. If support was present but ignored, improve answer constraints and evaluation.'),
    ('Build a recoverable tool workflow',
     'Build an assistant that searches notes and proposes one change. Require approval before applying the change.',
     ('Validate tool names and input schemas.', 'Limit steps, time and repeated calls.',
      'A restart can resume from a durable checkpoint.', 'Instructions inside retrieved notes cannot grant permissions.'),
     'The assistant times out after sending a change request. How do you prevent a retry from applying the change twice?',
     'Use an operation ID and reconcile the saved outcome before retrying. A checkpoint must describe the external effect, not only the model’s last message.'),
    ('Build a monitored ML pipeline',
     'Validate a small dataset, train a versioned model, and publish a report of quality and serving latency.',
     ('Record data, code and model versions together.', 'Compare training and serving feature definitions.',
      'Measure latency and error rates on a repeatable workload.', 'Document a rollback trigger and test the rollback path.'),
     'Latency is healthy but prediction quality falls after a data-source change. What will you inspect?',
     'Check schema and feature changes, missing values and input distributions. Separate drift indicators from measured quality when labels arrive later.'),
    ('Build a recommendation feature',
     'Start with a popularity baseline. Add one personalised approach and compare them on a defined task.',
     ('Describe how new users and new items get recommendations.', 'Choose a time split that avoids future interactions.',
      'Measure a ranking metric and a product guardrail.', 'Explain how feedback collection could bias future training.'),
     'Clicks rise after launch, but users return less often. Decide what evidence you need before keeping the change.',
     'Check the experiment assignment, uncertainty and longer-term guardrails. Higher clicks alone do not establish better recommendations or user value.'),
    ('Deliver the capstone',
     'Combine a useful user flow, an API, storage and one measured AI feature. Make the project runnable by another person.',
     ('The README states the problem, inputs and measurable success criteria.', 'Include an architecture drawing, API examples and data model.',
      'Run an evaluation set and document important failures.', 'Record a five-minute demo covering one failure and its recovery.'),
     'You have one week left. Choose between another AI feature and improving reliability. Defend your scope decision.',
     'Use the project goal and measured failures to prioritise. Show the smallest complete outcome, the cost of each option and a clear next experiment.'),
    ('Run a complete practice interview',
     'Use a fresh question from each subject. Record your reasoning or practise with a partner, then inspect the reference answers.',
     ('Clarify requirements before proposing a solution.', 'Work an example and test an edge case.',
      'Explain a trade-off and an alternative.', 'Write down the exact mistake and solve a related question without notes.'),
     'Your first solution does not meet the time or scale limit. How do you recover during an interview?',
     'State the bottleneck honestly, use the constraints to choose another approach, and check it with a small example. Explain rather than silently replacing the solution.'),
    ('Complete a final readiness review',
     'Repeat your weakest interview topics and demonstrate the capstone from a clean setup.',
     ('Complete one unseen coding task with tests and a complexity explanation.', 'Give a system-design answer with requirements, estimates and failure handling.',
      'Defend an ML evaluation choice and describe a limitation.', 'Tell one truthful project story with your own contribution and evidence.'),
     'A practice score improves but you still need hints for unfamiliar problems. What should your next week focus on?',
     'Use new examples to test transfer. Revisit the missing concept, practise explaining without prompts, and keep a mistake log. A completed calendar is not proof of job readiness.'),
)


def weekly_assessment(week):
    interview_course.week_spec(week)
    title, brief, checks, prompt, guidance = _PROJECTS[week - 1]
    return {'title': title, 'brief': brief, 'checks': list(checks), 'mock_question': prompt, 'mock_answer': guidance,
            'rubric': ['0: I needed the answer or could not explain the idea.',
                       '1: I explained part of it, but missed an example, test or trade-off.',
                       '2: I explained it alone, checked an example and discussed a limitation.'],
            'timing': ('Run a 90-minute rehearsal: 20 minutes for AI/ML questions, 25 for system design, '
                       '35 for one coding problem, and 10 for your project story. Choose unseen questions from this week’s bank.'
                       if week >= 12 else
                       'Practise this case for 20 minutes: 3 to clarify, 10 to solve, 5 to test and 2 to review.')}
