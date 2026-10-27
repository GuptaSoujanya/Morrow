"""Selected onboarding resumes drive study prompts, with contact lines removed."""
from pathlib import Path
from datetime import date
import json
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from pdf_helpers import pdf_bytes
from common import ai_cli
from pipeline import briefing, content, learning
from common import persona


def test_selected_pdf_drives_resume_learning_and_contacts_stay_out_of_prompt(tmp_path, monkeypatch):
    if not shutil.which("pdftotext"):
        pytest.skip("Poppler is required for PDF integration tests")
    selected = tmp_path / "selected.pdf"
    selected.write_bytes(pdf_bytes("Synthetic Person\nprivate@example.com\n+91 99999 12345\nhttps://github.com/private-handle\nPython FastAPI selected resume project"))
    legacy = tmp_path / "legacy.tex"
    legacy.write_text("Unrelated LegacySkill experience\n")
    monkeypatch.setattr(learning, "RESUME_TEX", legacy)
    monkeypatch.setenv("RESUME_PATH", str(selected))
    monkeypatch.setattr(learning, "resume_areas", lambda resume_path=None: [("01", "python", "Python")])
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


def test_selected_resume_overrides_stale_onboarding_areas_and_prompt_facts(tmp_path, monkeypatch):
    selected = tmp_path / 'selected.txt'
    selected.write_text('Python and FastAPI services with PostgreSQL, Docker and PyTorch.\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    monkeypatch.setattr(persona, 'load_persona', lambda: persona.Persona(
        headline='COBOL engineer at OldEmployer', focus='COBOL',
        study_areas=[persona.StudyArea('legacy', 'COBOL and mainframes')]))
    areas = learning.resume_areas()
    titles = ' '.join(area[2] for area in areas)
    assert all(skill in titles for skill in ('Python', 'FastAPI', 'PostgreSQL', 'Docker', 'PyTorch'))
    assert 'COBOL' not in titles
    assert 'OldEmployer' not in learning.week_prompt(1, tmp_path)
    assert 'FastAPI' in briefing.context(date(2026, 10, 22), tmp_path)
    assert 'COBOL' not in briefing.brief_for(briefing.by_key('papers'))


def _week(label):
    return '# Week 1: %s\n\n' % label + '\n'.join(
        '## Day %d: %s\n\n**System Design: %s**\n' % (day, label, label)
        for day in range(1, 8))


def test_resume_change_refreshes_unfinished_days_and_preserves_completion(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python FastAPI\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'learning'
    old_path = learning.ensure_week(1, lambda prompt: _week('Python'), root)
    old_text = old_path.read_text()
    old_hash = learning.resume_fingerprint()
    learning.save_progress({'done': [1, 2], 'marked': {'2026-10-20': 1}}, root)
    assert learning.ensure_week(1, lambda prompt: pytest.fail('Current cache should be reused'), root) == old_path
    selected.write_text('Rust distributed services\n')
    prompts = []
    learning.ensure_week(1, lambda prompt: prompts.append(prompt) or _week('Rust'), root)
    sections = learning.split_days(old_path.read_text())
    assert 'Python' in sections[1] and 'Python' in sections[2]
    assert all('Rust' in sections[day] for day in range(3, 8))
    assert 'Rust distributed' in prompts[0]
    assert learning.load_progress(root)['done'] == [1, 2]
    assert learning.load_progress(root)['marked'] == {'2026-10-20': 1}
    metadata = json.loads(old_path.with_suffix('.meta.json').read_text())
    assert metadata['resume_sha256'] == learning.resume_fingerprint()
    assert metadata['day_resume_sha256']['1'] == old_hash
    assert metadata['day_resume_sha256']['3'] == learning.resume_fingerprint()
    archives = list((root / 'weeks/archive/week-01').glob('*.md'))
    assert len(archives) == 1 and archives[0].read_text() == old_text


def test_legacy_week_is_never_silently_claimed_as_current_resume(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('React TypeScript\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'learning'
    path = learning.week_path(1, root)
    path.parent.mkdir(parents=True)
    path.write_text(_week('Legacy'))
    learning.save_progress({'done': [1]}, root)
    learning.ensure_week(1, lambda prompt: _week('React'), root)
    metadata = json.loads(path.with_suffix('.meta.json').read_text())
    assert metadata['day_resume_sha256']['1'] == ''
    assert metadata['day_resume_sha256']['2'] == learning.resume_fingerprint()


def test_failed_refresh_leaves_previous_lessons_and_metadata_intact(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'learning'
    path = learning.ensure_week(1, lambda prompt: _week('Python'), root)
    old_text, old_metadata = path.read_text(), path.with_suffix('.meta.json').read_text()
    selected.write_text('TypeScript\n')
    with pytest.raises(ai_cli.AIError):
        learning.ensure_week(1, lambda prompt: '# Week 1\n## Day 1: incomplete\n', root)
    assert path.read_text() == old_text
    assert path.with_suffix('.meta.json').read_text() == old_metadata


def test_resume_topics_create_new_revisions_without_overwriting_bookmarked_paths(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python and FastAPI project A\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'topics'
    def answer(prompt):
        return '# Python\n\n## Interview questions and answers\n' + ('Project A' if 'project A' in prompt else 'Project B')
    original = learning.fill_resume_learning(answer, root)
    old_contents = {path: path.read_text() for path in original}
    assert not learning.fill_resume_learning(lambda prompt: pytest.fail('Already generated'), root)
    selected.write_text('Python and FastAPI project B\n')
    revisions = learning.fill_resume_learning(answer, root)
    assert len(revisions) == len(original) and set(revisions).isdisjoint(original)
    assert all(path.read_text() == content for path, content in old_contents.items())
    assert all('Project B' in path.read_text() for path in revisions)
    assert 'previous resume' in (root / 'README.md').read_text()
    assert not learning.missing_resume_areas(root)


def test_missing_selected_resume_fails_before_using_an_old_week(tmp_path, monkeypatch):
    monkeypatch.setenv('RESUME_PATH', str(tmp_path / 'missing.txt'))
    path = learning.week_path(1, tmp_path)
    path.parent.mkdir()
    path.write_text(_week('Legacy'))
    with pytest.raises(ai_cli.AIError, match='selected resume'):
        learning.ensure_week(1, lambda prompt: pytest.fail('Must not generate without selected evidence'), tmp_path)


def test_content_validation_selects_current_resume_revision(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'topics'
    root.mkdir()
    (root / '01-languages.md').write_text('# Old and incomplete\n')
    answer = '# Languages\n\n' + '\n'.join(content.RESUME_SECTIONS) + '\n' + '\n'.join('### Q%d' % n for n in range(5))
    learning.fill_resume_learning(lambda prompt: answer, root)
    assert content.resume_problems(root) == []
    assert (root / '01-languages.md').read_text() == '# Old and incomplete\n'


def test_daily_notes_record_actual_day_source_and_keep_prior_date_revision(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'learning'
    day, path = learning.write_today(lambda prompt: _week('Python'), root, date(2026, 10, 22))
    old_text = path.read_text()
    old_hash = learning.resume_fingerprint()
    assert json.loads(path.with_suffix('.meta.json').read_text())['resume_sha256'] == old_hash
    selected.write_text('Rust\n')
    learning.write_today(lambda prompt: _week('Rust'), root, date(2026, 10, 22))
    archived = list((root / 'daily/archive/2026-10-22').glob('*.md'))
    assert len(archived) == 1 and archived[0].read_text() == old_text
    assert json.loads(archived[0].with_suffix('.meta.json').read_text())['resume_sha256'] == old_hash


def test_resume_changed_during_generation_is_not_mislabeled_or_saved(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    def generate(prompt):
        selected.write_text('Rust\n')
        return _week('Python')
    with pytest.raises(ai_cli.AIError, match='changed during generation'):
        learning.ensure_week(1, generate, tmp_path / 'learning')
    assert not learning.week_path(1, tmp_path / 'learning').exists()


def test_selected_user_relative_resume_follows_private_data_directory(tmp_path, monkeypatch):
    private = tmp_path / 'private-data'
    selected = private / 'resume/base.tex'
    selected.parent.mkdir(parents=True)
    selected.write_text('Rust project in selected private data\n')
    monkeypatch.setenv('MORROW_USER_DIR', str(private))
    monkeypatch.setenv('RESUME_PATH', 'user/resume/base.tex')
    assert learning.selected_resume_path() == selected
    assert 'selected private data' in learning.resume_text()


def test_archived_lesson_keeps_relative_course_links_working(tmp_path):
    root = tmp_path / 'learning'
    course = tmp_path / 'course'
    course.mkdir()
    (course / 'lesson.md').write_text('# A lesson\n')
    path = learning.week_path(1, root)
    path.parent.mkdir(parents=True)
    text = '# Week 1\n\n[Lesson](../../course/lesson.md)\n'
    learning._archive(path, text)
    archived = next((path.parent / 'archive/week-01').glob('*.md'))
    assert '[Lesson](../../../../course/lesson.md)' in archived.read_text()
    from pipeline import links
    assert links.link_problems(archived) == []
