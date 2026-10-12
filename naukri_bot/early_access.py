"""Share interest in Naukri "Early access" roles.

Early access roles are not job postings.  They are saved recruiter searches:
Naukri stores the Boolean query a recruiter ran against its resume database and
shows it to candidates the query matched.  The card's button says "Share
interest", not "Apply" - pressing it flags the profile against that saved query
so the profile ranks higher when the recruiter runs it again.

Two consequences shape this module:

* No application is created, so **none of the 50/day apply quota is spent**.
  This runs beside the apply pipeline and can never cannibalise it.
* The cards carry no job id, no data attribute and no link - the title is an
  ``<a>`` without an href.  Roles are therefore keyed by a hash of their
  visible text so a second run does not re-share the same one.

The page is a client-side route: navigating straight to
``/mnjuser/recommended-earjobs`` redirects to the homepage.  It only resolves
when the homepage "View all" link is clicked, which is what ``open_page`` does.
"""

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common.browser import human_pause, safe_get
from common.models import Settings

logger = logging.getLogger(__name__)

HOMEPAGE_URL = "https://www.naukri.com/mnjuser/homepage"
EARLY_ACCESS_PATH = "/mnjuser/recommended-earjobs"
VIEW_ALL_SELECTOR = "a[href='%s']" % EARLY_ACCESS_PATH
CARD_SELECTOR = "div.cust-job-tuple"
SHARE_BUTTON_SELECTOR = "button.unshared"
SAVE_APPLY_PATH = "/myapply/saveApply"
LISTING_URL = "https://www.naukri.com" + EARLY_ACCESS_PATH

# Deliberately slower than the browsing default: this path clicks many buttons
# in sequence, which is the pattern that looks least like a person.
SHARE_PAUSE = (1.5, 4.0)


@dataclass
class EarlyAccessRole:
    """One early access card's visible details."""

    index: int
    role_key: str
    title: str = ""
    company: str = ""
    experience: str = ""
    location: str = ""
    posted_label: str = ""

    def describe(self) -> str:
        parts = [self.title or "(untitled)"]
        if self.company:
            parts.append("@ %s" % self.company)
        if self.location:
            parts.append("(%s)" % self.location)
        return " ".join(parts)


@dataclass
class EarlyAccessSummary:
    found: int = 0
    already_shared: int = 0
    shared: int = 0
    failed: int = 0
    skipped: int = 0
    aborted_reason: str = ""
    roles: List[EarlyAccessRole] = field(default_factory=list)


def role_key(title: str, company: str, experience: str, location: str) -> str:
    """Stable identifier for a card that carries no id of its own."""
    raw = "|".join(part.strip().lower() for part in (title, company, experience, location))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _attr_or_text(card: Any, selector: str) -> str:
    try:
        element = card.select_one(selector)
    except AttributeError as exc:
        logger.debug("Could not query %s: %s", selector, exc)
        return ""
    if element is None:
        return ""
    value = element.get("title", "") or ""
    if value.strip():
        return value.strip()
    return element.get_text(" ", strip=True)


def _land_on_listing(driver: Any, url: str, wait_s: int = 15) -> bool:
    """Load ``url`` and report whether we ended up on a rendered listing."""
    if not safe_get(driver, url):
        return False
    try:
        current = driver.current_url
    except WebDriverException as exc:
        logger.debug("Could not read the current URL after loading %s: %s", url, exc)
        return False
    if EARLY_ACCESS_PATH not in current:
        logger.debug("%s redirected to %s", url, current)
        return False
    try:
        WebDriverWait(driver, wait_s).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR))
        )
    except TimeoutException:
        logger.debug("%s rendered no cards within %ds", current, wait_s)
        return False
    return True


def open_page(driver: Any, settings: Settings, attempts: int = 3) -> bool:
    """Reach the early access listing.

    Direct navigation works once the session is warm (6 of 6 when probed) but
    bounced back to the homepage on a cold session right after login, so the
    homepage link stays as a fallback.  That fallback is unreliable on its own:
    Naukri serves the early access strip on only about a third of homepage
    renders, and on a miss the entire widget is absent from the HTML rather
    than lazy-loaded, so reloading is the only recourse.

    Returns False rather than raising when the page cannot be reached.
    """
    if _land_on_listing(driver, LISTING_URL, wait_s=15):
        human_pause()
        return True

    link = None
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        if not safe_get(driver, HOMEPAGE_URL):
            logger.warning("Could not load the Naukri homepage; early access skipped.")
            return False
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, VIEW_ALL_SELECTOR))
            )
            link = driver.find_element(By.CSS_SELECTOR, VIEW_ALL_SELECTOR)
            break
        except TimeoutException:
            logger.info(
                "Homepage render %d of %d did not include the early access strip.",
                attempt,
                total,
            )
            human_pause()

    if link is None:
        logger.warning(
            "No early access link after %d homepage loads - either there are no "
            "early access roles right now, or the homepage layout changed.",
            total,
        )
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", link)
        human_pause()
        link.click()
    except (
        ElementClickInterceptedException,
        StaleElementReferenceException,
        WebDriverException,
    ) as exc:
        logger.warning("Could not open the early access listing: %s", exc)
        return False

    try:
        WebDriverWait(driver, 20).until(lambda d: EARLY_ACCESS_PATH in d.current_url)
    except TimeoutException:
        logger.warning(
            "Clicking the early access link left us on %s instead of %s.",
            driver.current_url,
            EARLY_ACCESS_PATH,
        )
        return False

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR))
        )
    except TimeoutException:
        logger.warning("Early access page loaded but rendered no cards within 20s.")
        return False
    human_pause()
    return True


def collect_roles(driver: Any) -> List[EarlyAccessRole]:
    """Read every rendered early access card. Clicks nothing."""
    try:
        soup = BeautifulSoup(driver.page_source, "html5lib")
    except WebDriverException as exc:
        logger.warning("Could not read the early access page: %s", exc)
        return []
    cards = list(soup.select(CARD_SELECTOR))
    roles: List[EarlyAccessRole] = []
    for index, card in enumerate(cards):
        title = _attr_or_text(card, "a.title")
        company = _attr_or_text(card, "span.comp-name")
        experience = _attr_or_text(card, "span.exp")
        location = _attr_or_text(card, "span.loc")
        posted = _attr_or_text(card, "span.job-post-day")
        if not title:
            logger.warning(
                "Early access card %d has no title; the card markup may have changed.",
                index + 1,
            )
            continue
        roles.append(
            EarlyAccessRole(
                index=index,
                role_key=role_key(title, company, experience, location),
                title=title,
                company=company,
                experience=experience,
                location=location,
                posted_label=posted,
            )
        )
    logger.info("Early access listing shows %d roles.", len(roles))
    return roles


def _share_button(driver: Any, index: int) -> Optional[Any]:
    """Return the unshared button on card ``index``, or None if there isn't one."""
    cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
    if index >= len(cards):
        return None
    buttons = cards[index].find_elements(By.CSS_SELECTOR, SHARE_BUTTON_SELECTOR)
    if not buttons:
        return None
    return buttons[0]


def _classify_redirect(url: str) -> Tuple[bool, str]:
    """Decide whether leaving the listing was a successful share or a fault.

    Sharing interest bounces the browser to Naukri's S2J confirmation URL, so
    leaving the listing is the success path here rather than an anomaly.  Any
    other destination is still treated as a fault.
    """
    if SAVE_APPLY_PATH not in url:
        return False, "navigated to %s" % url

    params = parse_qs(urlparse(url).query)
    sources = params.get("src", []) + params.get("acpPageType", [])
    if not any("S2J" in value for value in sources):
        return False, "navigated to a non-S2J %s" % url

    job_id = params.get("strJobsarr", [""])[0].strip("[] ")
    responses = params.get("multiApplyResp", [""])[0]
    if job_id and responses:
        if ('"%s":200' % job_id) not in responses.replace(" ", ""):
            return False, "Naukri returned %s for job %s" % (responses, job_id)

    title = params.get("jobTitle", [""])[0]
    return True, "Naukri confirmed job %s (%s)" % (job_id or "?", title or "untitled")


def _share_outcome(
    driver: Any, index: int, listing_url: str, timeout: int = 15
) -> Tuple[bool, str, str]:
    """Confirm a share landed, returning ``(ok, kind, detail)``.

    ``kind`` is "flipped" when the button left the unshared state in place, or
    "navigated" when Naukri redirected to its S2J confirmation URL.  A click
    that did not raise proves nothing, so one of those two signals is required.
    """
    deadline = time.monotonic() + timeout
    last_url = listing_url
    while time.monotonic() < deadline:
        try:
            last_url = driver.current_url
        except WebDriverException as exc:
            return False, "", "could not read the current URL: %s" % exc

        if last_url != listing_url:
            ok, detail = _classify_redirect(last_url)
            if ok:
                return True, "navigated", detail
            return False, "", detail

        try:
            if _share_button(driver, index) is None:
                return True, "flipped", "button left the unshared state"
        except (StaleElementReferenceException, WebDriverException) as exc:
            return False, "", "could not re-read the button: %s" % exc

        time.sleep(0.4)

    return (
        False,
        "",
        "button still reads 'Share interest' (last url %s)" % last_url,
    )


def share_all(
    driver: Any,
    settings: Settings,
    ledger: Any,
    limit: int = 20,
    dry_run: bool = False,
) -> EarlyAccessSummary:
    """Share interest in up to ``limit`` early access roles.

    Stops at the first anomaly rather than pressing on: if a button does not
    flip, or the page lands somewhere other than Naukri's S2J confirmation,
    something is wrong and the remaining clicks would be guesses.
    """
    summary = EarlyAccessSummary()
    if not open_page(driver, settings):
        summary.aborted_reason = "early access listing unreachable"
        return summary

    roles = collect_roles(driver)
    summary.found = len(roles)
    summary.roles = roles
    if not roles:
        return summary

    if dry_run:
        for role in roles:
            try:
                if ledger.has_shared_interest(role.role_key):
                    summary.already_shared += 1
                    continue
            except sqlite3.Error:
                logger.exception("Ledger lookup failed for %s", role.describe())
                summary.aborted_reason = "ledger lookup failed"
                return summary
            logger.info("[DRY RUN] Would share interest: %s", role.describe())
            summary.skipped += 1
        return summary

    # A successful share navigates away and the listing reshuffles, so card
    # indices go stale. role_key is a hash of the card's text and survives that.
    handled = set()  # type: Set[str]
    while summary.shared < limit:
        listing_url = driver.current_url

        role = None  # type: Optional[EarlyAccessRole]
        ledger_failed = False
        for candidate in roles:
            if candidate.role_key in handled:
                continue
            try:
                if ledger.has_shared_interest(candidate.role_key):
                    summary.already_shared += 1
                    handled.add(candidate.role_key)
                    continue
            except sqlite3.Error:
                logger.exception("Ledger lookup failed for %s", candidate.describe())
                summary.aborted_reason = "ledger lookup failed"
                ledger_failed = True
                break
            role = candidate
            break
        if ledger_failed or role is None:
            break
        handled.add(role.role_key)

        button = _share_button(driver, role.index)
        if button is None:
            logger.info("%s is already shared on Naukri's side.", role.describe())
            summary.already_shared += 1
            continue

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'})", button
            )
            human_pause(*SHARE_PAUSE)
            button.click()
        except ElementClickInterceptedException as exc:
            logger.warning("Share button for %s was blocked: %s", role.describe(), exc)
            summary.failed += 1
            summary.aborted_reason = "share button was not clickable"
            break
        except (StaleElementReferenceException, NoSuchElementException) as exc:
            logger.warning("Share button for %s went stale: %s", role.describe(), exc)
            summary.failed += 1
            summary.aborted_reason = "page changed under us"
            break
        except WebDriverException as exc:
            logger.warning("Could not click share for %s: %s", role.describe(), exc)
            summary.failed += 1
            summary.aborted_reason = "click failed"
            break

        ok, kind, detail = _share_outcome(driver, role.index, listing_url)
        if not ok:
            logger.warning("Not counting %s: %s", role.describe(), detail)
            summary.failed += 1
            summary.aborted_reason = "share was not confirmed: %s" % detail
            break

        try:
            ledger.record_interest_share(
                role.role_key,
                title=role.title,
                company=role.company,
                experience=role.experience,
                location=role.location,
                posted_label=role.posted_label,
            )
        except sqlite3.Error:
            logger.exception("Could not record the share for %s", role.describe())
            summary.aborted_reason = "could not record the share"
            break

        summary.shared += 1
        logger.info("Shared interest: %s (%s)", role.describe(), detail)

        if kind == "navigated":
            if not open_page(driver, settings):
                summary.aborted_reason = "could not return to the early access listing"
                break
            roles = collect_roles(driver)

        human_pause(*SHARE_PAUSE)

    summary.skipped += sum(1 for role in roles if role.role_key not in handled)
    return summary


__all__ = [
    "EarlyAccessRole",
    "EarlyAccessSummary",
    "collect_roles",
    "open_page",
    "role_key",
    "share_all",
]
