"""Learning fetches share output locks with manually started pipeline stages."""
import sys

import pytest

from common import browser_lanes
from web import run_isolation
from web.runner import Run, Runner, conflicts, resources_for
from web.state import Command


def command(*args):
    return Command('Daily course & discoveries', (sys.executable, '-m', 'pipeline', *args))


def resources(*args, action='pipeline'):
    return resources_for(command(*args), action)


@pytest.mark.parametrize('action,args', [
    ('learning-feed', ('study',)),
    ('pipeline', ('study',)),
    ('pipeline', ('continue', '--only', 'study')),
])
def test_study_reserves_only_its_four_outputs_and_no_job_browser_resources(action, args):
    actual = resources(*args, action=action)
    assert actual == frozenset({'pipeline:writer', 'stage:learn', 'stage:brief:papers',
                                'stage:brief:tech-news', 'stage:brief:repositories'})
    assert not any(key.startswith('browser:') for key in actual)
    for group in ('profile', 'apply', 'research:resume', 'brief:companies', 'brief:goal', 'brief:system-design'):
        assert not conflicts(actual, resources('continue', '--only', group))


def test_feed_conflicts_with_all_four_manual_stages_and_full_briefing():
    feed = resources('study', action='learning-feed')
    for stage in ('learn', 'brief:papers', 'brief:tech-news', 'brief:repositories', 'brief', 'study'):
        assert conflicts(feed, resources('continue', '--only', stage)), stage
    assert conflicts(feed, resources('continue', '--only', 'apply:naukri', '--fresh'))
    without_repos = resources('study', '--skip', 'brief:repositories')
    assert not conflicts(without_repos, resources('continue', '--only', 'brief:repositories'))


@pytest.mark.parametrize('action', ['learning-feed', 'pipeline'])
def test_study_never_initializes_browser_profiles(tmp_path, monkeypatch, action):
    monkeypatch.setattr(browser_lanes, 'prepare_all', lambda *_args, **_kwargs: pytest.fail('Study has no browser work.'))
    item = command('study')
    run_isolation.prepare(tmp_path, item, action, 'study-run', {}, resources_for(item, action))
    assert not list(tmp_path.iterdir())


def test_manual_stage_cannot_start_after_feed_but_independent_profile_can(monkeypatch):
    runner = Runner()
    def started(item, action, day, reserved, prepared=None):
        run = Run(item, action, day, reserved)
        runner.runs[run.id] = run
        return run.id
    monkeypatch.setattr(runner, '_start_locked', started)
    runner.start(command('study'), 'learning-feed')
    for stage in ('learn', 'brief:papers', 'brief:tech-news', 'brief:repositories'):
        with pytest.raises(RuntimeError, match='still running'):
            runner.start(command('continue', '--only', stage), 'pipeline')
    runner.start(command('continue', '--only', 'profile:linkedin'), 'pipeline')
    assert len(runner.runs) == 2


def test_feed_cannot_start_after_a_manual_repository_fetch(monkeypatch):
    runner = Runner()
    def started(item, action, day, reserved, prepared=None):
        run = Run(item, action, day, reserved)
        runner.runs[run.id] = run
        return run.id
    monkeypatch.setattr(runner, '_start_locked', started)
    runner.start(command('continue', '--only', 'brief:repositories'), 'pipeline')
    with pytest.raises(RuntimeError, match='still running'):
        runner.start(command('study'), 'learning-feed')
    assert len(runner.runs) == 1
