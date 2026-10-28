import importlib.util
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from common import ai_cli

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('morrow_setup_defaults', ROOT / 'scripts/setup_defaults.py')
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)


def test_installer_configuration_rerun_preserves_credentials_and_personal_files(tmp_path):
    env = tmp_path / '.env'
    env.write_text('NAUKRI_PASSWORD="private value"\nCUSTOM=yes\nLLM_BACKEND=claude-cli\nPIPELINE_AI_CLI=claude\n')
    profile = tmp_path / 'profile.yaml'; profile.write_text('personal data')
    defaults.configure(tmp_path, 'kiro')
    first = env.read_text()
    defaults.configure(tmp_path, 'kiro')
    assert env.read_text() == first
    values = dotenv_values(env)
    assert values['NAUKRI_PASSWORD'] == 'private value' and values['CUSTOM'] == 'yes'
    assert values['LLM_BACKEND'] == 'kiro-cli' and values['PIPELINE_AI_CLI'] == 'kiro'
    assert profile.read_text() == 'personal data'
    assert env.stat().st_mode & 0o777 == 0o600


def test_installer_help_has_no_setup_side_effects(tmp_path):
    script = tmp_path / 'setup.sh'; script.write_text((ROOT / 'setup.sh').read_text())
    result = subprocess.run(['bash', str(script), '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and '--provider' in result.stdout
    assert list(tmp_path.iterdir()) == [script]
    assert subprocess.run(['bash', str(script), '--provider', 'unknown'], capture_output=True).returncode == 2


def test_closing_dashboard_kills_ai_process_group(monkeypatch):
    stop = threading.Event()
    process = SimpleNamespace(args=['synthetic-cli'], returncode=None)
    killed = []
    monkeypatch.setattr(ai_cli, 'chosen_cli', lambda _: 'claude')
    def launch(*args, **kwargs):
        stop.set()
        return process
    monkeypatch.setattr(ai_cli.subprocess, 'Popen', launch)
    monkeypatch.setattr(ai_cli, '_kill_group', killed.append)
    with pytest.raises(ai_cli.AIError, match='cancelled'):
        ai_cli.ask('Synthetic fixture', web=False, cancel_event=stop)
    assert killed == [process]


def test_cancelled_preparation_does_not_launch_another_ai_process(monkeypatch):
    stop = threading.Event(); stop.set()
    def launch(*args, **kwargs):
        pytest.fail('Cancelled preparation must not launch an AI process')
    monkeypatch.setattr(ai_cli.subprocess, 'Popen', launch)
    with pytest.raises(ai_cli.AIError, match='cancelled'):
        ai_cli.ask('Synthetic fixture', cancel_event=stop)


def test_ai_cancellation_polling_keeps_real_timeout(monkeypatch):
    stop = threading.Event()
    process = SimpleNamespace(args=['synthetic-cli'], returncode=None,
                              communicate=lambda **_: (_ for _ in ()).throw(subprocess.TimeoutExpired('synthetic', 1)))
    killed = []
    monkeypatch.setattr(ai_cli, 'chosen_cli', lambda _: 'claude')
    monkeypatch.setattr(ai_cli.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(ai_cli, '_kill_group', killed.append)
    clock = iter([0, 0.5, 2])
    monkeypatch.setattr(ai_cli.time, 'monotonic', lambda: next(clock))
    with pytest.raises(ai_cli.AIError, match='ran past'):
        ai_cli.ask('Synthetic fixture', timeout_s=1, web=False, cancel_event=stop)
    assert killed == [process]
