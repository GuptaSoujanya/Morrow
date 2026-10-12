"""Searches ask Naukri for jobs matching the candidate's experience.

Measured on 8 October: /jobs-in-india?k=AI Engineer&sort=f&experience=3 returned
13 of 20 cards whose range covers 3 years, because the query endpoint redirects
to the canonical slug and drops the filter on the way. Requesting the slug
directly, /ai-engineer-jobs?k=ai engineer&sort=f&experience=3, returned 20 of 20
for the same page load.

Slug landing pages only exist for terms Naukri curates, and a missing one serves
an empty results page rather than a 404 - which is why an earlier attempt at
slug URLs was reverted: niche keywords silently returned nothing. So the
fallback to the query endpoint is the point of these tests, not a detail.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import sources
from common.models import JobPosting, Settings


CARD = """
<div class="srp-jobtuple-wrapper">
  <h2><a class="title" href="/job-listings-%(jid)s">AI Engineer</a></h2>
  <a class="comp-name">Acme</a>
  <span class="expwdth">2-4 Yrs</span>
  <span class="job-post-day">1 Day Ago</span>
</div>
"""


def _page(cards):
    return "<html><body>%s</body></html>" % "".join(
        CARD % {"jid": "%d" % n} for n in cards
    )


class _Driver:
    """Enough of a driver for _collect_pages: it serves pages by URL."""

    def __init__(self, pages_by_url, default=""):
        self.pages_by_url = pages_by_url
        self.default = default
        self.requested = []
        self.page_source = ""

    def get(self, url):
        self.requested.append(url)
        self.page_source = self.pages_by_url.get(url, self.default)


@pytest.fixture
def no_wait(monkeypatch):
    """Cards are present the moment the page is served, so skip the render wait."""

    class _Wait:
        def __init__(self, driver, timeout):
            pass

        def until(self, condition):
            return True

    monkeypatch.setattr(sources, "WebDriverWait", _Wait)
    monkeypatch.setattr(sources, "human_pause", lambda *a, **k: None)
    monkeypatch.setattr(sources, "safe_get", lambda driver, url: bool(driver.get(url) or True))


SLUG_P1 = (
    "https://www.naukri.com/ai-engineer-jobs"
    "?k=ai%20engineer&sort=f&experience=3"
)
# The page number goes in the path. ?pageNo=2 is redirected to this path with
# the query string discarded, which cost nothing visible in the log -- the
# requested URL still read "sort=f&experience=3" -- while page 2 came back
# unfiltered: 0 of 20 cards covering 3 years against 20 of 20 on page 1.
SLUG_P2 = (
    "https://www.naukri.com/ai-engineer-jobs-2"
    "?k=ai%20engineer&sort=f&experience=3"
)
QUERY_P1 = (
    "https://www.naukri.com/ai-engineer-jobs-in-india?k=AI%20Engineer&sort=f"
)
QUERY_P2 = (
    "https://www.naukri.com/ai-engineer-jobs-in-india-2?k=AI%20Engineer&sort=f"
)


def test_the_fallback_endpoint_keeps_its_sort_on_every_page():
    """/jobs-in-india?k=... is redirected and loses sort=f, page 1 included.

    Measured on Machine Learning Engineer: the query form gave 6 of 20 cards
    within 4 days and a 21-day-old oldest card, the path form 20 of 20 posted
    today, and the same on pages 2 and 3.
    """
    assert sources._search_url("AI Engineer", "", 1, True) == QUERY_P1
    assert sources._search_url("AI Engineer", "", 2, True) == QUERY_P2
    assert "pageNo" not in sources._search_url("AI Engineer", "", 2, True)
    assert sources._search_url("AI Engineer", "", 3, True).startswith(
        "https://www.naukri.com/ai-engineer-jobs-in-india-3?"
    )


def test_a_keyword_with_no_sluggable_characters_still_searches():
    """"++" has no path to build from, so take the redirect over "/-jobs-in-india"."""
    url = sources._search_url("++", "", 2, True)

    assert url.startswith("https://www.naukri.com/jobs-in-india?")
    assert "pageNo=2" in url


def test_the_filter_only_goes_on_the_slug_url():
    """The query endpoint drops `experience`, so putting it there is misleading."""
    assert "experience=3" in sources._slug_search_url("AI Engineer", "", 1, True, 3)
    assert "experience" not in sources._search_url("AI Engineer", "", 1, True)


def test_the_slug_url_is_the_one_measured_to_work():
    assert sources._slug_search_url("AI Engineer", "", 1, True, 3) == SLUG_P1


def test_the_page_number_goes_in_the_path_not_the_query():
    """?pageNo= is redirected to the path form and the filter is lost with it."""
    url = sources._slug_search_url("AI Engineer", "", 2, True, 3)

    assert url == SLUG_P2
    assert "pageNo" not in url
    assert sources._slug_search_url("AI Engineer", "", 3, True, 3).startswith(
        "https://www.naukri.com/ai-engineer-jobs-3?"
    )


def test_page_one_has_no_page_suffix():
    """/ai-engineer-jobs-1 is not a page Naukri serves."""
    assert "-jobs?" in sources._slug_search_url("AI Engineer", "", 1, True, 3)


def test_every_page_of_a_keyword_stays_filtered(no_wait):
    """Page 2 onwards must carry the filter too, or most results are unfiltered."""
    driver = _Driver({SLUG_P1: _page([1, 2]), SLUG_P2: _page([3, 4])})

    jobs = sources.collect_from_search(
        driver, "AI Engineer", pages=2, experience=3
    )

    assert driver.requested == [SLUG_P1, SLUG_P2]
    assert len(jobs) == 4
    assert all("experience=3" in url for url in driver.requested)


def test_a_keyword_with_no_slug_page_falls_back_instead_of_vanishing(no_wait):
    """The failure that had slug URLs reverted: zero cards, no error, keyword lost."""
    driver = _Driver({QUERY_P1: _page([1, 2, 3])}, default="<html><body></body></html>")

    jobs = sources.collect_from_search(
        driver, "AI Engineer", pages=1, experience=3
    )

    assert driver.requested == [SLUG_P1, QUERY_P1]
    assert [job.job_id for job in jobs] == [
        sources.job_id_from_url("/job-listings-%d" % n) for n in (1, 2, 3)
    ]


def test_a_working_slug_is_not_searched_twice(no_wait):
    """Falling back after a successful slug would double every keyword's traffic."""
    driver = _Driver({SLUG_P1: _page([1])})

    sources.collect_from_search(driver, "AI Engineer", pages=1, experience=3)

    assert QUERY_P1 not in driver.requested


def test_zero_experience_uses_the_query_endpoint(no_wait):
    """Unset means unfiltered: no slug request, so no slug-404 risk at all."""
    driver = _Driver({QUERY_P1: _page([1])})

    sources.collect_from_search(driver, "AI Engineer", pages=1, experience=0)

    assert driver.requested == [QUERY_P1]


def test_collect_candidates_passes_the_configured_experience(monkeypatch):
    """The setting is dead weight unless the collection loop forwards it."""
    seen = {}

    def _search(driver, keyword, location="", pages=1, sort_by_date=True, experience=0):
        seen[keyword] = experience
        return [JobPosting(job_id=keyword, url="u", title="t", company="c")]

    monkeypatch.setattr(sources, "RECOMMENDED_TABS", [])
    monkeypatch.setattr(sources, "collect_from_search", _search)

    settings = Settings(
        email="t@example.com",
        password="secret",
        search_experience_years=3,
        pages_per_keyword=2,
        max_candidates=50,
    )
    sources.collect_candidates(object(), settings, ["AI Engineer"])

    assert seen == {"AI Engineer": 3}
