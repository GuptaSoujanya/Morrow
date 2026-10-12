"""Apply on job boards other than Naukri, with one loop for all of them.

Each board is a Board record: its search pages, what its job links look like,
and the words on its Apply and Applied controls. The loop collects job cards
from the search pages, ranks them with the same scoring as Naukri, opens each
chosen job, clicks Apply, answers any form with the company-site filler, and
counts the application only when the board shows the job as applied after a
reload. A board page the script cannot finish goes to the browser agent when
it is on, and otherwise to data/company_sites.md for a person.

    python3 -m naukri_bot.platforms --site hirist --limit 10 [--dry-run]
"""

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from selenium.common.exceptions import WebDriverException

from . import browser_agent
from . import external as ext
from .browser import human_pause, safe_get
from .models import ApplyResult, ApplyStatus, JobPosting, Profile, RunSummary, Settings

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


@dataclass(frozen=True)
class Board:
    name: str
    label: str
    home: str
    # Pages listing jobs picked for the signed-in profile, read before any search.
    feeds: Tuple[str, ...]
    # "{slug}" is the keyword in lower-case-hyphen form, "{query}" the URL-encoded keyword; "" = feeds only.
    search: str
    job_link: str
    job_id: str
    apply: str
    applied: str
    external: str = r"company (?:site|website)|apply on company|external"
    signed_out: str = r"^(?:log ?in|sign ?in|login / register|candidate login)$"
    # Card heading is "Company - Title".
    company_first: bool = True
    # The job page's <title>, with named groups "title" and "company" when the board puts both there.
    page_title: str = ""
    # The board's terms forbid automated use; it is skipped unless named on purpose.
    risky: bool = False
    # Address the board moves to once an application went through.
    applied_url: str = ""
    # A board whose Apply only opens its own job view, with a second Apply there.
    # The Applied marker then shows on that view, not on the public job page.
    second_apply: str = ""


BOARDS = {
    "hirist": Board(
        name="hirist",
        label="Hirist",
        home="https://www.hirist.tech/jobfeed",
        feeds=("https://www.hirist.tech/jobfeed",),
        search="https://www.hirist.tech/search/{slug}",
        job_link=r"^https://www\.hirist\.tech/j/[a-z0-9-]+-\d+",
        job_id=r"-(\d+)/?$",
        apply=r"^(?:apply|apply now|quick apply)$",
        applied=r"^(?:applied|already applied)(?: on .{0,20})?$",
        page_title=r"^(?P<title>.+) - (?P<company>[^-|]+?) \| hirist\.tech$",
        applied_url=r"^https://www\.hirist\.tech/job/applied\b",
    ),
    "instahyre": Board(
        name="instahyre",
        label="Instahyre",
        home="https://www.instahyre.com/candidate/opportunities/",
        feeds=("https://www.instahyre.com/candidate/opportunities/?matching=true",),
        search="https://www.instahyre.com/{slug}-jobs/",
        job_link=r"^https://www\.instahyre\.com/job-\d+-",
        job_id=r"/job-(\d+)-",
        apply=r"^(?:apply|apply now|i'?m interested|interested)$",
        # The Apply button turns into "Application sent!" the moment it is clicked.
        applied=r"^(?:applied|application sent|interest sent)!?(?: on .{0,20})?$",
        signed_out=r"^(?:log ?in|sign ?in)$",
        page_title=r"^(?P<title>.+?) job at (?P<company>.+?) - Instahyre$",
    ),
    "cutshort": Board(
        name="cutshort",
        label="Cutshort",
        home="https://cutshort.io/jobs/datascience-jobs",
        # Cutshort's keyword search gave the same nine jobs for every keyword; its category pages are the feed.
        feeds=("https://cutshort.io/jobs/datascience-jobs", "https://cutshort.io/jobs/backend-developer-jobs",
               "https://cutshort.io/jobs/frontend-developer-jobs"),
        search="",
        job_link=r"^https://cutshort\.io/job/[A-Za-z0-9-]+-[A-Za-z0-9]{8}$",
        job_id=r"-([A-Za-z0-9]{8})/?$",
        # Only the posting's own button: the related jobs below it each have an "Apply now".
        apply=r"^apply to this job$",
        applied=r"^(?:applied|application sent|already applied)!?(?: on .{0,20})?$",
        company_first=False,
        page_title=r"^(?P<company>.+?) is hiring (?P<title>.+?) job in .+\| Cutshort$",
        # "Apply to this job" leads to /profile/all-jobs?jobid=..., where "Apply now" opens the form.
        second_apply=r"^apply now$",
    ),
    "wellfound": Board(
        name="wellfound",
        label="Wellfound",
        home="https://wellfound.com/jobs",
        feeds=("https://wellfound.com/jobs",),
        search="https://wellfound.com/role/r/{slug}",
        job_link=r"^https://wellfound\.com/jobs/\d+-",
        job_id=r"/jobs/(\d+)-",
        apply=r"^(?:apply|apply now|send application)$",
        applied=r"^(?:applied|application sent)(?: on .{0,20})?$",
        signed_out=r"^(?:log ?in|sign ?in)$",
        company_first=False,
        page_title=r"^(?P<title>.+?) (?:at|@) (?P<company>[^•|]+?)(?: [•|].*)?$",
    ),
}


def board_job_id(board: Board, url: str) -> str:
    found = re.search(board.job_id, url.split("?")[0].split("#")[0])
    return "%s:%s" % (board.name, found.group(1) if found else url)


def search_url(board: Board, keyword: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    return board.search.format(slug=slug, query=quote_plus(keyword))


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
_NOISE = re.compile(
    r"^(?:\d+(?:\.\d+)?|\+\d+ more|\+\d+|[\d,]+\+?\s*reviews?|view job.*|apply(?: now| to this job)?|save|share"
    r"|founded in \d{4}|posted by .+|[₹$€£][\d.,]+[lk]?\s*-\s*[₹$€£][\d.,]+[lk]?(?:\s*/\s*yr)?"
    r"|[\d,]+\s*-\s*[\d,]+ employees|[\d,]+\+? employees|promoted|featured|new|be an early applicant)$",
    re.I,
)


def _posted_days(label: str) -> Optional[float]:
    """Naukri-style "3 days ago", or a date such as "7 Oct 2026" (Cutshort)."""
    from .sources import parse_posted_days

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
        company, title = [part.strip() for part in heading.split(" - ", 1)]
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
        elif _NOISE.match(line):
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
    except WebDriverException as exc:
        logger.warning("%s: could not read the job cards: %s", board.label, str(exc).split("\n")[0])
        return []
    jobs = []
    for item in raw:
        job = card_to_job(board, item.get("href", ""), item.get("heading", ""), item.get("lines") or [])
        if job is not None:
            jobs.append(job)
    return jobs


def collect(driver: Any, board: Board, keywords: List[str], limit: int) -> List[JobPosting]:
    """Job cards from the board's own feed, then one search page per keyword; first sighting wins."""
    found: Dict[str, JobPosting] = {}
    pages = [(url, "feed") for url in board.feeds]
    if board.search:
        pages += [(search_url(board, kw), "search:%s" % kw) for kw in keywords]
    for url, source in pages:
        if len(found) >= limit:
            break
        if not safe_get(driver, url):
            logger.info("%s: could not open %s", board.label, url)
            continue
        time.sleep(PAGE_WAIT_S)
        _scroll(driver)
        jobs = read_cards(driver, board)
        fresh = 0
        for job in jobs:
            if job.job_id not in found:
                found[job.job_id] = replace(job, source="%s:%s" % (board.name, source))
                fresh += 1
        logger.info("%s: %s gave %d jobs (%d new)", board.label, source, len(jobs), fresh)
    return list(found.values())[:limit]


def _scroll(driver: Any) -> None:
    for _ in range(3):
        try:
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight)")
        except WebDriverException:
            return
        time.sleep(1.0)


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
    return any(wanted.search(" ".join(str(text).split())) for text in texts)


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


def answer_form(
    driver: Any, job: JobPosting, profile: Profile, engine: Any, settings: Settings, resume_pdf: Optional[Path]
) -> Tuple[bool, List[str], List[str]]:
    """Fill the board's own application form page by page; (submitted, filled, missing)."""
    writer = ext.long_answer_writer(settings, engine, job)
    filled = []  # type: List[str]
    for _ in range(MAX_FORM_PAGES):
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
            sent, filled, missing = answer_form(driver, job, profile, engine, settings, resume_pdf)
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
    from . import answers as answers_module
    from . import ranking
    from .cli import _pause_between_applications, _summary_record, derive_keywords

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
        jobs = collect(driver, board, derive_keywords(profile, settings), settings.max_candidates)
        summary.collected = len(jobs)
        for job in jobs:
            ledger.record_seen(job)
        jobs, summary.too_old = ranking.drop_stale_candidates(jobs, settings)
        ranked = ranking.rank(profile, jobs, client, settings)
        summary.ranked = len(ranked)
        for scored in ranked:
            ledger.record_seen(scored.job, scored.score)
        selected = ranking.select_for_application(ranked, settings, ledger.has_applied)
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
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m naukri_bot.platforms",
        description="Apply on other job boards with the same facts, answers, ranking and records as Naukri.",
    )
    parser.add_argument("--site", action="append", choices=sorted(BOARDS) + ["all"],
                        help="board to work on; repeat for several (default: PLATFORMS in .env)")
    parser.add_argument("--limit", type=int, help="applications per board this run (default: PLATFORM_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="collect, rank and open each job, click nothing")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def chosen_boards(names: Optional[List[str]], settings: Settings) -> List[Board]:
    wanted = names or [name.strip() for name in settings.platforms.split(",") if name.strip()]
    if "all" in wanted:
        return [board for board in BOARDS.values() if not board.risky]
    return [BOARDS[name] for name in wanted if name in BOARDS]


def main(argv: Optional[List[str]] = None) -> int:
    from . import browser, config, ledger as ledger_module, llm, profile as profile_module, report
    from . import resume as resume_module
    from .answers import AnswerEngine
    from .cli import EXIT_CONFIG, EXIT_OK, configure_logging, keep_log

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env, {"dry_run": True} if args.dry_run else {})
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    boards = chosen_boards(args.site, settings)
    if not boards:
        logger.error("No board chosen: pass --site (%s) or set PLATFORMS in .env.", ", ".join(sorted(BOARDS)))
        return EXIT_CONFIG
    keep_log(settings, "boards")
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
    try:
        for board in boards:
            if not browser_alive(drivers[-1]) and restart() is None:
                logger.error("The browser keeps closing; stopping.")
                break
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
    if not args.dry_run:
        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
