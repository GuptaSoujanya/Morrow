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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import apply as apply_module
from naukri_bot import auth, cli, ranking, sources
from common import browser, llm
from common.models import (
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
        apply_delay_min_s=0.0,
        apply_delay_max_s=0.0,
        dry_run=False,
    )
    values.update(overrides)
    return Settings(**values)


def _scored(score, days, jid):
    # llm_score is set because these tests are about the apply loop, not about
    # ranking health: without it every job looks unranked and the LLM coverage
    # guard stops the run before the loop is reached.
    return ScoredJob(
        job=JobPosting(
            job_id=jid,
            url="https://www.naukri.com/job-listings-%s" % jid,
            title="Role %s" % jid,
            company="Co %s" % jid,
            posted_days_ago=days,
        ),
        score=score,
        llm_score=score,
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
    monkeypatch.chdir(tmp_path)  # user/worklists/external_jobs.md is written to the cwd

    attempted = []

    class _Client:
        def available(self):
            return True

    monkeypatch.setattr(llm, "build_client", lambda settings: _Client())
    monkeypatch.setattr(browser, "create_driver", lambda settings: object())
    monkeypatch.setattr(
        auth,
        "ensure_logged_in",
        lambda driver, settings: LoginResult(ok=True, reason="session_reused"),
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


def test_the_loop_works_down_the_queue_in_score_order(fake_naukri, tmp_path):
    """Selection returns one score-ordered queue; the loop walks it in order.

    This replaced a test for a three-tier scheme that preferred fresher jobs
    over higher-scoring stale ones. The tiers were removed because the orders
    they produced were identical to plain score ordering, and because freshness
    already earns up to ten points inside the score.
    """
    install, attempted = fake_naukri
    queue = [_scored(80.0 - i, 1, "j%02d" % i) for i in range(20)]
    # Half of the best ones cannot be applied to, so the loop must keep going.
    script = {"j%02d" % i: ApplyStatus.EXTERNAL_SKIPPED for i in range(0, 10, 2)}
    install(queue, script)

    summary = _run(tmp_path, _settings(target_applications=10))

    assert summary.applied == 10
    assert attempted == sorted(attempted), "the queue was not walked in order"
    assert attempted[0] == "j00", "did not start with the highest score"


def test_below_min_score_is_never_applied_to(fake_naukri, tmp_path):
    """A short run is preferable to an irrelevant application under the user's name.

    min_score is now the single quality bar; there is no second floor.
    """
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


def test_per_company_cap_spreads_applications(fake_naukri, tmp_path):
    """One prolific poster must not take a large share of the day's quota."""
    install, attempted = fake_naukri
    # 20 roles at one employer, all scoring well, then 10 elsewhere.
    hoard = [_scored(80.0 - i * 0.01, 1, "soul%02d" % i) for i in range(20)]
    others = [_scored(60.0, 1, "other%02d" % i) for i in range(10)]
    for s in hoard:
        s.job.company = "Soul Ai"
    for i, s in enumerate(others):
        s.job.company = "Company %d" % i
    install(hoard + others, {})

    summary = _run(tmp_path, _settings(target_applications=10, max_per_company=3))

    soul = [j for j in attempted if j.startswith("soul")]
    assert len(soul) == 3, "cap did not hold: %d roles attempted at one company" % len(soul)
    assert summary.applied == 10, "cap must not stop the run reaching its target"


def test_company_cap_ignores_suffix_and_case_differences(fake_naukri, tmp_path):
    """Naukri prints the same employer inconsistently; the cap must still group them."""
    install, attempted = fake_naukri
    variants = ["Soul Ai", "SOUL AI", "Soul Ai Pvt Ltd", "soul ai private limited"]
    jobs = [_scored(80.0 - i, 1, "v%d" % i) for i in range(4)]
    for job, name in zip(jobs, variants):
        job.job.company = name
    filler = [_scored(60.0, 1, "f%02d" % i) for i in range(10)]
    for i, f in enumerate(filler):
        f.job.company = "Other %d" % i
    install(jobs + filler, {})

    _run(tmp_path, _settings(target_applications=5, max_per_company=2))

    assert len([j for j in attempted if j.startswith("v")]) == 2, (
        "suffix or case variants were treated as different companies"
    )


def test_external_roles_survive_an_interrupted_run(fake_naukri, tmp_path, monkeypatch):
    """The worklist is written as roles are found, not after the loop ends.

    A terminal status still breaks the loop cleanly and reaches the post-loop
    write, so it proves nothing here. This kills the run mid-loop the way a
    crash or a SIGKILL does, where no code after the loop ever executes.
    """
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%02d" % i) for i in range(10)]
    install(queue, {"j%02d" % i: ApplyStatus.EXTERNAL_SKIPPED for i in range(4)})

    # Blow up on the 5th job, after four company-site roles have been found.
    real_apply = apply_module.apply_to_job

    def _explode(driver, job, profile, engine, settings):
        if job.job_id == "j04":
            raise RuntimeError("simulated crash mid-loop")
        return real_apply(driver, job, profile, engine, settings)

    monkeypatch.setattr(apply_module, "apply_to_job", _explode)

    with pytest.raises(RuntimeError):
        _run(tmp_path, _settings(target_applications=50))

    written = (tmp_path / "user/worklists/external_jobs.md").read_text()
    for i in range(4):
        assert "job-listings-j%02d" % i in written, (
            "company-site role found before the crash was lost"
        )


def test_company_site_roles_are_recorded_for_manual_application(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%02d" % i) for i in range(10)]
    install(queue, {"j%02d" % i: ApplyStatus.EXTERNAL_SKIPPED for i in range(5)})

    _run(tmp_path, _settings(target_applications=5))

    written = (tmp_path / "user/worklists/external_jobs.md").read_text()
    for i in range(5):
        assert "job-listings-j%02d" % i in written, "external role was lost"


def test_a_job_that_stopped_for_you_waits_until_you_answer(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    install([_scored(80.0, 1, "a"), _scored(75.0, 1, "b")], {"a": ApplyStatus.ABSTAINED})

    _run(tmp_path, _settings(target_applications=5))
    _run(tmp_path, _settings(target_applications=5))
    assert attempted == ["a", "b"]

    (tmp_path / "user" / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user" / "inputs" / "answers.txt").write_text("Q: What is your notice period?\nA: 30 days\n")
    _run(tmp_path, _settings(target_applications=5))
    assert attempted == ["a", "b", "a"]


def test_only_the_latest_attempt_under_the_same_facts_keeps_a_job_waiting(tmp_path):
    from common.ledger import Ledger

    ledger = Ledger(str(tmp_path / "w.db"))
    job = _scored(80.0, 1, "a").job
    other = _scored(80.0, 1, "b").job
    unloaded = _scored(80.0, 1, "c").job
    ledger.record_attempt(_result(job, ApplyStatus.ABSTAINED), facts="f1")
    needs_her = _result(other, ApplyStatus.EXTERNAL_MANUAL)
    needs_her.detail = "greenhouse | needs you for: Cover letter"
    ledger.record_attempt(needs_her, facts="f1")
    not_loaded = _result(unloaded, ApplyStatus.EXTERNAL_MANUAL)
    not_loaded.detail = "workday | no application form found on https://x (controls: none)"
    ledger.record_attempt(not_loaded, facts="f1")
    assert ledger.waiting_on_you("f1") == {"a", "b"}
    assert ledger.waiting_on_you("f2") == set()

    ledger.record_attempt(_result(job, ApplyStatus.ERROR), facts="f1")
    assert ledger.waiting_on_you("f1") == {"b"}
    assert ledger.waiting_on_you("") == set()
    ledger.close()


def test_a_company_site_submit_without_a_confirmation_is_never_sent_again(fake_naukri, tmp_path):
    from common.ledger import Ledger

    install, attempted = fake_naukri
    install([_scored(80.0, 1, "sent"), _scored(75.0, 1, "agent"), _scored(70.0, 1, "fresh")], {})
    ledger = Ledger(str(tmp_path / "test.db"))
    clicked = _result(_scored(80.0, 1, "sent").job, ApplyStatus.ERROR)
    clicked.detail = "https://acme.test/careers | Submit was clicked but no confirmation within 30 seconds"
    ledger.record_attempt(clicked, facts="old")
    silent = _result(_scored(75.0, 1, "agent").job, ApplyStatus.ERROR)
    silent.detail = "website | the browser agent did not report (timeout); check the site before trying again"
    ledger.record_attempt(silent, facts="old")
    assert ledger.sent_unconfirmed() == {"sent", "agent"}
    ledger.close()

    summary = _run(tmp_path, _settings(target_applications=5))

    assert attempted == ["fresh"]
    assert summary.held_back == 2


def test_the_summary_says_where_every_collected_job_went(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    queue = [_scored(80, 1, "good"), _scored(30, 1, "weak"), _scored(60, 1, "fine")]
    install(queue, {})

    summary = _run(tmp_path, _settings(target_applications=5))

    assert (summary.collected, summary.below_score, summary.eligible) == (3, 1, 2)
    assert (summary.too_old, summary.not_ranked, summary.held_back) == (0, 0, 0)
    assert sorted(attempted) == ["fine", "good"]


def test_three_refusals_in_a_row_end_the_run_after_one_cool_off(fake_naukri, tmp_path, monkeypatch):
    install, attempted = fake_naukri
    waited = []
    monkeypatch.setattr(cli, "REFUSAL_COOLOFF_S", 7)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: waited.append(seconds))
    queue = [_scored(80.0, 1, "j%03d" % i) for i in range(10)]
    install(queue, {"j002": ApplyStatus.NAUKRI_REFUSED, "j003": ApplyStatus.NAUKRI_REFUSED,
                    "j004": ApplyStatus.NAUKRI_REFUSED})

    summary = _run(tmp_path, _settings(target_applications=10))

    assert attempted == ["j000", "j001", "j002", "j003", "j004"]
    assert summary.applied == 2
    assert 7 in waited, "the bot cooled off after the second refusal before the last try"


def test_two_refusals_followed_by_an_application_keep_the_run_going(fake_naukri, tmp_path, monkeypatch):
    install, attempted = fake_naukri
    monkeypatch.setattr(cli, "REFUSAL_COOLOFF_S", 0)
    queue = [_scored(80.0, 1, "j%03d" % i) for i in range(6)]
    install(queue, {"j001": ApplyStatus.NAUKRI_REFUSED, "j002": ApplyStatus.NAUKRI_REFUSED})

    summary = _run(tmp_path, _settings(target_applications=10))

    assert len(attempted) == 6
    assert summary.applied == 4


def test_one_refusal_between_applications_does_not_end_the_run(fake_naukri, tmp_path):
    install, attempted = fake_naukri
    queue = [_scored(80.0, 1, "j%03d" % i) for i in range(5)]
    install(queue, {"j001": ApplyStatus.NAUKRI_REFUSED, "j003": ApplyStatus.NAUKRI_REFUSED})

    summary = _run(tmp_path, _settings(target_applications=10))

    assert len(attempted) == 5
    assert summary.applied == 3
