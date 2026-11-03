from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.models import JobPosting, Settings, ApplyStatus
from sites_bot import application_brain as brain, browser_agent
from sites_bot.external import ExternalResult


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=str(tmp_path/'inputs'))


@pytest.fixture
def job():
    return JobPosting('hirist:123', 'https://www.hirist.com/job/123', title='AI Engineer', company='Acme')


def test_running_uncertain_confirmed_attempts_block_future_processes(settings, job):
    assert brain.claim(settings, job, job.url)
    assert not brain.claim(settings, job, job.url)
    assert brain.blocked(settings, job) == 'running'
    result = ExternalResult(status=ApplyStatus.ERROR, url=job.url, detail='No receipt')
    brain.finish(settings, job, result, None)
    assert brain.blocked(replace(settings), job) == 'uncertain'
    brain.resolve(settings, job.job_id, 'confirmed')
    assert brain.blocked(settings, job) == 'confirmed'


def test_explicit_no_send_is_retryable_and_review_requires_no_live_process(settings, job):
    assert brain.claim(settings, job, job.url)
    with pytest.raises(ValueError, match='still running'):
        brain.resolve(settings, job.job_id, 'not_sent')
    brain.finish(settings, job, ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url=job.url),
                 dict(status='needs_you', submission_attempted=False, next_step='Enter notice period'))
    assert not brain.blocked(settings, job)
    assert brain.history(settings)[0]['next_step'] == 'Enter notice period'
    assert brain.claim(settings, job, job.url)
    brain.finish(settings, job, ExternalResult(status=ApplyStatus.ERROR, url=job.url), {})
    brain.resolve(settings, job.job_id, 'not_sent')
    assert brain.claim(settings, job, job.url)


@pytest.mark.parametrize('board', ['naukri','hirist','instahyre','cutshort','wellfound','linkedin','company'])
def test_each_board_has_its_own_instructions(board):
    job = JobPosting(board+':1', 'https://example.com/job')
    assert brain.role_for(job) == board
    prompt = brain.instructions(job)
    assert 'observe' in prompt and 'submission_attempted' in prompt
    assert 'dry run' in prompt and 'untrusted data' in prompt


def test_redirect_account_and_verification_states():
    assert brain.observe('https://accounts.google.com/choose', 'Choose an account')[0] == 'sign_in'
    assert brain.observe('https://jobs.acme.com', 'Check your email')[0] == 'email_verification'
    assert brain.observe('https://jobs.acme.com', 'Verify you are human')[0] == 'needs_you'
    assert brain.observe('https://jobs.acme.com/apply', 'Attach resume')[0] == 'inspect'


def test_email_authorization_requires_explicit_posting_instruction_and_one_recipient():
    def driver(links):return SimpleNamespace(execute_script=lambda _:links)
    footer={'href':'mailto:careers@acme.com','text':'Careers contact','around':'careers@acme.com'}
    assert not brain.mailbox(driver([footer]))
    application={**footer,'text':'Apply by email','around':'Send your resume to careers@acme.com'}
    assert brain.mailbox(driver([application]))=='careers@acme.com'
    assert not brain.mailbox(driver([{**application,'href':'mailto:a@acme.com,b@acme.com'}]))
    assert not brain.mailbox(driver([application,{**application,'href':'mailto:other@acme.com'}]))


class Gmail:
    current_window_handle = 'mail'
    window_handles = ['mail']
    current_url = 'https://mail.google.com/mail/u/0/#sent/abc'
    switch_to = SimpleNamespace(window=lambda handle:None)
    def execute_script(self, script):
        return dict(subjects=['Application: AI Engineer'], addresses=['me@acme.com','jobs@employer.com'], attachments=['resume.pdf'])


def test_email_receipt_requires_exact_recipient_sender_subject_and_attachment():
    report = dict(_authorized_recipient='jobs@employer.com', recipient='jobs@employer.com', _sender='me@acme.com',
                  subject='Application: AI Engineer', _resume_name='resume.pdf')
    assert brain.verify_sent_email(Gmail(), report)
    for field,value in [('recipient','wrong@employer.com'),('_sender','other@acme.com'),('subject','Different role'),('_resume_name','missing.pdf')]:
        assert not brain.verify_sent_email(Gmail(), {**report, field:value})
    draft = Gmail(); draft.current_url = 'https://mail.google.com/mail/u/0/#drafts/abc'
    assert not brain.verify_sent_email(draft, report)


def test_ai_cannot_claim_a_dry_run_submission(monkeypatch, tmp_path):
    monkeypatch.setattr('sites_bot.external.already_applied', lambda driver:'')
    report = dict(status='submitted', confirmation='Application submitted successfully')
    result = browser_agent.to_result(None, browser_agent.AgentRun(report, tmp_path, 1), ExternalResult(url='https://acme.com', status=ApplyStatus.ERROR), True)
    assert result.status == ApplyStatus.ERROR and 'dry run' in result.detail


def test_submission_tool_evidence_overrides_false_no_send_report(tmp_path):
    import json
    event = {'message': {'content': [{'type':'tool_use','name':'mcp__browser__browser_click','input':{'element':'Send application'}}]}}
    (tmp_path/'transcript.jsonl').write_text(json.dumps(event))
    assert brain.submission_click_recorded(tmp_path)
    event['message']['content'][0]['input']['element'] = 'Next page'
    (tmp_path/'transcript.jsonl').write_text(json.dumps(event))
    assert not brain.submission_click_recorded(tmp_path)


def test_startup_jobs_get_the_startup_specialist():
    from types import SimpleNamespace
    from sites_bot import application_brain as brain

    for job_id, source in (("yc:123", "yc:jobs"), ("hn:456", "hn:whoishiring:2026-11")):
        job = SimpleNamespace(job_id=job_id, source=source, url="https://jobs.lever.co/naukri-like")
        assert brain.role_for(job) == "startups"
        assert "Startup specialist" in brain.instructions(job)
    assert brain.role_for(SimpleNamespace(job_id="hirist:1", source="hirist:feed", url="")) == "hirist"


def test_yc_instructions_follow_the_actual_application_destination(job):
    prompt = brain.instructions(job, 'https://www.ycombinator.com/companies/acme/jobs/123-engineer')
    assert 'YC role application' in prompt and 'founder funding application' in prompt
    assert 'YC role application' in brain.instructions(job, 'https://www.workatastartup.com/application?signup_job_id=123')
    assert 'YC role application' not in brain.instructions(job, 'https://ycombinator.com.evil.test/companies/acme/jobs/123')


def test_yc_open_role_link_is_navigation_but_actual_send_is_still_uncertain(tmp_path):
    import json
    path = tmp_path / 'transcript.jsonl'
    url = 'https://www.ycombinator.com/companies/acme/jobs/123-engineer'
    def event(label):
        return json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'mcp__browser__browser_click',
                                                   'input': {'element': label}}]}})
    path.write_text(event('Apply to role link'))
    assert not brain.submission_click_recorded(tmp_path, url)
    assert brain.submission_click_recorded(tmp_path, 'https://other.test/jobs/123')
    path.write_text(event('Apply to role link') + '\n' + event('Submit application'))
    assert brain.submission_click_recorded(tmp_path, url)
    path.write_text(event('Apply to role button'))
    assert brain.submission_click_recorded(tmp_path, url)


def test_malformed_transcript_message_does_not_hide_a_later_submission(tmp_path):
    import json
    events = [{'message': 'malformed'}, {'message': {'content': 'bad shape'}},
              {'message': {'content': [{'type': 'tool_use', 'name': 'mcp__browser__browser_click',
                                       'input': {'element': 'Submit'}}]}}]
    (tmp_path / 'transcript.jsonl').write_text('\n'.join(json.dumps(event) for event in events))
    assert brain.submission_click_recorded(tmp_path)
