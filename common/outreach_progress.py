"""Durable, factual per-company draft progress for the dashboard."""
import json
from pathlib import Path
import sqlite3
import time
import os
from contextlib import closing
from .company_store import connect

TABLE='company_outreach_progress'
ACTIVE={'queued','contacts','writing','attaching','saving'}

def initialize(db):
    with connect(db) as con:
        con.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
            company_id TEXT NOT NULL, sender TEXT NOT NULL, data_json TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY(company_id,sender))''')

def record(db, sender, company, phase, message='', job=None, issue=None):
    now=time.time()
    with connect(db) as con:
        row=con.execute(f'SELECT data_json FROM {TABLE} WHERE company_id=? AND sender=?',(company['company_id'],sender)).fetchone()
        data=json.loads(row[0]) if row and phase!='queued' else {'started_at':now,'history':[]}
        if phase=='queued' and os.environ.get('MORROW_RUN_ID'):
            data['run_id']=os.environ['MORROW_RUN_ID']
        if job:
            data.update(job_id=job.get('job_id',''),title=job.get('title',''))
        if issue:
            data['issue']=issue
        data.update(phase=phase,message=message,updated_at=now)
        if not data['history'] or data['history'][-1]['phase']!=phase:
            data['history'].append({'phase':phase,'at':now})
        con.execute(f'''INSERT INTO {TABLE} VALUES(?,?,?,?) ON CONFLICT(company_id,sender)
            DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at''',
            (company['company_id'],sender,json.dumps(data),now))

def read(db,sender):
    if not Path(db).is_file():return {}
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():return {}
        result={}
        for key,raw in con.execute(f'SELECT company_id,data_json FROM {TABLE} WHERE sender=?',(sender,)):
            data=json.loads(raw)
            if data['phase'] in ACTIVE and time.time()-data['updated_at']>1800:
                data.update(phase='failed',message='This draft run was interrupted. Retry to continue.')
            result[key]=data
        return result
