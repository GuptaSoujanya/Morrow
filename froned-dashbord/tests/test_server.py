"""Dashboard integration checks use only temporary files and never start the bots."""
import importlib.util
import json
import sys
import threading
import http.client
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('dashboard_server', Path(__file__).parents[1] / 'server.py')
dashboard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dashboard
spec.loader.exec_module(dashboard)

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard.state, 'APPLY', tmp_path)
    profile = tmp_path / 'profile.yaml'
    profile.write_text('name: Before\n')
    monkeypatch.setattr(dashboard.server, 'files', lambda: {'profile': profile})
    server = dashboard.DashboardServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, profile
    server.shutdown()
    server.server_close()
    thread.join()

def request(app, method, path, body=None, headers=None):
    server, _ = app
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
    connection.request(method, path, body=json.dumps(body) if body is not None else None,
                       headers={'Content-Type': 'application/json', **(headers or {})})
    response = connection.getresponse()
    text = response.read()
    result = json.loads(text) if response.getheader('Content-Type').startswith('application/json') else text
    connection.close()
    return response.status, result

def test_dashboard_and_modules_are_served(app):
    assert request(app, 'GET', '/')[0] == 200
    assert request(app, 'GET', '/assets/main.js' if (dashboard.ROOT / 'dist/index.html').exists() else '/js/main.js')[0] == 200
    assert request(app, 'GET', '/.env')[0] == 404
    assert request(app, 'GET', '/../web/state.py')[0] == 404

def test_foreign_origin_and_host_cannot_change_files(app):
    assert request(app, 'GET', '/api/file?name=profile', headers={'Host': 'untrusted.example'})[0] == 403
    assert request(app, 'POST', '/api/file', {'name': 'profile', 'text': 'changed'}, {'Origin': 'https://untrusted.example'})[0] == 403
    assert app[1].read_text() == 'name: Before\n'

def test_file_saving_is_versioned_and_backed_up(app):
    _, original = request(app, 'GET', '/api/file?name=profile')
    assert request(app, 'POST', '/api/file', {'name': 'profile', 'revision': original['revision'], 'text': 'name: After\n'})[0] == 200
    assert app[1].read_text() == 'name: After\n'
    backups = list((app[1].parent / 'data/inputs/backups').glob('*.bak'))
    assert len(backups) == 1 and backups[0].read_text() == 'name: Before\n'
    assert request(app, 'POST', '/api/file', {'name': 'profile', 'revision': original['revision'], 'text': 'stale edit'})[0] == 409
    assert app[1].read_text() == 'name: After\n'

def test_board_command_is_bounded_and_does_not_shell_interpolate():
    cmd = dashboard.board_command({'board': 'hirist', 'dry_run': True, 'limit': '5'})
    assert cmd.argv[1:] == ('-m', 'sites_bot.platforms', '--site', 'hirist', '--dry-run', '--limit', '5')
    for options in [{'board': ';touch bad'}, {'limit': '-1'}, {'mode': 'shell'}, {'limit': '1.5'}]:
        with pytest.raises(ValueError): dashboard.board_command(options)

def test_pipeline_only_accepts_supported_groups():
    cmd = dashboard.pipeline_command({'group': 'apply', 'dry_run': True})
    assert cmd.argv[1:] == ('-m', 'pipeline', 'continue', '--only', 'apply', '--dry-run')
    with pytest.raises(ValueError): dashboard.pipeline_command({'group': '--shell'})
    with pytest.raises(ValueError): dashboard.pipeline_command({'command': 'delete'})

def test_missing_checkpoint_is_an_honest_empty_state(app):
    status, data = request(app, 'GET', '/api/pipeline')
    assert status == 200 and data['stages'] == [] and data['status'] == 'not started'
    assert {'site': 'hirist', 'url': data['watch'][2]['url']} in data['watch'] and ':6083/vnc.html' in data['watch'][2]['url']

def test_bot_inventory_never_claims_an_unfinished_record_is_live(monkeypatch):
    monkeypatch.setattr(dashboard.state, '_query', lambda *args: [
        {'started_at':'2026-10-22T12:00:00Z','finished_at':None,'summary_json':json.dumps({'board':'hirist','collected':23})},
        {'started_at':'2026-10-21T12:00:00Z','finished_at':'2026-10-21T13:00:00Z','summary_json':'[]'},
    ])
    data=dashboard.bots_status(dashboard.server.Runner())
    assert len(data['bots']) == 18
    assert not any(bot['running'] for bot in data['bots'])
    hirist=next(bot for bot in data['bots'] if bot['id']=='hirist')
    assert hirist['last_run']['finished'] is False and hirist['last_run']['found']==23

def test_bot_status_matches_the_selected_board_only(monkeypatch):
    monkeypatch.setattr(dashboard.state, '_query', lambda *args: [])
    class FakeRunner:
        def snapshot(self):
            return {'running':True,'action':'boards','shown':'python -m sites_bot.platforms --site hirist --dry-run'}
    data=dashboard.bots_status(FakeRunner())
    assert [bot['id'] for bot in data['bots'] if bot['running']] == ['hirist']

def test_missing_database_is_honest_and_bot_endpoint_is_local(app,monkeypatch):
    monkeypatch.setattr(dashboard.state,'database',lambda:app[1].parent/'missing.db')
    status,data=request(app,'GET','/api/bots')
    assert status==200 and len(data['bots'])==18
    assert all(bot['last_run'] is None and not bot['running'] for bot in data['bots'])
    assert request(app,'GET','/api/bots',headers={'Host':'untrusted.example'})[0]==403

def test_schedule_command_cannot_target_an_arbitrary_service():
    cmd=dashboard.schedule_command('profile','disable')
    assert cmd.argv[-2:]==('profile','disable')
    with pytest.raises(ValueError): dashboard.schedule_command('com.apple.other','disable')
    with pytest.raises(ValueError): dashboard.schedule_command('profile','delete')

def test_schedule_disable_preserves_files_and_only_calls_expected_service(monkeypatch):
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('dashboard_schedule',dashboard.ROOT/'schedule.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys,'platform','darwin')
    calls=[]
    def fake_run(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    module.change_schedule('linkedin','disable',run=fake_run,uid=501)
    target='gui/501/com.naukri-bot.linkedin-post'
    assert calls==[['/bin/launchctl','disable',target],['/bin/launchctl','bootout',target]]


@pytest.mark.parametrize('board',['hirist','instahyre','cutshort','wellfound','all'])
def test_profile_crew_commands_and_live_status_are_separate_from_applications(monkeypatch,board):
    monkeypatch.setattr(dashboard.state,'_query',lambda *args:[])
    cmd=dashboard.board_command({'board':board,'mode':'profile','dry_run':True})
    assert '--profile-only' in cmd.argv and '--create-profile' in cmd.argv and '--dry-run' in cmd.argv
    class FakeRunner:
        def snapshot(self):return {'running':True,'action':'boards','shown':cmd.shown}
    active=[bot['id'] for bot in dashboard.bots_status(FakeRunner())['bots'] if bot['running']]
    expected=[name+'_profile' for name in dashboard.BOARDS] if board=='all' else [board+'_profile']
    assert active==expected


def test_profile_history_is_not_borrowed_from_application_runs(monkeypatch):
    monkeypatch.setattr(dashboard.state,'_query',lambda *args:[
        {'started_at':'2026-10-22','finished_at':'2026-10-22','summary_json':json.dumps({'board':'wellfound','applied':3})}])
    bots={b['id']:b for b in dashboard.bots_status(dashboard.server.Runner())['bots']}
    assert bots['wellfound']['last_run']['sent']==3
    assert bots['wellfound_profile']['last_run'] is None


def test_resume_api_is_download_only_and_contained(app,monkeypatch):
    root=app[1].parent/'resumes';root.mkdir();(root/'demo.pdf').write_bytes(b'%PDF fixture')
    monkeypatch.setattr(dashboard.state,'RESUMES',root)
    assert request(app,'GET','/api/resume-file?file=demo.pdf')==(200,b'%PDF fixture')
    assert request(app,'GET','/api/resume-file?file=../profile.yaml')[0]==400
    assert request(app,'GET','/api/resume-file?file=demo.pdf',headers={'Host':'evil.example'})[0]==403
