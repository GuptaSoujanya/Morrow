"""Resume-first intake, grounded drafts, retry and review boundaries."""
import base64
import json
from pathlib import Path
import sys
import threading

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes
from common.local_setup import LocalSetup, SetupError, resume_profile

RESUME = '''Example Candidate
candidate@example.com | +91 5555555555 | Pune
Software Engineer at Example Ltd, Jan 2022 - Present
4 years of experience
Skills: Python, SQL, React
BSc Computer Science
linkedin.com/in/example-candidate
'''
FIELDS = [
    ('full_name', 'Example Candidate', 'Example Candidate'),
    ('email', 'candidate@example.com', 'candidate@example.com'),
    ('phone', '+91 5555555555', '+91 5555555555'),
    ('current_location', 'Pune', 'Pune'),
    ('titles', ['Software Engineer', 'Backend Engineer'], 'Software Engineer'),
    ('preferred_locations', ['Pune'], 'Pune'),
    ('skills', ['Python', 'SQL', 'React'], 'Skills: Python, SQL, React'),
    ('total_experience_years', 4, '4 years of experience'),
    ('highest_qualification', 'BSc Computer Science', 'BSc Computer Science'),
    ('current_company', 'Example Ltd', 'Software Engineer at Example Ltd, Jan 2022 - Present'),
    ('current_designation', 'Software Engineer', 'Software Engineer'),
    ('employment_history', 'Software Engineer at Example Ltd, Jan 2022 - Present', 'Software Engineer at Example Ltd, Jan 2022 - Present'),
    ('linkedin_url', 'linkedin.com/in/example-candidate', 'linkedin.com/in/example-candidate'),
]


def result(fields=FIELDS):
    return json.dumps({'fields': [{'field': k, 'value': v, 'evidence': e} for k, v, e in fields]})


@pytest.fixture
def setup(tmp_path):
    return LocalSetup(tmp_path, ask=lambda *a, **kw: result())


def upload(setup, text=RESUME, provider='kiro'):
    return setup.upload_resume({'revision': setup.status()['revision'], 'provider': provider,
                               'filename': 'candidate.pdf', 'content_base64': base64.b64encode(pdf_bytes(text)).decode()})


def wait(setup):
    setup.extraction_worker.join(5)
    assert not setup.extraction_worker.is_alive()
    return setup.status()


def test_resume_is_first_input_and_prefills_all_review_steps(setup):
    upload(setup)
    status = wait(setup)
    draft = status['profile_draft']
    assert status['profile'] == {} and status['provider'] == 'kiro'
    assert status['extraction']['state'] == 'ready'
    assert status['extraction']['sources']['titles'] == 'suggested'
    assert draft['full_name'] == 'Example Candidate'
    assert draft['skills'] == ['Python', 'SQL', 'React']
    assert draft['total_experience_years'] == 4
    assert draft['titles'] == ['Software Engineer', 'Backend Engineer']
    assert draft['preferred_locations'] == ['Pune']
    assert draft['extra_facts']['current_company'] == 'Example Ltd'
    assert draft['extra_facts']['linkedin_url'].startswith('https://')
    assert 'expected_ctc_lpa' not in draft and 'notice_period_days' not in draft
    assert not setup.path('user/inputs/profile.yaml').exists() and not setup.path('.env').exists()
    for path in ['user/resume/onboarding.pdf', 'user/inputs/setup.json']:
        assert setup.path(path).stat().st_mode & 0o777 == 0o600
    reopened = LocalSetup(setup.root).status()
    assert reopened['profile_draft'] == draft and reopened['review_step'] == 'profile'
    draft['full_name'] = 'Reviewed Candidate'
    draft['titles'] = ['Backend Engineer']
    status = setup.save_draft({'revision': status['revision'], 'profile': draft})
    assert status['review_step'] == 'preferences' and status['profile'] == {}
    assert LocalSetup(setup.root).status()['profile_draft']['full_name'] == 'Reviewed Candidate'
    status = setup.save({'revision': status['revision'], 'profile': draft})
    assert status['profile']['full_name'] == 'Reviewed Candidate'
    assert status['profile']['titles'] == ['Backend Engineer']
    assert 'RESUME_PATH' in setup.path('.env').read_text()


def test_grounding_and_validation_drop_bad_fields_without_losing_good_ones():
    fields = FIELDS + [
        ('skills', ['Python', 'InventedTech'], 'Python, SQL, React'),
        ('expected_ctc_lpa', 75, 'invented salary quote'),
        ('notice_period_days', -1, 'Pune'),
        ('work_authorization', 'Citizen', ''),
        ('has_passport', 'true', 'Pune'),
        ('phone', '+1 2222222222', '+91 5555555555'),
        ('api_key', 'secret', 'Pune'),
    ]
    profile, sources = resume_profile(result(fields), RESUME)
    assert profile['skills'] == ['Python', 'SQL', 'React']
    assert profile['phone'] == '+91 5555555555'
    assert not {'expected_ctc_lpa', 'notice_period_days', 'work_authorization', 'has_passport', 'api_key'} & profile.keys()
    assert 'api_key' not in sources


def test_failure_keeps_resume_and_contacts_then_retry_recovers(setup):
    setup.ask = lambda *a, **kw: 'not JSON'
    upload(setup)
    status = wait(setup)
    assert status['extraction']['state'] == 'error'
    assert status['resume']['filename'] == 'candidate.pdf'
    assert status['profile_draft']['email'] == 'candidate@example.com'
    assert status['profile_draft']['phone'] == '+91 5555555555'
    assert 'total_experience_years' not in status['profile_draft']
    assert 'full_name' not in status['profile_draft']
    setup.ask = lambda *a, **kw: result()
    setup.extract_resume({'revision': status['revision'], 'provider': 'claude'})
    assert wait(setup)['extraction']['state'] == 'ready'
    assert setup.status()['provider'] == 'claude'


def test_inflight_is_deduplicated_and_cannot_race_profile_writes(setup):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def ask(prompt, **kw):
        calls.append(kw)
        entered.set()
        release.wait(5)
        return result()
    setup.ask = ask
    status = upload(setup)
    try:
        assert entered.wait(2)
        assert status['extraction']['state'] == 'running'
        assert setup.extract_resume({'revision': status['revision']})['extraction']['id'] == status['extraction']['id']
        with pytest.raises(SetupError, match='being read'):
            setup.save_draft({'revision': status['revision'], 'profile': {}})
        with pytest.raises(SetupError, match='being read'):
            upload(setup)
        assert LocalSetup(setup.root).status()['extraction']['state'] == 'error'
    finally:
        release.set()
        wait(setup)
    assert len(calls) == 1 and calls[0]['web'] is False and calls[0]['timeout_s'] == 180
    with pytest.raises(SetupError, match='another tab'):
        setup.save_draft({'revision': status['revision'], 'profile': setup.status()['profile_draft']})


def test_new_resume_replaces_draft_but_keeps_reviewed_profile_until_confirmation(setup):
    upload(setup)
    status = wait(setup)
    original = {**status['profile_draft'], 'current_ctc_lpa': 10}
    setup.save({'revision': status['revision'], 'profile': original})
    setup.ask = lambda *a, **kw: result([('full_name', 'New Candidate', 'New Candidate')])
    upload(setup, 'New Candidate\nnew@example.com')
    status = wait(setup)
    assert status['profile']['full_name'] == 'Example Candidate'
    assert status['profile_draft']['full_name'] == 'New Candidate'
    assert 'skills' not in status['profile_draft']
    assert 'current_ctc_lpa' not in status['profile_draft']
    with pytest.raises(SetupError, match='Review your resume'):
        setup.start({'revision': status['revision']})
    with pytest.raises(SetupError, match='phone'):
        setup.save_draft({'revision': status['revision'], 'profile': status['profile_draft']})
    reviewed = {**original, 'full_name': 'New Candidate'}
    reviewed.pop('current_ctc_lpa')
    status = setup.save({'revision': status['revision'], 'profile': reviewed})
    assert status['profile']['full_name'] == 'New Candidate'
    assert 'current_ctc_lpa' not in status['profile']


def test_incomplete_fields_remain_editable_without_invented_defaults(setup):
    setup.ask = lambda *a, **kw: result([('email', 'candidate@example.com', 'candidate@example.com')])
    upload(setup)
    status = wait(setup)
    assert status['extraction']['state'] == 'ready'
    assert 'total_experience_years' not in status['profile_draft']
    assert 'titles' not in status['profile_draft']
    with pytest.raises(SetupError, match='full name'):
        setup.save({'revision': status['revision'], 'profile': status['profile_draft']})


def test_interrupted_extraction_retry_and_manual_fallback(setup):
    upload(setup)
    status = wait(setup)
    data = setup._manifest()
    data['extraction']['state'] = 'running'
    setup._save_manifest(data)
    reopened = LocalSetup(setup.root, ask=setup.ask)
    assert reopened.status()['extraction']['state'] == 'error'
    reopened.extract_resume({'revision': reopened.status()['revision']})
    status = wait(reopened)
    assert status['extraction']['state'] == 'ready'
    # AI failures do not prevent a user from completing a reviewed profile.
    reopened.ask = lambda *a, **kw: 'bad output'
    reopened.extract_resume({'revision': status['revision']})
    failed = wait(reopened)
    saved = reopened.save_draft({'revision': failed['revision'], 'profile': status['profile_draft']})
    assert saved['review_step'] == 'preferences'


def test_close_cancels_resume_reading_without_publishing_draft(setup):
    entered = threading.Event()
    def ask(*a, cancel_event, **kw):
        entered.set()
        cancel_event.wait(3)
        return result()
    setup.ask = ask
    upload(setup)
    assert entered.wait(2)
    setup.close()
    assert not setup.extraction_worker.is_alive()
    assert setup.status()['extraction']['state'] == 'error'
    assert not setup.status()['complete']
    assert 'full_name' not in setup.status()['profile_draft']
