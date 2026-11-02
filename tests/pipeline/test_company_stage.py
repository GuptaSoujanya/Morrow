from argparse import Namespace
from datetime import date
from common.memory import Memory
from pipeline import run


def args():
    return Namespace(fresh=False,dry_run=False,env=None,verbose=False,cli=None,only=[],skip=[],redo=False,
                     agents=2,bots=1,containers=False,no_watch=True,today=date(2026,11,2),command='continue')


def test_company_research_waits_for_every_lane_and_other_research(tmp_path, monkeypatch):
    calls=[]
    monkeypatch.setattr(run, '_companies_left', lambda _:0)
    monkeypatch.setattr(run, 'sync_applied', lambda *a:None)
    monkeypatch.setattr(run, 'write_index', lambda *a:None)
    stages=[run.Stage('apply:naukri', lambda:calls.append('apply') or 0),
            run.Stage('research:resume', lambda:calls.append('resume') or 0, parallel=True),
            run.Stage('research:companies', lambda:calls.append('companies') or 0, final=True)]
    mem=Memory(tmp_path,args().today)
    assert run.run_day(args(), stages, mem) == 0
    assert calls[-1] == 'companies' and len(calls)==3


def test_new_jobs_reopen_completed_company_stage_and_remaining_batch_stays_pending(tmp_path, monkeypatch):
    pending=[0];calls=[]
    monkeypatch.setattr(run, '_companies_left', lambda _:pending[0])
    mem=Memory(tmp_path,args().today)
    stages=[run.Stage('research:companies', lambda:calls.append('batch') or 0, final=True)]
    run.run_day(args(),stages,mem)
    assert mem.is_done('research:companies')
    pending[0]=5
    run.run_day(args(),stages,mem)
    assert len(calls)==2 and mem.stage('research:companies')['status']=='pending'


def test_company_research_is_last_and_can_be_selected_independently():
    stages=run.build_stages(args(),['hirist'])
    assert stages[-1].name=='research:companies' and stages[-1].final
    assert [s.name for s in run.selected(stages,['research:companies'],[])]==['research:companies']
