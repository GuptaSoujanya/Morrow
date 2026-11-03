"""The startup bot applies on its own: links in its own browser, addresses as drafts, its own to-do file.

Startup posts used to be dropped into Naukri's company_sites.md, labelled as
Naukri jobs, and waited for another bot's retry. Now startup_bot ranks them,
applies to links itself, drafts emails for addresses, and lists what needs
you in startup_jobs.md.
"""

import os
import sys

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
    monkeypatch.setattr(ranking, "drop_stale_candidates", lambda jobs, s: (jobs, []))
    monkeypatch.setattr(ranking, "rank", lambda p, jobs, c, s: [ScoredJob(job=j, score=60) for j in jobs])
    monkeypatch.setattr(ranking, "select_for_application", lambda ranked, s, applied: ranked)
    monkeypatch.setattr("sites_bot.application_brain.blocked", lambda s, job: "")
    monkeypatch.setattr("common.answers.facts_fingerprint", lambda p, s: "f")
    drafted = []
    monkeypatch.setattr(cold_email, "draft_all",
                        lambda s, p, c, leads, limit, dry: drafted.extend(leads) or {"drafted": len(leads)})
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
    counts = cli.run(settings, None, _Ledger(), None, _Engine(), 10, False, open_browser=browser)
    assert [lead.email for lead in drafted] == ["careers@serpapi.example"]
    assert counts["emails drafted"] == 1 and counts["need you"] == 0
    assert "## " not in ((tmp_path / "startup_jobs.md").read_text() if (tmp_path / "startup_jobs.md").exists() else "")


def test_a_bundled_hn_title_becomes_one_role():
    assert sj._first_role("Junior to Senior Fullstack Engineer multiple positions; Customer Success") == \
        "Junior to Senior Fullstack Engineer"
    assert sj._first_role("DevOps Engineer; https://x.com/jobs") == "DevOps Engineer"
