"""Answer the recruiter questionnaires waiting in the Instahyre inbox for applications already sent.

The same rules as cutshort_bot.questionnaires: a follow-up to an existing application, never a
new one; one answered questionnaire per thread, journalled before the agent may submit, in
its own file (instahyre_questionnaires.json) so Cutshort's claims and Instahyre's never mix.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta

from selenium.common.exceptions import WebDriverException

from common.answers import facts_fingerprint
from common.browser import safe_get
from common.shared_files import atomic_write_text
from cutshort_bot import questionnaires as shared
from sites_bot import browser_agent, external as ext

logger = logging.getLogger(__name__)
PENDING_URL = "https://www.instahyre.com/candidate/inbox/"
JOURNAL_NAME = "instahyre_questionnaires.json"
RETRY_COOLDOWN_S = shared.RETRY_COOLDOWN_S

# Inbox rows (date, recruiter, "Company - Role", "Name: message") whose message asks for a questionnaire.
_ROWS_SCRIPT = r"""
const ask = /questionnaire|assessment|fill (in|out) (the|this) form|as part of (the|your) application process/i;
return [...document.querySelectorAll('a, li, [role="listitem"], [role="button"], .inbox-row, .message-row, .conversation')]
  .filter(el => {
    const r = el.getBoundingClientRect(); const t = el.innerText || '';
    return r.width && r.height && ask.test(t) && / - /.test(t) && !el.querySelector('a, li, [role="listitem"]');
  }).map(el => {
    const lines = (el.innerText || '').split('\n').map(x => x.trim()).filter(Boolean);
    const about = lines.find(x => / - /.test(x) && !/:/.test(x)) || '';
    const [company, ...role] = about.split(' - ');
    return {element: el, company: (company || '').trim(), title: role.join(' - ').trim(),
            key: lines.filter(x => !/^[A-Z][a-z]{2} \d{1,2}$|ago$/.test(x)).join('|')};
  });
"""


def pending_rows(driver):
    try:
        return driver.execute_script(_ROWS_SCRIPT) or []
    except (AttributeError, WebDriverException):
        return []


def thread_key(row):
    """What identifies the thread: the company and the role, as the inbox row names them."""
    norm = lambda value: " ".join(str(value or "").split()).casefold()
    company, title = norm(row.get("company")), norm(row.get("title"))
    return re.sub(r"[^a-z0-9|]+", "-", "%s|%s" % (company, title)).strip("-") if company and title else ""


def _journal(settings):
    return shared._journal(settings, JOURNAL_NAME)


def _claim(settings, identity, facts, url):
    return shared._claim(settings, identity, facts, url, journal=JOURNAL_NAME)


def _record(settings, identity, **values):
    shared._record(settings, identity, journal=JOURNAL_NAME, **values)


def prompt(url, company, title, facts, email):
    instruction = (
        "Complete only the recruiter questionnaire already requested in this exact Instahyre inbox "
        "conversation: %s. Company: %s. Role: %s. Verify the selected thread, company and role first. "
        "Open its questionnaire and answer using only the candidate facts and saved answers below. "
        "You may submit it once every required answer is supported. Do not apply to any job, do not send a "
        "chat message, open another conversation, contact a recruiter or use Gmail. Do not invent experience, "
        "salary, location, availability or qualifications. If this is a skills test, coding assessment, "
        "CAPTCHA, or asks for an unknown required fact, stop with needs_you and list it. If answers are already "
        "submitted, do not submit again. If a Submit result is uncertain, stop; never click it twice. After "
        "submitting, reopen this exact thread and copy the exact text Instahyre shows for the submitted "
        "questionnaire in confirmation. A saved draft, the request itself or a closed dialog is not proof. "
        "If no questionnaire exists in this thread, report needs_you without sending anything."
    ) % (url, company, title)
    schema = ('Reply with ONE JSON object: {"status":"done|needs_you|failed", "why":"", '
              '"submission_attempted":false, "confirmation":"", "missing":[], '
              '"blocker":"missing_facts|human_check|sign_in|transient|none", '
              '"written":[{"question":"","answer":""}]}')
    return browser_agent.task_prompt(instruction, url, facts, email, has_password=False, report=schema)


def _verified(driver, report):
    """The confirmation the agent quoted is on the reloaded thread and says the answers went in."""
    quote = " ".join(str(report.get("confirmation") or "").split())
    words = re.compile(r"\b(submitted|received|sent|completed|thank(s| you) for (your )?(answers?|responses?))\b", re.I)
    negative = re.compile(r"\b(not|never|unable|cannot|failed|pending|unsent|incomplete|drafts?|unsubmitted)\b|n't\b", re.I)
    if len(quote) < 12 or negative.search(quote) or not words.search(quote):
        return False
    page = " ".join(ext._page_text(driver).split()).casefold()
    return quote.casefold() in page


def finish_pending(driver, profile, settings, limit=10):
    """Bounded pass over inbox rows that ask for a questionnaire; ordinary messages are left alone."""
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
        time.sleep(2)
        rows = [row for row in pending_rows(driver) if row.get("key") not in seen]
        if not rows:
            break
        row = rows[0]
        seen.add(row.get("key"))
        identity = thread_key(row)
        if not identity:
            logger.warning("Instahyre: a questionnaire row names no company and role; leaving it alone")
            continue
        ext._click(driver, row["element"])
        time.sleep(1)
        url = ext._current_url(driver) or PENDING_URL
        try:
            claimed = _claim(settings, identity, facts, url)
        except (OSError, ValueError):
            logger.exception("Instahyre questionnaire journal could not be read; leaving questionnaires for review")
            break
        if not claimed:
            continue
        if not browser_agent.reserve_task(settings):
            _record(settings, identity, state="deferred")
            break
        attempts += 1
        workdir = browser_agent.workdir_for(settings, "Instahyre questionnaire " + row.get("company", ""))
        logger.info("Instahyre: answering questionnaire for %s at %s", row.get("title"), row.get("company"))
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
                verified = _verified(driver, report)
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
            atomic_write_text(workdir / "questionnaire-report.json",
                              json.dumps({"url": url, "state": state, "report": report}, indent=2))
            results.append({"thread": identity, "state": state})
            logger.info("Instahyre questionnaire: %s (%s)", state, report.get("why") or run.problem)
        except Exception:
            _record(settings, identity, state="uncertain", folder=str(workdir))
            logger.exception("Instahyre questionnaire stopped; review its saved attempt before retrying")
            break
    return results
