"""Browser visibility is fixed at confirmation and propagated without real bots."""
import json
import os
import subprocess
import sys

import pytest

from web import server, state


@pytest.mark.parametrize('mode,headless', [('background', 'true'), ('visible', 'false')])
def test_browser_mode_overrides_inherited_environment(monkeypatch, mode, headless):
    monkeypatch.setenv('HEADLESS', 'true' if headless == 'false' else 'false')
    monkeypatch.setenv('BACKGROUND', 'true')
    command = server.build('naukri', {'browser_mode': mode, 'dry_run': True})
    child = subprocess.run([sys.executable, '-c',
        'import json,os; print(json.dumps({k:os.getenv(k) for k in ("HEADLESS","BACKGROUND","DRY_RUN")}))'],
        env={**os.environ, **dict(command.env)}, capture_output=True, text=True, check=True)
    assert json.loads(child.stdout) == {'HEADLESS': headless, 'BACKGROUND': 'false', 'DRY_RUN': 'true'}
    assert ('--headless' in command.argv) == (mode == 'background')


def test_visible_mode_overrides_old_headless_option_without_mutation():
    options = {'browser_mode': 'visible', 'headless': True}
    command = server.build('naukri', options)
    assert '--headless' not in command.argv
    assert dict(command.env) == {'HEADLESS': 'false', 'BACKGROUND': 'false'}
    assert options['headless'] is True


@pytest.mark.parametrize('action', sorted(server.BROWSER_ACTIONS))
def test_browser_mode_reaches_every_browser_action_including_actions_without_cli_flag(monkeypatch, action):
    monkeypatch.setitem(server.ACTIONS, action, lambda options, save: state.Command('Synthetic', (sys.executable, '-c', 'pass')))
    command = server.build(action, {'browser_mode': 'background'})
    assert dict(command.env) == {'HEADLESS': 'true', 'BACKGROUND': 'false'}


@pytest.mark.parametrize('mode', ['', None, True, 'quiet', 'visible; unsafe', {}, []])
def test_invalid_mode_is_rejected_before_building_or_saving(monkeypatch, mode):
    built = []
    monkeypatch.setitem(server.ACTIONS, 'resume', lambda options, save: built.append(save))
    with pytest.raises(ValueError, match='Choose Background or Visible'):
        server.build('resume', {'browser_mode': mode}, save=True)
    assert built == []


def test_browser_modes_do_not_apply_to_manual_sign_in_action():
    with pytest.raises(ValueError, match='not available'):
        server.build('google', {'browser_mode': 'background'})


def test_legacy_requests_keep_their_existing_command_environment():
    assert not server.build('naukri', {}).env


def test_batch_preview_has_the_same_explicit_mode_as_launch_commands():
    requests = server.batch_requests({'runs': [
        {'key': 'naukri', 'action': 'naukri', 'options': {'browser_mode': 'background', 'dry_run': True}},
        {'key': 'profile', 'action': 'profile', 'options': {'browser_mode': 'visible', 'dry_run': True}},
    ]})
    preview = server.build_batch(requests, save=False)
    launch = server.build_batch(requests, save=True)
    assert [item.command for item in preview] == [item.command for item in launch]
    assert dict(preview[0].command.env)['HEADLESS'] == 'true'
    assert dict(preview[1].command.env)['HEADLESS'] == 'false'
