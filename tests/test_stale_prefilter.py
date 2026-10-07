"""Stale jobs must not consume the LLM ranking budget.

Age was only ever applied in select_for_application, which runs after ranking,
so every collected posting was scored and the old ones were then discarded. On
25 September that was 556 of 900. Because max_candidates is a hard cap, those
postings displaced fresher ones from the pool as well as wasting LLM calls.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import ranking
from naukri_bot.models import JobPosting, Settings


def _settings(max_days_old=3):
    return Settings(
        email="t@example.com",
        password="secret",
        max_days_old=max_days_old,
    )


def _job(jid, days):
    return JobPosting(job_id=jid, url="u/%s" % jid, title="t", company="c",
                      posted_days_ago=days)


def test_stale_jobs_are_dropped_before_ranking():
    jobs = [_job("fresh", 1), _job("edge", 3), _job("stale", 4), _job("ancient", 30)]
    kept, dropped = ranking.drop_stale_candidates(jobs, _settings())
    assert [j.job_id for j in kept] == ["fresh", "edge"]
    assert dropped == 2


def test_unknown_age_is_kept():
    """_tier_of treats an unknown age as fresh; dropping them would gut the pool."""
    jobs = [_job("unknown", None), _job("stale", 9)]
    kept, dropped = ranking.drop_stale_candidates(jobs, _settings())
    assert [j.job_id for j in kept] == ["unknown"]
    assert dropped == 1


def test_a_wider_max_days_old_keeps_more(jobs=None):
    """max_days_old is now the single age gate; there is no second limit."""
    jobs = [_job("fresh", 1), _job("nine", 9), _job("twenty", 20)]
    kept, dropped = ranking.drop_stale_candidates(jobs, _settings(14))
    assert [j.job_id for j in kept] == ["fresh", "nine"]
    assert dropped == 1


def test_nothing_is_dropped_when_all_are_fresh():
    jobs = [_job("a", 0), _job("b", 1), _job("c", None)]
    kept, dropped = ranking.drop_stale_candidates(jobs, _settings())
    assert len(kept) == 3
    assert dropped == 0


def test_the_filter_does_not_change_order():
    """rank() and prefilter rely on the incoming order; this must be pass-through."""
    jobs = [_job("a", 1), _job("old", 9), _job("b", 2), _job("c", None)]
    kept, _ = ranking.drop_stale_candidates(jobs, _settings())
    assert [j.job_id for j in kept] == ["a", "b", "c"]


def test_the_filter_never_removes_what_selection_would_keep():
    """The pre-filter and selection must use the same age rule.

    Both read max_days_old, so anything the filter drops must also have been
    rejected by selection. This pins the two together so they cannot drift.
    """
    settings = _settings(4)
    jobs = [_job("j%02d" % i, d) for i, d in
            enumerate([0, 1, 3, 4, 5, 9, 14, 20, None])]
    kept_ids = {j.job_id for j in ranking.drop_stale_candidates(jobs, settings)[0]}

    scored = [ranking.ScoredJob(job=job, score=70.0) for job in jobs]
    selected_ids = {
        c.job.job_id
        for c in ranking.select_for_application(scored, settings, lambda jid: False)
    }
    assert selected_ids <= kept_ids, (
        "selection kept %s which the pre-filter had already dropped"
        % (selected_ids - kept_ids)
    )


def test_selection_orders_by_score_even_if_given_unsorted_input():
    """The queue must be best-first regardless of the order it arrives in.

    rank() happens to return score-sorted candidates, so without this the sort
    in select_for_application is never exercised and could be removed unnoticed.
    """
    settings = _settings(4)
    scores = [55.0, 80.0, 61.0, 72.0, 58.0]
    scored = [
        ranking.ScoredJob(
            job=_job("j%d" % i, 1),
            score=score,
        )
        for i, score in enumerate(scores)
    ]
    selected = ranking.select_for_application(scored, settings, lambda jid: False)
    got = [c.score for c in selected]
    assert got == sorted(scores, reverse=True), "not ordered best first: %s" % got
