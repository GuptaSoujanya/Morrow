"""Visible dashboard browsers by default, explicit background jobs; no real bots."""
import json
import os
import subprocess
import sys

import pytest

from web import server, state


MODE_CHOICES = [
    ({}, False),
    ({'browser_mode': 'visible'}, False),
    ({'browser_mode': 'background'}, True),
    ({'headless': False}, False),
    ({'headless': True}, True),
    ({'browser_mode': 'visible', 'headless': True}, False),
    ({'browser_mode': 'background', 'headless': False}, True),
]


@pytest.mark.parametrize('options,headless', MODE_CHOICES)
def test_browser_choice_overrides_inherited_environment(monkeypatch, options, headless):
    monkeypatch.setenv('HEADLESS', 'true' if not headless else 'false')
    monkeypatch.setenv('BACKGROUND', 'true')
    command = server.build('naukri', {**options, 'dry_run': True})
    child = subprocess.run([sys.executable, '-c',
        'import json,os; print(json.dumps({k:os.getenv(k) for k in ("HEADLESS","BACKGROUND","DRY_RUN")}))'],
        env={**os.environ, **dict(command.env)}, capture_output=True, text=True, check=True)
    assert json.loads(child.stdout) == {'HEADLESS': str(headless).lower(), 'BACKGROUND': 'false', 'DRY_RUN': 'true'}
    assert ('--headless' in command.argv) is headless


def test_browser_options_are_normalized_without_mutating_request():
    options = {'browser_mode': 'visible', 'headless': False}
    command = server.build('naukri', options)
    assert '--headless' not in command.argv
    assert dict(command.env) == {'HEADLESS': 'false', 'BACKGROUND': 'false'}
    assert options == {'browser_mode': 'visible', 'headless': False}


@pytest.mark.parametrize('action', sorted(server.BROWSER_ACTIONS))
@pytest.mark.parametrize('options,headless', MODE_CHOICES)
def test_browser_choice_reaches_every_agent_including_actions_without_cli_flag(monkeypatch, action, options, headless):
    received = []
    def build(options, save):
        received.append(options)
        return state.Command('Synthetic', (sys.executable, '-c', 'pass'), env=(('HEADLESS', 'false'), ('BACKGROUND', 'true')))
    monkeypatch.setitem(server.ACTIONS, action, build)
    command = server.build(action, options)
    assert received[0]['headless'] is headless
    assert received[0]['browser_mode'] == ('background' if headless else 'visible')
    assert dict(command.env) == {'HEADLESS': str(headless).lower(), 'BACKGROUND': 'false'}


@pytest.mark.parametrize('mode', ['', None, True, 'quiet', 'visible; unsafe', {}, []])
def test_invalid_mode_is_rejected_before_building_or_saving(monkeypatch, mode):
    built = []
    monkeypatch.setitem(server.ACTIONS, 'resume', lambda options, save: built.append(save))
    with pytest.raises(ValueError, match='Visible browser or Background job'):
        server.build('resume', {'browser_mode': mode}, save=True)
    assert built == []


def test_browser_modes_do_not_apply_to_manual_sign_in_action():
    with pytest.raises(ValueError, match='not available'):
        server.build('google', {'browser_mode': 'background'})


@pytest.mark.parametrize('action', ['google', 'report', 'profile_status', 'linkedin_status'])
def test_manual_sign_in_and_non_agent_actions_keep_their_existing_environment(action):
    assert not server.build(action, {}).env


def test_batch_preview_and_launch_keep_each_selected_browser_mode():
    requests = server.batch_requests({'runs': [
        {'key': 'naukri', 'action': 'naukri', 'options': {'browser_mode': 'background', 'dry_run': True}},
        {'key': 'profile', 'action': 'profile', 'options': {'browser_mode': 'visible', 'dry_run': True}},
        {'key': 'assist', 'action': 'assist', 'options': {'dry_run': True}},
    ]})
    preview = server.build_batch(requests, save=False)
    launch = server.build_batch(requests, save=True)
    assert [item.command for item in preview] == [item.command for item in launch]
    assert dict(preview[0].command.env)['HEADLESS'] == 'true'
    assert dict(preview[1].command.env)['HEADLESS'] == 'false'
    assert dict(preview[2].command.env)['HEADLESS'] == 'false'
    assert '--headless' in preview[0].command.argv
    assert all('--headless' not in item.command.argv for item in preview[1:])
