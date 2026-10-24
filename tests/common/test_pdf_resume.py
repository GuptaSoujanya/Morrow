"""Uploaded PDF resumes are readable inputs and unchanged attachments."""
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes
from common import profile, resume
from common.models import JobPosting, Settings


@pytest.fixture
def pdf(tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    path = tmp_path / "candidate.PDF"
    path.write_bytes(pdf_bytes("Synthetic Person - Python engineer - SQL"))
    return path


def test_pdf_text_extraction_supports_the_uploaded_resume(pdf, tmp_path):
    facts = tmp_path / "profile.yaml"
    facts.write_text("full_name: Synthetic Person\nemail: synthetic@example.com\n")
    result = profile.load_profile(Settings(profile_path=str(facts), resume_path=str(pdf)))
    assert "Synthetic Person" in result.resume_text
    assert "Python" in result.skills and "SQL" in result.skills
    assert "%PDF" not in result.resume_text


def test_pdf_attachment_is_original_without_compile_or_writes(pdf, monkeypatch):
    original = pdf.read_bytes(), pdf.stat().st_mtime_ns
    monkeypatch.setattr(resume, "compile_pdf", lambda *a, **kw: pytest.fail("Uploaded PDF must not be compiled"))
    output = pdf.parent / "unused-output"
    result = resume.build_base_pdf(Settings(resume_path=str(pdf), resume_out_dir=str(output)))
    assert result == pdf.resolve()
    assert (pdf.read_bytes(), pdf.stat().st_mtime_ns) == original
    assert not output.exists()


def test_pdf_tailoring_fails_before_binary_decoding_or_model_call(pdf):
    client = SimpleNamespace(complete_json=lambda *a: pytest.fail("PDF tailoring called an AI model"))
    with pytest.raises(resume.ResumeError, match=r"tailoring requires.*\.tex"):
        resume.build_tailored_pdf(Settings(resume_path=str(pdf)), client, JobPosting("synthetic", "https://example.com/job"))


@pytest.mark.parametrize("content,repair", [(pdf_bytes(""), "selectable text"), (pdf_bytes(pages=21), "20 pages"), (b"%PDF-1.4\ninvalid", "unlocked PDF")], ids=["scanned", "too-many-pages", "invalid"])
def test_unusable_pdf_has_actionable_error_without_invented_text(content, repair):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    with pytest.raises(profile.ProfileError, match=repair):
        profile.extract_pdf_text(content)


def test_missing_parser_explains_the_prerequisite(monkeypatch):
    monkeypatch.setattr(profile.shutil, "which", lambda binary: None)
    with pytest.raises(profile.ProfileError, match="Install Poppler"):
        profile.extract_pdf_text(pdf_bytes())


def test_parser_errors_do_not_expose_pdf_content(monkeypatch):
    monkeypatch.setattr(profile.shutil, "which", lambda binary: "/synthetic/pdftotext")
    monkeypatch.setattr(profile.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b"private resume", stderr=b"token=secret"))
    with pytest.raises(profile.ProfileError) as caught:
        profile.extract_pdf_text(pdf_bytes())
    assert "secret" not in str(caught.value) and "private resume" not in str(caught.value)


def test_pdf_parser_timeout_returns_a_fix(monkeypatch):
    monkeypatch.setattr(profile.shutil, "which", lambda binary: "/synthetic/pdftotext")
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("pdftotext", 15)
    monkeypatch.setattr(profile.subprocess, "run", timeout)
    with pytest.raises(profile.ProfileError, match="simpler PDF"):
        profile.extract_pdf_text(pdf_bytes())
