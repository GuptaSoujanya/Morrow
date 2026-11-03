import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from common import company_research as research, company_store as store
from common.ledger import Ledger
from common.models import JobPosting
from common.public_web import public_url, fetch_page


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'jobs.db'
    with Ledger(str(path)) as ledger:
        ledger.record_seen(JobPosting('c', 'https://jobs.beta.com/1', company='Beta', title='Developer'))
        ledger.record_seen(JobPosting('a', 'https://jobs.acme.com/1', company='Acme Labs', title='AI Engineer'))
        ledger.record_seen(JobPosting('b', 'https://jobs.acme.com/2', company=' ACME  Labs ', title='Data Engineer'))
    return path


def reply():
    return dict(identity=dict(matched=True, source='https://acme.com/about', evidence='Acme Labs builds software'),
                fields=dict(website=[dict(value='https://acme.com', source='https://acme.com/about', evidence='Acme Labs builds software')],
                            email=[dict(value='careers@acme.com', source='https://acme.com/about', evidence='Email careers@acme.com to apply')],
                            ceo=[dict(value='Invented Person', source='https://acme.com/about', evidence='Our CEO is Invented Person')]), notes='No public CTO listed.')


def page(url):
    return dict(url=url, text='Acme Labs builds software. Email careers@acme.com to apply.', links=['https://acme.com'])


def test_read_only_catalog_deduplicates_and_does_not_create_research_table(db):
    items = store.catalog(db)
    assert len(items) == 2
    assert items[0]['job_count'] == 2
    assert items[0]['status'] == 'pending'
    with sqlite3.connect(db) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='company_research'").fetchone()


def test_only_checkable_evidence_is_saved():
    data = research.validate(reply(), {'name':'Acme Labs'}, page)
    assert set(data['fields']) == {'website', 'email'}
    assert data['fields']['email'][0]['source_checked']
    assert '1 claims could not be checked' in data['notes']


def test_cli_prose_and_markdown_wrapping_do_not_discard_valid_json():
    raw = 'I checked the company pages.\n```json\n' + json.dumps(reply()) + '\n```\nResearch complete.'
    assert research.validate(raw, {'name':'Acme Labs'}, page)['fields']['email']


def test_ambiguous_or_wrong_company_does_not_gain_facts():
    result = reply()
    result['identity']['matched'] = False
    assert research.validate(result, {'name':'Acme Labs'}, page)['fields'] == {}
    assert research.validate(reply(), {'name':'Different Employer'}, page)['fields'] == {}


def test_identity_quote_can_name_role_when_page_identifies_employer():
    response=reply()
    response['identity']['evidence']='Email careers@acme.com to apply'
    assert research.validate(response, {'name':'Acme Labs'}, page)['fields']['email']


def test_model_paraphrases_are_replaced_with_literal_source_excerpts():
    response=reply()
    response['identity']['evidence']='A paraphrase, not a quotation'
    response['fields']['email'][0]['evidence']='Contact their hiring team'
    result=research.validate(response, {'name':'Acme Labs'}, page)
    evidence=result['fields']['email'][0]['evidence']
    assert 'careers@acme.com' in evidence and evidence in page('https://acme.com')['text']
    assert 'A paraphrase' not in result['identity']['evidence']


def test_research_is_resumable_and_reuses_company_evidence(db):
    first = research.run(db, limit=1, ask=lambda _:reply(), fetch=page)
    assert first == dict(completed=1, failed=0, remaining=1)
    rows = store.catalog(db)
    assert rows[0]['status'] == 'partial' and rows[0]['researched']
    assert rows[0]['job_count'] == 2 and 'cto' in rows[0]['missing']
    second = research.run(db, ask=lambda _:dict(identity={'matched':False}, fields={}), fetch=page)
    assert second['completed'] == 1 and second['remaining'] == 0
    assert research.run(db, ask=lambda _:pytest.fail('Completed companies must not be researched again'))['completed'] == 0


def test_claim_prevents_parallel_research(db):
    store.initialize(db)
    item = store.catalog(db)[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:store.claim(db, item), range(2))) == [False, True]
    assert not store.claim(db, item, retry=True)


def test_expired_lease_and_failure_can_be_retried_without_losing_evidence(db):
    research.run(db, limit=1, ask=lambda _:reply(), fetch=page)
    item = store.catalog(db)[0]
    assert store.claim(db, item, retry=True)
    store.finish(db, item['company_id'], error='Provider unavailable')
    failed = store.catalog(db)[0]
    assert failed['status'] == 'failed' and failed['fields']['email']
    assert not store.eligible(failed)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE company_research SET status='researching',lease_until=0,updated_at=?", (time.time()-4000,))
    interrupted = store.catalog(db)[0]
    assert interrupted['status'] == 'failed'
    assert store.claim(db, interrupted)


def test_dry_run_does_not_write_or_call_provider(db):
    assert research.run(db, dry_run=True, ask=lambda _:pytest.fail())['remaining'] == 2
    with sqlite3.connect(db) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='company_research'").fetchone()


def test_bad_reply_is_failure_not_not_found_and_does_not_poison_other_companies(db):
    calls = iter(['not json', json.dumps(dict(identity={'matched':False}, fields={}))])
    result = research.run(db, ask=lambda _:next(calls))
    assert result['failed'] == 1 and result['completed'] == 1
    assert {item['status'] for item in store.catalog(db)} == {'failed','not_found'}


@pytest.mark.parametrize('url', ['file:///etc/passwd','http://localhost/a','http://127.0.0.1','https://a.local/',
                                'http://169.254.169.254/latest/meta-data','https://user:pass@acme.com','http://acme.com:8100','javascript:alert(1)'])
def test_only_public_source_urls(url):
    assert not public_url(url)


def test_public_hostname_resolving_to_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError, match='private'):
        fetch_page('https://acme.com')


def test_summary_filters_paginate_and_keep_missing_fields(db):
    research.run(db, limit=1, ask=lambda _:reply(), fetch=page)
    response = store.summary(db, {'status':'partial','q':'careers@acme.com','size':'1'})
    assert response['total'] == 1 and response['counts']['pending'] == 1
    assert response['rows'][0]['information_found']
    with pytest.raises(ValueError):store.summary(db, {'size':'500'})


def test_contact_filters_and_order_apply_before_pagination(db):
    research.run(db, limit=1, ask=lambda _:reply(), fetch=page)
    beta = next(row for row in store.catalog(db) if row['name'] == 'Beta')
    assert store.claim(db, beta)
    store.finish(db, beta['company_id'], {'fields':{'phone':[{'value':'+1 555 0100'}]}})
    with Ledger(str(db)) as ledger:
        ledger.record_seen(JobPosting('d', 'https://missing.example/job', company='Aardvark'))
    response = store.summary(db, {'size':1})
    assert response['contact_counts'] == dict(all=3, email=1, phone=1, missing=1)
    assert response['rows'][0]['fields']['email']  # Contacts beat alphabetically earlier pending entries.
    assert store.summary(db, {'size':1, 'page':2})['rows'][0]['name'] == 'Beta'
    assert store.summary(db, {'contact':'phone'})['total'] == 1
    assert store.summary(db, {'contact':'email', 'q':'careers@acme.com'})['total'] == 1
    assert store.summary(db, {'contact':'email', 'status':'pending'})['total'] == 0
    assert store.summary(db, {'contact':'missing'})['rows'][0]['name'] == 'Aardvark'
    with pytest.raises(ValueError, match='contact filter'):
        store.summary(db, {'contact':'made-up'})
