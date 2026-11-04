"""The bot never applies to, shares interest in or writes to the current employer."""
import logging
from types import SimpleNamespace

import pytest

from common import guardrails
from common.models import ApplyStatus, JobPosting, Profile, Settings

PROFILE = Profile(full_name="Jane Doe", email="jane@example.org",
                  extra_facts={"current_company": "Ethara AI", "never_apply_to": ["Old Co Pvt Ltd"]})


class _NeverNavigates:
    """A browser that fails the test the moment anything tries to use it."""

    current_url = "https://www.naukri.com/job-listings-x"

    def get(self, url):
        raise AssertionError("the guardrail must refuse before the browser is touched: %s" % url)

    def __getattr__(self, name):
        raise AssertionError("the guardrail must refuse before the browser is touched: %s" % name)


@pytest.mark.parametrize("company, url, email, text, expected", [
    ("Ethara AI", "", "", "", "Ethara AI"),
    ("ethara ai private limited", "", "", "", "Ethara AI"),
    ("ETHARA", "", "", "", "Ethara AI"),
    ("", "https://careers.ethara.ai/jobs/12", "", "", "Ethara AI"),
    ("", "https://boards.greenhouse.io/ethara/jobs/12", "", "", "Ethara AI"),
    ("", "https://jobs.lever.co/etharaai/abc", "", "", "Ethara AI"),
    ("", "", "hiring@ethara.ai", "", "Ethara AI"),
    ("", "", "", "Ethara AI | Senior Engineer | Gurugram | Full time", "Ethara AI"),
    ("Old Co", "", "", "", "Old Co Pvt Ltd"),
    ("Etharaa Systems", "", "", "", ""),
    ("Acme AI", "https://acme.ai/careers", "jobs@acme.ai", "AI Engineer at Acme", ""),
    ("", "https://www.naukri.com/job-listings-ai-engineer-ethara-ai-gurugram", "", "", "Ethara AI"),
    ("", "https://www.naukri.com/job-listings-ai-engineer-etharaa-gurugram", "", "", ""),
])
def test_the_current_employer_is_recognised_by_name_domain_or_address(company, url, email, text, expected):
    assert guardrails.own_company(PROFILE, company=company, url=url, email=email, text=text) == expected


def test_a_blank_or_absent_current_company_protects_nothing():
    assert guardrails.protected_companies(Profile()) == []
    assert guardrails.protected_companies(Profile(extra_facts={"current_company": "  "})) == []
    assert guardrails.own_company(None, company="Ethara AI") == ""
    assert guardrails.own_company(Profile(extra_facts={"current_company": "Co"}), company="Co") == ""


def test_own_company_postings_are_dropped_before_ranking_and_named_in_the_log(caplog):
    jobs = [
        JobPosting("1", "https://x/1", title="AI Engineer", company="Ethara AI"),
        JobPosting("2", "https://x/2", title="Backend Engineer", company="Acme"),
        JobPosting("3", "https://ethara.ai/careers/3", title="Platform Engineer", company=""),
    ]
    with caplog.at_level(logging.WARNING, logger="common.guardrails"):
        kept, dropped = guardrails.drop_own_company(jobs, PROFILE, source="Naukri")
    assert [job.job_id for job in kept] == ["2"] and dropped == 2
    line = caplog.records[-1].getMessage()
    assert line.startswith("Naukri: guardrail dropped 2 posting(s) from your current employer Ethara AI")
    assert "AI Engineer @ Ethara AI" in line and "Platform Engineer @ Ethara AI" in line


def test_naukri_apply_refuses_the_current_employer_without_opening_the_page():
    from naukri_bot import apply as naukri_apply

    job = JobPosting("n1", "https://www.naukri.com/job-listings-n1", title="AI Engineer", company="Ethara AI Pvt Ltd")
    result = naukri_apply.apply_to_job(_NeverNavigates(), job, PROFILE, object(), Settings(dry_run=False))
    assert result.status == ApplyStatus.OWN_COMPANY and not result.quota_consumed
    assert "Ethara AI is your current employer" in result.detail


def test_board_apply_refuses_the_current_employer_without_opening_the_page():
    from sites_bot import platforms

    job = JobPosting("hirist:1", "https://hirist.tech/j/1", title="AI Engineer", company="Ethara AI")
    result = platforms.apply_to(_NeverNavigates(), object(), job, PROFILE, object(), Settings(), None, False)
    assert result.status == ApplyStatus.OWN_COMPANY


def test_company_site_apply_refuses_the_employers_own_site_even_when_the_posting_names_nobody(tmp_path):
    from sites_bot import external as ext

    driver = _NeverNavigates()
    driver.current_url = "https://careers.ethara.ai/apply/42"
    job = JobPosting("c1", "https://www.naukri.com/job-listings-c1", title="Engineer", company="")
    result = ext.apply_here(driver, job, PROFILE, object(), Settings(data_dir=str(tmp_path)), None, dry_run=False)
    assert result.status == ApplyStatus.OWN_COMPANY
    assert result.to_apply_result(job).status == ApplyStatus.OWN_COMPANY


def test_startup_apply_refuses_the_current_employer_and_records_nothing(tmp_path):
    from sites_bot.startup_jobs import StartupPost
    from startup_bot import cli

    job = JobPosting("hn1", "https://news.ycombinator.com/item?id=1", title="Founding Engineer", company="Ethara AI")
    post = StartupPost(job, [], apply_url="https://ethara.ai/jobs", text="Ethara AI | Founding Engineer")
    settings = Settings(data_dir=str(tmp_path), db_path=str(tmp_path / "jobs.db"))
    status = cli.apply_on_site(_NeverNavigates(), settings, PROFILE, object(), object(), object(), post,
                               dry_run=False, no_tailor=True)
    assert status == ApplyStatus.OWN_COMPANY
    assert not (tmp_path / cli.PENDING_FILE).exists()


def test_early_access_never_shares_interest_in_the_current_employer(monkeypatch):
    from naukri_bot import early_access

    roles = [early_access.EarlyAccessRole(0, "k0", title="AI Engineer", company="Ethara AI"),
             early_access.EarlyAccessRole(1, "k1", title="AI Engineer", company="Acme")]
    monkeypatch.setattr(early_access, "open_page", lambda driver, settings: True)
    monkeypatch.setattr(early_access, "collect_roles", lambda driver: list(roles))
    ledger = SimpleNamespace(has_shared_interest=lambda key: False)
    summary = early_access.share_all(object(), Settings(), ledger, limit=5, dry_run=True, profile=PROFILE)
    assert [role.company for role in summary.roles] == ["Acme"]
    assert summary.found == 2 and summary.skipped == 2


def test_no_cold_email_lead_is_kept_for_the_current_employer(tmp_path, caplog):
    from sites_bot import cold_email

    settings = Settings(data_dir=str(tmp_path), resume_out_dir=str(tmp_path / "out"))
    leads = [cold_email.Lead("jobs@ethara.ai", "", "AI Engineer", "https://news.ycombinator.com/item?id=2", "hn"),
             cold_email.Lead("hr@acme.example", "Ethara AI", "AI Engineer", "", "hn"),
             cold_email.Lead("hr@acme.example", "Acme", "AI Engineer", "", "hn")]
    with caplog.at_level(logging.WARNING, logger="sites_bot.cold_email"):
        kept = cold_email.unique_leads(settings, PROFILE, leads)
    assert [(lead.email, lead.company) for lead in kept] == [("hr@acme.example", "Acme")]
    assert sum("is your current employer" in record.getMessage() for record in caplog.records) == 2


def test_company_email_drafts_skip_the_current_employer_by_name_site_or_address():
    from common import company_outreach as outreach

    by_name = {"company_id": "a", "name": "Ethara AI", "fields": {}}
    by_site = {"company_id": "b", "name": "Unknown", "fields": {"website": [{"value": "https://www.ethara.ai"}]}}
    by_mail = {"company_id": "c", "name": "Unknown", "fields": {"email": [{"value": "careers@ethara.ai"}]}}
    other = {"company_id": "d", "name": "Acme Labs", "fields": {"email": [{"value": "careers@acmelabs.in"}]}}
    assert [outreach.own_employer(PROFILE, c) for c in (by_name, by_site, by_mail, other)] == [
        "Ethara AI", "Ethara AI", "Ethara AI", ""]


def test_the_run_summary_and_dashboard_funnel_report_the_dropped_employer_postings():
    from common.report import funnel_text
    from naukri_bot.cli import _summary_record, _tally
    from common.models import ApplyResult, RunSummary

    summary = RunSummary(collected=3, own_company=1, eligible=1)
    _tally(summary, ApplyResult(job_id="x", url="", status=ApplyStatus.OWN_COMPANY, detail="guardrail"))
    record = _summary_record(summary, Settings())
    assert record["own_company"] == 2 and summary.errors == 0
    assert "2 from your current employer" in funnel_text(record)


def _posting(company, description, url="https://www.naukri.com/job-listings-x"):
    return JobPosting("x", url, title="Software Engineer", company=company, description=description)


def _at(employer):
    return Profile(extra_facts={"current_company": employer})


@pytest.mark.parametrize("employer, company, description", [
    ("Microsoft", "Infosys", "Build services on Microsoft Azure. Experience with Microsoft SQL Server a plus."),
    ("Amazon", "Zeta", "Deploy on AWS (Amazon Web Services): EC2, S3, Lambda."),
    ("Google", "Razorpay", "Experience with Google Cloud Platform (GCP) and BigQuery."),
    ("Google", "Razorpay", "Ship features built on Google's Gemini models."),
    ("Oracle", "TCS", "Strong SQL on Oracle Database or PostgreSQL."),
    ("Meta", "Sarvam AI", "Fine-tune open models such as Meta Llama 3 and Mistral."),
])
def test_another_companys_posting_that_uses_the_employers_product_is_not_the_employers(employer, company, description):
    """#27: a mention of the employer's product refused postings from every other company."""
    assert guardrails.guard_job(_at(employer), _posting(company, description)) == ""


@pytest.mark.parametrize("employer, company, description", [
    ("Ethara AI", "Acme", "Our client, Ethara AI, is hiring an AI engineer."),
    ("Microsoft", "Confidential", "Join Microsoft's Azure team; Microsoft is hiring in Hyderabad."),
    ("Microsoft", "Confidential", "Built on Microsoft Azure. Microsoft is hiring."),
    ("Microsoft", "Confidential", "Work from our Microsoft office in Hyderabad."),
    ("Microsoft", "Microsoft Azure", "Build services on Azure."),
    ("Amazon", "Amazon Web Services", "Deploy on AWS."),
])
def test_the_employer_itself_is_still_refused(employer, company, description):
    assert guardrails.guard_job(_at(employer), _posting(company, description)) == employer
