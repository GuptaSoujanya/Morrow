"""Read-only record accuracy and command adapters. All files use temporary fixtures."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
import commands
import dashboard_data as data

@pytest.fixture
def ledger(tmp_path,monkeypatch):
    path=tmp_path/'test.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE jobs_seen(job_id TEXT PRIMARY KEY,url TEXT,title TEXT,company TEXT,source TEXT,first_seen TEXT,last_seen TEXT,score REAL);
        CREATE TABLE applications(id INTEGER PRIMARY KEY,job_id TEXT,url TEXT,title TEXT,company TEXT,status TEXT,detail TEXT,quota_consumed INTEGER,at TEXT);
        INSERT INTO jobs_seen VALUES('1','https://jobs.example/1','Engineer','Example','search:Engineer','2026-10-22T10:00:00','2026-10-22T11:00:00',70);
        INSERT INTO jobs_seen VALUES('hirist:2','javascript:alert(1)','Designer','Studio','hirist:search:Designer','2026-10-21T10:00:00','2026-10-22T10:00:00',40);
        INSERT INTO jobs_seen VALUES('3','https://jobs.example/3','Older role','Other','search:Engineer','2026-09-01T10:00:00','2026-10-22T10:00:00',NULL);
        INSERT INTO applications VALUES(1,'1','','','','applied','Confirmed',1,'2026-10-22T11:00:00');
        INSERT INTO applications VALUES(2,'1','','','','error','Retry needed',0,'2026-10-22T12:00:00');
        INSERT INTO applications VALUES(3,'hirist:2','javascript:alert(1)','Designer','Studio','external_manual','Continue manually',0,'2026-10-21T10:00:00');
        INSERT INTO applications VALUES(4,'3','https://jobs.example/3','Older role','Other','applied','Confirmed',1,'2026-09-01T11:00:00');
        ''')
    monkeypatch.setattr(data.state,'_setting_number',lambda *args:45)
    return path

def read(ledger,**params):return data.records(params,db=ledger,today=dt.date(2026,10,22))

def test_attempts_stay_distinct_and_missing_metadata_uses_discovery_record(ledger):
    r=read(ledger,days=14)
    assert r['total']==3
    assert [x['id'] for x in r['rows']]==[2,1,3]
    assert r['rows'][0]['title']=='Engineer' and r['rows'][0]['company']=='Example'
    assert r['rows'][0]['url']=='https://jobs.example/1'
    assert r['rows'][-1]['url']==''

def test_confirmed_submission_excludes_failed_and_manual_outcomes(ledger):
    r=read(ledger,outcome='submitted')
    assert r['total']==1 and r['rows'][0]['status']=='applied'
    assert read(ledger,days=0,outcome='submitted')['total']==2

def test_jobs_are_unique_latest_status_and_first_seen_range(ledger):
    r=read(ledger,kind='jobs',days=14)
    assert r['total']==2
    assert r['rows'][0]['status']=='error'
    assert read(ledger,kind='jobs',days=0)['total']==3
    assert read(ledger,kind='jobs',outcome='matched')['total']==1

def test_search_board_score_and_pagination(ledger):
    assert read(ledger,q='EXAMPLE')['total']==2
    assert read(ledger,board='hirist')['rows'][0]['job_id']=='hirist:2'
    assert read(ledger,sort='score')['rows'][0]['score']==70
    r=read(ledger,size=1,page=2)
    assert r['page']==2 and r['pages']==3 and r['rows'][0]['id']==1
    assert read(ledger,size=1,page=999)['page']==3
    assert read(ledger,q='not here')['total']==0

@pytest.mark.parametrize('params',[{'days':-1},{'days':'1.5'},{'size':101},{'page':0},{'board':'unknown'},{'kind':'run'},{'sort':'sql'}])
def test_record_filters_are_bounded(ledger,params):
    with pytest.raises(ValueError):read(ledger,**params)

def test_missing_database_has_no_invented_records(tmp_path):
    r=data.records({},db=tmp_path/'absent.db')
    assert r['rows']==[] and r['total']==0

@pytest.fixture
def library(tmp_path,monkeypatch):
    monkeypatch.setattr(data.state,'APPLY',tmp_path)
    monkeypatch.setattr(data.state,'REPORTS',tmp_path/'reports')
    root=tmp_path/'.research';root.mkdir()
    (root/'safe.md').write_text('# Learning notes\n\n<script>alert(1)</script>\n\n[Next](next.md)\n\n![remote](https://remote.example/a.png)\n\n[External](https://example.com)')
    (root/'next.md').write_text('# Next lesson\n\nSafe text')
    outside=tmp_path/'private.md';outside.write_text('Do not expose')
    (root/'escape.md').symlink_to(outside)
    return root

def test_library_blocks_traversal_symlinks_raw_html_and_remote_images(library):
    items=data.artifacts()['items']
    assert len(items)==2 and all(x['id']!='research/escape.md' for x in items)
    for key in ['research/../private.md','research/escape.md','/etc/passwd']:
        with pytest.raises(ValueError):data.artifact(key)
    html=data.artifact('research/safe.md')['html']
    assert '<script>' not in html and '<img' not in html
    assert '/#/research/research%2Fnext.md' in html
    assert 'noopener noreferrer' in html

def test_saved_email_is_readable_and_escaped(library):
    folder=data.state.REPORTS/'2026-10-22'/'emails';folder.mkdir(parents=True)
    (folder/'intro.eml').write_text('Subject: Hello <script>\nTo: someone@example.com\nContent-Type: text/plain; charset=utf-8\n\nHi there <b>friend</b>')
    r=data.artifact('email/2026-10-22/emails/intro.eml')
    assert 'someone@example.com' in r['html'] and '&lt;b&gt;friend&lt;/b&gt;' in r['html']

def test_invalid_checkpoint_is_reported(tmp_path):
    path=tmp_path/'progress.json';path.write_text('[]')
    with pytest.raises(ValueError,match='could not be read'):data.read_json(path,{})

def test_extended_command_flags_reach_the_real_modules():
    cmd=commands.naukri_command({'dry_run':True,'min_score':'65.5','max_days_old':'7','llm_backend':'none','early_access_limit':'12'})
    assert '--min-score' in cmd.argv and '65.5' in cmd.argv and '--max-days-old' in cmd.argv and '--llm-backend' in cmd.argv
    assert '--review' in commands.profile_command({'review':True,'dry_run':True}).argv
    assert commands.linkedin_profile_command({'dry_run':True}).argv[-3:]==('-m','linkedin_bot.update_profile','--dry-run')
    mail=commands.cold_email_command({'to':'person@example.com','company':'A; echo unsafe','dry_run':True})
    assert 'A; echo unsafe' in mail.argv and '--dry-run' in mail.argv
    flow=commands.pipeline_command({'group':'brief:papers','redo':True,'dry_run':True,'agents':'3','cli':'kiro','date':'2026-10-22','skip':'profile,apply'})
    assert '--only' in flow.argv and 'brief:papers' in flow.argv and '--redo' in flow.argv and flow.argv.count('--skip')==2
    assert '--done' in commands.pipeline_command({'command':'learn','done':True}).argv
    assert commands.pipeline_command({'bots':'3'}).argv[-2:]==('--bots','3')
    assert commands.pipeline_command({'containers':True,'dry_run':True}).argv[-3:]==('--dry-run','--containers','--no-watch')

@pytest.mark.parametrize('fn,options',[
    (commands.naukri_command,{'min_score':'nan'}),(commands.naukri_command,{'max_days_old':'1.5'}),
    (commands.naukri_command,{'llm_backend':'shell'}),(commands.cold_email_command,{'to':'not email'}),
    (commands.cold_email_command,{'url':'javascript:alert(1)'}),(commands.cold_email_command,{'limit':0}),
    (commands.pipeline_command,{'redo':True}),(commands.pipeline_command,{'agents':9}),
    (commands.pipeline_command,{'date':'tomorrow'}),(commands.pipeline_command,{'skip':['shell']}),
    (commands.pipeline_command,{'command':'run','done':True}),
    (commands.pipeline_command,{'bots':7}),(commands.pipeline_command,{'containers':True,'bots':2}),
])
def test_command_validation_blocks_invalid_options(fn,options):
    with pytest.raises(ValueError):fn(options)


def test_data_inventory_counts_and_contains_only_supported_sources(ledger,library,monkeypatch):
    root=data.state.APPLY
    monkeypatch.setattr(data.state,'database',lambda:ledger)
    monkeypatch.setattr(data.state,'RESUMES',root/'data/resume')
    data.state.RESUMES.mkdir(parents=True)
    (data.state.RESUMES/'portfolio.pdf').write_bytes(b'%PDF-1.4 fixture')
    (data.state.RESUMES/'private.txt').write_text('secret')
    profile=root/'profile.yaml';profile.write_text('name: Demo')
    secret=root/'.env';secret.write_text('TOKEN=private')
    result=data.inventory({'profile':profile,'env':secret})
    counts={s['id']:s['count'] for s in result['sources']}
    assert counts['applications']==4 and counts['jobs']==3
    assert counts['research']==2 and counts['resumes']==1 and counts['profile']==1
    assert counts['reports']==0 and counts['flows']==0
    assert all(f['path'] not in ('.env','private.md','data/resume/private.txt') for f in result['files'])
    assert all('bytes' in f and 'updated_at' in f for f in result['files'])
    assert result['sources'][0]['href']=='#/records/applications%2Fall%2F0'


def test_resume_download_rejects_traversal_and_symlink_escape(library,monkeypatch):
    root=data.state.APPLY
    monkeypatch.setattr(data.state,'RESUMES',root/'resumes')
    data.state.RESUMES.mkdir()
    good=data.state.RESUMES/'saved.pdf';good.write_bytes(b'%PDF fixture')
    outside=root/'private.pdf';outside.write_bytes(b'%PDF private')
    (data.state.RESUMES/'escape.pdf').symlink_to(outside)
    assert data.resume_file('saved.pdf')==good
    for name in ('../private.pdf','escape.pdf','missing.pdf','',str(outside),str(good)):
        with pytest.raises(ValueError): data.resume_file(name)


def test_data_inventory_reports_corrupt_sources_without_losing_other_collections(library,monkeypatch):
    root=data.state.APPLY
    bad=root/'bad.db';bad.write_text('not a database')
    monkeypatch.setattr(data.state,'database',lambda:bad)
    monkeypatch.setattr(data.state,'RESUMES',root/'resumes')
    (root/'.memory').mkdir();(root/'.memory/progress.json').write_text('[]')
    result=data.inventory({})
    by_id={s['id']:s for s in result['sources']}
    assert by_id['applications']['count'] is None and by_id['applications']['error']
    assert by_id['flows']['count'] is None and by_id['flows']['error']
    assert by_id['research']['count']==2
