"""Collect job candidates from Naukri search and recommended feeds."""

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlencode, urlsplit

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common.browser import human_pause, safe_get
from common.models import JobPosting, Settings


logger = logging.getLogger(__name__)

_SEARCH_CARD_SELECTORS = (
    "div.srp-jobtuple-wrapper",
    "div.cust-job-tuple",
    "article.jobTuple",
)
_RECOMMENDED_CARD_SELECTORS = (
    "div.srp-jobtuple-wrapper",
    "div.cust-job-tuple",
    "[class*='job-tuple']",
    ".recommended-jobs-list > div",
    "article.jobTuple",
)


def job_id_from_url(url: str) -> str:
    """Return a stable job identifier derived from a Naukri URL."""
    path = unquote(urlsplit(url).path)
    normalised_path = re.sub(r"/+", "/", path).rstrip("/") or "/"
    numeric_id = re.search(r"(?:-|/)(\d+)$", normalised_path)
    if numeric_id:
        return numeric_id.group(1)
    return hashlib.sha1(normalised_path.encode("utf-8")).hexdigest()[:16]


def parse_posted_days(label: str) -> Optional[float]:
    """Translate a recognised Naukri freshness label to days."""
    value = " ".join(label.strip().lower().split())
    if not value:
        return None
    if value in ("just now", "few hours ago", "today"):
        return 0.0

    day_match = re.fullmatch(r"(\d+)\+? days? ago", value)
    if day_match:
        return float(day_match.group(1))

    week_match = re.fullmatch(r"(\d+)\+? weeks? ago", value)
    if week_match:
        return float(int(week_match.group(1)) * 7)

    month_match = re.fullmatch(r"(\d+)\+? months? ago", value)
    if month_match:
        return float(int(month_match.group(1)) * 30)

    if value in ("a month ago", "a week ago"):
        return 30.0 if "month" in value else 7.0
    return None


def _first(card: Any, selectors: Tuple[str, ...], field: str) -> Optional[Any]:
    for selector in selectors:
        try:
            element = card.select_one(selector)
        except AttributeError as exc:
            logger.debug("Could not parse %s with %s: %s", field, selector, exc)
            continue
        if element is not None:
            return element
    return None


def _text(card: Any, selectors: Tuple[str, ...], field: str) -> str:
    element = _first(card, selectors, field)
    if element is None:
        return ""
    try:
        return element.get_text(" ", strip=True)
    except AttributeError as exc:
        logger.debug("Could not read %s text: %s", field, exc)
        return ""


def _tags(card: Any, selector: str = "ul.tags-gt li") -> List[str]:
    try:
        elements = card.select(selector)
    except AttributeError as exc:
        logger.debug("Could not parse tags: %s", exc)
        return []

    tags: List[str] = []
    for element in elements:
        try:
            text = element.get_text(" ", strip=True)
        except AttributeError as exc:
            logger.debug("Could not read a tag: %s", exc)
            continue
        if text:
            tags.append(text)
    return tags


def _parse_cards(cards: List[Any], source: str) -> List[JobPosting]:
    jobs: List[JobPosting] = []
    missing_title = 0
    missing_href = 0
    for index, card in enumerate(cards, 1):
        title_link = _first(card, ("h2 a.title", "a.title"), "title link")
        title = ""
        href = ""
        if title_link is not None:
            try:
                title = title_link.get_text(" ", strip=True)
            except AttributeError as exc:
                logger.debug("Could not read title on card %d: %s", index, exc)
            try:
                href = title_link.get("href", "") or ""
            except AttributeError as exc:
                logger.debug("Could not read href on card %d: %s", index, exc)
        if not title:
            missing_title += 1
            logger.debug("Skipping %s card %d: title is missing", source, index)
            continue
        if not href:
            missing_href += 1
            logger.debug("Skipping %s card %d: href is missing", source, index)
            continue
        if href.startswith("/"):
            href = "https://www.naukri.com" + href

        posted_label = _text(
            card, ("span.job-post-day", "[class*='job-post-day']"), "posted label"
        )
        jobs.append(
            JobPosting(
                job_id=job_id_from_url(href),
                url=href,
                title=title,
                company=_text(card, ("a.comp-name", "[class*='comp-name']"), "company"),
                experience=_text(card, ("span.expwdth", "[class*='exp']"), "experience"),
                salary=_text(card, ("span.sal", "[class*='sal']"), "salary"),
                location=_text(card, ("span.locWdth", "[class*='loc']"), "location"),
                description=_text(
                    card, ("span.job-desc", "[class*='job-desc']"), "description"
                ),
                tags=_tags(card),
                posted_label=posted_label,
                posted_days_ago=parse_posted_days(posted_label),
                source=source,
            )
        )
    if missing_title or missing_href:
        logger.warning(
            "%s: dropped %d of %d cards (%d without a title, %d without a job "
            "URL). If this is every card, Naukri's card markup has changed.",
            source,
            missing_title + missing_href,
            len(cards),
            missing_title,
            missing_href,
        )
    return jobs


def _parse_recommended_cards(cards: List[Any], source: str) -> List[JobPosting]:
    """Parse the legacy ``article.jobTuple`` cards used by the recommended feed.

    These cards carry no anchor at all: the title is a ``<p>`` and the only
    href points off-site to AmbitionBox.  The job id lives on the article as
    ``data-job-id``, and ``/job-listings-<id>`` resolves without the usual
    slug, so the URL is constructed rather than read.
    """
    jobs: List[JobPosting] = []
    missing_id = 0
    missing_title = 0
    for index, card in enumerate(cards, 1):
        job_id = ""
        try:
            job_id = (card.get("data-job-id", "") or "").strip()
        except AttributeError as exc:
            logger.debug("Could not read data-job-id on card %d: %s", index, exc)
        if not job_id:
            missing_id += 1
            continue

        title = _text(card, ("p.title", "[class*='title']"), "title")
        if not title:
            missing_title += 1
            continue

        posted_label = _text(
            card,
            (
                "div.jobTupleFooter span.fw500",
                "div.type.plcHolder span",
                "[class*='plcHolder'] span",
            ),
            "posted label",
        )
        jobs.append(
            JobPosting(
                job_id=job_id,
                url="https://www.naukri.com/job-listings-%s" % job_id,
                title=title,
                company=_text(card, ("span.subTitle", "[class*='subTitle']"), "company"),
                experience=_text(card, ("li.experience span",), "experience"),
                salary=_text(card, ("li.salary span",), "salary"),
                location=_text(card, ("li.location span",), "location"),
                description=_text(
                    card, ("div.job-description span", "div.job-description"), "description"
                ),
                tags=_tags(card, "ul.tags li"),
                posted_label=posted_label,
                posted_days_ago=parse_posted_days(posted_label),
                source=source,
            )
        )
    if missing_id or missing_title:
        logger.warning(
            "%s: dropped %d of %d cards (%d without a job id, %d without a "
            "title). If this is every card, Naukri's card markup has changed.",
            source,
            missing_id + missing_title,
            len(cards),
            missing_id,
            missing_title,
        )
    return jobs


def _matching_cards(soup: BeautifulSoup, selectors: Tuple[str, ...]) -> Tuple[List[Any], str]:
    for selector in selectors:
        cards = list(soup.select(selector))
        if cards:
            return cards, selector
    return [], selectors[-1]


def _slug_search_url(
    keyword: str, location: str, page: int, sort_by_date: bool, experience: int
) -> str:
    """Build the slug search URL, which is the only one honouring `experience`.

    /jobs-in-india?k=... ignores an experience parameter: Naukri redirects it to
    the canonical slug and drops the filter on the way. Requesting the slug
    directly keeps it, and the filter is worth having -- unfiltered pages
    returned 40-70% of cards with a range covering the candidate's experience,
    filtered ones about 100%.

    Slug pages only exist for terms Naukri has a landing page for, and a missing
    one serves an empty results page rather than a 404, so the caller must treat
    zero cards on the first page as "try the query endpoint instead".

    The page number goes in the path, as `-jobs-2`, because `?pageNo=2` is
    redirected to that path with the whole query string discarded -- so page 2
    arrived unfiltered and relevance-sorted while the requested URL still read
    correctly in the log. Measured on /machine-learning-engineer-jobs, page 2:
    `?pageNo=2` gave 0 of 20 cards covering 3 years and ages of 3-7 days, the
    path form 20 of 20 and every card posted today.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.casefold()).strip("-")
    path = "%s-jobs" % slug if page <= 1 else "%s-jobs-%d" % (slug, page)
    params = [("k", keyword.casefold())]
    if location:
        params.append(("l", location))
    if sort_by_date:
        params.append(("sort", "f"))
    if experience > 0:
        params.append(("experience", str(experience)))
    return "https://www.naukri.com/%s?%s" % (
        path,
        urlencode(params, quote_via=quote),
    )


def _search_url(keyword: str, location: str, page: int, sort_by_date: bool) -> str:
    """Build a Naukri search URL for keywords with no slug landing page.

    An earlier version built SEO slug paths like ``/llm-engineer-jobs``.  Those
    landing pages only exist for a curated set of popular terms, so niche
    keywords 404 - and a 404 still loads cleanly in Selenium, which means the
    only visible symptom is "zero cards".  ``/jobs-in-india?k=...`` is the real
    search endpoint; Naukri server-redirects it to whatever slug it considers
    canonical for that keyword.

    That redirect is the problem: it discards the query string, taking `sort=f`
    with it, so this endpoint was never date-sorted on any page -- not just the
    paged ones. Requesting the redirect target directly, `/<slug>-jobs-in-india`
    with the page number in the path, keeps it. Measured on Machine Learning
    Engineer: `?k=...&sort=f` gave 6 of 20 cards within 4 days and a 21-day-old
    oldest, the path form 20 of 20 with everything posted today, and the same
    on pages 2 and 3.

    Unlike `/<slug>-jobs`, this path is generated from the keyword rather than
    curated, so an invented keyword still returns its handful of matches. Pages
    past the last one wrap back to page 1, which the caller deduplicates by job
    id.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.casefold()).strip("-")
    params = [("k", keyword)]
    if location:
        params.append(("l", location))
    if sort_by_date:
        params.append(("sort", "f"))
    if not slug:
        # Nothing to build a path from, so accept the redirect and its dropped
        # sort rather than requesting "/-jobs-in-india".
        if page > 1:
            params.append(("pageNo", str(page)))
        return "https://www.naukri.com/jobs-in-india?%s" % urlencode(
            params, quote_via=quote
        )
    path = "%s-jobs-in-india" % slug
    if page > 1:
        path = "%s-%d" % (path, page)
    return "https://www.naukri.com/%s?%s" % (path, urlencode(params, quote_via=quote))


def collect_from_search(
    driver, keyword: str, location: str = "", pages: int = 3,
    sort_by_date: bool = True, experience: int = 0
) -> List[JobPosting]:
    """Collect job cards from date-sorted Naukri search pages.

    With `experience` set, the slug endpoint is tried first because it is the
    only one that applies the filter. A slug Naukri has no landing page for
    serves an empty results page rather than an error, so finding nothing on the
    first page falls back to the query endpoint for that keyword rather than
    silently losing it -- the failure that had this approach reverted before.
    """
    if experience > 0:
        jobs = _collect_pages(
            driver, keyword, location, pages, sort_by_date, experience, slug=True
        )
        if jobs:
            return jobs
        logger.info(
            "No cards from the filtered slug for %r; falling back to the query "
            "endpoint without the experience filter",
            keyword,
        )
    return _collect_pages(
        driver, keyword, location, pages, sort_by_date, 0, slug=False
    )


def _collect_pages(
    driver, keyword: str, location: str, pages: int, sort_by_date: bool,
    experience: int, slug: bool
) -> List[JobPosting]:
    jobs: List[JobPosting] = []
    for page in range(1, max(0, pages) + 1):
        url = (
            _slug_search_url(keyword, location, page, sort_by_date, experience)
            if slug
            else _search_url(keyword, location, page, sort_by_date)
        )
        if page > 1:
            human_pause()
        try:
            if not safe_get(driver, url):
                logger.warning("Could not navigate to search page %s", url)
                break
            # Naukri renders search results client-side.  driver.get() returns
            # as soon as the shell document is ready, so reading page_source
            # right away finds an empty results container - which is
            # indistinguishable from "this search has no matches".  Wait for a
            # card to actually exist before parsing.
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ", ".join(_SEARCH_CARD_SELECTORS))
                    )
                )
            except TimeoutException:
                logger.warning(
                    "No job cards rendered within 20s on %s - either this search "
                    "genuinely has no matches, or the card markup changed.",
                    url,
                )
                break
            soup = BeautifulSoup(driver.page_source, "html5lib")
        except TimeoutException as exc:
            logger.warning("Timed out loading search page %s: %s", url, exc)
            break
        except WebDriverException as exc:
            logger.warning("WebDriver failed on search page %s: %s", url, exc)
            break
        except AttributeError as exc:
            logger.warning("Could not read search page %s: %s", url, exc)
            break

        cards, selector = _matching_cards(soup, _SEARCH_CARD_SELECTORS)
        if not cards:
            logger.warning("Search page yielded zero cards: %s", url)
            break
        logger.info("Search page %s matched %s (%d cards)", url, selector, len(cards))
        jobs.extend(_parse_cards(cards, "search:%s" % keyword))
    return jobs


def _active_tab_id(driver) -> str:
    selectors = ".tab-list-item.active, .tab-list-item[aria-selected='true']"
    try:
        active = driver.find_elements(By.CSS_SELECTOR, selectors)
        if not active:
            return "default (unidentified)"
        tab_id = driver.execute_script(
            "var n=arguments[0]; while(n && !n.id){n=n.parentElement;} return n && n.id;",
            active[0],
        )
        return str(tab_id) if tab_id else "default (unidentified)"
    except (WebDriverException, AttributeError) as exc:
        logger.warning("Could not identify the active recommended tab: %s", exc)
        return "default (unidentified)"


RECOMMENDED_PATH = "/mnjuser/recommendedjobs"
RECOMMENDED_URL = "https://www.naukri.com" + RECOMMENDED_PATH
RECOMMENDED_HOMEPAGE = "https://www.naukri.com/mnjuser/homepage"
RECOMMENDED_TABS = ("profile", "top_candidate", "apply", "preference", "similar_jobs")


def _current_url(driver) -> str:
    try:
        return driver.current_url or ""
    except WebDriverException as exc:
        logger.debug("Could not read the current URL: %s", exc)
        return ""


def _reach_recommended(driver, attempts: int = 2) -> bool:
    """Land on the recommended-jobs listing, warming the session first.

    Navigating straight there immediately after login bounces to the homepage,
    where the dashboard strip shows Early Access cards that carry no job link.
    Loading the homepage first and then navigating avoids that.
    """
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        if not safe_get(driver, RECOMMENDED_HOMEPAGE):
            logger.warning("Could not load the Naukri homepage; recommended jobs skipped.")
            return False
        human_pause()
        if not safe_get(driver, RECOMMENDED_URL):
            logger.warning("Could not navigate to recommended jobs at %s", RECOMMENDED_URL)
            return False
        if RECOMMENDED_PATH in _current_url(driver):
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".tab-list"))
                )
            except TimeoutException:
                logger.warning("Recommended jobs loaded but showed no tab list within 20s.")
                return False
            return True
        logger.info(
            "Recommended jobs bounced to %s on attempt %d of %d.",
            _current_url(driver),
            attempt,
            total,
        )
        human_pause()
    logger.warning("Recommended jobs kept redirecting away; skipping that source.")
    return False


def collect_from_recommended(
    driver, tab_id: str = "top_candidate", max_pages: int = 3
) -> List[JobPosting]:
    """Collect cards from a recommended-jobs tab, including lazy-loaded cards.

    Staying on the listing between tabs matters: re-navigating for each tab
    would pay the homepage warm-up five times over.
    """
    if RECOMMENDED_PATH not in _current_url(driver) and not _reach_recommended(driver):
        return []

    requested_selector = "div#%s .tab-list-item" % tab_id
    try:
        requested_tabs = driver.find_elements(By.CSS_SELECTOR, requested_selector)
        if requested_tabs:
            requested_tabs[0].click()
            human_pause()
        else:
            logger.warning(
                "Recommended tab %s was not found; continuing on active tab %s",
                tab_id,
                _active_tab_id(driver),
            )
    except (WebDriverException, AttributeError) as exc:
        logger.warning(
            "Could not activate recommended tab %s; continuing on active tab %s: %s",
            tab_id,
            _active_tab_id(driver),
            exc,
        )
    logger.info("Recommended feed active tab: %s (requested: %s)", _active_tab_id(driver), tab_id)

    latest_cards: List[Any] = []
    try:
        soup = BeautifulSoup(driver.page_source, "html5lib")
        latest_cards, selector = _matching_cards(soup, _RECOMMENDED_CARD_SELECTORS)
        logger.info("Recommended selector %s matched %d cards", selector, len(latest_cards))
        previous_count = len(latest_cards)
        for _ in range(max(0, max_pages)):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            human_pause()
            soup = BeautifulSoup(driver.page_source, "html5lib")
            cards, selector = _matching_cards(soup, _RECOMMENDED_CARD_SELECTORS)
            logger.info("Recommended selector %s matched %d cards", selector, len(cards))
            if len(cards) <= previous_count:
                break
            latest_cards = cards
            previous_count = len(cards)
    except TimeoutException as exc:
        logger.warning("Timed out while loading recommended cards: %s", exc)
    except WebDriverException as exc:
        logger.warning("WebDriver failed while loading recommended cards: %s", exc)
    except AttributeError as exc:
        logger.warning("Could not parse recommended cards: %s", exc)

    parsed = _parse_recommended_cards(latest_cards, "recommended:%s" % tab_id)
    if latest_cards and not parsed:
        logger.warning(
            "Recommended tab %s yielded %d cards but no usable postings. The "
            "cards should carry a data-job-id; if none do, either we landed on "
            "the homepage dashboard strip instead of the listing, or Naukri's "
            "card markup has changed.",
            tab_id,
            len(latest_cards),
        )
    return parsed


def collect_candidates(
    driver, settings: Settings, keywords: List[str], location: str = ""
) -> List[JobPosting]:
    """Collect and first-seen deduplicate recommended and search candidates."""
    result: List[JobPosting] = []
    seen = set()
    breakdown: Dict[str, int] = {}

    def add_unique(jobs: List[JobPosting], source: str) -> None:
        breakdown.setdefault(source, 0)
        for job in jobs:
            if len(result) >= settings.max_candidates:
                return
            if job.job_id in seen:
                continue
            seen.add(job.job_id)
            result.append(job)
            breakdown[job.source] = breakdown.get(job.source, 0) + 1

    for tab_id in RECOMMENDED_TABS:
        if len(result) >= settings.max_candidates:
            break
        add_unique(
            collect_from_recommended(driver, tab_id=tab_id),
            "recommended:%s" % tab_id,
        )
    consecutive_empty = 0
    for keyword in keywords:
        if len(result) >= settings.max_candidates:
            break
        search_source = "search:%s" % keyword
        found = collect_from_search(
            driver,
            keyword,
            location=location,
            pages=settings.pages_per_keyword,
            sort_by_date=True,
            experience=settings.search_experience_years,
        )
        add_unique(found, search_source)

        # A search that returns nothing waits the full render timeout first, so
        # when the search page itself is failing every keyword costs that timeout
        # and yields nothing. Naukri's search broke for logged-in users on
        # 28 September and the run was on course to spend fourteen minutes
        # requesting a page that was returning an error to everyone.
        if found:
            consecutive_empty = 0
            continue
        consecutive_empty += 1
        if 0 < settings.max_empty_searches <= consecutive_empty:
            logger.warning(
                "Abandoning keyword search: %d searches in a row returned no "
                "jobs, so the search page is most likely failing rather than "
                "every keyword genuinely having no matches. Continuing with the "
                "%d candidates already collected.",
                consecutive_empty,
                len(result),
            )
            break

    for source, count in breakdown.items():
        logger.info("Candidate source %s contributed %d unique jobs", source, count)
    return result


__all__ = [
    "collect_candidates",
    "collect_from_recommended",
    "collect_from_search",
    "job_id_from_url",
    "parse_posted_days",
]
