import json
import os
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from common import company_outreach as outreach, company_store as store
from common.ledger import Ledger
from common.models import JobPosting, Profile, Settings

REAL_WRITE_EMAIL = outreach.mail.write_email
REAL_JOB_CONTEXT = outreach.job_context


def test_automatic_role_selection_uses_a_saved_id_and_rejects_invented_roles():
    company={'company_id':'a'*24,'name':'Acme','jobs':[
        {'job_id':'j1','title':'Front Office Executive','url':'https://example.com/1'},
        {'job_id':'j2','title':'Python AI Engineer','url':'https://example.com/2'}]}
    class Client:
        def available(self):return True
        def complete_json(self,*args):return {'job_id':self.choice}
    client=Client();client.choice='j2'
    chosen=outreach.automatic_company(company,client,SimpleNamespace(plain_text='Python AI software engineer'))
    assert chosen['jobs'][0]['job_id']=='j2' and chosen['automatic']
    client.choice=None
    assert outreach.automatic_company(company,client,SimpleNamespace(plain_text='Python AI'))['jobs']==[]
    client.choice='invented'
    with pytest.raises(ValueError,match='unknown role'):
        outreach.automatic_company(company,client,SimpleNamespace(plain_text='Python AI'))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for key in ('COLD_EMAIL_FROM','GMAIL_APP_PASSWORD'):
        monkeypatch.setenv(key, os.getenv(key, ''))
    settings = Settings(db_path=str(tmp_path/'jobs.db'), data_dir=str(tmp_path/'inputs'),
                        report_dir=str(tmp_path/'reports'), resume_path=str(tmp_path/'Resume.pdf'),
                        google_email='applicant@gmail.com', env_file=str(tmp_path/'.env'))
    Path(settings.resume_path).write_bytes(b'%PDF-1.4 resume fixture')
    profile = Profile(full_name='Candidate Name', email='applicant@gmail.com')
    with Ledger(settings.db_path) as ledger:
        ledger.record_seen(JobPosting('j1','https://acmelabs.in/jobs/1',company='Acme Labs',title='AI Engineer'))
    store.initialize(settings.db_path)
    company = store.catalog(settings.db_path)[0]
    store.claim(settings.db_path, company)
    store.finish(settings.db_path, company['company_id'], dict(fields={'email':[
        dict(value='careers@acmelabs.in',source='https://acmelabs.in/careers',source_checked=True,
             evidence='Send your resume to careers@acmelabs.in')]}))
    company = store.catalog(settings.db_path)[0]
    outreach.initialize(settings.db_path)
    monkeypatch.setattr(outreach.resume, 'load_source', lambda path:SimpleNamespace(plain_text='My resume',terms=frozenset()))
    monkeypatch.setattr(outreach.mail,'attachment_for',lambda settings,lead:Path(settings.resume_path))
    monkeypatch.setattr(outreach,'job_context',lambda company,job:(job.get('description') or 'Role title only','saved_posting' if job.get('description') else 'title_only'))
    monkeypatch.setattr(outreach.mail,'write_email',lambda *args:('AI Engineer application','I build AI evaluations. My resume is attached.'))
    return settings, profile, company


def prepare(setup):
    settings, profile, company = setup
    contact = outreach.hiring_contacts(company)[0]
    outreach.make_local(settings, profile, object(), company, contact, SimpleNamespace())
    return outreach.records(settings.db_path)[0]


def test_one_local_draft_per_recipient_contains_pitch_and_pdf(setup):
    settings, profile, company=setup
    first=prepare(setup)
    second=prepare(setup)
    assert first['draft_id']==second['draft_id'] and len(outreach.records(settings.db_path))==1
    parsed=BytesParser(policy=policy.default).parsebytes(Path(first['data']['eml']).read_bytes())
    assert parsed['To']=='careers@acmelabs.in' and parsed['X-Unsent']=='1'
    assert parsed['From']=='Candidate Name <applicant@gmail.com>'
    assert list(parsed.iter_attachments())[0].get_filename()=='Resume.pdf'
    body = parsed.get_body(preferencelist=('plain',)).get_content().strip()
    assert body == first['data']['body'] == 'I build AI evaluations. My resume is attached.'


def test_one_automatic_run_turns_unrelated_role_into_introduction_and_verified_gmail_draft(setup,monkeypatch):
    settings,profile,company=setup
    calls=[]
    def write(client,base,lead):
        calls.append(lead)
        if not lead.introduction:raise outreach.PitchIssue('role_mismatch','No relevant background for the saved job.')
        assert not lead.job_url and lead.title=='Introduction based on your résumé'
        return 'Introduction: software opportunities','I build AI evaluations. Are there relevant opportunities? My resume is attached.'
    class VerifiedGmail:
        saves=0
        def save(self,row,uncertain=False):
            self.saves+=1
            parsed=BytesParser(policy=policy.default).parsebytes(Path(row['data']['eml']).read_bytes())
            assert str(parsed['Subject'])=='Introduction: software opportunities'
            assert len(list(parsed.iter_attachments()))==1
            assert list(parsed.iter_attachments())[0].get_payload(decode=True)==Path(settings.resume_path).read_bytes()
            return 'https://mail.google.com/mail/u/0/#search/verified'
    monkeypatch.setattr(outreach.mail,'write_email',write)
    gmail=VerifiedGmail()
    result=outreach._run(settings,profile,object(),company_ids=[company['company_id']],automatic=True,research=False,gmail=gmail)
    assert result['gmail']==1 and result['failed']==0 and gmail.saves==1
    assert len(calls)==2 and calls[1].introduction
    row=outreach.records(settings.db_path)[0]
    assert row['data']['context_source']=='general_inquiry' and row['data']['job_url']==''
    state=outreach.progress.read(settings.db_path,settings.google_email)[company['company_id']]
    assert state['phase']=='ready' and state['title']=='Introduction based on your résumé'
    # Repeat the same click: keep the saved draft even if AI is now unavailable.
    outreach._run(settings,profile,None,company_ids=[company['company_id']],automatic=True,research=False,gmail=gmail)
    assert gmail.saves==1 and len(calls)==2


def test_automatic_drafting_does_not_disguise_ai_or_resume_failures(setup,monkeypatch):
    settings,profile,company=setup
    calls=[]
    def write(*args):
        calls.append(True)
        raise outreach.PitchIssue('resume_unreadable','The résumé could not be read.')
    monkeypatch.setattr(outreach.mail,'write_email',write)
    result=outreach._run(settings,profile,object(),company_ids=[company['company_id']],automatic=True,research=False)
    assert result['failed']==1 and len(calls)==1
    assert not list(Path(settings.report_dir).rglob('*.eml'))


def test_parallel_preparation_claims_address_once(setup):
    settings, profile, company=setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:outreach.claim(settings.db_path,company,'careers@acmelabs.in',settings.google_email),range(2)))
    assert sorted(fresh for _,fresh in results)==[False,True]


def test_unknown_or_irrelevant_emails_never_become_recipients(setup):
    _,_,company=setup
    original=company['fields']['email'][0]
    company['fields']['email'] += [dict(original, value='sales@acmelabs.in', evidence='Contact sales@acmelabs.in'),
                                  dict(original, value='info@acmelabs.in', evidence='Contact info@acmelabs.in for information'),
                                  dict(original, value='invented@acmelabs.in', source_checked=False),
                                  dict(original, value='careers@acmelabs.in\nBcc: bad@evil.in')]
    assert [c['value'] for c in outreach.hiring_contacts(company)]==['careers@acmelabs.in']
    assert outreach.hiring_contacts(company, {'careers@acmelabs.in'})==[]


def test_missing_resume_or_rejected_pitch_never_creates_eml(setup,monkeypatch):
    settings,_,_=setup
    monkeypatch.setattr(outreach.mail,'attachment_for',lambda *args:None)
    row=prepare(setup)
    assert row['state']=='failed' and 'PDF resume' in row['error']
    assert not list(Path(settings.report_dir).rglob('*.eml'))


def test_pdf_resume_source_is_used_and_repeated_run_does_not_rewrite(setup,monkeypatch):
    settings,profile,company=setup
    called=[]
    monkeypatch.setattr(outreach.resume,'load_source',lambda path:called.append(path) or SimpleNamespace())
    outreach.run(settings,profile,object(),research=False)
    assert called==[settings.resume_path]
    monkeypatch.setattr(outreach.mail,'write_email',lambda *args:pytest.fail('Already drafted'))
    outreach.run(settings,profile,object(),research=False)
    assert len(outreach.records(settings.db_path))==1


class Gmail:
    messages=[]
    appends=0
    lose_response=False
    change_attachment=False
    def __init__(self,*args,**kwargs):pass
    def login(self,user,password):pass
    def list(self):return 'OK',[b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"']
    def select(self,folder,readonly=False):
        assert readonly
        return 'OK',[b'1']
    def uid(self,command,*args):
        if command=='search':return 'OK',[b'1' if self.messages else b'']
        return 'OK',[(b'1', self.messages[0])]
    def append(self,folder,flags,when,raw):
        assert flags=='\\Draft'
        type(self).appends+=1
        self.messages.append(raw)
        if self.lose_response:raise OSError('connection lost after save')
        return 'OK',[]
    def logout(self):pass


@pytest.fixture(autouse=True)
def reset_gmail():
    Gmail.messages=[];Gmail.appends=0;Gmail.lose_response=False


def test_gmail_draft_is_confirmed_with_body_and_attachment(setup):
    settings,_,_=setup
    row=prepare(setup);settings.gmail_app_password='a'*16
    outreach.sync_gmail(settings,row,factory=Gmail)
    saved=outreach.records(settings.db_path)[0]
    assert saved['state']=='gmail' and Gmail.appends==1
    outreach.sync_gmail(settings,saved,factory=Gmail)
    assert Gmail.appends==1
    # This adapter has no send/SMTP method; only a Draft APPEND.


def test_lost_save_response_reconciles_without_duplicate(setup):
    settings,_,_=setup
    row=prepare(setup);settings.gmail_app_password='a'*16;Gmail.lose_response=True
    outreach.sync_gmail(settings,row,factory=Gmail)
    row=outreach.records(settings.db_path)[0]
    assert row['state']=='needs_review'
    outreach.sync_gmail(settings,row,factory=Gmail)
    assert outreach.records(settings.db_path)[0]['state']=='gmail' and Gmail.appends==1


def test_unconfirmed_save_is_never_blindly_repeated(setup):
    settings,_,_=setup
    row=prepare(setup);settings.gmail_app_password='a'*16
    outreach.update(settings.db_path,row['draft_id'],'needs_review')
    outreach.sync_gmail(settings,outreach.records(settings.db_path)[0],factory=Gmail)
    assert Gmail.appends==0 and outreach.records(settings.db_path)[0]['state']=='needs_review'


def test_changed_existing_draft_requires_review_instead_of_duplicate(setup):
    settings,_,_=setup
    row=prepare(setup);settings.gmail_app_password='a'*16
    raw=Path(row['data']['eml']).read_bytes().replace(b'AI evaluations',b'other content')
    Gmail.messages=[raw]
    outreach.sync_gmail(settings,row,factory=Gmail)
    assert Gmail.appends==0 and outreach.records(settings.db_path)[0]['state']=='needs_review'


def test_public_table_data_has_pitch_and_download_without_private_paths_or_password(setup):
    settings,_,company=setup
    prepare(setup)
    outreach.attach_rows(settings,[company])
    draft=company['drafts'][0]
    assert draft['body'] and draft['resume']=='Resume.pdf' and draft['download_url'].startswith('/reports/')
    assert 'eml' not in draft and 'gmail_app_password' not in json.dumps(draft)
    assert draft['gmail_url']=='' and outreach.public_status(settings)['gmail_configured'] is False


def test_connection_validates_before_saving_and_never_returns_secret(setup):
    settings,_,_=setup
    response=outreach.connect_gmail(settings,'applicant@gmail.com','abcd efgh ijkl mnop',factory=Gmail)
    assert response=={'connected':True,'sender':'applicant@gmail.com'}
    assert 'GMAIL_APP_PASSWORD=abcdefghijklmnop' in Path(settings.env_file).read_text()
    assert Path(settings.env_file).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):outreach.connect_gmail(settings,'bad\nemail','password',factory=Gmail)


def test_preview_does_not_research_generate_or_create_drafts(setup,monkeypatch):
    settings,profile,_=setup
    monkeypatch.setattr(outreach.mail,'write_email',lambda *args:pytest.fail('preview'))
    assert outreach.run(settings,profile,object(),dry_run=True)['preview'] is True
    assert outreach.records(settings.db_path)==[]


def test_old_recruiter_tool_respects_company_draft_reservation(setup,monkeypatch):
    settings,profile,company=setup
    prepare(setup)
    monkeypatch.setattr(outreach.mail,'write_email',lambda *args:pytest.fail('Duplicate draft'))
    lead=outreach.mail.Lead('careers@acmelabs.in','Acme Labs','AI Engineer','https://acmelabs.in/jobs/1','test')
    counts=outreach.mail.draft_all(settings,profile,object(),[lead],10,False)
    assert counts['already written']==1 and counts['drafted']==0


def test_existing_recruiter_draft_is_reused_without_rewriting(setup,monkeypatch):
    settings,profile,company=setup
    path=outreach.mail.records_path(settings);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'email':'careers@acmelabs.in','subject':'Existing introduction','eml':'saved.eml'})+'\n')
    monkeypatch.setattr(outreach.mail,'write_email',lambda *args:pytest.fail('Duplicate draft'))
    outreach.run(settings,profile,object(),research=False)
    row=outreach.records(settings.db_path)[0]
    assert row['state']=='existing' and row['data']['subject']=='Existing introduction'


def add_company(settings, name, address):
    with Ledger(settings.db_path) as ledger:
        ledger.record_seen(JobPosting(name, 'https://acmelabs.in/jobs/'+name, company=name, title='AI Engineer'))
    company = next(row for row in store.catalog(settings.db_path) if row['name']==name)
    store.claim(settings.db_path, company)
    store.finish(settings.db_path, company['company_id'], dict(fields={'email':[
        dict(value=address, source='https://acmelabs.in/careers', source_checked=True,
             evidence='Send your resume to '+address)]}))
    return next(row for row in store.catalog(settings.db_path) if row['name']==name)


def test_selected_companies_are_exact_and_not_truncated_by_automatic_limit(setup):
    settings, profile, unselected = setup
    first = add_company(settings, 'Selected One', 'careers.one@acmelabs.in')
    second = add_company(settings, 'Selected Two', 'careers.two@acmelabs.in')
    selected = [second['company_id'], first['company_id']]
    result = outreach.run(settings, profile, object(), company_ids=selected, limit=1, research=False)
    assert result['companies']==2 and result['drafts']==2
    assert [row['company_id'] for row in result['company_results']]==selected
    assert {row['company_id'] for row in outreach.records(settings.db_path)}==set(selected)
    assert unselected['company_id'] not in selected


@pytest.mark.parametrize('selection', [[], 'a'*24, [None], ['../private'], ['a'*24]*2, [f'{n:024x}' for n in range(51)]])
def test_invalid_explicit_selection_never_falls_back_to_all_companies(setup, selection):
    settings, profile, _ = setup
    with pytest.raises(ValueError):
        outreach.run(settings, profile, object(), company_ids=selection)
    assert outreach.records(settings.db_path)==[]


def test_unknown_or_ambiguous_selection_stops_before_preparing_any_draft(setup):
    settings, profile, company = setup
    for options in ({'company_ids':[company['company_id'], 'f'*24]},
                    {'company_ids':[company['company_id']], 'all_remaining':True},
                    {'company_ids':[company['company_id']], 'company_id':company['company_id']}):
        with pytest.raises(ValueError):
            outreach.run(settings, profile, object(), **options)
    assert outreach.records(settings.db_path)==[]


def test_selected_preview_lists_exact_ids_without_writing(setup):
    settings, profile, company = setup
    second = add_company(settings, 'Not selected', 'careers.two@acmelabs.in')
    result = outreach.run(settings, profile, object(), company_ids=[company['company_id']], dry_run=True)
    assert result['company_ids']==[company['company_id']] and result['companies']==1
    assert second['company_id'] not in result['company_ids']
    assert outreach.records(settings.db_path)==[]


def test_one_provider_failure_does_not_stop_other_selected_companies(setup, monkeypatch):
    settings, profile, first = setup
    second = add_company(settings, 'Selected Two', 'careers.two@acmelabs.in')
    def write(client, base, lead):
        if lead.email=='careers@acmelabs.in':
            raise RuntimeError('provider failure containing secret')
        return 'AI Engineer application', 'I build AI evaluations. My resume is attached.'
    monkeypatch.setattr(outreach.mail, 'write_email', write)
    result = outreach.run(settings, profile, object(), company_ids=[first['company_id'], second['company_id']], research=False)
    assert result['companies']==2 and result['drafts']==1 and result['failed']==1
    assert [row['state'] for row in result['company_results']]==['failed', 'local']
    assert 'secret' not in json.dumps(outreach.records(settings.db_path))
    assert all(row['state']!='preparing' for row in outreach.records(settings.db_path))


def test_selected_shared_recipient_never_creates_duplicate_pitch(setup):
    settings, profile, first = setup
    second = add_company(settings, 'Shared hiring team', 'careers@acmelabs.in')
    result = outreach.run(settings, profile, object(), company_ids=[first['company_id'], second['company_id']], research=False)
    assert len(outreach.records(settings.db_path))==1 and result['drafts']==1
    assert result['company_results'][1]['state']=='existing'


def test_require_gmail_rejects_local_only_save_before_creating_drafts(setup, monkeypatch):
    settings, profile, company = setup
    monkeypatch.setattr(outreach, 'public_status', lambda settings:{'gmail_configured':False})
    with pytest.raises(ValueError, match='Connect Gmail'):
        outreach.run(settings, profile, object(), company_ids=[company['company_id']], require_gmail=True)
    assert outreach.records(settings.db_path)==[]


def test_browser_gmail_marks_success_only_after_verified_save_and_never_rewrites(setup):
    settings, _, _ = setup
    row = prepare(setup)
    calls = []
    class Browser:
        def save(self, row, uncertain=False):
            calls.append((row['draft_id'], uncertain))
            return 'https://mail.google.com/mail/u/0/#search/verified'
    outreach.sync_browser(settings, row, Browser())
    saved = outreach.records(settings.db_path)[0]
    assert saved['state']=='gmail' and len(calls)==1
    assert saved['data']['gmail_browser_url'].startswith('https://mail.google.com/')
    outreach.sync_browser(settings, saved, Browser())
    assert len(calls)==1


def test_browser_uncertain_save_requires_reconciliation_without_new_draft(setup):
    settings, _, _ = setup
    row=prepare(setup)
    class Interrupted:
        def save(self, row, uncertain=False):
            raise OSError('secret failure')
    outreach.sync_browser(settings, row, Interrupted())
    saved=outreach.records(settings.db_path)[0]
    assert saved['state']=='needs_review' and 'secret' not in saved['error']
    class Reconcile:
        def save(self, row, uncertain=False):
            assert uncertain is True
            return 'https://mail.google.com/mail/u/0/#search/verified'
    outreach.sync_browser(settings, saved, Reconcile())
    assert outreach.records(settings.db_path)[0]['state']=='gmail'


def test_google_browser_requires_managed_session_with_same_verified_sender(setup):
    from common.gmail_browser import available
    from common.connections import mark_managed, write_metadata
    settings, _, _=setup
    root=Path(settings.db_path).parent/'browser'
    settings.browser_profile_dir=str(root)
    assert not available(settings, settings.google_email)
    mark_managed(root)
    write_metadata(root, {'google':{'state':'connected','verified_account':'someone.else@gmail.com'}})
    assert not available(settings, settings.google_email)
    write_metadata(root, {'google':{'state':'connected','verified_account':settings.google_email}})
    assert available(settings, settings.google_email)
    status=outreach.public_status(settings)
    assert status['gmail_configured'] and status['gmail_method']=='browser'


def test_browser_selected_batch_verifies_all_selected_and_skips_already_saved(setup,monkeypatch):
    from common import gmail_browser
    settings,profile,first=setup
    second=add_company(settings,'Second company','careers.two@acmelabs.in')
    calls=[]
    class Session:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def save(self,row,uncertain=False):
            calls.append(row['recipient'])
            return 'https://mail.google.com/mail/u/0/#drafts'
    monkeypatch.setattr(gmail_browser,'GmailDrafts',Session)
    monkeypatch.setattr(outreach,'public_status',lambda settings:{'gmail_configured':True,'gmail_method':'browser'})
    selected=[first['company_id'],second['company_id']]
    first_run=outreach.run(settings,profile,object(),company_ids=selected,research=False,require_gmail=True)
    assert first_run['gmail']==2 and first_run['needs_review']==0
    outreach.run(settings,profile,object(),company_ids=selected,research=False,require_gmail=True)
    assert calls==['careers@acmelabs.in','careers.two@acmelabs.in']


def test_selected_role_survives_contact_research_and_reports_verified_stages(setup, monkeypatch):
    settings, profile, company = setup
    key = company['company_id']
    with Ledger(settings.db_path) as ledger:
        ledger.record_seen(JobPosting('j2', 'https://acmelabs.in/jobs/2', company='Acme Labs', title='Front Office Executive'))
    store.finish(settings.db_path, key, dict(fields={}))
    checked = []
    def research(db, **kwargs):
        checked.append(kwargs['company_id'])
        store.finish(db, key, dict(fields=company['fields']))
    def write(client, base, lead):
        assert lead.title == 'AI Engineer' and lead.job_url.endswith('/1')
        return 'AI Engineer application', 'My résumé is attached.'
    class Gmail:
        def save(self, row, uncertain=False):
            assert Path(row['data']['eml']).is_file()
            assert outreach.progress.read(settings.db_path, settings.google_email)[key]['phase']=='saving'
            return 'https://mail.google.com/mail/u/0/#drafts'
    monkeypatch.setattr(outreach.company_research, 'run', research)
    monkeypatch.setattr(outreach.mail, 'write_email', write)
    result = outreach._run(settings, profile, object(), company_ids=[key], roles={key:'j1'}, gmail=Gmail())
    state = outreach.progress.read(settings.db_path, settings.google_email)[key]
    assert checked == [key] and result['gmail']==1
    assert state['job_id']=='j1' and state['title']=='AI Engineer'
    assert [step['phase'] for step in state['history']]==['queued','contacts','writing','attaching','saving','ready']
    assert outreach.progress.read(settings.db_path, 'different@gmail.com')=={}


def test_unrelated_role_explains_failure_without_creating_a_draft(setup, monkeypatch):
    settings, profile, company = setup
    class Client:
        def available(self):return True
        def complete_json(self, *args):return {'can_write':False,'reason_code':'role_mismatch','reason':'The selected role requires evidence that this résumé does not provide.'}
    monkeypatch.setattr(outreach.mail, 'write_email', REAL_WRITE_EMAIL)
    result=outreach.run(settings,profile,Client(),company_ids=[company['company_id']],roles={company['company_id']:'j1'},research=False)
    state=outreach.progress.read(settings.db_path,settings.google_email)[company['company_id']]
    assert result['failed']==1 and state['phase']=='failed'
    assert state['issue']['code']=='role_mismatch' and 'requires evidence' in state['message']
    assert not list(Path(settings.report_dir).rglob('*.eml'))


@pytest.mark.parametrize('code', ['missing_context','resume_unreadable','unknown',''])
def test_refusal_reasons_are_not_mislabeled_as_role_mismatch(setup, monkeypatch, code):
    settings, profile, company = setup
    class Client:
        def available(self):return True
        def complete_json(self,*args):return {'can_write':False,'reason_code':code,'reason':'Insufficient source information.'}
    monkeypatch.setattr(outreach.mail,'write_email',REAL_WRITE_EMAIL)
    outreach.run(settings,profile,Client(),company_ids=[company['company_id']],research=False)
    state=outreach.progress.read(settings.db_path,settings.google_email)[company['company_id']]
    assert state['issue']['code']==(code if code in ('missing_context','resume_unreadable') else 'review_needed')
    assert state['message']=='Insufficient source information.'


def test_saved_job_description_survives_summary_refresh_and_reaches_pitch(setup, monkeypatch):
    settings,profile,company=setup
    with Ledger(settings.db_path) as ledger:
        ledger.record_seen(JobPosting('j1','https://acmelabs.in/jobs/1',company='Acme Labs',title='AI Engineer',description='Build evaluation tooling with Python.'))
        ledger.record_seen(JobPosting('j1','https://acmelabs.in/jobs/1',company='Acme Labs',title='AI Engineer'))
    saved=store.catalog(settings.db_path)[0]
    assert saved['jobs'][0]['description']=='Build evaluation tooling with Python.'
    def write(client,base,lead):
        assert 'Build evaluation tooling with Python.' in lead.posting
        assert 'Send your resume' not in lead.posting
        return 'AI Engineer','My résumé is attached.'
    monkeypatch.setattr(outreach.mail,'write_email',write)
    outreach.make_local(settings,profile,object(),saved,outreach.hiring_contacts(saved)[0],SimpleNamespace())
    assert outreach.records(settings.db_path)[0]['state']=='local'


def test_public_job_context_rejects_login_pages_and_unrelated_redirects(setup,monkeypatch):
    _,_,company=setup
    job=company['jobs'][0]
    monkeypatch.setattr(outreach,'fetch_page',lambda url:{'text':'Please sign in to view jobs. '*30})
    assert REAL_JOB_CONTEXT(company,job)[1]=='title_only'
    monkeypatch.setattr(outreach,'fetch_page',lambda url:{'text':'Acme Labs AI Engineer. Build evaluation infrastructure. '*20})
    assert REAL_JOB_CONTEXT(company,job)[1]=='public_posting'


def test_gmail_deep_link_uses_sender_instead_of_automation_browser_account_index(setup):
    settings,_,company=setup
    row=prepare(setup)
    outreach.update(settings.db_path,row['draft_id'],'gmail',dict(row['data'],gmail_browser_url='https://mail.google.com/mail/u/3/#search/verified'))
    public=outreach.attach_rows(settings,[company])[0]['drafts'][0]
    assert public['gmail_url']=='https://mail.google.com/mail/u/?authuser=applicant%40gmail.com#search/verified'


def test_browser_startup_failure_is_visible_and_invalid_roles_never_open_browser(setup, monkeypatch):
    from common import gmail_browser
    settings, profile, company = setup
    calls=[]
    class Session:
        def __init__(self,*args):calls.append(True)
        def __enter__(self):raise ValueError('Google sign-in needs attention.')
        def __exit__(self,*args):pass
    monkeypatch.setattr(gmail_browser,'GmailDrafts',Session)
    monkeypatch.setattr(outreach,'public_status',lambda settings:{'gmail_configured':True,'gmail_method':'browser'})
    key=company['company_id']
    for role in ('unknown-job', None, 1):
        with pytest.raises(ValueError):outreach.run(settings,profile,object(),company_ids=[key],roles={key:role})
    assert not calls
    with pytest.raises(ValueError,match='sign-in'):
        outreach.run(settings,profile,object(),company_ids=[key],roles={key:'j1'})
    state=outreach.progress.read(settings.db_path,settings.google_email)[key]
    assert state['phase']=='failed' and state['message']=='Google sign-in needs attention.'
    assert not outreach.records(settings.db_path)


def test_existing_recipient_for_another_role_is_not_claimed_as_new_success(setup):
    settings,profile,company=setup
    first=prepare(setup)
    with Ledger(settings.db_path) as ledger:
        ledger.record_seen(JobPosting('j2','https://acmelabs.in/jobs/2',company='Acme Labs',title='Backend Engineer'))
    result=outreach.run(settings,profile,object(),company_ids=[company['company_id']],roles={company['company_id']:'j2'},research=False)
    state=outreach.progress.read(settings.db_path,settings.google_email)[company['company_id']]
    assert result['failed']==1 and 'different role' in state['message']
    rows=outreach.records(settings.db_path)
    assert len(rows)==1 and rows[0]['data']==first['data']


def test_browser_draft_content_rejects_wrong_sender_and_missing_pdf(setup):
    from common.gmail_browser import draft_content,DraftVerificationError
    settings,_,_=setup
    row=prepare(setup)
    raw=Path(row['data']['eml']).read_bytes()
    subject,body,filename,payload=draft_content(raw,settings.google_email,row['recipient'])
    assert filename=='Resume.pdf' and payload.startswith(b'%PDF-')
    with pytest.raises(DraftVerificationError):draft_content(raw,'wrong@gmail.com',row['recipient'])
    with pytest.raises(DraftVerificationError):draft_content(raw,settings.google_email,'wrong@example.com')
    parsed=BytesParser(policy=policy.default).parsebytes(raw)
    parsed.set_payload([parsed.get_body(preferencelist=('plain',))])
    with pytest.raises(DraftVerificationError):draft_content(parsed.as_bytes(),settings.google_email,row['recipient'])


def test_required_gmail_does_not_report_local_only_as_success(setup,monkeypatch):
    settings,profile,company=setup
    monkeypatch.setattr(outreach,'public_status',lambda settings:{'gmail_configured':True,'gmail_method':'imap'})
    result=outreach.run(settings,profile,object(),company_ids=[company['company_id']],research=False,require_gmail=True)
    assert result['failed']==1 and result['gmail']==0
    assert result['company_results'][0]['state']=='local'


def test_gmail_browser_search_waits_for_current_query_and_matching_rows(setup):
    from common.gmail_browser import GmailDrafts
    settings,_,_=setup
    gmail=GmailDrafts(settings,settings.google_email)
    subject='AI Engineer application'
    query=f'in:anywhere to:({settings.google_email}) subject:"{subject}"'
    class Input:
        def get_attribute(self,key):return 'in:draft' if gmail.stage==0 else query
    class Row:
        text=subject
        def is_displayed(self):return True
    class Main:
        text=''
        def find_elements(self,*args):return [Row()]
    gmail.driver=SimpleNamespace(get=lambda value:None,find_elements=lambda *args:[Main()])
    gmail.check_account=lambda:None
    gmail.visible=lambda css:[Input()] if css.startswith('input') else [Main()]
    gmail.stage=0
    def wait(condition,seconds=30):
        # The first wait checks only whether Gmail's main region is present.
        if condition.__name__=='<lambda>':return condition(gmail.driver)
        assert condition(gmail.driver) is False
        gmail.stage=1
        return condition(gmail.driver)
    gmail.wait=wait
    assert len(gmail.search(subject,settings.google_email))==1
    gmail.account_url='https://mail.google.com/mail/u/0/'
    assert gmail.url('#drafts')=='https://mail.google.com/mail/u/0/#drafts'
