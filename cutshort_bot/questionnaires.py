"""Complete recruiter screening forms already waiting in Cutshort conversations.

These are follow-ups to existing applications, with their own attempt journal.
They must never be counted as new applications or sent through the chat composer.
The journal allows one completed questionnaire per thread. Further questionnaires
in that same thread require review rather than risking a duplicate response.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium.common.exceptions import WebDriverException

from common.answers import facts_fingerprint
from common.browser import safe_get
from common.shared_files import atomic_write_text, locked_file
from sites_bot import browser_agent, external as ext

logger = logging.getLogger(__name__)
PENDING_URL = "https://cutshort.io/profile/candidate-conversations?i=all&stage=awaiting"
_CONVERSATION_PATHS = {"/profile/candidate-conversations", "/profile/conversations/candidate"}
RETRY_COOLDOWN_S = 900
_STATES = frozenset(('running', 'uncertain', 'done', 'needs_you', 'retry_later', 'deferred'))

# A View conversation link is evidence only on a single, signed-in job view.
# An inbox link, related job card or arbitrary chat is not an application marker.
_CONVERSATION_SCRIPT = r"""
const text = (document.body.innerText || '').replace(/\s+/g, ' ');
if (!/\bShowing 1 recently active jobs?\b/i.test(text) || /\bShowing (?:[2-9]|\d{2,}) recently active jobs?\b/i.test(text)) return [];
const links = [...document.querySelectorAll('a[href]')].filter(a => {
  const r = a.getBoundingClientRect();
  return r.width && r.height && !a.closest('header, nav, footer') &&
    /^view conversation$/i.test((a.innerText || '').trim());
});
return links.map(a => a.href);
"""


def thread_id(url):
    parsed = urlparse(url or "")
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.hostname not in ("cutshort.io", "www.cutshort.io")
            or parsed.path.rstrip("/") not in _CONVERSATION_PATHS):
        return ""
    values = parse_qs(parsed.query).get("thread", [])
    value = values[0] if len(values) == 1 else ""
    return value.lower() if re.fullmatch(r"[a-fA-F0-9]{24}", value) else ""


def application_conversation(driver):
    parsed = urlparse(ext._current_url(driver) or "")
    if (parsed.hostname not in ("cutshort.io", "www.cutshort.io")
            or parsed.path.rstrip("/") != "/profile/all-jobs"
            or len(parse_qs(parsed.query).get("jobid", [])) != 1):
        return ""
    try:
        links = driver.execute_script(_CONVERSATION_SCRIPT) or []
    except (AttributeError, WebDriverException):
        return ""
    # More than one result means the page is not scoped tightly enough.
    valid = [url for url in links if thread_id(url)
             and parse_qs(urlparse(url).query).get("stage") == ["awaiting"]]
    return valid[0] if len(links) == len(valid) == 1 else ""


_ROWS_SCRIPT = r"""
return [...document.querySelectorAll('[role="tabpanel"] button, [role="tabpanel"] [role="button"]')]
  .filter(el => {
    const r = el.getBoundingClientRect(); const t = el.innerText || '';
    return r.width && r.height && /\[Questionnaire\]/i.test(t) && /For job\s+/i.test(t);
  }).map(el => {
    const lines = (el.innerText || '').split('\n').map(x => x.trim()).filter(Boolean);
    const role = lines.find(x => /^For job\s+/i.test(x)) || '';
    return {element: el, company: lines[0] || '', title: role.replace(/^For job\s+/i, ''),
            key: lines.filter(x => !/ago$|^DP$/.test(x)).join('|')};
  });
"""


def pending_rows(driver):
    try:
        return driver.execute_script(_ROWS_SCRIPT) or []
    except (AttributeError, WebDriverException):
        return []


JOURNAL_NAME = "cutshort_questionnaires.json"


def _journal(settings, name=JOURNAL_NAME):
    return Path(settings.data_dir) / name


def _read(path):
    try:
        result = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    # A damaged journal must stop the pass, not clear duplicate protection.
    if not isinstance(result, dict) or any(not isinstance(value, dict) for value in result.values()):
        raise ValueError("Cutshort questionnaire journal is not an object")
    normalized = {}
    for identity, record in result.items():
        canonical = identity.lower() if re.fullmatch(r'[a-fA-F0-9]{24}', identity) else identity
        if canonical in normalized and normalized[canonical] != record:
            raise ValueError('Cutshort questionnaire journal has conflicting thread identities')
        normalized[canonical] = record
    return normalized


def _claim(settings, identity, facts, url, journal=JOURNAL_NAME):
    with locked_file(_journal(settings, journal)) as path:
        records = _read(path)
        prior = records.get(identity, {})
        if identity in records and prior.get('state') not in _STATES:
            # Unknown state is not proof that an earlier send was safe to retry.
            raise ValueError('Cutshort questionnaire has an unknown saved state; review it before retrying')
        if prior.get("state") in ("running", "uncertain", "done"):
            return False
        if prior.get("state") == "needs_you" and prior.get("facts") == facts:
            return False
        if prior.get("state") == "retry_later":
            try:
                if datetime.fromisoformat(prior["retry_after"]) > datetime.now():
                    return False
            except (KeyError, TypeError, ValueError):
                return False
        records[identity] = {"state": "running", "facts": facts, "url": url,
                             "at": datetime.now().isoformat()}
        atomic_write_text(path, json.dumps(records, indent=2))
    return True


def _record(settings, identity, journal=JOURNAL_NAME, **values):
    with locked_file(_journal(settings, journal)) as path:
        records = _read(path)
        records[identity].update(values, at=datetime.now().isoformat())
        atomic_write_text(path, json.dumps(records, indent=2))


def prompt(url, company, title, facts, email):
    instruction = (
        "Complete only the recruiter screening questionnaire already requested in this exact Cutshort "
        "conversation: %s. Company: %s. Role: %s. Verify the selected thread, company and role first. "
        "Open its pending questionnaire and answer using only the candidate facts and saved answers below. "
        "You may submit this questionnaire once every required answer is supported. Do not apply again, "
        "send a chat message, type into 'Type your message...', open another conversation, contact a recruiter, "
        "or use Gmail. Do not invent experience, salary, location, availability or qualifications. "
        "Write short explanations using only the candidate's actual work. If this is a skills test, coding "
        "assessment, CAPTCHA, or asks for an unknown required fact, stop with needs_you and list it. "
        "If answers are already submitted, do not submit again. If a Submit result is uncertain, stop; "
        "never click it twice. After submitting, reopen this exact thread and verify the questionnaire "
        "shows that the answers were submitted or received. Leave that proof visible and copy its exact text in "
        "confirmation. Saved/autosaved answers, a received questionnaire request, a chat message, application "
        "Pending status or simply closing a dialog are not proof of submission. "
        "If no questionnaire exists in this thread, report needs_you without sending anything."
    ) % (url, company, title)
    schema = ('Reply with ONE JSON object: {"status":"done|needs_you|failed", "why":"", '
              '"submission_attempted":false, "confirmation":"", "missing":[], '
              '"blocker":"missing_facts|human_check|sign_in|transient|none", '
              '"written":[{"question":"","answer":""}]}')
    return browser_agent.task_prompt(instruction, url, facts, email, has_password=False, report=schema)


_PANEL_SCRIPT = r"""
const visible = el => { const r = el.getBoundingClientRect(); return r.width && r.height; };
const composers = [...document.querySelectorAll('textarea[placeholder="Type your message..."], input[placeholder="Type your message..."], [role="textbox"][aria-label="Type your message..."]')].filter(visible);
let panel = composers.length === 1 && composers[0].parentElement;
while (panel && panel !== document.body) {
  if (panel.querySelector('[role="tabpanel"]')) return [];
  if (panel.querySelector('a[href*="/job/"]') && /For job\s+/i.test(panel.innerText || '')) break;
  panel = panel.parentElement;
}
if (!panel || panel === document.body) return [];
"""

_CONTEXT_SCRIPT = _PANEL_SCRIPT + r"""
// Read the selected thread's job card and heading, not an inbox preview or chat.
const jobLinks = [...panel.querySelectorAll('a[href]')].filter(visible).filter(a => {
  const u = new URL(a.href); return ['cutshort.io', 'www.cutshort.io'].includes(u.hostname) && u.pathname.startsWith('/job/');
});
// The employer is plain text in the thread header: the line above "For job <role>" and the
// job card's "at <employer>" line. The only /company/ link there may be the hiring agency.
const headerText = [...panel.querySelectorAll('*')].filter(visible)
  .filter(el => !el.closest('[role="log"], [data-message-id]'));
const own = el => (el.innerText || '').trim();
const titleEls = headerText.filter(el => /^For job\s+[^\n]+$/.test(own(el)));
const companies = [
  ...[...panel.querySelectorAll('a[href*="/company/jobs-at-"]')].filter(visible).map(own),
  ...titleEls.map(el => el.previousElementSibling).filter(Boolean).map(own).filter(t => t && !t.includes('\n')),
  ...headerText.map(own).filter(t => /^at\s+\S[^\n]*$/.test(t)).map(t => t.replace(/^at\s+/, '')),
];
const titles = titleEls.map(el => own(el).replace(/^For job\s+/, ''));
return {companies: [...new Set(companies)], titles: [...new Set(titles)], jobs: [...new Set(jobLinks.map(a => a.href))]};
"""


def _selected_thread_matches(driver, row):
    """A failed/stale row click must never hand the previous conversation to the agent."""
    try:
        context = driver.execute_script(_CONTEXT_SCRIPT) or {}
    except (AttributeError, WebDriverException):
        return False
    norm = lambda value: ' '.join(str(value or '').split()).casefold()
    # The single job link and the one "For job <role>" heading identify the thread; an agency
    # job names the agency as well as the employer, so the row's company only has to be there.
    return bool(isinstance(context, dict) and len(context.get('jobs', [])) == 1
                and norm(row.get('company')) in [norm(x) for x in context.get('companies', [])]
                and [norm(x) for x in context.get('titles', [])] == [norm(row.get('title'))]
                and norm(row.get('company')) and norm(row.get('title')))


_PROOF_SCRIPT = _PANEL_SCRIPT + r"""
// A sidebar preview or ordinary chat message is never questionnaire proof. Cutshort states the
// receipt as a plain div inside the questionnaire form, so take short leaf lines from the form
// too: a leaf cannot carry the whole thread's text, which would make any quote "found".
const limit = 200;  // a receipt is one short line; a longer block is the form or the chat
return [...panel.querySelectorAll('[role="status"], [role="alert"], form div, form p, form span')]
  .filter(el => {
    const r = el.getBoundingClientRect();
    const own = (el.innerText || '').replace(/\s+/g, ' ').trim();
    return r.width && r.height && own && own.length <= limit
      && ![...el.children].some(child => (child.innerText || '').replace(/\s+/g, ' ').trim() === own)
      && !el.closest('header, nav, footer, [role="tabpanel"], [role="tablist"], [role="log"], [data-message-id]');
  }).map(el => (el.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
"""


def _verified(driver, url, report):
    quote = " ".join(str(report.get("confirmation") or "").split())
    predicate = r'\s+(?:(?:has|have)\s+been\s+|(?:was|were|is|are)\s+)?(?:successfully\s+)?'
    words = re.compile(
        r'\b(?:questionnaire(?:\s+(?:answers?|responses?))?|answers?|responses?)' + predicate + r'submitted\b|'
        r'\b(?:answers?|responses?)' + predicate + r'(?:sent|received)\b|'
        r'\b(?:successfully\s+)?submitted\s+(?:(?:your|the)\s+)?(?:questionnaire|answers?|responses?)\b', re.I)
    negative = re.compile(r"\b(?:not|never|unable|cannot|failed|failure|error|pending|unsent|incomplete|drafts?|unsubmitted|"
                          r"after|before|when|once|if|until|please|must|should|will|can|may)\b|n't\b", re.I)
    try:
        proof = driver.execute_script(_PROOF_SCRIPT) or []
    except (AttributeError, WebDriverException):
        proof = []
    identity = thread_id(url)
    return bool(identity and thread_id(ext._current_url(driver)) == identity and len(quote) >= 12
                and not negative.search(quote)
                and words.search(quote) and any(quote.casefold() in text.casefold() and not negative.search(text)
                                               for text in proof if isinstance(text, str)))


#: The conversations list renders well after the page loads; a fixed two-second sleep used to
#: read zero rows and end the whole pass as if no questionnaire were waiting. Polls, not a
#: deadline, so a test that stubs the sleep away does not spin for the whole wait.
_POLL_S = 0.5
_RENDER_POLLS = 40
_OPEN_POLLS = 20


def _settle(check, polls):
    value = check()
    for _ in range(polls):
        if value:
            break
        time.sleep(_POLL_S)
        value = check()
    return value


def _rows_once_rendered(driver, seen):
    return _settle(lambda: [row for row in pending_rows(driver) if row.get("key") not in seen], _RENDER_POLLS)


def _thread_once_open(driver):
    return _settle(lambda: thread_id(ext._current_url(driver)), _OPEN_POLLS)


def finish_pending(driver, profile, settings, limit=10):
    """Bounded pass over explicit Pending questionnaire rows; no ordinary messages."""
    if not settings.browser_agent or limit <= 0 or browser_agent.tasks_left(settings) <= 0:
        return []
    results, seen = [], set()
    facts = facts_fingerprint(profile, settings)
    attempts = 0
    for _ in range(50):
        if attempts >= min(limit, 10):
            break
        if not safe_get(driver, PENDING_URL):
            break
        rows = _rows_once_rendered(driver, seen)
        if not rows:
            break
        row = rows[0]
        seen.add(row.get("key"))
        ext._click(driver, row["element"])
        identity = _thread_once_open(driver)
        url = ext._current_url(driver)
        if not identity or not _settle(lambda: _selected_thread_matches(driver, row), _OPEN_POLLS):
            logger.warning("Cutshort: selected questionnaire thread does not match its company and role; leaving it alone")
            continue
        try:
            claimed = _claim(settings, identity, facts, url)
        except (OSError, ValueError):
            logger.exception("Cutshort questionnaire journal could not be read; leaving questionnaires for review")
            break
        if not claimed:
            continue
        if not browser_agent.reserve_task(settings):
            _record(settings, identity, state="deferred")
            break
        attempts += 1
        workdir = browser_agent.workdir_for(settings, "Cutshort questionnaire " + row.get("company", ""))
        logger.info("Cutshort: answering questionnaire for %s at %s", row.get("title"), row.get("company"))
        try:
            task = prompt(url, row.get("company", ""), row.get("title", ""),
                          browser_agent.facts_text(profile, settings), profile.email or settings.email)
            run = browser_agent.run_agent(driver, settings, task, workdir)
            report = run.report or {}
            from sites_bot.application_brain import submission_click_recorded
            if submission_click_recorded(workdir):
                report["submission_attempted"] = True
            verified = False
            if report.get("status") == "done" and safe_get(driver, url):
                time.sleep(2)
                verified = _verified(driver, url, report)
            if verified:
                state = "done"
            elif report.get("status") == "needs_you" and report.get("submission_attempted") is False:
                transient = report.get("blocker") in ("human_check", "sign_in", "transient")
                state = "retry_later" if transient else "needs_you"
            else:
                state = "uncertain"
            _record(settings, identity, state=state, report=report, folder=str(workdir),
                    retry_after=(datetime.now() + timedelta(seconds=RETRY_COOLDOWN_S)).isoformat()
                    if state == "retry_later" else None)
            workdir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(workdir / "questionnaire-report.json", json.dumps({"url": url, "state": state, "report": report}, indent=2))
            results.append({"thread": identity, "state": state, "company": row.get("company", ""),
                            "title": row.get("title", "")})
            logger.info("Cutshort questionnaire: %s (%s)", state, report.get("why") or run.problem)
        except Exception:
            _record(settings, identity, state="uncertain", folder=str(workdir))
            logger.exception("Cutshort questionnaire stopped; review its saved attempt before retrying")
            break
    return results
