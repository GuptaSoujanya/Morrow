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


def _settings(max_days_old=3, fallback=3):
    return Settings(
        email="t@example.com",
        password="secret",
        max_days_old=max_days_old,
        max_days_old_fallback=fallback,
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


def test_the_wider_of_the_two_age_limits_is_used():
    """With the fallback tier enabled, its jobs must survive to be ranked."""
    jobs = [_job("fresh", 1), _job("fallback_age", 9), _job("beyond", 20)]
    kept, dropped = ranking.drop_stale_candidates(jobs, _settings(3, 14))
    assert [j.job_id for j in kept] == ["fresh", "fallback_age"]
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


def test_survivors_still_reach_the_same_tier_as_before():
    """The pre-filter must not remove anything select_for_application would keep.

    Both use the same limits, so any job the filter drops must also have been
    dropped by tiering. This pins the two together.
    """
    settings = _settings(3, 14)
    jobs = [_job("j%02d" % i, d) for i, d in
            enumerate([0, 1, 3, 4, 9, 14, 15, 30, None])]
    kept, _ = ranking.drop_stale_candidates(jobs, settings)
    kept_ids = {j.job_id for j in kept}

    for job in jobs:
        scored = ranking.ScoredJob(job=job, score=70.0)  # comfortably over min_score
        tier = ranking.tier_of(scored, settings)
        if job.job_id not in kept_ids:
            assert tier is None, (
                "%r (age %s) was filtered out but tiering would have kept it"
                % (job.job_id, job.posted_days_ago)
            )
