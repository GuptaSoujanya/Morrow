"""Parallel agents keep private artifacts and merge their shared user records."""

import json
import multiprocessing
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from threading import Barrier

import pytest

from common import assist, memory, report, resume
from common.answers import AnswerBook, AnswerEngine
from common.models import ApplyStatus, JobPosting, Profile, Settings
from common.ledger import Ledger
from sites_bot import browser_agent, cold_email, external


TEX = r"""\documentclass{article}
\begin{document}
{\LARGE\bfseries JANE DOE}\\[3pt]
{\normalsize\color{muted} Software Engineer}\\[5pt]
\section{Summary}
I build services with Python and JavaScript.

\section{Skills}
{\bfseries Languages:} Python, JavaScript\par\vspace{2pt}

\end{document}
"""


def test_three_simultaneous_compilers_cannot_overwrite_each_others_resumes(tmp_path, monkeypatch):
    source = tmp_path / "base.tex"
    source.write_text(TEX)
    rendezvous = Barrier(3)

    def compile_fake(tex_path, out_dir, compiler="", timeout_s=240):
        out_dir.mkdir(parents=True, exist_ok=True)
        rendezvous.wait(timeout=5)
        pdf = out_dir / (tex_path.stem + ".pdf")
        pdf.write_bytes(tex_path.read_bytes())
        rendezvous.wait(timeout=5)
        return pdf

    monkeypatch.setattr(resume, "compile_pdf", compile_fake)
    monkeypatch.setattr(resume, "pdf_page_count", lambda path: 1)
    monkeypatch.setattr(resume, "tailor", lambda client, base, job: (
        replace(base.sections, summary=job.description), []))

    def build(site):
        settings = Settings(resume_path=str(source), resume_out_dir=str(tmp_path / "out" / "runs" / site))
        job = JobPosting(job_id=site + ":1", url="https://" + site + ".test/1",
                         company="Same Company", title="Same Role", description="Posting for " + site)
        pdf, _ = resume.build_tailored_pdf(settings, None, job)
        return site, pdf

    with ThreadPoolExecutor(max_workers=3) as pool:
        built = list(pool.map(build, ["naukri", "hirist", "instahyre"]))
    assert len({pdf for _, pdf in built}) == 3
    for site, pdf in built:
        assert "Posting for " + site in pdf.read_text()
        record = json.loads((pdf.parent / "tailoring.json").read_text())
        assert record["job_id"] == site + ":1"
    assert source.read_text() == TEX


def _saved_posting(root, job_id, address, generated="2026-10-24T12:00:00", url=None):
    folder = root / "tailored" / "Same Company - Same Role"
    folder.mkdir(parents=True)
    (folder / "posting.txt").write_text(
        "Title: Same Role\nCompany: Same Company\nURL: %s\n\nSend your resume to %s" % (url or job_id, address))
    (folder / "tailoring.json").write_text(json.dumps({"job_id": job_id, "url": url or job_id, "generated_at": generated}))
    (folder / "Resume.pdf").write_bytes(job_id.encode())
    return folder


def test_library_readers_find_legacy_direct_and_pipeline_runs(tmp_path, monkeypatch):
    root = tmp_path / "out"
    _saved_posting(root, "legacy", "careers@legacy.org")
    _saved_posting(root / "runs" / "one", "hirist:1", "careers@hirist.org")
    _saved_posting(root / "runs" / "pipeline" / "lanes" / "instahyre", "instahyre:1", "careers@instahyre.org")
    current = root / "runs" / "emails"
    settings = Settings(resume_out_dir=str(current), report_dir=str(tmp_path / "reports"), data_dir=str(tmp_path / "inputs"))
    monkeypatch.setenv("MORROW_RESUME_LIBRARY_DIR", str(root))
    assert len(resume.tailored_artifact_paths(settings, "posting.txt")) == 3
    assert {lead.email for lead in cold_email.leads_from_files(settings)} == {
        "careers@legacy.org", "careers@hirist.org", "careers@instahyre.org"}
    assert {record["job_id"] for record in report._tailored_today(settings, date(2026, 10, 24))} == {
        "legacy", "hirist:1", "instahyre:1"}


def test_previous_resume_and_posting_are_matched_by_exact_job_id(tmp_path, monkeypatch):
    root = tmp_path / "out"
    _saved_posting(root / "runs" / "one", "hirist:1", "careers@one.org")
    expected = _saved_posting(root / "runs" / "two", "instahyre:1", "careers@two.org", url="https://instahyre.test/jobs/1")
    settings = Settings(resume_out_dir=str(root / "runs" / "emails"))
    monkeypatch.setenv("MORROW_RESUME_LIBRARY_DIR", str(root))
    lead = cold_email.Lead("careers@two.org", "Same Company", "Same Role", "https://instahyre.test/jobs/1", "test")
    assert cold_email.attachment_for(settings, lead) == expected / "Resume.pdf"
    kept = cold_email.unique_leads(settings, Profile(), [lead])
    assert "careers@two.org" in kept[0].posting
    assert "careers@one.org" not in kept[0].posting
    other = JobPosting(job_id="other:1", url="other:1", company="Same Company", title="Same Role")
    assert resume.saved_tailoring_dir(settings, other) is None


def _write_agent_records(folder, site, start):
    root = Path(folder)
    settings = Settings(data_dir=str(root / "inputs"), profile_path=str(root / "inputs" / "profile.yaml"),
                        report_dir=str(root / "reports"))
    engine = AnswerEngine(None, None, Profile(), settings)
    start.wait(timeout=15)
    engine.book.add_blank("Shared unanswered question", "missing")
    for index in range(6):
        engine._keep_judged("%s answer %d?" % (site, index), "%s value %d" % (site, index),
                            {"reason": "Given in the test profile", "evidence": "Test evidence"}, saved=True)
        question = "%s assisted %d?" % (site, index)
        engine.book.add_blank(question, "missing")
        assert assist._apply(settings, assist.Change("answers.txt", question, "filled", "profile", "Test evidence"), set())
        job = JobPosting(job_id="%s:%d" % (site, index), url="https://%s.test/%d" % (site, index),
                         company=site, title="Role %d" % index)
        external.record_company_site(settings, job, external.ExternalResult(ApplyStatus.EXTERNAL_MANUAL, detail="Needs user"))
        memory.record_profile(site, memory.PROFILE_UPDATED, "https://%s.test/profile" % site, folder=root / "memory")
    assert assist._apply(settings, assist.Change("profile.yaml", site, site + " fact", "resume", "Test evidence"), set())


def test_parallel_processes_preserve_answers_facts_worklist_and_profile_history(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "answers.txt").write_text("Q: Existing answer\nA: Keep this\n")
    (inputs / "profile.yaml").write_text("naukri: null\nhirist: null\ninstahyre: null\n")
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(3)
    sites = ["naukri", "hirist", "instahyre"]
    processes = [context.Process(target=_write_agent_records, args=(str(tmp_path), site, start)) for site in sites]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert [process.exitcode for process in processes] == [0, 0, 0]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    book = AnswerBook(str(inputs / "answers.txt"))
    assert book.answer_for("Existing answer") == "Keep this"
    assert (inputs / "answers.txt").read_text().count("Q: Shared unanswered question") == 1
    written = {question: answer for questions, answer in book.entries for question in questions}
    for site in sites:
        for index in range(6):
            assert written["%s answer %d?" % (site, index)] == "%s value %d" % (site, index)
            assert book.answer_for("%s assisted %d?" % (site, index)) == "filled"
        assert site + " fact" in (inputs / "profile.yaml").read_text()
    pending = external.pending_company_sites(Settings(data_dir=str(inputs)))
    assert len(pending) == 18
    profiles = memory.load_profiles(tmp_path / "memory")
    assert set(profiles) == set(sites)
    assert all(len(entry["history"]) == 6 for entry in profiles.values())
    assert len(assist.read_changes(Settings(report_dir=str(tmp_path / "reports")))) == 39


def test_agent_transcripts_get_distinct_folders_even_with_same_label_and_time(tmp_path):
    settings = Settings(report_dir=str(tmp_path))
    now = datetime(2026, 10, 24, 12, 0)
    paths = [browser_agent.workdir_for(settings, "Same Company Same Role", now) for _ in range(3)]
    assert len(set(paths)) == 3
    assert all(path.parent == tmp_path / "2026-10-24" / "agent" for path in paths)


def _open_parallel_ledger(path, site, start):
    # Widen the old check-then-ALTER race without replacing SQLite transactions.
    original_connect = sqlite3.connect

    class SlowSchemaConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            cursor = super().execute(sql, *args, **kwargs)
            if sql.startswith("PRAGMA table_info("):
                rows = list(cursor)
                time.sleep(0.03)
                return rows
            return cursor

    sqlite3.connect = lambda *args, **kwargs: original_connect(*args, factory=SlowSchemaConnection, **kwargs)
    start.wait(timeout=15)
    with Ledger(path) as ledger:
        ledger.record_seen(JobPosting(job_id=site + ":1", url="https://%s.test/1" % site, title=site))


@pytest.mark.parametrize("legacy", [False, True], ids=["first-launch", "old-schema"])
def test_three_processes_can_initialize_and_migrate_one_ledger(tmp_path, legacy):
    path = tmp_path / "ledger.db"
    if legacy:
        with sqlite3.connect(path) as connection:
            connection.executescript("""
                CREATE TABLE answers(question_norm TEXT PRIMARY KEY, answer TEXT);
                INSERT INTO answers VALUES ('existing', 'Keep this');
                CREATE TABLE applications(id INTEGER PRIMARY KEY, job_id TEXT, at TEXT);
            """)
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(3)
    sites = ["naukri", "hirist", "instahyre"]
    processes = [context.Process(target=_open_parallel_ledger, args=(str(path), site, start)) for site in sites]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        assert [process.exitcode for process in processes] == [0, 0, 0]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    with sqlite3.connect(path) as connection:
        assert {row[0] for row in connection.execute("SELECT job_id FROM jobs_seen")} == {site + ":1" for site in sites}
        assert [row[1] for row in connection.execute("PRAGMA table_info(answers)")].count("profile_fingerprint") == 1
        assert [row[1] for row in connection.execute("PRAGMA table_info(applications)")].count("facts_fingerprint") == 1
        if legacy:
            assert connection.execute("SELECT answer FROM answers WHERE question_norm='existing'").fetchone()[0] == "Keep this"
