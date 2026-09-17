"""The apply loop must reach its target despite jobs it cannot apply to.

Most of a day's ranked queue is not applicable: company-site redirects cannot
be submitted through Naukri at all, and a questionnaire with one unanswerable
question abandons the whole application. Neither is knowable until the job page
is open, so the loop has to keep drawing from the queue until it has actually
submitted target_applications, not until it has tried that many times.

These tests drive the real cli.run() with Naukri replaced by a script of
outcomes, so the loop, the tier ordering and the run's stopping conditions are
exercised as they ship. Nothing here opens a browser or touches the network.
"""

import os
import sys
import tempfile

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
        daily_quota=50,
        target_applications=50,
        min_score=55.0,
        max_days_old=3,
        min_score_floor=50.0,
        max_days_old_fallback=14,
        dry_run=False,
    )
    values.update(overrides)
    return Settings(**values)


def _scored(score, days, jid):
    return ScoredJob(
        job=JobPosting(
            job_id=jid,
            url="https://www.naukri.com/job-listings-%s" % jid,
            title="Role %s" % jid,
            company="Co %s" % jid,
            posted_days_ago=days,
        ),
        score=score,
    )


def _result(job, status):
    return ApplyResult(
        job_id=job.job_id,
        url=job.url,
        status=status,
        quota_consumed=(status == ApplyStatus.APPLIED),
    )


@pytest.fixture
def fake_naukri(monkeypatch, tmp_path):
    """Replace every outward edge of run() and record what the loop attempted."""
    monkeypatch.chdir(tmp_path)  # external_jobs.md is written to the cwd

    attempted = []

    class _Client:
        def available(self):
            return True

    monkeypatch.setattr(llm, "build_client", lambda settings: _Client())
    monkeypatch.setattr(browser, "create_driver", lambda settings: object())
    monkeypatch.setattr(
        auth, "login", lambda driver, settings: LoginResult(ok=True, reason="verified")
    )
    monkeypatch.setattr(sources, "collect_candidates", lambda *a, **k: [])

    def _install(queue, script):
        """`script` maps job_id -> ApplyStatus; anything unlisted applies cleanly."""
        monkeypatch.setattr(sources, "collect_candidates",
                            lambda *a, **k: [s.job for s in queue])
        monkeypatch.setattr(ranking, "rank", lambda *a, **k: list(queue))

        def _apply(driver, job, profile, engine, settings):
            attempted.append(job.job_id)
            return _result(job, script.get(job.job_id, ApplyStatus.APPLIED))

        monkeypatch.setattr(apply_module, "apply_to_job", _apply)

    return _install, attempted


def _run(tmp_path, settings):
    settings.db_path = str(tmp_path / "test.db")
    return cli.run(settings, Profile(full_name="T"))


def test_loop_draws_more_jobs_when_most_cannot_be_applied_to(fake_naukri, tmp_path):
    """The scenario from a real run: externals and abstains must not cost a slot."""
    install, attempted = fake_naukri
    # 120 fresh, good jobs. Every third is a company-site redirect and every
    # fifth abandons on a question, so only ~47% are actually applicable.
    queue = [_scored(80.0 - i * 0.1, 1, "j%03d" % i) for i in range(120)]
    script = {}
    for i in range(120):
        if i % 3 == 0:
            script["j%03d" % i] = ApplyStatus.EXTERNAL_SKIPPED
        elif i % 5 == 0:
            script["j%03d" % i] = ApplyStatus.ABSTAINED
    install(queue, script)

    summary = _run(tmp_path, _settings(target_applications=10))

    assert summary.applied == 10, "loop stopped short of the target"
    assert len(attempted) > 10, "loop counted attempts instead of applications"
    assert summary.skipped_external > 0 and summary.skipped_abstained > 0


def test_loop_stops_exactly_at_the_target(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%03d" % i) for i in range(100)]
    install(queue, {})  # every job applies

    summary = _run(tmp_path, _settings(target_applications=50))

    assert summary.applied == 50
    assert len(attempted) == 50, "loop kept applying past the target"


def test_loop_descends_into_fallback_tiers_only_after_tier_one(fake_naukri, tmp_path):
    """Tier 1 is preferred, but must not cap the run when it cannot fill the target."""
    install, attempted = fake_naukri
    tier1 = [_scored(60.0, 1, "fresh%02d" % i) for i in range(10)]
    tier2 = [_scored(75.0, 9, "old%02d" % i) for i in range(10)]  # higher score, older
    tier3 = [_scored(52.0, 1, "weak%02d" % i) for i in range(10)]
    # Only half of tier 1 is applicable, so the target needs tier 2 as well.
    script = {"fresh%02d" % i: ApplyStatus.EXTERNAL_SKIPPED for i in range(0, 10, 2)}
    install(tier1 + tier2 + tier3, script)

    summary = _run(tmp_path, _settings(target_applications=10))

    assert summary.applied == 10
    assert attempted[:10] == ["fresh%02d" % i for i in range(10)], (
        "fresh jobs must be offered before older ones even when scored lower"
    )
    assert any(jid.startswith("old") for jid in attempted), "never reached tier 2"
    assert not any(jid.startswith("weak") for jid in attempted), (
        "reached tier 3 while tier 2 still had applicable jobs"
    )


def test_below_the_floor_is_never_applied_to(fake_naukri, tmp_path):
    """A short run is preferable to an irrelevant application under the user's name."""
    install, attempted = fake_naukri
    good = [_scored(60.0, 1, "ok%02d" % i) for i in range(5)]
    junk = [_scored(30.0, 1, "junk%02d" % i) for i in range(50)]
    install(good + junk, {})

    summary = _run(tmp_path, _settings(target_applications=50))

    assert summary.applied == 5, "run should end short rather than pad the count"
    assert not any(jid.startswith("junk") for jid in attempted)


def test_terminal_status_stops_the_run_immediately(fake_naukri, tmp_path):
    """A signed-out session must not keep opening job pages."""
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%02d" % i) for i in range(30)]
    install(queue, {"j03": ApplyStatus.SESSION_EXPIRED})

    summary = _run(tmp_path, _settings(target_applications=50))

    assert summary.applied == 3
    assert len(attempted) == 4, "loop continued past a terminal status"


def test_company_site_roles_are_recorded_for_manual_application(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%02d" % i) for i in range(10)]
    install(queue, {"j%02d" % i: ApplyStatus.EXTERNAL_SKIPPED for i in range(5)})

    _run(tmp_path, _settings(target_applications=5))

    written = (tmp_path / "external_jobs.md").read_text()
    for i in range(5):
        assert "job-listings-j%02d" % i in written, "external role was lost"
