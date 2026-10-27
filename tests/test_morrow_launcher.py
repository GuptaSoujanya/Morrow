"""The beta launcher owns only its recorded process group, never another server."""
import importlib.util
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'scripts/morrow_launcher.py'
    spec = importlib.util.spec_from_file_location('morrow_launcher_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'checkout'
    (root / 'scripts').mkdir(parents=True)
    (root / 'scripts/morrow').write_text('# launcher\n')
    (root / 'froned-dashbord').mkdir()
    runtime = root / 'reports/morrow'
    runtime.mkdir(parents=True)
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'RUNTIME', runtime)
    monkeypatch.setattr(module, 'START_TIMEOUT', 1)
    monkeypatch.setattr(module, 'check_dependencies', lambda: None)
    monkeypatch.setattr(module, 'port_in_use', lambda port: False)
    monkeypatch.setattr(module, 'beta_ready', lambda port: True)
    monkeypatch.setattr(module, 'listener_owned', lambda port, group: True)
    monkeypatch.setattr(module, 'listener_pids', lambda port: [6543])
    monkeypatch.setattr(module, 'process_started', lambda pid: 'original-start')
    monkeypatch.setattr(module.os, 'getpgid', lambda pid: pid)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Unexpected process start'))
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('Unexpected external command'))
    monkeypatch.setattr(module.os, 'killpg', lambda *a: pytest.fail('No test may signal a real process'))
    clock = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    module.stopped = []
    monkeypatch.setattr(module, 'stop_group', module.stopped.append)
    return module


def saved_state(launcher, **changes):
    state = dict(pid=4321, started='original-start', root=str(launcher.ROOT), port=8116, mode='beta')
    state.update(changes)
    launcher.write_state(state)
    return state


def fake_child(launcher, monkeypatch, *, pid=5432, exit_code=None):
    calls = []
    process = SimpleNamespace(pid=pid, returncode=exit_code, poll=lambda: exit_code)
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda argv, **kwargs: calls.append((argv, kwargs)) or process)
    return calls


def test_start_forces_beta_and_waits_for_owned_readiness(launcher, monkeypatch, capsys):
    monkeypatch.setenv('MORROW_MODE', 'accounts')
    monkeypatch.setenv('MORROW_API_URL', 'http://account-service.invalid')
    calls = fake_child(launcher, monkeypatch)
    ready = iter((False, True, True))
    ownership = iter((False, True))
    monkeypatch.setattr(launcher, 'beta_ready', lambda port: next(ready))
    monkeypatch.setattr(launcher, 'listener_owned', lambda port, group: next(ownership))
    assert launcher.main(['start', '--port', '8116']) == 0
    argv, options = calls[0]
    assert argv == ['node', 'scripts/start.mjs', '--mode', 'beta', '--port', '8116']
    assert options['cwd'] == launcher.ROOT / 'froned-dashbord'
    assert options['env']['MORROW_MODE'] == 'beta'
    assert options['env']['DASHBOARD_PYTHON'] == launcher.sys.executable
    assert options['start_new_session'] is True and options['stdin'] == launcher.subprocess.DEVNULL
    assert launcher.load_state() == dict(pid=5432, started='original-start', root=str(launcher.ROOT), port=8116,
                                         mode='beta', server_pid=6543, server_started='original-start')
    assert stat.S_IMODE(launcher.state_path().stat().st_mode) == 0o600
    assert launcher.time.monotonic() == 0.5
    assert 'is ready: http://127.0.0.1:8116' in capsys.readouterr().out
    assert launcher.stopped == []


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'foreign_listener', 'missing_start'])
def test_failed_start_stops_only_its_new_group_and_clears_state(launcher, monkeypatch, failure, capsys):
    fake_child(launcher, monkeypatch, exit_code=7 if failure == 'exit' else None)
    if failure == 'timeout':
        monkeypatch.setattr(launcher, 'beta_ready', lambda port: False)
    elif failure == 'foreign_listener':
        monkeypatch.setattr(launcher, 'listener_owned', lambda port, group: False)
    elif failure == 'missing_start':
        monkeypatch.setattr(launcher, 'process_started', lambda pid: '')
    assert launcher.main(['start', '--port', '8116']) == 1
    assert launcher.stopped == [5432]
    assert not launcher.state_path().exists()
    assert 'is ready' not in capsys.readouterr().out


def test_unrelated_listener_is_refused_without_starting_or_killing(launcher, monkeypatch, capsys):
    monkeypatch.setattr(launcher, 'port_in_use', lambda port: True)
    monkeypatch.setattr(launcher, 'check_dependencies', lambda: pytest.fail('Do not install before resolving occupied port'))
    assert launcher.main(['start', '--port', '8100']) == 1
    assert launcher.stopped == [] and not launcher.state_path().exists()
    assert 'used by another server' in capsys.readouterr().err


def test_owned_start_is_idempotent_and_reuses_saved_custom_port(launcher, monkeypatch, capsys):
    state = saved_state(launcher)
    monkeypatch.setattr(launcher, 'check_dependencies', lambda: pytest.fail('Already running'))
    assert launcher.main(['start']) == 0
    assert launcher.load_state() == state and launcher.stopped == []
    assert 'already running: http://127.0.0.1:8116' in capsys.readouterr().out


def test_owned_start_cannot_silently_change_port_or_accept_unready_server(launcher, monkeypatch):
    state = saved_state(launcher)
    assert launcher.main(['start', '--port', '8120']) == 1
    monkeypatch.setattr(launcher, 'beta_ready', lambda port: False)
    assert launcher.main(['start']) == 1
    assert launcher.load_state() == state and launcher.stopped == []


@pytest.mark.parametrize('changed', ['pid_reused', 'different_group', 'different_checkout', 'invalid_pid', 'missing_process'])
def test_stop_discards_stale_state_without_signalling_any_process(launcher, monkeypatch, changed):
    saved_state(launcher, **({'root': '/another/checkout'} if changed == 'different_checkout' else {'pid': True} if changed == 'invalid_pid' else {}))
    if changed == 'pid_reused':
        monkeypatch.setattr(launcher, 'process_started', lambda pid: 'new-unrelated-start')
    elif changed == 'different_group':
        monkeypatch.setattr(launcher.os, 'getpgid', lambda pid: pid + 1)
    elif changed == 'missing_process':
        def missing(pid):
            raise ProcessLookupError()
        monkeypatch.setattr(launcher.os, 'getpgid', missing)
    assert launcher.main(['stop']) == 0
    assert launcher.stopped == [] and not launcher.state_path().exists()


@pytest.mark.parametrize('new_port', [None, 8123])
def test_restart_retains_or_changes_port_then_stop_owns_new_process(launcher, monkeypatch, new_port):
    saved_state(launcher)
    calls = fake_child(launcher, monkeypatch)
    args = ['restart'] + (['--port', str(new_port)] if new_port else [])
    assert launcher.main(args) == 0
    assert launcher.stopped == [4321]
    assert calls[0][0][-1] == str(new_port or 8116)
    assert launcher.load_state()['pid'] == 5432
    assert launcher.main(['stop']) == 0
    assert launcher.stopped == [4321, 5432]
    assert not launcher.state_path().exists()


def test_failed_stop_keeps_ownership_state_for_retry(launcher, monkeypatch):
    state = saved_state(launcher)
    def fail(pid):
        raise launcher.LauncherError('Process group did not stop')
    monkeypatch.setattr(launcher, 'stop_group', fail)
    assert launcher.main(['stop']) == 1
    assert launcher.load_state() == state


@pytest.mark.parametrize('backend_reused', [False, True])
def test_stop_after_node_exit_verifies_surviving_backend_identity(launcher, monkeypatch, backend_reused):
    saved_state(launcher, server_pid=6543, server_started='backend-start')
    def group(pid):
        if pid == 4321:
            raise ProcessLookupError()
        return 4321
    monkeypatch.setattr(launcher.os, 'getpgid', group)
    monkeypatch.setattr(launcher, 'process_started', lambda pid: 'unrelated-start' if backend_reused else 'backend-start')
    assert launcher.main(['stop']) == 0
    assert launcher.stopped == ([] if backend_reused else [4321])
    assert not launcher.state_path().exists()


@pytest.mark.parametrize('kind', ['file', 'symlink', 'dangling_symlink'])
def test_install_preserves_unrelated_existing_target(launcher, tmp_path, monkeypatch, kind):
    home = tmp_path / 'home'
    target = home / '.local/bin/morrow'
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    unrelated = tmp_path / 'another-command'
    if kind == 'file':
        target.write_text('unrelated command')
    else:
        if kind == 'symlink':
            unrelated.write_text('unrelated command')
        target.symlink_to(unrelated)
    assert launcher.main(['install']) == 1
    if kind == 'file':
        assert not target.is_symlink() and target.read_text() == 'unrelated command'
    else:
        assert target.is_symlink() and target.readlink() == unrelated


def test_install_creates_checkout_link_and_is_idempotent(launcher, tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    assert launcher.main(['install']) == 0
    target = home / '.local/bin/morrow'
    assert target.is_symlink() and target.resolve() == launcher.ROOT / 'scripts/morrow'
    before = target.lstat().st_ino
    assert launcher.main(['install']) == 0
    assert target.lstat().st_ino == before


def test_accounts_argument_is_rejected_without_starting(launcher):
    with pytest.raises(SystemExit) as exit_status:
        launcher.main(['start', 'accounts'])
    assert exit_status.value.code == 2
    assert not launcher.state_path().exists() and launcher.stopped == []
