"""Keyword collection must give up when the search page itself is failing.

On 28 September Naukri's /jobs-in-india search returned an error page to
logged-in users in an ordinary browser. Every search therefore waited its full
render timeout and returned nothing, and with 21 keywords the run was on course
to spend about fourteen minutes requesting a page that could not work. The
recommended feed was unaffected, so the run looked healthy apart from a growing
column of identical warnings.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import sources
from common.models import JobPosting, Settings


def _settings(max_empty=3, **overrides):
    values = dict(
        email="t@example.com",
        password="secret",
        max_empty_searches=max_empty,
        max_candidates=900,
        pages_per_keyword=2,
    )
    values.update(overrides)
    return Settings(**values)


KEYWORDS = ["k%02d" % i for i in range(21)]


@pytest.fixture
def fake_sources(monkeypatch):
    """Record which keywords were searched; the recommended feed returns nothing."""
    searched = []

    monkeypatch.setattr(sources, "RECOMMENDED_TABS", [])

    def _install(results_for):
        def _search(
            driver, keyword, location="", pages=1, sort_by_date=True, experience=0
        ):
            searched.append(keyword)
            return results_for(keyword)

        monkeypatch.setattr(sources, "collect_from_search", _search)

    return _install, searched


def _job(jid):
    return JobPosting(job_id=jid, url="u/%s" % jid, title="t", company="c")


def test_search_is_abandoned_after_three_empty_results(fake_sources):
    """The 28 September outage: every search returns nothing."""
    install, searched = fake_sources
    install(lambda keyword: [])

    sources.collect_candidates(object(), _settings(), KEYWORDS)

    assert len(searched) == 3, (
        "kept searching a failing endpoint: %d of 21 keywords attempted" % len(searched)
    )


def test_a_genuinely_empty_keyword_does_not_abandon_the_rest(fake_sources):
    """One or two keywords with no matches is normal and must not stop collection."""
    install, searched = fake_sources
    empty = {"k00", "k05", "k06"}  # never 3 in a row
    install(lambda keyword: [] if keyword in empty else [_job(keyword)])

    result = sources.collect_candidates(object(), _settings(), KEYWORDS)

    assert len(searched) == 21, "stopped early on scattered empty keywords"
    assert len(result) == 18


def test_the_streak_resets_on_a_successful_search(fake_sources):
    install, searched = fake_sources
    # two empty, one hit, then a full run of empties
    def _results(keyword):
        index = KEYWORDS.index(keyword)
        return [] if index != 2 else [_job(keyword)]

    install(_results)

    sources.collect_candidates(object(), _settings(), KEYWORDS)

    # k00,k01 empty -> k02 hit resets -> k03,k04,k05 empty -> abandon
    assert len(searched) == 6


def test_zero_disables_the_guard(fake_sources):
    install, searched = fake_sources
    install(lambda keyword: [])

    sources.collect_candidates(object(), _settings(max_empty=0), KEYWORDS)

    assert len(searched) == 21


def test_candidates_collected_before_the_outage_are_kept(fake_sources):
    """Abandoning search must not discard what the working keywords found."""
    install, searched = fake_sources
    good = {"k00", "k01"}
    install(lambda keyword: [_job(keyword)] if keyword in good else [])

    result = sources.collect_candidates(object(), _settings(), KEYWORDS)

    assert [j.job_id for j in result] == ["k00", "k01"]
    assert len(searched) == 5  # 2 hits, then 3 empties
