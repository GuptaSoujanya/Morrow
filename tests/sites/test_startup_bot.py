"""The startup bot applies on its own: links in its own browser, addresses as drafts, its own to-do file.

Startup posts used to be dropped into Naukri's company_sites.md, labelled as
Naukri jobs, and waited for another bot's retry. Now startup_bot ranks them,
applies to links itself, drafts emails for addresses, and lists what needs
you in startup_jobs.md.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import ApplyStatus, JobPosting, ScoredJob, Settings
from sites_bot import startup_jobs as sj
from sites_bot.external import ExternalResult
from startup_bot import cli


def _post(job_id, email="", url=""):
    job = JobPosting(job_id=job_id, url="https://news.ycombinator.com/item?id=%s" % job_id[3:],
                     title="Engineer", company="Co %s" % job_id, source="hn:whoishiring:2026-11")
    contacts = [sj.Contact(email, "hiring")] if email else []
    return sj.StartupPost(job=job, contacts=contacts, apply_url=url, text="post")


class _Ledger:
    def __init__(self):
        self.attempts = []

    def record_seen(self, *a, **k):
        pass

    def waiting_on_you(self, facts):
        return {"hn:4"}

    def sent_unconfirmed(self):
        return set()

    def has_applied(self, job_id):
        return False

    def open_per_company(self, days=None):
        return {}

    def record_attempt(self, result, **k):
        self.attempts.append(result)


class _Engine:
    def set_job_context(self, job):
        self.job = job


def _setup(monkeypatch, tmp_path, posts, status=ApplyStatus.APPLIED_EXTERNAL):
    from naukri_bot import ranking
    from sites_bot import browser_agent, cold_email
    from sites_bot import external as ext

    monkeypatch.setattr(sj, "collect", lambda profile, fetch: posts)
    monkeypatch.setattr(ranking, "drop_stale_candidates", lambda jobs, s, **kw: (jobs, []))
    monkeypatch.setattr(ranking, "rank", lambda p, jobs, c, s, **kw: [ScoredJob(job=j, score=60) for j in jobs])
    monkeypatch.setattr(ranking, "select_for_application", lambda ranked, s, applied, **kw: ranked)
    monkeypatch.setattr("sites_bot.application_brain.blocked", lambda s, job: "")
    monkeypatch.setattr("common.answers.facts_fingerprint", lambda p, s: "f")
    drafted = []
    monkeypatch.setattr(cold_email, "draft_all",
                        lambda s, p, c, leads, limit, dry, driver=None: drafted.extend(leads) or {"drafted": len(leads)})
    visited = []
    monkeypatch.setattr(ext, "resume_to_attach", lambda *a: None)
    monkeypatch.setattr(ext, "safe_get", lambda d, url: visited.append(url) or True)
    monkeypatch.setattr(ext, "human_pause", lambda *a: None)
    monkeypatch.setattr(ext, "apply_here", lambda d, job, *a: ExternalResult(
        status=status, url="https://site/%s" % job.job_id, detail="done" if status == ApplyStatus.APPLIED_EXTERNAL
        else "needs you for: Notice", missing=[] if status == ApplyStatus.APPLIED_EXTERNAL else ["Notice"]))
    monkeypatch.setattr(browser_agent, "take_over", lambda d, job, p, s, pdf, dry, result: result)

    class _Driver:
        def quit(self):
            pass

    settings = Settings(data_dir=str(tmp_path))
    return settings, drafted, visited, (lambda s: _Driver())


def test_links_are_applied_to_and_addresses_drafted(monkeypatch, tmp_path):
    posts = [_post("hn:1", email="jobs@a.io"), _post("hn:2", url="https://jobs.lever.co/b"), _post("hn:3"),
             _post("hn:4", url="https://held")]
    settings, drafted, visited, browser = _setup(monkeypatch, tmp_path, posts)
    ledger = _Ledger()
    counts = cli.run(settings, None, ledger, None, _Engine(), 10, False, open_browser=browser)
    assert [lead.email for lead in drafted] == ["jobs@a.io"]
    assert visited == ["https://jobs.lever.co/b"]  # hn:4 waits on your answers
    assert counts["applied"] == 1 and counts["emails drafted"] == 1 and counts["no way to apply"] == 1
    assert len(ledger.attempts) == 1
    assert not (tmp_path / "company_sites.md").exists()


def test_what_needs_you_goes_to_its_own_file_and_is_replaced_not_repeated(monkeypatch, tmp_path):
    posts = [_post("hn:2", url="https://jobs.lever.co/b")]
    settings, _, _, browser = _setup(monkeypatch, tmp_path, posts, status=ApplyStatus.EXTERNAL_MANUAL)
    cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    text = (tmp_path / "startup_jobs.md").read_text()
    assert text.count("## ") == 1 and "Left for you: Notice" in text and "Naukri" not in text
    cli.forget_pending(settings, posts[0].job)
    assert "## " not in (tmp_path / "startup_jobs.md").read_text()


def test_a_dry_run_records_nothing(monkeypatch, tmp_path):
    posts = [_post("hn:1", email="jobs@a.io"), _post("hn:2", url="https://jobs.lever.co/b")]
    settings, _, _, browser = _setup(monkeypatch, tmp_path, posts, status="dry_run")
    ledger = _Ledger()
    cli.run(settings, None, ledger, None, _Engine(), 10, True, open_browser=browser)
    assert ledger.attempts == [] and not list(tmp_path.iterdir())


def test_a_site_that_takes_email_gets_a_draft_not_a_to_do(monkeypatch, tmp_path):
    posts = [_post("hn:2", url="https://serpapi.example/careers")]
    settings, drafted, _, browser = _setup(monkeypatch, tmp_path, posts, status=ApplyStatus.EXTERNAL_MANUAL)
    from sites_bot import external as ext
    monkeypatch.setattr(ext, "apply_here", lambda d, job, *a: ExternalResult(
        status=ApplyStatus.EXTERNAL_MANUAL, detail="needs you for: Permission to send an email application to "
        "careers@serpapi.example (posting URL: x)", missing=["Permission to send an email application to careers@serpapi.example"]))
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@serpapi.example")
    counts = cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    assert [lead.email for lead in drafted] == ["careers@serpapi.example"]
    assert counts["emails drafted"] == 1 and counts["need you"] == 0
    assert "## " not in ((tmp_path / "startup_jobs.md").read_text() if (tmp_path / "startup_jobs.md").exists() else "")


def test_a_bundled_hn_title_becomes_one_role():
    assert sj._first_role("Junior to Senior Fullstack Engineer multiple positions; Customer Success") == \
        "Junior to Senior Fullstack Engineer"
    assert sj._first_role("DevOps Engineer; https://x.com/jobs") == "DevOps Engineer"


@pytest.mark.parametrize("detail,missing", [
    ("needs you for: Notice period", ["Notice period"]),
    ("the browser agent stopped (needs_you): Record a project walkthrough video.", []),
])
def test_manual_startup_does_not_reopen_until_answers_change(monkeypatch, tmp_path, detail, missing):
    from common.ledger import Ledger
    from sites_bot import external as ext

    post = _post("hn:27", url="https://jobs.example/careers/backend")
    settings, _, visited, browser = _setup(monkeypatch, tmp_path, [post])
    monkeypatch.setattr(ext, "apply_here", lambda *a: ExternalResult(
        status=ApplyStatus.EXTERNAL_MANUAL, detail=detail, missing=missing))
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        cli.run(settings, None, ledger, None, _Engine(), 10, False, open_browser=browser)
        assert ledger.waiting_on_you("f") == {post.job.job_id}
        assert cli.run(settings, None, ledger, None, _Engine(), 10, False,
                       open_browser=browser)["chosen"] == 0
        assert visited == [post.apply_url]
        assert not ledger.has_applied(post.job.job_id)
        monkeypatch.setattr("common.answers.facts_fingerprint", lambda p, s: "new-facts")
        cli.run(settings, None, ledger, None, _Engine(), 10, False, open_browser=browser)
        assert visited == [post.apply_url, post.apply_url]


@pytest.mark.parametrize("problem", ["Sign in to Microsoft Live", "Complete the CAPTCHA", "Enter a verification code"])
def test_access_can_be_retried_without_editing_profile(monkeypatch, tmp_path, problem):
    from common.ledger import Ledger
    from sites_bot import external as ext

    post = _post("hn:28", url="https://jobs.example/careers/backend")
    settings, _, visited, browser = _setup(monkeypatch, tmp_path, [post])
    monkeypatch.setattr(ext, "apply_here", lambda *a: ExternalResult(
        status=ApplyStatus.EXTERNAL_MANUAL, detail="needs you for: " + problem, missing=[problem]))
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        cli.run(settings, None, ledger, None, _Engine(), 10, False, open_browser=browser)
        assert ledger.waiting_on_you("f") == set()
        cli.run(settings, None, ledger, None, _Engine(), 10, False, open_browser=browser)
        assert len(visited) == 2


def test_legacy_email_draft_skips_only_the_same_post_and_role(monkeypatch, tmp_path):
    import json
    from sites_bot.cold_email import records_path

    old = _post("hn:50342697", url="https://serpapi.example/careers")
    old.job.company, old.job.title = "SerpApi", "Junior to Senior Fullstack Engineer"
    other = _post("hn:50342698", url="https://serpapi.example/careers")
    other.job.company, other.job.title = old.job.company, old.job.title
    settings, _, visited, browser = _setup(monkeypatch, tmp_path, [old, other])
    records_path(settings).write_text(json.dumps({
        "job_url": old.job.url, "title": " Junior  to Senior Fullstack Engineer ", "company": "SerpApi",
        "email": "careers@serpapi.example", "drafted_at": "2026-11-03T17:32:09",
        "eml": "/saved/application.eml", "gmail_draft": True,
    }) + "\n")
    counts = cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    assert counts["chosen"] == 1 and visited == [other.apply_url]
    old.job.title = "Developer Advocate"
    assert len(cli.choose(settings, None, _Ledger(), None, 10)) == 2


def test_email_draft_is_saved_as_needing_review_never_as_applied(monkeypatch, tmp_path):
    from common.ledger import Ledger

    post = _post("hn:29", url="https://jobs.example/careers/backend")
    settings, drafted, visited, browser = _setup(monkeypatch, tmp_path, [post], status=ApplyStatus.EXTERNAL_MANUAL)
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@employer.test")
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        assert cli.run(settings, None, ledger, None, _Engine(), 10, False,
                       open_browser=browser)["emails drafted"] == 1
        assert ledger.waiting_on_you("f") == {post.job.job_id}
        assert not ledger.has_applied(post.job.job_id)
        assert cli.run(settings, None, ledger, None, _Engine(), 10, False,
                       open_browser=browser)["chosen"] == 0
        assert len(drafted) == len(visited) == 1


@pytest.mark.parametrize("links,expected", [
    ([{"href": "mailto:careers@employer.test", "text": "Send your resume", "around": "Apply for this role"}],
     "careers@employer.test"),
    ([{"href": "mailto:careers@employer.test", "text": "Contact", "around": "Help with our products"}], ""),
    ([{"href": "mailto:candidate@personal.test", "text": "Send your resume", "around": "Apply"}], ""),
    ([{"href": "mailto:candidate@personal.test", "text": "Get a code to sign in", "around": "Check your email"}], ""),
    ([], ""),
])
def test_email_recipient_requires_published_application_evidence(links, expected):
    from common.models import Profile

    class Driver:
        def execute_script(self, script):
            return links

    assert cli.emailed_to(Driver(), Settings(), Profile(email="candidate@personal.test")) == expected


def test_agent_narrative_cannot_create_a_hiring_contact(monkeypatch, tmp_path):
    from sites_bot import external as ext
    from sites_bot.cold_email import contacts_path

    settings, drafted, _, browser = _setup(monkeypatch, tmp_path, [_post("hn:30", url="https://jobs.example")])
    monkeypatch.setattr(ext, "apply_here", lambda *a: ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL,
        detail="needs you for: Microsoft Live sign-in for candidate@personal.test; check your email at candidate@personal.test"))
    counts = cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    assert counts["emails drafted"] == 0 and drafted == []
    assert not contacts_path(settings).exists()


@pytest.mark.parametrize("status", [ApplyStatus.ALREADY_APPLIED, ApplyStatus.APPLIED_EXTERNAL,
                                    ApplyStatus.ERROR, "gone"])
def test_visible_mailbox_never_drafts_after_other_application_outcomes(monkeypatch, tmp_path, status):
    post = _post("hn:31", url="https://jobs.example/careers/backend")
    settings, drafted, _, browser = _setup(monkeypatch, tmp_path, [post], status=status)
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@employer.test")
    cli.apply_on_site(browser(settings), settings, None, _Engine(), None, _Ledger(), post, False, False)
    assert drafted == []


@pytest.mark.parametrize("hold", ["running", "uncertain", "confirmed", "ledger"])
def test_visible_mailbox_never_bypasses_submission_hold(monkeypatch, tmp_path, hold):
    post = _post("hn:32", url="https://jobs.example/careers/backend")
    settings, drafted, _, browser = _setup(monkeypatch, tmp_path, [post], status=ApplyStatus.EXTERNAL_MANUAL)
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@employer.test")
    monkeypatch.setattr("sites_bot.application_brain.blocked", lambda s, j: "" if hold == "ledger" else hold)
    ledger = _Ledger()
    if hold == "ledger":
        monkeypatch.setattr(ledger, "sent_unconfirmed", lambda: {post.job.job_id})
    cli.apply_on_site(browser(settings), settings, None, _Engine(), None, ledger, post, False, False)
    assert drafted == [] and ledger.attempts == []


def test_prior_uncertain_ledger_entry_is_not_overwritten(monkeypatch, tmp_path):
    from common.ledger import Ledger
    from common.models import ApplyResult

    post = _post("hn:33", url="https://jobs.example/careers/backend")
    settings, drafted, visited, browser = _setup(monkeypatch, tmp_path, [post], status=ApplyStatus.EXTERNAL_MANUAL)
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@employer.test")
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        ledger.record_attempt(ApplyResult(job_id=post.job.job_id, url=post.job.url,
            status=ApplyStatus.ERROR, detail="Submit was clicked but confirmation was not found"))
        cli.apply_on_site(browser(settings), settings, None, _Engine(), None, ledger, post, False, False)
        assert ledger.sent_unconfirmed() == {post.job.job_id}
        assert drafted == visited == []


def test_new_uncertain_outcome_cannot_fall_back_to_an_email_draft(monkeypatch, tmp_path):
    post = _post("hn:34", url="https://jobs.example/careers/backend")
    settings, drafted, visited, browser = _setup(monkeypatch, tmp_path, [post], status=ApplyStatus.EXTERNAL_MANUAL)
    state = {"blocked": ""}
    monkeypatch.setattr("sites_bot.application_brain.blocked", lambda s, j: state["blocked"])
    monkeypatch.setattr("sites_bot.application_brain.mailbox", lambda driver: "careers@employer.test")

    def uncertain(driver, job, profile, settings, resume, dry_run, result):
        state["blocked"] = "uncertain"
        return result

    monkeypatch.setattr("sites_bot.browser_agent.take_over", uncertain)
    cli.apply_on_site(browser(settings), settings, None, _Engine(), None, _Ledger(), post, False, False)
    assert visited == [post.apply_url] and drafted == []


def test_a_company_at_the_open_cap_is_not_applied_to_again(monkeypatch, tmp_path):
    """MAX_PER_COMPANY counts what every bot sent: two open at Acme already means no third from here."""
    from dataclasses import replace

    from common.ledger import Ledger
    from common.models import ApplyResult

    posts = [_post("hn:%d" % n, url="https://jobs.example/%d" % n) for n in (1, 2, 3)]
    for post, company in zip(posts, ("Acme Pvt Ltd", "Acme", "Beta")):
        post.job.company = company
    settings, _, visited, browser = _setup(monkeypatch, tmp_path, posts)
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        for n in (1, 2):
            ledger.record_attempt(ApplyResult(job_id="naukri:%d" % n, url="u%d" % n, status=ApplyStatus.APPLIED),
                                  company="ACME")
        counts = cli.run(replace(settings, max_per_company=2), None, ledger, None, _Engine(), 10, False,
                         open_browser=browser)
    assert visited == ["https://jobs.example/3"]
    assert counts["at the company cap"] == 2 and counts["applied"] == 1


def test_applications_made_in_this_run_count_toward_the_cap(monkeypatch, tmp_path):
    from dataclasses import replace

    from common.ledger import Ledger

    posts = [_post("hn:%d" % n, url="https://jobs.example/%d" % n) for n in (1, 2, 3)]
    for post in posts:
        post.job.company = "Acme"
    settings, _, visited, browser = _setup(monkeypatch, tmp_path, posts)
    with Ledger(str(tmp_path / "applications.db")) as ledger:
        counts = cli.run(replace(settings, max_per_company=2), None, ledger, None, _Engine(), 10, False,
                         open_browser=browser)
    assert len(visited) == 2 and counts["applied"] == 2 and counts["at the company cap"] == 1
