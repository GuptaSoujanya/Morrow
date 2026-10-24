"""Selected onboarding resumes drive study prompts, with contact lines removed."""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes
from common import ai_cli
from pipeline import learning


def test_selected_pdf_drives_resume_learning_and_contacts_stay_out_of_prompt(tmp_path, monkeypatch):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    selected = tmp_path / "selected.pdf"
    selected.write_bytes(pdf_bytes("Synthetic Person\nprivate@example.com\n+91 99999 12345\nhttps://github.com/private-handle\nPython FastAPI selected resume project"))
    legacy = tmp_path / "legacy.tex"
    legacy.write_text("Unrelated LegacySkill experience\n")
    monkeypatch.setattr(learning, "RESUME_TEX", legacy)
    monkeypatch.setenv("RESUME_PATH", str(selected))
    monkeypatch.setattr(learning, "RESUME_AREAS", (("01", "python", "Python"),))
    prompts = []
    written = learning.fill_resume_learning(lambda prompt: prompts.append(prompt) or "# Python\n\n## Interview questions and answers\nSynthetic answer", tmp_path / "study")
    assert len(written) == 1 and len(prompts) == 1
    assert "selected resume project" in prompts[0] and "LegacySkill" not in prompts[0]
    assert "private@example.com" not in prompts[0] and "99999" not in prompts[0] and "private-handle" not in prompts[0]
    assert "LaTeX source" not in prompts[0] and "%PDF" not in prompts[0]


def test_explicit_tex_path_wins_over_environment_and_keeps_original_structure(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.tex"
    explicit.write_text("\\textbf{ExplicitSkill}\n\\href{mailto:hidden@example.com}{Email}\nA selected project\n")
    monkeypatch.setenv("RESUME_PATH", str(tmp_path / "missing.pdf"))
    text = learning.resume_text(explicit)
    assert "\\textbf{ExplicitSkill}" in text and "A selected project" in text
    assert "hidden@example.com" not in text


def test_no_selected_input_keeps_legacy_resume_path(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.tex"
    legacy.write_text("Legacy resume facts\n")
    monkeypatch.delenv("RESUME_PATH", raising=False)
    monkeypatch.setattr(learning, "RESUME_TEX", legacy)
    assert learning.resume_text() == "Legacy resume facts"


def test_unreadable_selected_pdf_does_not_fall_back_or_call_an_ai(tmp_path, monkeypatch):
    selected = tmp_path / "selected.pdf"
    selected.write_bytes(b"not a PDF")
    monkeypatch.setenv("RESUME_PATH", str(selected))
    with pytest.raises(ai_cli.AIError, match="valid resume PDF"):
        learning.fill_resume_learning(lambda prompt: pytest.fail("An AI was called without resume facts"), tmp_path / "study")
    assert not (tmp_path / "study").exists()
