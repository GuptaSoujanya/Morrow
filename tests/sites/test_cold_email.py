"""Cold emails: only published addresses, only grounded text, only drafts."""

import email
import json
import os
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sites_bot import cold_email as ce
from common.models import Profile, Settings

TEX = r"""\documentclass{extarticle}
\begin{document}
\begin{center}
  {\LARGE\bfseries\color{ink} JANE DOE}\\[3pt]
  {\normalsize\color{muted} Software Engineer \;$\cdot$\; AI Agent Evaluation}\\[5pt]
\end{center}
\section{Summary}
I build evaluation pipelines for AI agents in Python and LangChain at Ethara AI, with FastAPI mock services.

\section{Skills}
{\bfseries Languages:} Python, TypeScript\par\vspace{2pt}
{\bfseries AI / LLM:} LangChain, RAG\par\vspace{2pt}

\end{document}
"""

BODY = ("I am writing about the AI Engineer role at Acme Labs that you posted. I build evaluation pipelines "
        "for AI agents in Python and LangChain at Ethara AI, and I run them against FastAPI mock services, "
        "which matches the agent tooling your posting describes. I have also worked with RAG in the same "
        "pipelines. My resume is attached. Would you consider my application for this role? I am happy to "
        "share more detail about any of this work if it helps.")


class _Client:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


@pytest.fixture
def settings(tmp_path):
    tex = tmp_path / "base.tex"
    tex.write_text(TEX, encoding="utf-8")
    return Settings(data_dir=str(tmp_path / "data" / "inputs"), report_dir=str(tmp_path / "reports"),
                    resume_out_dir=str(tmp_path / "out"), resume_path=str(tex),
                    google_email="jane.jobs@example.org")


@pytest.fixture
def profile():
    return Profile(full_name="Jane Doe", phone="+91 90000 00000",
                   extra_facts={"linkedin_url": "https://linkedin.com/in/jane", "portfolio_url": "https://jane.dev"})


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(ce, "attachment_for", lambda settings, lead: None)


def _lead(address="hr@acmelabs.in", posting="Acme Labs is hiring an AI Engineer for agent tooling."):
    return ce.Lead(address, "Acme Labs", "AI Engineer", "https://www.naukri.com/job-listings-1", "test", posting)


@pytest.mark.parametrize("text, found", [
    ("Interested candidates can share their CV at careers@acmelabs.in today.", ["careers@acmelabs.in"]),
    ("Send your resume to Priya.S@AcmeLabs.in.", ["priya.s@acmelabs.in"]),
    ("Write to hr@acmelabs.in", ["hr@acmelabs.in"]),
    ("For billing questions mail support@acmelabs.in or noreply@acmelabs.in", []),
    ("logo@2x.png and icon@3x.webp in the page", []),
    ("send your resume to you@example.com", []),
    ("Our founder is john@acmelabs.in and he loves cricket.", []),
])
def test_only_addresses_published_for_applications_are_taken(text, found):
    assert ce.find_addresses(text) == found


def test_leads_come_from_saved_postings_agent_reports_and_company_sites(settings, tmp_path):
    folder = tmp_path / "out" / "tailored" / "Acme Labs - AI Engineer"
    folder.mkdir(parents=True)
    (folder / "posting.txt").write_text(
        "Title: AI Engineer\nCompany: Acme Labs\nURL: https://www.naukri.com/job-listings-1\n\n"
        "Share your resume at talent@acmelabs.in\n", encoding="utf-8")
    agent = tmp_path / "reports" / "2026-10-12" / "agent" / "003341 Clyptus - AI ML Engineer"
    agent.mkdir(parents=True)
    (agent / "report.json").write_text(json.dumps({
        "job": {"title": "AI / ML Engineer", "company": "Clyptus", "naukri": "https://n/2"},
        "site": "https://clyptus.com/career/",
        "report": {"why": "No form; the modal says: Please share your resume at hr@clyptus.com"}}), encoding="utf-8")

    leads = ce.leads_from_files(settings)

    assert [(lead.email, lead.company, lead.title) for lead in leads] == [
        ("talent@acmelabs.in", "Acme Labs", "AI Engineer"),
        ("hr@clyptus.com", "Clyptus", "AI / ML Engineer"),
    ]


def test_a_grounded_email_is_kept_and_a_buzzword_one_is_sent_back(settings):
    from common.resume import load_base

    base = load_base(settings.resume_path)
    client = _Client({"subject": "AI Engineer role - Jane Doe", "body": "I am thrilled and passionate. " + BODY},
                     {"subject": "AI Engineer role, Jane Doe", "body": BODY})
    assert ce.write_email(client, base, _lead()) == ("AI Engineer role, Jane Doe", BODY)
    assert "Your last draft was refused" in client.prompts[1]
    assert "Acme Labs is hiring an AI Engineer" in client.prompts[0]


def test_an_email_claiming_what_the_resume_does_not_say_is_dropped(settings):
    from common.resume import load_base

    claim = BODY.replace("I have also worked with RAG", "I have also shipped Kubernetes clusters")
    client = _Client({"subject": "AI Engineer role", "body": claim}, {"subject": "AI Engineer role", "body": claim})
    assert ce.write_email(client, load_base(settings.resume_path), _lead()) is None


def test_the_draft_carries_her_signature_and_opens_as_unsent(settings, profile, tmp_path):
    pdf = tmp_path / "Jane_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    message = ce.build_message("jane.jobs@example.org", _lead(), "AI Engineer role", BODY, profile, pdf)
    parsed = email.message_from_bytes(bytes(message))
    assert parsed["To"] == "hr@acmelabs.in" and parsed["X-Unsent"] == "1"
    assert parsed["From"] == "Jane Doe <jane.jobs@example.org>"
    text = parsed.get_payload()[0].get_payload(decode=True).decode()
    assert text.endswith("Jane Doe\n+91 90000 00000\nhttps://linkedin.com/in/jane\nhttps://jane.dev\n")
    assert parsed.get_payload()[1].get_filename() == "Jane_Doe_Resume.pdf"


def test_drafts_are_saved_recorded_and_never_written_twice(settings, profile, no_pdf):
    client = _Client({"subject": "AI Engineer role", "body": BODY})
    now = datetime(2026, 10, 12, 12, 0)

    counts = ce.draft_all(settings, profile, client, [_lead(), _lead()], 10, False, now)

    assert counts == {"drafted": 1, "in gmail": 0, "already written": 0, "not written": 0}
    records = ce.read_records(settings)
    assert records[0]["email"] == "hr@acmelabs.in" and records[0]["gmail_draft"] is False
    assert os.path.exists(records[0]["eml"])
    again = ce.draft_all(settings, profile, _Client(), [_lead()], 10, False, now + timedelta(days=5))
    assert again["already written"] == 1
    assert not ce.already_written(records, "hr@acmelabs.in", now + timedelta(days=31))


def test_a_dry_run_saves_nothing(settings, profile, no_pdf):
    counts = ce.draft_all(settings, profile, _Client({"subject": "AI Engineer role", "body": BODY}), [_lead()], 10, True)
    assert counts["drafted"] == 1
    assert ce.read_records(settings) == []


def test_with_an_app_password_the_draft_also_lands_in_gmail(settings, profile, no_pdf, monkeypatch):
    appended = []

    class _Imap:
        def __init__(self, host):
            assert host == "imap.gmail.com"

        def login(self, user, password):
            appended.append(("login", user, password))

        def append(self, folder, flags, when, data):
            appended.append((folder, flags, b"hr@acmelabs.in" in data))
            return "OK", [b""]

        def logout(self):
            pass

    monkeypatch.setattr(ce.imaplib, "IMAP4_SSL", _Imap)
    settings.gmail_app_password = "abcdabcdabcdabcd"
    counts = ce.draft_all(settings, profile, _Client({"subject": "AI Engineer role", "body": BODY}), [_lead()], 10, False)
    assert counts["in gmail"] == 1
    assert appended == [("login", "jane.jobs@example.org", "abcdabcdabcdabcd"), ('"[Gmail]/Drafts"', "\\Draft", True)]
    assert ce.read_records(settings)[0]["gmail_draft"] is True


def test_the_daily_report_lists_todays_drafts(settings, profile, no_pdf):
    from common import report

    ce.draft_all(settings, profile, _Client({"subject": "AI Engineer role", "body": BODY}), [_lead()], 10, False)
    text = report.build_report(settings, date.today())
    assert "## Cold emails drafted today (not sent)" in text
    assert "| hr@acmelabs.in | Acme Labs | AI Engineer | no |" in text


def test_her_own_addresses_are_never_leads_and_each_address_is_written_once(settings, profile):
    settings.email = "jane@naukri-login.in"
    leads = [_lead("jane.jobs@example.org"), _lead("JANE@naukri-login.in".lower()), _lead(), _lead()]
    assert [lead.email for lead in ce.unique_leads(settings, profile, leads)] == ["hr@acmelabs.in"]


def test_a_lead_uses_the_posting_saved_for_its_job(settings, profile, tmp_path):
    folder = tmp_path / "out" / "tailored" / "Acme Labs - AI Engineer"
    folder.mkdir(parents=True)
    (folder / "posting.txt").write_text("Title: AI Engineer\n\nFull posting text about agent evaluation.")
    lead = ce.unique_leads(settings, profile, [_lead(posting="share your resume at hr@acmelabs.in")])[0]
    assert "Full posting text about agent evaluation." in lead.posting
