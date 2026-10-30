"""Optional process-owned loopback forwarding for the local Colima rehearsal.

The caller must validate its exact owned source before entering this context.
No forwarding is used on normal local Docker or Linux CI. No shared SSH master,
VM lifecycle, Docker resource or existing tunnel is changed.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import time


def forwarding_command(ports):
    configuration = os.environ.get('TALLI_RF_RESTORE_SSH_CONFIG')
    host = os.environ.get('TALLI_RF_RESTORE_SSH_HOST')
    if not configuration and not host: return None
    if not configuration or not host or host.startswith('-') or any(c.isspace() for c in host):
        raise ValueError('Local restore forwarding requires an explicit SSH config and host')
    path = Path(configuration).resolve(strict=True)
    if not path.is_file(): raise ValueError('Local restore SSH config must be a file')
    if not ports or len(set(ports)) != len(ports) or any(type(port) is not int or not 1024 <= port <= 65535 for port in ports):
        raise ValueError('Local restore forwards require distinct unprivileged ports')
    base = ['ssh', '-F', str(path), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ExitOnForwardFailure=yes', '-o', 'BatchMode=yes', '-o', 'PermitLocalCommand=no',
            '-o', 'RemoteCommand=none', '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none']
    # Resolve configuration before contacting the host. An explicit path/alias is
    # not by itself evidence that this is the owner's local VM.
    try:
        result = subprocess.run(base + ['-G', host], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Local restore SSH configuration timed out') from None
    if result.returncode: raise RuntimeError('Local restore SSH configuration failed')
    settings = [line.split(' ', 1) for line in result.stdout.decode().splitlines() if ' ' in line]
    effective = dict(settings)
    if (effective.get('hostname') not in ('127.0.0.1', 'localhost', '::1')
            or any(key in ('localforward', 'remoteforward', 'dynamicforward') for key, _ in settings)):
        raise ValueError('Restore SSH host must be local and have no inherited forwards')
    return base + ['-N', '-T'] + [arg for port in ports for arg in ('-L', f'127.0.0.1:{port}:127.0.0.1:{port}')] + [host]


def assert_unbound(ports):
    # Reject a pre-existing listener before starting SSH. Otherwise connecting to
    # it could look ready during the brief interval before SSH reports bind failure.
    sockets = []
    try:
        for port in ports:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(listener)
            try: listener.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError('Local restore forward port is already occupied') from None
    finally:
        for listener in sockets: listener.close()


@contextmanager
def forwarded_ports(ports):
    """Forward discovered container ports, killing only our returned SSH process."""
    ports = tuple(ports)
    command = forwarding_command(ports)
    if command is None:
        yield
        return
    assert_unbound(ports)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None: raise RuntimeError('Owned local restore SSH forwarding failed')
            connected = True
            for port in ports:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1): pass
                except OSError:
                    connected = False
                    break
            if connected: break
            time.sleep(0.1)
        else: raise RuntimeError('Owned local restore SSH forwarding did not become ready')
        if process.poll() is not None: raise RuntimeError('Owned local restore SSH forwarding exited before use')
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
