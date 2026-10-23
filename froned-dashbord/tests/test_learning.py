"""Durability and reading direction; all progress writes stay in temporary workspaces."""
import datetime as dt
import importlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from common import learning_memory as memory
from pipeline import learning
from web import state
import dashboard_data
import research_learning


def _complete(args):
    root, number = args
    memory.set_course(Path(root), f'lesson-{number}.md', True, f'Lesson {number}')


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for key, relative in [('APPLY','.'),('COURSE','course'),('REPORTS','data/reports'),('STUDIED','data/reports/studied.json')]:
        monkeypatch.setattr(state, key, tmp_path / relative)
    course = tmp_path / 'course';course.mkdir()
    (course / '_sidebar.md').write_text('- **Systems**\n  - [Introduction](intro.md)\n')
    (course / 'intro.md').write_text('# Introduction\nA lesson.')
    root = tmp_path / '.research/learning';(root / 'weeks').mkdir(parents=True)
    (root / 'weeks/week-01.md').write_text('# Week 1\n\n## Day 1: Client and server\nRead the first topic.\n\n## Day 2: Caching\nRead the second topic.\n')
    (root / 'progress.json').write_text('{"start":"2026-10-22"}')
    (root / 'daily').mkdir()
    (root / 'daily/2026-10-22.md').write_text('# 2026-10-22: Day 1 of 90\n## Day 1: Client and server\nRead.')
    (root / 'today.md').write_text('# 2026-10-23: Day 1 of 90\n## Day 1: Client and server\nRead.')
    brief = tmp_path / '.research/daily/2026-10-22';brief.mkdir(parents=True)
    (brief / 'README.md').write_text('# Saved briefing\nA real dated briefing.')
    return tmp_path


def test_migrates_legacy_progress_once_and_preserves_originals(workspace):
    state.STUDIED.parent.mkdir(parents=True)
    state.STUDIED.write_text('["intro.md"]')
    path = workspace / '.research/learning/progress.json'
    path.write_text('{"done":[1],"start":"2026-10-22"}')
    data = memory.transact(workspace)
    assert data['course']['intro.md']['done'] and data['plan']['done'] == [1]
    assert 'completed_at' not in data['course']['intro.md']
    assert data['history'] == []
    assert (workspace / '.memory/learning.json').is_file()
    state.mark_studied('intro.md',False)
    assert not state.studied()
    assert state.STUDIED.read_text() == '["intro.md"]'
    assert json.loads(path.read_text())['done'] == [1]
    importlib.reload(memory)
    assert not state.studied()  # no reimport from the unchanged legacy file


def test_daily_direction_aliases_and_history_are_consistent(workspace):
    first = research_learning.summary()
    assert first['focus']['day'] == 1 and first['plan_done'] == 0
    assert '2026-10-22' in first['queue'][1]['caption']
    assert not dashboard_data.artifact('plan/day-1')['read']
    assert 'Client and server' in dashboard_data.artifact('plan/day-1')['html']
    research_learning.mark('research/learning/today.md', True)
    research_learning.mark('research/learning/daily/2026-10-22.md', True)
    data = research_learning.summary()
    assert data['focus']['day'] == 2 and data['plan_done'] == 1
    assert len(data['completed_today']) == 1 and data['history']['total'] == 1
    assert dashboard_data.artifact('plan/day-1')['read']
    state.mark_studied('intro.md',True)
    assert len(research_learning.summary()['completed_today']) == 2
    research_learning.mark('plan/day-1',False)
    assert research_learning.summary()['focus']['day'] == 1
    assert research_learning.summary()['plan_done'] == 0
    assert research_learning.summary()['history']['items'][0]['action'] == 'reopened'
    assert len(research_learning.summary()['completed_today']) == 1


def test_cli_and_dashboard_use_the_same_locked_progress(workspace):
    root = workspace / '.research/learning'
    assert learning.mark_done(root) == 1
    assert research_learning.summary()['focus']['day'] == 2
    assert learning.mark_done(root) == 1  # same-day CLI retry remains idempotent
    stale = learning.load_progress(root)
    research_learning.mark('plan/day-2',True)
    learning.save_progress(stale,root)
    assert learning.load_progress(root)['done'] == [1,2]
    assert state.studied() == set()


def test_independent_processes_do_not_lose_each_others_progress(workspace):
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(_complete, [(str(workspace),n) for n in range(16)]))
    data = memory.transact(workspace)
    assert len(data['course']) == 16 and len(data['history']) == 16
    assert all(value['done'] for value in data['course'].values())


def test_corruption_is_reported_and_never_reset(workspace):
    memory.transact(workspace)
    path = workspace / '.memory/learning.json';path.write_text('{damaged')
    with pytest.raises(ValueError,match='not been reset'):
        state.mark_studied('intro.md')
    assert path.read_text() == '{damaged'


def test_failed_atomic_replace_preserves_previous_commit(workspace,monkeypatch):
    memory.set_course(workspace,'intro.md',True)
    path=workspace/'.memory/learning.json';before=path.read_bytes()
    def fail(*args):raise OSError('Disk unavailable')
    monkeypatch.setattr(memory.os,'replace',fail)
    with pytest.raises(OSError):memory.set_course(workspace,'intro.md',False)
    assert path.read_bytes()==before
    assert not list(path.parent.glob('.learning-*'))


def test_unknown_document_wrong_boolean_and_missing_plan_are_rejected(workspace):
    for identifier in ['research/../../.env','plan/day-0','plan/day-91','research/absent.md']:
        with pytest.raises(ValueError):research_learning.mark(identifier,True)
    with pytest.raises(ValueError):research_learning.mark('plan/day-1','false')
    with pytest.raises(ValueError,match='not in the saved'):dashboard_data.artifact('plan/day-3')
    assert research_learning.summary()['plan_done'] == 0


def test_history_is_bounded_and_survives_reload(workspace):
    for n in range(19):memory.set_course(workspace,f'lesson-{n}.md',True)
    importlib.reload(memory)
    data=research_learning.summary({'page':'2'})
    assert data['history']['page']==2 and len(data['history']['items'])==4
    assert data['history']['total']==19
    assert research_learning.summary({'page':'999'})['history']['page']==2


def test_malformed_history_is_reported_without_overwriting(workspace):
    data=memory.transact(workspace);data['history']=[{'action':'completed'}]
    path=workspace/'.memory/learning.json';path.write_text(json.dumps(data));before=path.read_bytes()
    with pytest.raises(ValueError,match='history.*not been reset'):research_learning.summary()
    assert path.read_bytes()==before


def test_daily_desk_exposes_each_source_without_substituting_another_date(workspace):
    folder=workspace/'.research/daily/2026-10-22'
    for filename,title in [('01-goal.md','Goal'),('02-system-design.md','Design'),('03-papers.md','Papers'),('04-tech-news.md','Tech news'),('05-companies.md','Companies')]:
        (folder/filename).write_text(f'# {title}\n\n## First saved section\nA real note.\n\n## Second saved section\nMore detail.')
    old=research_learning.summary({'date':'2026-10-22'})['briefing']
    assert old['ready']==6 and old['total']==6
    assert {section['key'] for section in old['sections']}=={'digest','papers','tech','companies','goal','design'}
    assert all(section['document']['id'].startswith('research/daily/2026-10-22/') for section in old['sections'])
    papers=next(section for section in old['sections'] if section['key']=='papers')
    assert papers['document']['preview']==['First saved section','Second saved section']
    missing=research_learning.summary({'date':'2026-10-23'})['briefing']
    assert missing['ready']==0 and missing['latest']=='2026-10-22'
    assert all(section['document'] is None for section in missing['sections'])
    with pytest.raises(ValueError,match='research date'):research_learning.summary({'date':'2026-02-30'})


def test_resume_learning_has_its_own_topics_and_a_complete_index(workspace):
    root=workspace/'.research/resume-learning';root.mkdir()
    for number,title in [(1,'Evaluation'),(2,'Serving'),(3,'Infrastructure')]:
        (root/f'{number:02}-topic.md').write_text(f'# {title}\n\n## Core concepts\nAn explanation.')
    learning.write_resume_index(root)
    index=(root/'README.md').read_text()
    assert index.startswith('# Resume learning') and all(f'{n:02}-topic.md' in index for n in range(1,4))
    assert '## Core concepts' not in index
    data=research_learning.summary()['resume']
    assert len(data['topics'])==3 and data['index']['title']=='Resume learning'
    assert [item['title'] for item in data['topics']]==['Evaluation','Serving','Infrastructure']
    research_learning.mark(data['topics'][0]['id'],True)
    assert research_learning.summary()['resume']['topics'][0]['read'] is True
    assert research_learning.summary()['plan_done']==0
