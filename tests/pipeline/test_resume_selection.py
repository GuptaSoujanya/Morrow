"""Resume topics stay personal; the shared interview course stays independent."""
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
    context = briefing.context(date(2026, 10, 22), tmp_path)
    assert 'FastAPI' not in context
    assert 'FastAPI' in briefing.prompt_for(briefing.by_key('companies'), context)
    assert 'COBOL' not in briefing.brief_for(briefing.by_key('papers'))


def _day(day, label):
    small = '\n\n'.join('### ' + title + '\nA worked example.' for title in
                         ('Words you need', 'The idea', 'A small example', 'Your turn', 'Check your answer')) + '\n\n---'
    return '## Day %d: %s\n\n' % (day, label) + '\n\n'.join(
        '**%s: %s**\n%s' % (part, label, small)
        for part in ('System Design', 'ML / GenAI', 'Full-stack', 'DSA')) + (
            '\n\n**Recall**\nExplain the example.\n\n**Go deeper**\n- [Docs](https://docs.python.org/3/)\n')


def _week(label):
    return '# Week 1: %s\n\n' % label + '\n'.join(_day(day, label) for day in range(1, 8))


def test_resume_change_does_not_change_shared_course_or_completed_reading(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('Python FastAPI\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    root = tmp_path / 'learning'
    path = learning.ensure_week(1, lambda prompt: _week('Shared course'), root)
    original = learning.split_days(path.read_text())[1]
    learning.save_progress({'done': [1, 2], 'marked': {'2026-10-20': 1}}, root)
    learning.ensure_day(3, lambda prompt: _day(3, 'After prior reading'), root)
    before = path.read_text(), path.with_suffix('.meta.json').read_text()
    selected.write_text('Rust distributed services\n')
    assert learning.ensure_day(3, lambda prompt: pytest.fail('Resume must not change the course'), root) == path
    assert (path.read_text(), path.with_suffix('.meta.json').read_text()) == before
    assert learning.split_days(path.read_text())[1] == original
    assert learning.load_progress(root)['done'] == [1, 2]
    assert learning.load_progress(root)['marked'] == {'2026-10-20': 1}
    metadata = json.loads(path.with_suffix('.meta.json').read_text())
    assert metadata['course_id'] == 'interview-90' and 'resume_sha256' not in metadata


def test_legacy_week_and_completion_are_not_relabelled_as_shared_course(tmp_path):
    root = tmp_path / 'learning'
    old = root / 'weeks/week-01.md'
    old.parent.mkdir(parents=True)
    old.write_text(_week('Legacy'))
    (root / 'progress.json').write_text(json.dumps({'done': [1]}))
    path = learning.ensure_week(1, lambda prompt: _week('Shared'), root)
    assert path != old and old.read_text() == _week('Legacy')
    assert json.loads((root / 'progress.json').read_text()) == {'done': [1]}
    assert learning.load_progress(root)['done'] == []
    assert json.loads(path.with_suffix('.meta.json').read_text())['course_id'] == 'interview-90'


def test_failed_refresh_leaves_previous_lessons_and_metadata_intact(tmp_path):
    root = tmp_path / 'learning'
    path = learning.ensure_week(1, lambda prompt: _week('Shared'), root)
    old_text, old_metadata = path.read_text(), path.with_suffix('.meta.json').read_text()
    learning.mark_done(root, date(2026, 10, 22))
    with pytest.raises(ai_cli.AIError):
        learning.ensure_day(2, lambda prompt: '## Day 2: incomplete\n', root)
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


def test_missing_selected_resume_does_not_block_shared_course(tmp_path, monkeypatch):
    monkeypatch.setenv('RESUME_PATH', str(tmp_path / 'missing.txt'))
    path = learning.ensure_day(1, lambda prompt: _day(1, 'Shared'), tmp_path)
    assert path.exists() and 'Shared' in path.read_text()


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


def test_daily_notes_record_course_source_and_keep_prior_date_revision(tmp_path):
    root = tmp_path / 'learning'
    day, path = learning.write_today(lambda prompt: _day(1, 'First lesson'), root, date(2026, 10, 22))
    old_text = path.read_text()
    old_metadata = json.loads(path.with_suffix('.meta.json').read_text())
    assert old_metadata['course_id'] == 'interview-90' and old_metadata['plan_day'] == 1
    learning.mark_done(root, date(2026, 10, 22))
    learning.write_today(lambda prompt: _day(2, 'Next lesson'), root, date(2026, 10, 22))
    archived = list((learning.content_root(root) / 'daily/archive/2026-10-22').glob('*.md'))
    assert len(archived) == 1 and archived[0].read_text() == old_text
    assert json.loads(archived[0].with_suffix('.meta.json').read_text()) == old_metadata


def test_resume_change_during_generation_does_not_change_course_source(tmp_path, monkeypatch):
    selected = tmp_path / 'resume.txt'
    selected.write_text('PrivateResumeStack\n')
    monkeypatch.setenv('RESUME_PATH', str(selected))
    def generate(prompt):
        selected.write_text('ChangedPrivateStack\n')
        assert 'PrivateResumeStack' not in prompt and 'ChangedPrivateStack' not in prompt
        return _day(1, 'Shared')
    path = learning.ensure_day(1, generate, tmp_path / 'learning')
    assert json.loads(path.with_suffix('.meta.json').read_text())['course_id'] == 'interview-90'


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
    text = '# Week 1\n\n[Lesson](../../../course/lesson.md)\n'
    learning._archive(path, text)
    archived = next((path.parent / 'archive/week-01').glob('*.md'))
    assert '[Lesson](../../../../../course/lesson.md)' in archived.read_text()
    from pipeline import links
    assert links.link_problems(archived) == []
