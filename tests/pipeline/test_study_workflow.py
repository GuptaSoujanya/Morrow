"""Daily learning is a bounded subset and must not replace the job workflow."""
import datetime as dt

from common.memory import Memory, FAILED
from pipeline import run


def test_study_selects_only_course_papers_news_and_repositories():
    names = ['learn', 'research:resume', 'profile:naukri', 'apply:naukri',
             'brief:goal', 'brief:system-design', 'brief:companies',
             'brief:papers', 'brief:tech-news', 'brief:repositories']
    stages = [run.Stage(name, lambda: 0) for name in names]
    assert [stage.name for stage in run.selected(stages, ['study'], [])] == [
        'learn', 'brief:papers', 'brief:tech-news', 'brief:repositories']
    assert [stage.name for stage in run.selected(stages, ['study'], ['brief:papers'])] == [
        'learn', 'brief:tech-news', 'brief:repositories']


def test_study_preserves_unfinished_jobs_and_their_saved_options(tmp_path, monkeypatch):
    day = dt.date(2026, 11, 2)
    mem = Memory(tmp_path, day)
    options = {'cli': 'kiro', 'agents': 2, 'bots': 1, 'containers': True}
    mem.plan(['profile:naukri', 'apply:naukri'], options)
    mem.mark('profile:naukri', FAILED, 'Sign-in required')
    monkeypatch.setattr(run, 'write_index', lambda *_: None)
    monkeypatch.setattr(run, 'check_day', lambda *_: None)
    monkeypatch.setattr(run, 'sync_applied', lambda *_: None)
    args = run.parse_args(['study'])
    args.today = day
    calls = []
    stages = [run.Stage(name, lambda name=name: calls.append(name) or 0, name.startswith('brief:'))
              for name in ('learn', 'brief:papers', 'brief:tech-news', 'brief:repositories')]
    assert run.run_day(args, stages, mem) == run.EXIT_OK
    saved = Memory(tmp_path, day)
    assert set(calls) == {stage.name for stage in stages}
    assert saved.left() == ['profile:naukri', 'apply:naukri']
    assert saved.today['run_options'] == options
    assert saved.stage('profile:naukri')['status'] == FAILED
