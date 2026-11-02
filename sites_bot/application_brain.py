"""Application-specific roles, page observation, and durable duplicate protection."""
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from common.models import ApplyStatus

SKILLS = Path(__file__).parent / 'skills' / 'application'
STATES = ('inspect', 'sign_in', 'email_verification', 'fill', 'review', 'submit',
          'email_application', 'confirmed', 'needs_you', 'uncertain')


def role_for(job):
    text = ' '.join([job.source or '', job.job_id or '', job.url or '']).lower()
    return next((board for board in ('naukri', 'hirist', 'instahyre', 'cutshort', 'wellfound', 'linkedin')
                 if board in text), 'company')


def instructions(job):
    # form-answers.md holds the free-text rules every board and company site shares.
    return '\n\n'.join((SKILLS / name).read_text(encoding='utf-8')
                       for name in ('SKILL.md', 'form-answers.md', role_for(job) + '.md'))


def submission_click_recorded(workdir):
    """Tool evidence overrides an agent claiming it never tried to submit."""
    path = Path(workdir) / 'transcript.jsonl'
    if not path.is_file():
        return False
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        for block in (event.get('message') or {}).get('content') or []:
            if not isinstance(block, dict) or block.get('type') != 'tool_use':
                continue
            name = str(block.get('name', ''))
            value = json.dumps(block.get('input') or {})
            if ('browser_click' in name or 'browser_press_key' in name or 'browser_run_code' in name
                    or 'browser_evaluate' in name) and re.search(r'\b(submit|send|apply)\b', value, re.I):
                return True
    return False


def observe(url, text):
    """A bounded initial state hint. The agent must inspect the actual page before acting."""
    host = (urlsplit(url).hostname or '').lower()
    content = ' '.join(str(text or '').lower().split())
    if any(s in content for s in ('captcha', 'verify you are human', 'unusual traffic')):
        return 'needs_you', 'Complete the browser verification.'
    if host == 'accounts.google.com':
        return 'sign_in', 'Select only the configured Google account; inspect requested permissions.'
    if host == 'mail.google.com':
        return 'email_verification', 'Check whether this is verification or an explicitly authorized application draft.'
    if any(s in content for s in ('verification code', 'check your email', 'verify your email')):
        return 'email_verification', 'Read only the newest matching verification message.'
    if any(s in content for s in ('sign in', 'create an account', 'log in')):
        return 'sign_in', 'Use the saved account or the permitted sign-in route.'
    return 'inspect', 'Inspect the current job, required fields, and next step.'


def mailbox(driver):
    from .external import apply_by_email
    try:
        value = apply_by_email(driver)
    except Exception:
        return ''
    # One explicit application recipient only; never use a mailto's cc/bcc/body payload.
    return value if re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value or '') else ''


def verify_sent_email(driver, report):
    """A generic Gmail toast or an unrelated open message is never a receipt."""
    from .external import _page_text
    recipient = report.get('_authorized_recipient', '')
    subject = str(report.get('subject', '')).strip()
    resume = report.get('_resume_name', '')
    sender = report.get('_sender', '')
    if not recipient or report.get('recipient', '').casefold() != recipient.casefold() or len(subject) < 8 or not resume or not sender:
        return False
    try:
        home = driver.current_window_handle
        try:
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                url = urlsplit(driver.current_url)
                if url.hostname != 'mail.google.com' or not url.fragment.startswith('sent/'):
                    continue
                message = driver.execute_script('''
                  const visible = e => !!(e.getClientRects().length);
                  return {
                    subjects: Array.from(document.querySelectorAll('h2.hP')).filter(visible).map(e=>e.innerText),
                    addresses: Array.from(document.querySelectorAll('[email]')).filter(visible).map(e=>e.getAttribute('email')),
                    attachments: Array.from(document.querySelectorAll('[download_url], .aV3')).filter(visible).map(e=>e.innerText)
                  };''') or {}
                addresses = {str(v).casefold() for v in message.get('addresses', [])}
                if (subject in message.get('subjects', []) and {recipient.casefold(), sender.casefold()} <= addresses
                        and any(resume in str(v) for v in message.get('attachments', []))):
                    return True
        finally:
            driver.switch_to.window(home)
    except Exception:
        return False
    return False


def db_path(settings):
    return Path(settings.data_dir) / 'application-agent.sqlite'


def _connect(settings):
    path = db_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS attempts(job_id TEXT PRIMARY KEY, title TEXT, company TEXT,
        url TEXT, state TEXT, next_step TEXT, detail TEXT, report_json TEXT, owner_pid INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    return con


def history(settings):
    path = db_path(settings)
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute('SELECT job_id,title,company,url,state,next_step,detail,updated_at FROM attempts ORDER BY updated_at DESC LIMIT 100')]


def blocked(settings, job):
    if not db_path(settings).is_file():
        return ''
    with closing(sqlite3.connect(db_path(settings).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as con:
        row = con.execute('SELECT state FROM attempts WHERE job_id=?', (job.job_id,)).fetchone()
    if row and row[0] in ('running', 'uncertain', 'confirmed'):
        return row[0]
    return ''


def claim(settings, job, url):
    with closing(_connect(settings)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT state FROM attempts WHERE job_id=?', (job.job_id,)).fetchone()
        if row and row[0] in ('running', 'uncertain', 'confirmed'):
            return False
        con.execute('''INSERT INTO attempts(job_id,title,company,url,state,next_step,detail,report_json,owner_pid)
            VALUES(?,?,?,?,'running','Inspect the current application','','{}',?) ON CONFLICT(job_id) DO UPDATE SET
            state='running',url=excluded.url,next_step=excluded.next_step,owner_pid=excluded.owner_pid,updated_at=CURRENT_TIMESTAMP''',
            (job.job_id, job.title, job.company, url, os.getpid()))
    return True


def finish(settings, job, result, report):
    report = report or {}
    confirmed = result.status in (ApplyStatus.APPLIED_EXTERNAL, ApplyStatus.ALREADY_APPLIED)
    # Only an explicit no-send report releases the reservation. A crash, missing report, or
    # uncertain click remains blocked across later processes and pipeline continuations.
    safe = report.get('submission_attempted') is False and report.get('status') in ('needs_you', 'ready', 'gone', 'failed')
    state = 'confirmed' if confirmed else 'needs_you' if safe else 'uncertain'
    next_step = 'Application confirmed; do not send again.' if confirmed else (
        str(report.get('next_step') or 'Complete the missing facts or sign-in, then retry.') if safe else
        'Check the application page or Sent folder before allowing another attempt.')
    with closing(_connect(settings)) as con, con:
        con.execute('''UPDATE attempts SET state=?,next_step=?,detail=?,report_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?''',
                    (state, next_step[:500], result.detail[:1000], json.dumps(report), job.job_id))


def resolve(settings, job_id, outcome):
    if outcome not in ('confirmed', 'not_sent'):
        raise ValueError('Confirm whether the application was sent or was not sent.')
    with closing(_connect(settings)) as con, con:
        row = con.execute('SELECT state,owner_pid FROM attempts WHERE job_id=?', (job_id,)).fetchone()
        if not row or row[0] not in ('uncertain', 'running'):
            raise ValueError('This application does not need submission review.')
        if row[0] == 'running' and row[1]:
            try:
                os.kill(row[1], 0)
            except ProcessLookupError:
                pass
            except PermissionError:
                raise ValueError('The agent process may still be running. Stop it before reviewing this attempt.') from None
            else:
                raise ValueError('The agent process is still running. Stop it before reviewing this attempt.')
        con.execute('''UPDATE attempts SET state=?, next_step=?,detail='Submission outcome checked by the user',updated_at=CURRENT_TIMESTAMP WHERE job_id=?''',
            ('confirmed' if outcome == 'confirmed' else 'needs_you',
             'Do not submit again.' if outcome == 'confirmed' else 'The user checked that nothing was sent; retry is allowed.', job_id))
