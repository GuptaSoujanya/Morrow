import base64
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes
from common import local_setup
from common.answers import AnswerBook, AnswerEngine
from common.models import Settings
from common.profile import load_profile

PROFILE = {'full_name': 'Example Candidate', 'email': 'candidate@example.com', 'phone': '+91 5555555555',
           'current_location': 'Pune', 'titles': ['Software Engineer'], 'skills': ['Python', 'SQL'],
           'total_experience_years': 0, 'notice_period_days': 0, 'willing_to_relocate': False}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    real_which = local_setup.shutil.which
    monkeypatch.setattr(local_setup.shutil, 'which', lambda binary: '/test/assistant' if binary in ('claude', 'kiro-cli') else real_which(binary))
    instance = local_setup.LocalSetup(tmp_path, ask=lambda *args, **kw: json.dumps({'questions': [{'field': 'full_name', 'question': 'Your full name?'}]}))
    return instance


def saved(setup):
    return setup.save({'revision': setup.status()['revision'], 'profile': PROFILE})


def uploaded(setup):
    saved(setup)
    setup.upload_resume({'revision': setup.status()['revision'], 'filename': 'candidate.pdf',
                         'content_base64': base64.b64encode(pdf_bytes('Example Candidate - Python engineer')).decode()})
    setup.extraction_worker.join(5)
    return saved(setup)  # User reviewed the uploaded resume, including any extraction gaps.


def finish(setup):
    setup.start({'revision': setup.status()['revision']})
    setup.worker.join(timeout=5)
    assert not setup.worker.is_alive()
    return setup.status()


def test_fresh_setup_resumes_and_keeps_private_files(setup):
    assert setup.status()['needs_setup']
    before = setup.status()['revision']
    state = saved(setup)
    assert state['profile']['total_experience_years'] == 0
    assert state['profile']['willing_to_relocate'] is False
    assert local_setup.LocalSetup(setup.root).status()['profile'] == state['profile']
    assert state['revision'] != before
    for path in ['.env', 'user/inputs/profile.yaml', 'user/inputs/setup.json']:
        assert setup.path(path).stat().st_mode & 0o777 == 0o600
    with pytest.raises(local_setup.SetupError, match='another tab'):
        setup.save({'revision': before, 'profile': PROFILE})


@pytest.mark.parametrize('field,value', [('total_experience_years', True), ('total_experience_years', float('nan')),
    ('notice_period_days', 0.5), ('email', 'invalid'), ('skills', 'Python'), ('phone', None), ('titles', []), ('willing_to_relocate', 'false')])
def test_invalid_input_never_writes(setup, field, value):
    with pytest.raises(local_setup.SetupError):
        setup.save({'revision': setup.status()['revision'], 'profile': {**PROFILE, field: value}})
    assert not setup.path('.env').exists()


def test_env_preserves_credentials_and_never_interpolates_profile_text(setup):
    setup.path('.env').write_text('NAUKRI_PASSWORD="keep-this"\nCUSTOM=value\nLLM_BACKEND=old\n')
    profile = {**PROFILE, 'full_name': "O'Brien ${HOME} `whoami`"}
    setup.save({'revision': setup.status()['revision'], 'profile': profile, 'provider': 'kiro'})
    env = dotenv_values(setup.path('.env'), interpolate=False)
    assert env['NAUKRI_PASSWORD'] == 'keep-this' and env['CUSTOM'] == 'value'
    assert env['FIRSTNAME'] == "O'Brien" and env['LASTNAME'] == '${HOME} `whoami`'
    assert setup.runtime_environment()['LLM_BACKEND'] == 'kiro-cli'
    assert 'NAUKRI_PASSWORD' not in setup.runtime_environment()


def test_real_pdf_and_generated_bank_are_consumable_without_manual_files(setup):
    uploaded(setup)
    state = finish(setup)
    assert state['complete'] and state['generation']['state'] == 'ready'
    settings = Settings(profile_path=str(setup.path('user/inputs/profile.yaml')), resume_path=str(setup.path('user/resume/onboarding.pdf')), data_dir=str(setup.path('user/inputs')))
    profile = load_profile(settings)
    resolver = AnswerEngine(None, None, profile, settings)
    resolver._refresh_fingerprint()
    assert resolver.book.answer_for('What is your full name?') == PROFILE['full_name']
    assert resolver.book.answer_for('How many years of work experience do you have?') == '0'
    assert resolver.book.answer_for('Are you willing to relocate?') == 'No'
    assert not resolver.book.source_entries  # Generated answers never become their own evidence.
    assert 'expected CTC' not in setup.path('user/inputs/answers.txt').read_text()
    assert local_setup.LocalSetup(setup.root).status()['complete']
    before = setup.path('user/inputs/answers.txt').read_text()
    assert setup.start({'revision': state['revision']})['complete']
    assert setup.path('user/inputs/answers.txt').read_text() == before


def test_generated_updates_preserve_manual_answers_and_refresh_provenance(setup):
    uploaded(setup)
    answers = setup.path('user/inputs/answers.txt')
    manual = 'Q: What is your email address?\nA: preferred@example.com\n'
    answers.write_text(manual)
    finish(setup)
    setup.save({'revision': setup.status()['revision'], 'profile': {**PROFILE, 'phone': '+91 4444444444'}})
    finish(setup)
    assert answers.read_text().startswith(manual)
    settings = Settings(profile_path=str(setup.path('user/inputs/profile.yaml')), resume_path=str(setup.path('user/resume/onboarding.pdf')), data_dir=str(setup.path('user/inputs')))
    resolver = AnswerEngine(None, None, load_profile(settings), settings)
    resolver._refresh_fingerprint()
    assert resolver.book.answer_for('What is your phone number?') == '+91 4444444444'
    assert resolver.book.answer_for('What is your email address?') == 'preferred@example.com'


@pytest.mark.parametrize('output', ['not JSON', '{"questions":[]}', '{"questions":[{"field":"made_up_salary","question":"Salary?"}]}'])
def test_bad_ai_output_is_retryable_and_does_not_touch_answers(setup, output):
    uploaded(setup)
    path = setup.path('user/inputs/answers.txt')
    path.write_text('Q: Your answer?\nA: Keep me\n')
    setup.ask = lambda *a, **kw: output
    state = finish(setup)
    assert state['generation']['state'] == 'error' and not state['complete']
    assert path.read_text() == 'Q: Your answer?\nA: Keep me\n'
    setup.ask = lambda *a, **kw: '{"questions":[{"field":"phone","question":"Phone number?"}]}'
    assert finish(setup)['complete']


def test_double_submit_single_job_and_manual_edits_during_generation_survive(setup):
    uploaded(setup)
    gate = threading.Event()
    calls = []
    def ask(*args, **kw):
        calls.append(kw); gate.wait(5)
        return '{"questions":[{"field":"phone","question":"Phone number?"}]}'
    setup.ask = ask
    first = setup.start({'revision': setup.status()['revision']})
    second = setup.start({'revision': setup.status()['revision']})
    assert first['generation']['id'] == second['generation']['id']
    with pytest.raises(local_setup.SetupError, match='being prepared'):
        saved(setup)
    setup.path('user/inputs/answers.txt').write_text('Q: Phone number?\nA: My edited answer\n')
    gate.set(); setup.worker.join(5)
    assert len(calls) == 1 and calls[0]['web'] is False
    assert AnswerBook(str(setup.path('user/inputs/answers.txt'))).answer_for('Phone number?') == 'My edited answer'


def test_interrupted_job_exposes_retry_and_never_claims_completion(setup):
    uploaded(setup)
    data = setup._manifest(); data['generation'] = {'state': 'running'}; setup._save_manifest(data)
    state = local_setup.LocalSetup(setup.root).status()
    assert not state['complete'] and state['generation']['state'] == 'error'
    assert finish(setup)['complete']


def test_busy_runner_and_symlinks_do_not_modify_inputs(setup, tmp_path):
    setup.runner = SimpleNamespace(running=True)
    with pytest.raises(local_setup.SetupError, match='Stop the active agents'):
        saved(setup)
    setup.runner = None
    outside = tmp_path / 'outside'; outside.mkdir()
    (tmp_path / 'user').symlink_to(outside, target_is_directory=True)
    with pytest.raises(local_setup.SetupError, match='symbolic'):
        setup.status()
    assert not list(outside.iterdir())


def test_unreadable_pdf_preserves_previous_resume(setup):
    uploaded(setup)
    before = setup.path('user/resume/onboarding.pdf').read_bytes()
    with pytest.raises(local_setup.SetupError):
        setup.upload_resume({'revision': setup.status()['revision'], 'filename': 'bad.pdf', 'content_base64': base64.b64encode(b'not pdf').decode()})
    assert setup.path('user/resume/onboarding.pdf').read_bytes() == before
