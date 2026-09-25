"""A run must not apply to jobs the LLM never ranked.

On 25 September the Claude CLI was found at startup and reported missing six
minutes later in the same process. Ranking fell back to the lexical formula,
re-scored 900 jobs in one second, and 28 of them cleared MIN_SCORE=55 where a
blended ranking had produced 124 the week before. The run then began applying.

A lexical score and 0.4*lexical + 0.6*llm are different quantities, so the
user's score bar silently came to mean something else. The root cause was never
identified, which is exactly why the guard is on coverage rather than on any
particular failure.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import apply as apply_module
from naukri_bot import auth, browser, cli, llm, ranking, sources
from naukri_bot.models import (
    ApplyResult,
    ApplyStatus,
    JobPosting,
    LoginResult,
    Profile,
    ScoredJob,
    Settings,
)


def _settings(**overrides):
    values = dict(
        email="t@example.com",
        password="secret",
        target_applications=50,
        min_score=55.0,
        max_days_old=3,
        min_score_floor=0.0,
        max_days_old_fallback=3,
        min_llm_rank_coverage=0.5,
        dry_run=False,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    attempted = []

    class _Client:
        def available(self):
            return True

    monkeypatch.setattr(llm, "build_client", lambda settings: _Client())
    monkeypatch.setattr(browser, "create_driver", lambda settings: object())
    monkeypatch.setattr(
        auth, "login", lambda driver, settings: LoginResult(ok=True, reason="verified")
    )

    def _install(rated_fraction):
        """Build 20 eligible jobs, a share of which carry an LLM score."""
        queue = []
        for index in range(20):
            scored = ScoredJob(
                job=JobPosting(
                    job_id="j%02d" % index,
                    url="https://www.naukri.com/job-listings-j%02d" % index,
                    title="Role",
                    company="Co %d" % index,
                    posted_days_ago=1,
                ),
                score=70.0,
            )
            if index < int(20 * rated_fraction):
                scored.llm_score = 70.0
            queue.append(scored)

        monkeypatch.setattr(sources, "collect_candidates",
                            lambda *a, **k: [s.job for s in queue])
        monkeypatch.setattr(ranking, "rank", lambda *a, **k: list(queue))

        def _apply(driver, job, profile, engine, settings):
            attempted.append(job.job_id)
            return ApplyResult(
                job_id=job.job_id, url=job.url,
                status=ApplyStatus.APPLIED, quota_consumed=True,
            )

        monkeypatch.setattr(apply_module, "apply_to_job", _apply)

    return _install, attempted


def _run(tmp_path, settings):
    settings.db_path = str(tmp_path / "t.db")
    return cli.run(settings, Profile(full_name="T"))


def test_no_llm_scores_at_all_sends_nothing(harness, tmp_path):
    """The 25 September failure: ranking wholly lexical."""
    install, attempted = harness
    install(0.0)

    summary = _run(tmp_path, _settings())

    assert attempted == [], "applied to jobs that were never LLM-ranked"
    assert summary.applied == 0


def test_partial_llm_outage_below_threshold_sends_nothing(harness, tmp_path):
    install, attempted = harness
    install(0.2)  # 20% covered, threshold 50%

    _run(tmp_path, _settings())

    assert attempted == []


def test_healthy_ranking_proceeds(harness, tmp_path):
    """A few timed-out batches must not stop a run: 17 Sep ran at ~97%."""
    install, attempted = harness
    install(0.95)

    summary = _run(tmp_path, _settings(target_applications=5))

    assert summary.applied == 5
    assert len(attempted) == 5


def test_coverage_exactly_at_the_threshold_proceeds(harness, tmp_path):
    install, attempted = harness
    install(0.5)

    summary = _run(tmp_path, _settings(target_applications=3))

    assert summary.applied == 3


def test_zero_threshold_allows_a_lexical_run(harness, tmp_path):
    """Opt out explicitly, for someone who wants lexical ranking."""
    install, attempted = harness
    install(0.0)

    summary = _run(tmp_path, _settings(target_applications=3, min_llm_rank_coverage=0.0))

    assert summary.applied == 3


def test_dry_run_still_reports_the_plan(harness, tmp_path):
    """A dry run spends nothing, so a degraded ranking is worth seeing."""
    install, attempted = harness
    install(0.0)

    _run(tmp_path, _settings(dry_run=True))

    assert attempted == []  # a dry run never applies regardless
