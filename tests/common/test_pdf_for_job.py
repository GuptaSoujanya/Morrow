"""The upload step attaches the PDF tailored for the posting or its company when there is one, else the base resume."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import resume
from common.models import JobPosting, Settings


def _settings(tmp_path):
    return Settings(resume_path=str(tmp_path / "onboarding.pdf"), resume_out_dir=str(tmp_path / "out"))


def _pdf(folder, name="resume.pdf", age=0.0):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.4 " + name.encode())
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_without_a_tailored_pdf_the_fallback_is_sent(tmp_path):
    job = JobPosting(job_id="1", url="u", title="Backend Engineer", company="Coris")
    base = _pdf(tmp_path, "onboarding.pdf")
    assert resume.pdf_for_job(_settings(tmp_path), job, base) == base
    assert resume.pdf_for_job(_settings(tmp_path), job, None) is None


def test_the_pdf_tailored_for_this_posting_wins(tmp_path):
    settings = _settings(tmp_path)
    job = JobPosting(job_id="1", url="u", title="Back End Engineer", company="Coris")
    base = _pdf(tmp_path, "onboarding.pdf")
    own = _pdf(resume.tailored_dir(settings, job), "Soujanya_Gupta_Resume.pdf")
    other = _pdf(tmp_path / "out" / "tailored" / "Coris - Platform Engineer", "Soujanya_Gupta_Resume.pdf", age=60)
    assert resume.pdf_for_job(settings, job, base) == own
    assert resume.tailored_pdfs_for(settings, job) == [own, other]


def test_a_pdf_tailored_for_the_same_company_is_used_for_another_role(tmp_path):
    settings = _settings(tmp_path)
    base = _pdf(tmp_path, "onboarding.pdf")
    older = _pdf(tmp_path / "out" / "tailored" / "Coris - Back End Engineer", "Soujanya_Gupta_Resume.pdf", age=120)
    newer = _pdf(tmp_path / "out" / "tailored" / "Coris - Platform Engineer", "Soujanya_Gupta_Resume.pdf", age=10)
    _pdf(tmp_path / "out" / "tailored" / "Corisco - Platform Engineer", "Soujanya_Gupta_Resume.pdf")
    job = JobPosting(job_id="9", url="u9", title="Data Engineer", company="Coris")
    assert resume.pdf_for_job(settings, job, base) == newer
    assert older in resume.tailored_pdfs_for(settings, job)
    unrelated = JobPosting(job_id="10", url="u10", title="Data Engineer", company="Zeta")
    assert resume.pdf_for_job(settings, unrelated, base) == base


def test_uploaded_pdf_is_the_resume_path_when_it_is_a_pdf(tmp_path):
    assert resume.uploaded_pdf(_settings(tmp_path)) is None
    base = _pdf(tmp_path, "onboarding.pdf")
    assert resume.uploaded_pdf(_settings(tmp_path)) == base.resolve()
    assert resume.uploaded_pdf(Settings(resume_path=str(tmp_path / "resume.tex"))) is None
