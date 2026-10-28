"""The loop every job board bot other than Naukri runs.

Each board is a Board record: its search pages, what its job links look like,
and the words on its Apply and Applied controls. The loop collects job cards
from the search pages, ranks them with the same scoring as Naukri, opens each
chosen job, clicks Apply, answers any form with the company-site filler, and
counts the application only when the board shows the job as applied after a
reload. A board page the script cannot finish goes to the browser agent when
it is on, and otherwise to user/inputs/company_sites.md for a person.

Each board is its own bot (hirist_bot, instahyre_bot, cutshort_bot,
wellfound_bot) with its Board in <name>_bot/board.py; this module is the loop
they share, and can still run several boards at once:

    python3 -m hirist_bot --limit 10 [--dry-run]
    python3 -m hirist_bot.update_profile                       # refresh the profile, apply nowhere
    python3 -m sites_bot.platforms --site all --profile-only   # every board in one run
"""

import argparse
import logging
import re
import sys
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from selenium.common.exceptions import WebDriverException

from . import browser_agent, profile_agent
from . import external as ext
from .board import Board
from common import memory, profile_plan
from common.browser import human_pause, safe_get
from common.models import ApplyResult, ApplyStatus, JobPosting, Profile, RunSummary, Settings
from cutshort_bot.board import BOARD as CUTSHORT
from hirist_bot.board import BOARD as HIRIST
from instahyre_bot.board import BOARD as INSTAHYRE
from wellfound_bot.board import BOARD as WELLFOUND

logger = logging.getLogger(__name__)

DRY_RUN = "dry_run"
PAGE_WAIT_S = 4.0
AFTER_CLICK_WAIT_S = 15.0
POLL_S = 0.5
MAX_FORM_PAGES = 6
#: A Chrome that closes mid-run (quit by hand, or gone under the browser agent) is
#: reopened this many times before the run stops.
MAX_BROWSER_RESTARTS = 2
#: Applications that went through without the board showing Applied, before the
#: board is left alone: the bot can no longer tell what its clicks are doing.
UNCONFIRMED_BEFORE_STOP = 2


# Each board lives in its own package (<name>_bot/board.py); this is the list the loop knows.
BOARDS = {board.name: board for board in (HIRIST, INSTAHYRE, CUTSHORT, WELLFOUND)}


def board_job_id(board: Board, url: str) -> str:
    found = re.search(board.job_id, url.split("?")[0].split("#")[0])
    return "%s:%s" % (board.name, found.group(1) if found else url)


def search_url(board: Board, keyword: str, page: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    template = board.search_page if page > 1 and board.search_page else board.search
    return template.format(slug=slug, query=quote_plus(keyword), page=page)


# ---------------------------------------------------------------------------
# Reading job cards
# ---------------------------------------------------------------------------

# Each job link climbs to the largest ancestor that still holds only that one
# job, which is the card on every board seen so far, and returns its lines.
_CARDS_SCRIPT = r"""
const pattern = new RegExp(arguments[0]);
const key = h => h.split('#')[0].split('?')[0];
const jobsIn = el => new Set([...el.querySelectorAll('a[href]')].map(x => key(x.href)).filter(h => pattern.test(h))).size;
const lines = el => (el.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
const out = new Map();
for (const a of document.querySelectorAll('a[href]')) {
  const href = key(a.href);
  if (!pattern.test(href) || out.has(href)) continue;
  let card = a;
  while (card.parentElement && card.parentElement !== document.body && jobsIn(card.parentElement) <= 1) {
    card = card.parentElement;
    if (lines(card).length >= 25) break;
  }
  out.set(href, {href: href, heading: (a.innerText || '').trim().split('\n')[0], lines: lines(card).slice(0, 30)});
}
return [...out.values()];
"""

_EXPERIENCE = re.compile(r"^\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:yrs?|years?)$|^\d+\+?\s*(?:yrs?|years?)$", re.I)
_POSTED = re.compile(r"^(?:posted(?:\s+on)?:?\s*)(.+)$|^(\d+\+?\s*(?:days?|weeks?|months?|hours?)\s+ago|today|just now|yesterday)$", re.I)
_COMPANY_LINE = re.compile(r"^at (.+)$", re.I)
_SALARY = re.compile(r'(?:\b(?:lpa|lakhs?|lacs?|salary|not disclosed)\b|[₹$€£])', re.I)
_ROLE_PREFIX = re.compile(r'\b(?:engineers?|developers?|scientists?|analysts?|architects?|consultants?|'
                          r'managers?|specialists?|programmers?|lead|head|director|intern)\b', re.I)
_NOISE = re.compile(
    r"^(?:\d+(?:\.\d+)?|\+\d+ more|\+\d+|[\d,]+\+?\s*reviews?|view job.*|apply(?: now| to this job)?|save|share"
    r"|founded in \d{4}|posted by .+|[₹$€£][\d.,]+[lk]?\s*-\s*[₹$€£][\d.,]+[lk]?(?:\s*/\s*yr)?"
    r"|[\d,]+\s*-\s*[\d,]+ employees|[\d,]+\+? employees|promoted|featured|new|be an early applicant)$",
    re.I,
)


def _posted_days(label: str) -> Optional[float]:
    """Naukri-style "3 days ago", or a date such as "7 Oct 2026" (Cutshort)."""
    from naukri_bot.sources import parse_posted_days

    days = parse_posted_days(label)
    if days is not None or not label:
        return days
    for layout in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            posted = datetime.strptime(label.strip(), layout).date()
        except ValueError:
            continue
        return float(max(0, (date.today() - posted).days))
    return None


def card_to_job(board: Board, href: str, heading: str, lines: List[str]) -> Optional[JobPosting]:
    # Cutshort puts "Bengaluru · 5 - 8 years · ₹2L - ₹15L / yr · Posted 7 Oct 2026" on one line.
    lines = [part.strip() for line in lines if line for part in line.split(" · ") if part.strip()]
    heading = (heading or (lines[0] if lines else "")).strip()
    if not heading:
        return None
    company, title = "", heading
    if board.company_first and " - " in heading:
        prefix, remainder = [part.strip() for part in heading.split(" - ", 1)]
        # Hirist also uses "Data Scientist - AI/ML Solutions" as a complete
        # job title. It is not a company called Data Scientist.
        if board.name != 'hirist' or not _ROLE_PREFIX.search(prefix):
            company, title = prefix, remainder
    experience = posted = location = ""
    tags = []  # type: List[str]
    blurbs = []  # type: List[str]
    for line in lines:
        if line == heading or line in (title, company):
            continue
        company_match = _COMPANY_LINE.match(line)
        if not company and company_match:
            company = company_match.group(1).strip()
            continue
        posted_match = None if line.casefold().startswith("posted by") else _POSTED.match(line)
        if not experience and _EXPERIENCE.match(line):
            experience = line
        elif not posted and posted_match:
            posted = (posted_match.group(1) or posted_match.group(2) or "").strip()
        elif _NOISE.match(line) or _SALARY.search(line):
            continue
        elif len(line) >= 60:
            blurbs.append(line)
        elif not location:
            location = line
        else:
            tags.append(line)
    return JobPosting(
        job_id=board_job_id(board, href),
        url=href,
        title=title,
        company=company,
        location=location,
        experience=experience,
        description=" ".join(blurbs),
        tags=tags[:15],
        posted_label=posted,
        posted_days_ago=_posted_days(posted),
        source="%s:%s" % (board.name, "cards"),
    )


def read_cards(driver: Any, board: Board) -> List[JobPosting]:
    try:
        raw = driver.execute_script(_CARDS_SCRIPT, board.job_link) or []
        if board.cards_script:
            seen = {item.get("href") for item in raw}
            raw += [item for item in (driver.execute_script(board.cards_script) or []) if item.get("href") not in seen]
    except WebDriverException as exc:
        logger.warning("%s: could not read the job cards: %s", board.label, str(exc).split("\n")[0])
        return []
    jobs = []
    for item in raw:
        job = card_to_job(board, item.get("href", ""), item.get("heading", ""), item.get("lines") or [])
        if job is not None:
            jobs.append(job)
    return jobs


def collect(driver: Any, board: Board, keywords: List[str], limit: int, pages: int = 1) -> List[JobPosting]:
    """Job cards from the board's own feed, then up to `pages` search pages per keyword; first sighting wins.

    A keyword stops early at a page that adds nothing new: the board ran out of results.
    """
    found: Dict[str, JobPosting] = {}
    sources = [((url,), "feed") for url in board.feeds]
    if board.search:
        depth = max(pages, 1) if board.search_page else 1
        sources += [(tuple(search_url(board, kw, n) for n in range(1, depth + 1)), "search:%s" % kw) for kw in keywords]
    for urls, source in sources:
        for number, url in enumerate(urls, 1):
            if len(found) >= limit:
                return list(found.values())[:limit]
            if not safe_get(driver, url):
                logger.info("%s: could not open %s", board.label, url)
                break
            time.sleep(PAGE_WAIT_S)
            _scroll(driver)
            jobs = read_cards(driver, board)
            fresh = 0
            for job in jobs:
                if job.job_id not in found:
                    found[job.job_id] = replace(job, source="%s:%s" % (board.name, source))
                    fresh += 1
            shown = source if number == 1 else "%s page %d" % (source, number)
            logger.info("%s: %s gave %d jobs (%d new)", board.label, shown, len(jobs), fresh)
            if not fresh:
                break
    return list(found.values())[:limit]


def _scroll(driver: Any, rounds: int = 6) -> None:
    """Scroll to the bottom until the page stops growing, so a feed that loads on scroll is read whole."""
    last = None
    for _ in range(rounds):
        try:
            height = driver.execute_script("window.scrollBy(0, document.body.scrollHeight); return document.body.scrollHeight")
        except WebDriverException:
            return
        time.sleep(1.0)
        if height == last:
            return
        last = height


# ---------------------------------------------------------------------------
# One job
# ---------------------------------------------------------------------------


def _controls(driver: Any, pattern: str) -> List[Any]:
    wanted = re.compile(pattern, re.I)
    return [control for control in ext._visible_controls(driver) if wanted.search(ext._control_text(control))]


# Shown controls outside the site's navigation, enabled or not. Wellfound and
# Hirist keep an "Applied" tab in the top bar of every page, which read as
# "already applied" for every job; Instahyre's "Application sent!" is disabled.
_MARKERS_SCRIPT = r"""
const out = [];
for (const el of document.querySelectorAll("button, a, [role='button'], [type='submit']")) {
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) continue;
  if (el.closest("nav, header, footer, [role='navigation'], [role='banner']")) continue;
  out.push((el.innerText || el.value || el.getAttribute('aria-label') || '').trim());
}
return out;
"""


def shows_applied(driver: Any, board: Board) -> bool:
    try:
        texts = driver.execute_script(_MARKERS_SCRIPT) or []
    except WebDriverException:
        return False
    wanted = re.compile(board.applied, re.I)
    # Wellfound writes "✓ Applied": a tick, an icon or a bullet around the word is still the word.
    return any(wanted.search(re.sub(r"^[^\w]+|[^\w.]+$", "", " ".join(str(text).split()))) for text in texts)


def signed_out(driver: Any, board: Board) -> bool:
    return bool(_controls(driver, board.signed_out))


def _page_text(driver: Any) -> str:
    try:
        return driver.execute_script("return document.body ? document.body.innerText : ''") or ""
    except WebDriverException:
        return ""


def browser_alive(driver: Any) -> bool:
    try:
        return bool(driver.window_handles)
    except WebDriverException:
        return False


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower().replace("www.", "")


def _names_from_page(driver: Any, board: Board, job: JobPosting) -> None:
    """Take the title and company from the job page's <title>, which is cleaner than the card's heading."""
    if not board.page_title:
        return
    try:
        found = re.match(board.page_title, (driver.title or "").strip())
    except WebDriverException:
        return
    if found:
        company = found.group("company").strip()
        title = found.group("title").strip()
        if company and title.casefold().startswith(company.casefold() + " - "):
            title = title[len(company) + 3:].strip()
        job.title = title or job.title
        job.company = company or job.company


def _result(job: JobPosting, status: str, detail: str, filled: int = 0, missing: int = 0) -> ApplyResult:
    return ApplyResult(
        job_id=job.job_id, url=job.url, status=status, detail=detail[:500], quota_consumed=False,
        questions_answered=filled, questions_abstained=missing,
    )


def _field_labels(driver: Any) -> set:
    return {item.question or item.name for item in ext.application_fields(ext.discover_fields(driver))}


def _wait_after_click(driver: Any, board: Board, handles: List[str], timeout_s: float, before: set) -> str:
    """What the Apply click led to: 'applied', 'site' (left the board), 'form', or '' (nothing seen)."""
    deadline = time.monotonic() + timeout_s
    home = _host(board.home)
    while time.monotonic() < deadline:
        new = [handle for handle in driver.window_handles if handle not in handles]
        if new:
            driver.switch_to.window(new[-1])
        url = ext._current_url(driver)
        if url and home not in _host(url) and "about:blank" not in url:
            return "site"
        if shows_applied(driver, board) or (board.applied_url and re.search(board.applied_url, url or "")):
            return "applied"
        if _field_labels(driver) - before:
            return "form"
        time.sleep(POLL_S)
    return ""


def application_landed(driver: Any, board: Board) -> bool:
    """The board already took the application: its Applied marker, applied page or a confirmation page is showing."""
    url = ext._current_url(driver) or ""
    if board.applied_url and re.search(board.applied_url, url):
        return True
    return shows_applied(driver, board) or ext._confirmation_url(url)


def answer_form(
    driver: Any, board: Board, job: JobPosting, profile: Profile, engine: Any, settings: Settings,
    resume_pdf: Optional[Path],
) -> Tuple[bool, List[str], List[str]]:
    """Fill the board's own application form page by page; (submitted, filled, missing).

    Hirist's last "Next" sends the application and lands on its applied page, so a form
    with no Submit button is checked for that before it is reported as needing a person.
    """
    writer = ext.long_answer_writer(settings, engine, job)
    filled = []  # type: List[str]
    fields = []  # type: List[Any]
    for _ in range(MAX_FORM_PAGES):
        if application_landed(driver, board):
            return True, filled, []
        fields = ext.application_fields(ext.discover_fields(driver))
        outcome = ext.fill_form(driver, fields, profile, engine, resume_pdf, writer)
        filled += outcome.filled
        missing = list(outcome.missing)
        if ext.challenge_shown(driver):
            missing.append("captcha (a check only a person may answer)")
        if missing:
            return False, filled, missing
        step = ext.find_next(driver)
        if step is None:
            break
        moved, problem = ext.next_page(driver, step)
        if not moved:
            return False, filled, ["the form did not move on (%s)" % problem]
    submit = ext.find_submit(driver)
    if submit is None:
        if application_landed(driver, board):
            return True, filled, []
        held = ext.disabled_step(driver)
        if held:
            blank = [item.question or item.name for item in fields if (item.question or item.name) not in filled and not item.value]
            return False, filled, ["the '%s' button stays disabled until every question is answered; still blank: %s"
                                   % (held, ", ".join(blank) or "none the bot can see")]
        return False, filled, ["no Submit button on the form"]
    ext._click(driver, submit)
    return True, filled, []


def _wait_for_controls(driver: Any, pattern: str, timeout_s: float) -> List[Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        found = _controls(driver, pattern)
        if found or time.monotonic() >= deadline:
            return found
        time.sleep(POLL_S)


def _verified(driver: Any, board: Board, job: JobPosting) -> bool:
    """Reload the job page in the board's tab and look for its Applied marker."""
    if not safe_get(driver, job.url):
        return False
    time.sleep(PAGE_WAIT_S)
    return shows_applied(driver, board)


def apply_to(
    driver: Any,
    board: Board,
    job: JobPosting,
    profile: Profile,
    engine: Any,
    settings: Settings,
    resume_pdf: Optional[Path],
    dry_run: bool,
) -> ApplyResult:
    """Apply to one job on the board; APPLIED_PLATFORM only when the board shows it applied after a reload."""
    from .page_brain import dead_reason

    home_handle = driver.current_window_handle
    keep = list(driver.window_handles)
    set_context = getattr(engine, "set_job_context", None)
    if callable(set_context):
        set_context(job)
    try:
        if not safe_get(driver, job.url):
            return _result(job, ApplyStatus.ERROR, "could not open the job page")
        time.sleep(PAGE_WAIT_S)
        _names_from_page(driver, board, job)
        if shows_applied(driver, board):
            return _result(job, ApplyStatus.ALREADY_APPLIED, "%s shows this job as applied" % board.label)
        if signed_out(driver, board):
            return _result(job, ApplyStatus.SESSION_EXPIRED, "%s is signed out" % board.label)
        gone = dead_reason(ext._page_text(driver))
        if gone:
            return _result(job, ApplyStatus.NO_APPLY_BUTTON, "the posting is gone: %s" % gone)
        buttons = _controls(driver, board.apply) + _controls(driver, board.external)
        if not buttons:
            return _result(job, ApplyStatus.NO_APPLY_BUTTON, "no Apply button (controls: %s)" % ", ".join(
                [ext._control_text(c) for c in ext._visible_controls(driver)][:8]))
        button = buttons[0]
        label = ext._control_text(button)
        if dry_run:
            return _result(job, DRY_RUN, "dry run: found %r, nothing clicked" % label)
        handles = list(driver.window_handles)
        before = _field_labels(driver)
        ext._click(driver, button)
        checked = job
        if board.second_apply:
            second = _wait_for_controls(driver, board.second_apply, AFTER_CLICK_WAIT_S)
            if second:
                checked = replace(job, url=ext._current_url(driver))
                before = _field_labels(driver)
                ext._click(driver, second[0])
        landed = _wait_after_click(driver, board, handles, AFTER_CLICK_WAIT_S, before)
        if landed == "site":
            return _company_site(driver, board, job, profile, engine, settings, resume_pdf)
        if landed == "applied":
            if _verified(driver, board, checked):
                return _result(job, ApplyStatus.APPLIED_PLATFORM, "%s shows Applied after a reload" % board.label)
            return _result(job, ApplyStatus.ERROR, "Submit was clicked (Apply) but %s did not show Applied after a reload" % board.label)
        filled, missing = [], ["the Apply click opened nothing the bot recognised"]  # type: List[str], List[str]
        if landed == "form":
            sent, filled, missing = answer_form(driver, board, job, profile, engine, settings, resume_pdf)
            if sent:
                human_pause(2.0, 4.0)
                if _verified(driver, board, checked):
                    return _result(job, ApplyStatus.APPLIED_PLATFORM, "form sent; %s shows Applied after a reload" % board.label,
                                   len(filled))
                return _result(job, ApplyStatus.ERROR, "Submit was clicked but %s did not show Applied after a reload" % board.label,
                               len(filled))
        stuck = ext.ExternalResult(
            status=ApplyStatus.EXTERNAL_MANUAL, url=ext._current_url(driver), ats=board.name,
            detail="needs you for: %s" % "; ".join(missing), filled=filled, missing=missing,
            resume=str(resume_pdf or ""))
        taken = browser_agent.take_over(driver, job, profile, settings, resume_pdf, False, stuck)
        if taken is not stuck and taken.status == ApplyStatus.APPLIED_EXTERNAL:
            if _verified(driver, board, checked):
                return _result(job, ApplyStatus.APPLIED_PLATFORM, "the browser agent applied; %s shows Applied" % board.label)
            return _result(job, ApplyStatus.ERROR, "Submit was clicked by the browser agent but %s did not show Applied" % board.label)
        if taken.status == ApplyStatus.ERROR:
            return _result(job, ApplyStatus.ERROR, taken.detail)
        ext.record_company_site(settings, job, taken)
        return _result(job, ApplyStatus.EXTERNAL_MANUAL, taken.detail, len(taken.filled), len(taken.missing))
    except WebDriverException as exc:
        return _result(job, ApplyStatus.ERROR, "%s: %s" % (type(exc).__name__, str(exc).split("\n")[0]))
    finally:
        ext.return_to(driver, home_handle, keep)


def _company_site(
    driver: Any, board: Board, job: JobPosting, profile: Profile, engine: Any, settings: Settings,
    resume_pdf: Optional[Path],
) -> ApplyResult:
    """The board's Apply led to the employer's own site: the company-site flow takes it from here."""
    url = ext._current_url(driver)
    if not settings.external_apply:
        ext.record_company_site(settings, job, ext.ExternalResult(
            status=ApplyStatus.EXTERNAL_MANUAL, url=url, ats=ext.detect_ats(url),
            detail="%s sends this one to the company's site; EXTERNAL_APPLY is off" % board.label))
        return _result(job, ApplyStatus.EXTERNAL_SKIPPED, "company site: %s" % url)
    logger.info("      company site: %s (%s)", url, ext.detect_ats(url))
    result = ext.apply_here(driver, job, profile, engine, settings, resume_pdf, False)
    result = browser_agent.take_over(driver, job, profile, settings, resume_pdf, False, result)
    if result.status in (ApplyStatus.APPLIED_EXTERNAL, ext.GONE):
        ext.forget_company_site(settings, job)
    else:
        ext.record_company_site(settings, job, result)
    return result.to_apply_result(job)


# ---------------------------------------------------------------------------
# A run on one board
# ---------------------------------------------------------------------------


def run_board(
    driver: Any, board: Board, settings: Settings, profile: Profile, ledger: Any, engine: Any, client: Any,
    limit: int, dry_run: bool, resume_pdf: Optional[Path],
    restart: Optional[Callable[[], Optional[Any]]] = None,
) -> RunSummary:
    """Collect, rank and apply on one board; `restart` opens a new browser when the old one closed."""
    from common import answers as answers_module
    from naukri_bot import ranking
    from naukri_bot.cli import _pause_between_applications, _summary_record, derive_keywords

    summary = RunSummary()
    run_id = ledger.start_run()
    try:
        if not safe_get(driver, board.home):
            logger.error("%s: could not open %s", board.label, board.home)
            return summary
        time.sleep(PAGE_WAIT_S)
        if signed_out(driver, board):
            logger.error(
                "%s is signed out in the bot's browser. Sign in once with: scripts/google_login.sh %s",
                board.label, board.home)
            return summary
        jobs = collect(driver, board, derive_keywords(profile, settings), settings.max_candidates,
                       settings.pages_per_keyword)
        summary.collected = len(jobs)
        for job in jobs:
            ledger.record_seen(job)
        jobs, summary.too_old = ranking.drop_stale_candidates(jobs, settings)
        ranked = ranking.rank(profile, jobs, client, settings)
        summary.ranked = len(ranked)
        for scored in ranked:
            ledger.record_seen(scored.job, scored.score)
        selected = ranking.select_for_application(ranked, replace(settings, target_applications=limit), ledger.has_applied)
        facts = answers_module.facts_fingerprint(profile, settings)
        held = ledger.waiting_on_you(facts) | ledger.sent_unconfirmed()
        summary.held_back = sum(1 for scored in selected if scored.job.job_id in held)
        selected = [scored for scored in selected if scored.job.job_id not in held]
        summary.eligible = len(selected)
        logger.info("%s: %d collected, %d ranked, %d eligible, target %d", board.label, summary.collected,
                    summary.ranked, summary.eligible, limit)
        sent = unconfirmed = 0
        for scored in selected:
            if sent >= limit:
                break
            job = scored.job
            if not browser_alive(driver):
                driver = restart() if restart is not None else None
                if driver is None:
                    logger.error("The browser closed and could not be reopened; stopping %s.", board.label)
                    break
            logger.info("[%s %d of %d applied] %s @ %s (%.0f)", board.label, sent, limit, job.title,
                        job.company or "-", scored.score)
            result = apply_to(driver, board, job, profile, engine, settings, resume_pdf, dry_run)
            logger.info("      -> %s (%s)", result.status, result.detail[:250])
            summary.attempted += 1
            if result.status == DRY_RUN:
                sent += 1
                continue
            ledger.record_attempt(result, title=job.title, company=job.company, facts=facts)
            _count(summary, result)
            if result.status in (ApplyStatus.APPLIED_PLATFORM, ApplyStatus.APPLIED_EXTERNAL):
                sent += 1
                _pause_between_applications(settings)
            if result.status == ApplyStatus.SESSION_EXPIRED:
                logger.error("%s signed out mid-run; stopping.", board.label)
                break
            if result.status == ApplyStatus.ERROR and "submit was clicked" in result.detail.casefold():
                unconfirmed += 1
                if unconfirmed >= UNCONFIRMED_BEFORE_STOP:
                    logger.error("%s: %d applications went through without the board showing Applied; stopping so "
                                 "the bot does not apply blind. Check them on %s.", board.label, unconfirmed, board.home)
                    break
    finally:
        record = _summary_record(summary, settings)
        record["board"] = board.name
        ledger.finish_run(run_id, record)
    return summary


def _count(summary: RunSummary, result: ApplyResult) -> None:
    if result.status in (ApplyStatus.APPLIED_PLATFORM, ApplyStatus.APPLIED_EXTERNAL):
        summary.applied += 1
    elif result.status == ApplyStatus.ALREADY_APPLIED:
        summary.skipped_already_applied += 1
    elif result.status in (ApplyStatus.EXTERNAL_SKIPPED, ApplyStatus.EXTERNAL_MANUAL):
        summary.external_manual += 1
    elif result.status == ApplyStatus.ABSTAINED:
        summary.skipped_abstained += 1
    else:
        summary.errors += 1
    summary.results.append(result)


# ---------------------------------------------------------------------------
# Profile update
# ---------------------------------------------------------------------------

_PROFILE_TASK = (
    "You start on the candidate's own profile page (if this page is not the profile, find the profile or "
    "edit-profile link). Bring every section in line with the planned profile and the facts, using only "
    "them; never invent anything. Save at least once even if nothing needed fixing, so the board records "
    "an update today. Do not apply to any job and do not change the password, email or phone number."
)


_CREATE_TASK = (
    "The candidate has no session on this job board. First look for a sign-in: if an account already "
    "exists for the email below, sign in (prefer \"Continue with Google\"; Chrome is signed in to that "
    "Google account) instead of creating a second one. Otherwise create the account with that email, "
    "again preferring Google sign-up, and build the candidate profile from the facts below: headline or "
    "summary, current role and company, skills, total experience, notice period, current and preferred "
    "location, expected salary. Use only the facts; never invent anything. Accept only the board's own "
    "terms; do not subscribe to newsletters or paid plans, and do not apply to any job. If the board "
    "asks for an OTP, a captcha, a password you do not have, or a phone number, stop and report "
    "needs_you. In notes, say whether you created or signed in to the account, give the URL of the "
    "candidate's profile page, and quote the board's confirmation text exactly as shown."
)

_URL = re.compile(r"https?://[^\s\"')\]]+")


def _profile_link(driver: Any, board: Board, notes: str) -> str:
    """The profile URL the agent reported, else the board page it ended on, else ""."""
    for url in _URL.findall(notes or ""):
        if urlparse(url).netloc.endswith(urlparse(board.home).netloc.replace("www.", "")):
            return url.rstrip(".,")
    try:
        current = driver.current_url
    except (AttributeError, WebDriverException):
        current = ""
    if current and urlparse(current).netloc == urlparse(board.home).netloc:
        return current
    return ""


def _remember_profile(driver: Any, board: Board, action: str, notes: str) -> None:
    try:
        link = (_profile_link(driver, board, notes) or memory.load_profiles().get(board.name, {}).get("url")
                or board.profile_url or board.home)
        memory.record_profile(board.name, action, link, notes)
    except OSError as exc:
        logger.warning("%s: could not note the profile in user/memory (%s)", board.label, exc)


def create_profile(driver: Any, board: Board, settings: Settings, profile: Profile,
                   resume_pdf: Optional[Path] = None, dry_run: bool = False) -> bool:
    """Sign in or sign up on the board and build the profile through the browser agent.

    True only when the agent says it finished and the board then shows a session.
    """
    from .accounts import account_email

    if dry_run:
        logger.info("%s: dry run, would create the account and profile; changed nothing.", board.label)
        return True
    if not safe_get(driver, board.home):
        logger.error("%s: could not open %s", board.label, board.home)
        return False
    time.sleep(PAGE_WAIT_S)
    workdir = browser_agent.workdir_for(settings, "%s create profile" % board.label)
    files = browser_agent.stage_files(workdir, (resume_pdf,) if resume_pdf else ())
    instruction = _CREATE_TASK + (" Upload the resume file given where the profile asks for one." if files else "")
    plan = profile_plan.plan_for(profile, settings)
    if plan is not None:
        instruction += "\n\n" + profile_plan.agent_brief(plan)
    prompt = browser_agent.task_prompt(instruction, board.home, browser_agent.facts_text(profile, settings),
                                       account_email(settings), files,
                                       has_password=bool(settings.company_site_password))
    run = browser_agent.run_agent(driver, settings, prompt, workdir, files)
    report = run.report or {}
    if run.problem or report.get("status") != "done":
        logger.error("%s profile not created: %s", board.label,
                     run.problem or report.get("why") or "the agent gave no reason")
        return False
    notes = report.get("notes") or report.get("why") or ""
    if signed_out(driver, board):
        logger.error("%s: the agent finished but the board still shows no session; not counting it.", board.label)
        return False
    created = "created" in notes.casefold()
    _remember_profile(driver, board, memory.PROFILE_CREATED if created else memory.PROFILE_UPDATED, notes)
    logger.info("%s account %s in %.0fs: %s", board.label, "created" if created else "signed in",
                run.seconds, notes)
    return True


def update_profile(driver: Any, board: Board, settings: Settings, profile: Profile,
                   resume_pdf: Optional[Path] = None, dry_run: bool = False, create: bool = False,
                   extra: str = "") -> bool:
    """Refresh the board profile through the browser agent; True only when the agent says it saved.

    `extra` is appended to the agent's task, for what one site needs on top (Naukri, LinkedIn).

    With `create`, a board with no session first gets its account and profile made (create_profile).
    """
    if not board.profile_url:
        logger.warning("%s: no profile page is known; skipping the profile update.", board.label)
        return False
    if not safe_get(driver, board.profile_url):
        logger.error("%s: could not open %s", board.label, board.profile_url)
        return False
    time.sleep(PAGE_WAIT_S)
    if signed_out(driver, board):
        if not create:
            logger.error("%s is signed out. Sign in once with scripts/google_login.sh (or pass --create-profile), "
                         "then run again.", board.label)
            return False
        if not create_profile(driver, board, settings, profile, resume_pdf, dry_run):
            return False
        if dry_run:
            return True
        if not safe_get(driver, board.profile_url):
            logger.error("%s: could not open %s", board.label, board.profile_url)
            return False
        time.sleep(PAGE_WAIT_S)
    if dry_run:
        logger.info("%s: dry run, opened %s and changed nothing.", board.label, board.profile_url)
        return True
    files = (resume_pdf,) if resume_pdf else ()
    instruction = _PROFILE_TASK + (" If the profile has a resume upload, replace the resume with the file given."
                                   if files else "") + (" " + extra if extra else "")
    plan = profile_plan.plan_for(profile, settings)
    if plan is None and profile is not None:
        logger.error("%s: no LLM-written profile plan, so the profile is left as it is (see the error above).",
                     board.label)
        return False
    if plan is not None:
        instruction += "\n\n" + profile_plan.agent_brief(plan)
    saved, notes = profile_agent.run(driver, board, settings, profile, instruction, files, plan, "profile")
    if saved:
        _remember_profile(driver, board, memory.PROFILE_UPDATED, notes)
    return saved


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None, only: Optional[Board] = None) -> argparse.Namespace:
    """The shared flags; `only` is the board of a per-board bot (python3 -m hirist_bot), which has no --site."""
    parser = argparse.ArgumentParser(
        prog="python3 -m %s_bot" % only.name if only else "python3 -m sites_bot.platforms",
        description=("Apply on %s with the same facts, answers, ranking and records as Naukri." % only.label
                     if only else "Apply on several job boards in one run (each board also has its own "
                     "bot: python3 -m hirist_bot, instahyre_bot, cutshort_bot, wellfound_bot)."),
    )
    if not only:
        parser.add_argument("--site", action="append", choices=sorted(BOARDS) + ["all"],
                            help="board to work on; repeat for several (default: PLATFORMS in .env)")
    parser.add_argument("--limit", type=int, help="applications per board this run (default: PLATFORM_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="collect, rank and open each job, click nothing")
    parser.add_argument("--update-profile", action="store_true",
                        help="refresh the board profile through the browser agent before applying")
    parser.add_argument("--profile-only", action="store_true",
                        help="refresh the board profile and apply nowhere")
    parser.add_argument("--create-profile", action="store_true",
                        help="when the board shows no session, sign in or create the account and profile first")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def chosen_boards(names: Optional[List[str]], settings: Settings) -> List[Board]:
    wanted = names or [name.strip() for name in settings.platforms.split(",") if name.strip()]
    if "all" in wanted:
        return [board for board in BOARDS.values() if not board.risky]
    return [BOARDS[name] for name in wanted if name in BOARDS]


def main(argv: Optional[List[str]] = None, only: Optional[Board] = None) -> int:
    """Run the board loop; `only` limits it to one board (the per-board bots call this)."""
    from common import browser, config, ledger as ledger_module, llm, profile as profile_module, report
    from common import resume as resume_module
    from common.answers import AnswerEngine
    from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging, keep_log

    args = parse_args(argv, only)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env, {"dry_run": True} if args.dry_run else {})
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    boards = [only] if only else chosen_boards(args.site, settings)
    if not boards:
        logger.error("No board chosen: pass --site (%s) or set PLATFORMS in .env.", ", ".join(sorted(BOARDS)))
        return EXIT_CONFIG
    keep_log(settings, only.name if only else "boards")
    limit = args.limit if args.limit is not None else settings.platform_limit
    browser_agent.reset()
    ledger = ledger_module.open_ledger(settings)
    client = llm.build_client(settings)
    engine = AnswerEngine(ledger, client, profile, settings)
    try:
        resume_pdf = resume_module.build_base_pdf(settings)  # type: Optional[Path]
    except resume_module.ResumeError as exc:
        logger.warning("No resume PDF to attach (%s)", exc)
        resume_pdf = None
    drivers = [browser.create_driver(settings)]

    def restart() -> Optional[Any]:
        if len(drivers) > MAX_BROWSER_RESTARTS:
            return None
        logger.warning("The browser closed (quit by hand, or it went away); opening a new one and going on.")
        try:
            drivers[-1].quit()
        except WebDriverException:
            pass
        drivers.append(browser.create_driver(settings))
        return drivers[-1]

    totals: Dict[str, RunSummary] = {}
    profiles_failed: List[str] = []
    try:
        for board in boards:
            if not browser_alive(drivers[-1]) and restart() is None:
                logger.error("The browser keeps closing; stopping.")
                break
            if args.update_profile or args.profile_only or args.create_profile:
                if not update_profile(drivers[-1], board, settings, profile, resume_pdf, args.dry_run,
                                      create=args.create_profile):
                    profiles_failed.append(board.label)
            if args.profile_only:
                continue
            totals[board.label] = run_board(drivers[-1], board, settings, profile, ledger, engine, client, limit,
                                            args.dry_run, resume_pdf, restart)
    finally:
        try:
            drivers[-1].quit()
        except WebDriverException:
            pass
        ledger.close()
    for label, summary in totals.items():
        logger.info("%s: applied %d, tried %d, for you %d, errors %d (collected %d, eligible %d)", label,
                    summary.applied, summary.attempted, summary.external_manual, summary.errors,
                    summary.collected, summary.eligible)
    if not args.dry_run and not args.profile_only:
        report.update_quietly(settings)
    if profiles_failed:
        logger.error("Profiles not updated: %s", ", ".join(profiles_failed))
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
