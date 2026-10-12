"""Optional forwarding cannot reuse masters, remote hosts or unowned processes."""
from contextlib import contextmanager
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import rf1086_local_forwarding as forwarding


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    path = tmp_path / 'ssh.config'
    path.write_text('Host owned-vm\n HostName 127.0.0.1\n')
    monkeypatch.setenv('TALLI_RF_RESTORE_SSH_CONFIG', str(path))
    monkeypatch.setenv('TALLI_RF_RESTORE_SSH_HOST', 'owned-vm')
    return path


def test_regular_docker_uses_no_ssh_process(monkeypatch):
    monkeypatch.delenv('TALLI_RF_RESTORE_SSH_CONFIG', raising=False)
    monkeypatch.delenv('TALLI_RF_RESTORE_SSH_HOST', raising=False)
    monkeypatch.setattr(forwarding.subprocess, 'Popen', lambda *_args, **_kwargs: pytest.fail('Unexpected SSH process'))
    with forwarding.forwarded_ports((5432, 9999)): pass


@pytest.mark.parametrize('settings', [b'hostname remote.example\n', b'hostname 127.0.0.1\nlocalforward 1234 remote:5432\n',
                                    b'hostname 127.0.0.1\nremoteforward 1234 remote:5432\n', b''])
def test_config_must_identify_local_host_without_existing_forwards(local_config, monkeypatch, settings):
    monkeypatch.setattr(forwarding.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=settings))
    with pytest.raises(ValueError): forwarding.forwarding_command((55101, 55102))


@pytest.mark.parametrize('ports', [(), (80,), (55001, 55001), (65536,), ('55001',)])
def test_invalid_ports_fail_before_ssh_config_or_process(local_config, monkeypatch, ports):
    monkeypatch.setattr(forwarding.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Invalid port reached SSH'))
    with pytest.raises(ValueError): forwarding.forwarding_command(ports)


@pytest.mark.parametrize('failure', [None, 'body', 'startup', 'terminate_timeout'])
def test_forwarding_cleans_only_its_process(local_config, monkeypatch, failure):
    events = []
    monkeypatch.setattr(forwarding, 'assert_unbound', lambda ports: events.append(('unbound', ports)))
    monkeypatch.setattr(forwarding.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=b'hostname 127.0.0.1\n'))
    class Process:
        def __init__(self, command, **_kwargs):
            events.append(('start', command))
            assert '-F' in command and str(local_config) in command
            assert 'ControlPath=none' in command and 'ControlMaster=no' in command
            assert command[-1] == 'owned-vm'
            assert '127.0.0.1:55101:127.0.0.1:55101' in command
            assert '127.0.0.1:55102:127.0.0.1:55102' in command
        def poll(self): return 1 if failure == 'startup' else None
        def terminate(self): events.append(('terminate',))
        def kill(self): events.append(('kill',))
        def wait(self, timeout):
            events.append(('wait', timeout))
            if failure == 'terminate_timeout' and ('kill',) not in events: raise subprocess.TimeoutExpired('ssh', timeout)
    monkeypatch.setattr(forwarding.subprocess, 'Popen', Process)
    @contextmanager
    def connected(endpoint, timeout):
        events.append(('connected', endpoint))
        yield
    monkeypatch.setattr(forwarding.socket, 'create_connection', connected)
    def run():
        with forwarding.forwarded_ports((55101, 55102)):
            if failure == 'body': raise ValueError('fixture body')
    if failure in ('body', 'startup'):
        with pytest.raises((ValueError, RuntimeError)): run()
    else: run()
    assert (('terminate',) in events) == (failure != 'startup')
    assert (('kill',) in events) == (failure == 'terminate_timeout')


def test_existing_loopback_listener_is_never_mistaken_for_new_ssh():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with pytest.raises(RuntimeError, match='already occupied'):
            forwarding.assert_unbound((listener.getsockname()[1],))
