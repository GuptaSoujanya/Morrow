"""Company research attached to the existing job ledger, with resumable leases."""
import hashlib
import json
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

FIELDS = ('website', 'careers', 'email', 'phone', 'ceo', 'cto', 'hiring_manager', 'location',
          'industry', 'about', 'linkedin', 'size')
STATUSES = ('pending', 'researching', 'found', 'partial', 'not_found', 'failed')


def company_key(name):
    normalized = ' '.join(unicodedata.normalize('NFKC', str(name or '')).casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:24] if normalized else ''


@contextmanager
def connect(db):
    con = sqlite3.connect(str(db), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize(db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS company_research (
            company_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}', updated_at REAL, lease_until REAL DEFAULT 0,
            attempts INTEGER DEFAULT 0, error TEXT NOT NULL DEFAULT '')''')


def catalog(db):
    """Read-only snapshot. Unresearched jobs appear without a migration or write."""
    if not Path(db).is_file():
        return []
    con = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        groups = {}
        if 'jobs_seen' in tables:
            columns = {row[1] for row in con.execute('PRAGMA table_info(jobs_seen)')}
            description = 'description' if 'description' in columns else "'' AS description"
            for job in con.execute('SELECT job_id,title,company,url,last_seen,score,'+description+' FROM jobs_seen ORDER BY last_seen DESC'):
                key = company_key(job['company'])
                if not key:
                    continue
                item = groups.setdefault(key, dict(company_id=key, name=job['company'], status='pending',
                    fields={}, missing=list(FIELDS), notes='', updated_at=None, attempts=0, error='', jobs=[]))
                item['jobs'].append(dict(job))
        if 'company_research' in tables:
            for row in con.execute('SELECT * FROM company_research'):
                item = groups.setdefault(row['company_id'], dict(company_id=row['company_id'], name=row['name'], jobs=[]))
                try:
                    data = json.loads(row['data_json'])
                except (ValueError, TypeError):
                    data = {}
                fields = data.get('fields', {})
                status = row['status']
                error = row['error']
                if status == 'researching' and row['lease_until'] < time.time():
                    status, error = 'failed', 'Research was interrupted. It can be retried.'
                item.update(status=status, fields=fields, missing=[k for k in FIELDS if not fields.get(k)],
                    notes=data.get('notes', ''), identity=data.get('identity', ''), updated_at=row['updated_at'],
                    attempts=row['attempts'], error=error)
        for item in groups.values():
            item['job_count'] = len(item['jobs'])
            item['researched'] = item['status'] in ('found', 'partial', 'not_found')
            item['information_found'] = bool(item['fields'])
        return list(groups.values())
    finally:
        con.close()


def eligible(item, retry=False, now=None):
    now = time.time() if now is None else now
    if item['status'] == 'pending':
        return True
    if item['status'] == 'researching':
        return False
    if retry:
        return True
    return (item['status'] == 'failed' and item['attempts'] < 3
            and now - (item['updated_at'] or 0) >= 300)


def claim(db, item, retry=False):
    """Claim exactly once across dashboard and pipeline processes; recover interrupted work."""
    now = time.time()
    with connect(db) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM company_research WHERE company_id=?', (item['company_id'],)).fetchone()
        if row:
            status = row['status']
            if status == 'researching':
                if row['lease_until'] > now:
                    return False
                status = 'failed'
            if not eligible(dict(status=status, attempts=row['attempts'], updated_at=row['updated_at']), retry):
                return False
        con.execute('''INSERT INTO company_research(company_id,name,status,updated_at,lease_until,attempts)
            VALUES(?,?,'researching',?,?,1) ON CONFLICT(company_id) DO UPDATE SET
            status='researching', updated_at=excluded.updated_at, lease_until=excluded.lease_until,
            attempts=company_research.attempts+1,error='' ''',
            (item['company_id'], item['name'], now, now + 3600))
    return True


def finish(db, key, data=None, error=''):
    data = data or {}
    fields = data.get('fields', {})
    status = 'failed' if error else 'found' if all(fields.get(k) for k in FIELDS) else 'partial' if fields else 'not_found'
    with connect(db) as con:
        # Failed refreshes retain earlier evidence, while making the failure visible.
        con.execute('''UPDATE company_research SET status=?, updated_at=?, lease_until=0,
            error=?, data_json=CASE WHEN ? THEN data_json ELSE ? END WHERE company_id=?''',
            (status, time.time(), error[:500], bool(error), json.dumps(data, ensure_ascii=False), key))
    return status


def summary(db, query=None):
    query = query or {}
    rows = catalog(db)
    counts = {status: sum(row['status'] == status for row in rows) for status in STATUSES}
    def has_contact(row, field):
        return any(str(entry.get('value') or '').strip() for entry in row['fields'].get(field, []))

    contact_counts = dict(all=len(rows), email=sum(has_contact(r, 'email') for r in rows),
                          phone=sum(has_contact(r, 'phone') for r in rows),
                          missing=sum(not has_contact(r, 'email') and not has_contact(r, 'phone') for r in rows))
    contact = query.get('contact', 'all')
    if contact not in contact_counts:
        raise ValueError('Choose a supported contact filter.')
    term = str(query.get('q', '')).strip().casefold()
    status = query.get('status', 'all')
    if status not in ('all', *STATUSES):
        raise ValueError('Choose a supported research status.')
    key = query.get('id', '')
    keys = str(query.get('ids','')).split(',') if query.get('ids') else []
    if keys and (len(keys)>50 or any(len(value)!=24 or any(char not in '0123456789abcdef' for char in value) for value in keys)):
        raise ValueError('Choose up to 50 valid companies.')
    filtered = [r for r in rows if (not key or r['company_id'] == key) and (not keys or r['company_id'] in keys)
                and (status == 'all' or r['status'] == status)
                and (contact == 'all' or (contact == 'missing' and not has_contact(r, 'email') and not has_contact(r, 'phone'))
                     or (contact in ('email', 'phone') and has_contact(r, contact)))
                and (not term or term in (r['name'] + ' ' + json.dumps(r['fields'], ensure_ascii=False)
                                         + ' ' + ' '.join(j.get('title') or '' for j in r['jobs'])).casefold())]
    # Put useful contacts first across the entire catalog, before pagination.
    filtered.sort(key=lambda r: (not has_contact(r, 'email'), not has_contact(r, 'phone'),
                                STATUSES.index(r['status']), r['name'].casefold()))
    try:
        page, size = int(query.get('page', 1)), int(query.get('size', 20))
        if not 1 <= page <= 1000000 or not 1 <= size <= 100:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Use a valid company page and a page size from 1 to 100.') from None
    pages = max(1, (len(filtered) + size - 1) // size)
    page = min(page, pages)
    return dict(rows=filtered[(page-1)*size:page*size], counts=counts, contact_counts=contact_counts, total=len(filtered),
                page=page, pages=pages, size=size, pending=sum(eligible(r) for r in rows))
