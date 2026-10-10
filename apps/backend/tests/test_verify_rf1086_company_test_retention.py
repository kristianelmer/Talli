"""Actual local CLI subprocesses; bounded inputs, finite diagnostics, no writes."""
from hashlib import sha256
from contextlib import contextmanager
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from talli_backend.application.shareholder_register_company_test_retention_stream import stream_company_test_retention
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_company_test_retention import COMPANY, capture, record, wire

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / 'scripts/verify_rf1086_company_test_retention.py'


def run_cli(path, *extra):
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'apps/backend/src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    return subprocess.run([sys.executable, str(CLI), '--input', str(path), '--company-id', str(COMPANY),
        *extra], env=env, capture_output=True, timeout=15)


@pytest.mark.parametrize('kind', ['artifact', 'stream', 'zero', 'unavailable', 'large-one-line'])
def test_cli_structural_only_and_source_files_unchanged(tmp_path, kind):
    snapshot = capture(record(payload_hash=' original ø hash '))
    if kind == 'zero': snapshot = capture()
    elif kind == 'unavailable': snapshot = rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)
    elif kind == 'large-one-line': snapshot = capture(record(feedback_summary='x'*65536))
    raw = b''.join(stream_company_test_retention(snapshot)) if kind == 'stream' else wire(snapshot).encode()
    path = tmp_path/'input-private';path.write_bytes(raw)
    before = sha256(raw).hexdigest()
    result = run_cli(path)
    assert result.returncode == 0 and result.stderr == b''
    output = json.loads(result.stdout)
    assert output['status'] == ['STRUCTURAL_INTEGRITY_ONLY'] and output['sourceOrigin'] == 'UNVERIFIED'
    assert output['coverage'] == snapshot.coverage
    if kind == 'unavailable': assert 'observedAt' not in output and 'recordCount' not in output
    else: assert output['observedAt'] == snapshot.observed_at and output['recordCount'] == snapshot.record_count
    assert sha256(path.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['input-private']


@pytest.mark.parametrize('kind', ['artifact', 'stream'])
def test_expected_capture_match_remains_origin_unverified(tmp_path, kind):
    snapshot = capture(record())
    source = tmp_path/'input'; expected = tmp_path/'expected'
    source.write_bytes(b''.join(stream_company_test_retention(snapshot)) if kind == 'stream' else wire(snapshot).encode())
    expected.write_text(wire(snapshot))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = run_cli(source, '--expected-source-capture', str(expected))
    assert result.returncode == 0 and result.stderr == b''
    assert json.loads(result.stdout)['status'] == ['STRUCTURAL_INTEGRITY_ONLY', 'EXPECTED_CAPTURE_MATCH']
    assert json.loads(result.stdout)['sourceOrigin'] == 'UNVERIFIED'
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('expected_kind', ['omission', 'time', 'unavailable', 'stream'])
def test_expected_capture_requires_fixed_exact_source(tmp_path, expected_kind):
    source = tmp_path/'input';expected = tmp_path/'expected'
    source.write_text(wire(capture(record())))
    snapshot = capture() if expected_kind == 'omission' else capture(record(), observed_at='2026-10-12T00:00:00+00:00')
    if expected_kind == 'unavailable': snapshot = rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)
    expected.write_bytes(b''.join(stream_company_test_retention(snapshot)) if expected_kind == 'stream' else wire(snapshot).encode())
    result = run_cli(source, '--expected-source-capture', str(expected))
    assert result.returncode == 1 and result.stdout == b''
    assert result.stderr == b'company_test_retention_verification_failed\n'


@pytest.mark.parametrize('raw', [b'', b'{"codec":"rf1086-archive-v6"}', b'private-sentinel', b'\xff',
    b'{"codec":"rf1086-company-test-retention-v1","secret":"private-sentinel"}'], ids=['empty','legacy','private','utf8','malformed'])
def test_invalid_inputs_have_finite_diagnostics_without_raw_values(tmp_path, raw):
    path = tmp_path/'private-name';path.write_bytes(raw)
    result = run_cli(path)
    assert result.returncode == 1 and result.stdout == b''
    assert result.stderr == b'company_test_retention_verification_failed\n'
    assert path.read_bytes() == raw


def test_missing_file_and_nonregular_input_fail_without_blocking(tmp_path):
    for path in [tmp_path/'missing', tmp_path]:
        result = run_cli(path)
        assert result.returncode == 1 and result.stdout == b''
        assert result.stderr == b'company_test_retention_verification_failed\n'
    fifo = tmp_path/'fifo';os.mkfifo(fifo)
    assert run_cli(fifo).returncode == 1


def test_artifact_over_cap_sparse_file_rejects_and_does_not_write(tmp_path):
    path = tmp_path/'input'
    with path.open('wb') as output:
        output.write(b'{"codec":"rf1086-company-test-retention-v1",')
        output.truncate(64*1024*1024 + 1)
    before = path.stat().st_size
    result = run_cli(path)
    assert result.returncode == 1 and result.stdout == b''
    assert result.stderr == b'company_test_retention_verification_failed\n'
    assert path.stat().st_size == before and list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('suffix', [b'', b'\n', b'private-sentinel'], ids=['truncated','extra-lf','private-tail'])
def test_cli_stream_completion_and_eof_failure_no_raw_diagnostic(tmp_path, suffix):
    raw = b''.join(stream_company_test_retention(capture(record())))
    if suffix == b'': raw = b''.join(raw.splitlines(keepends=True)[:-1])
    else: raw += suffix
    path = tmp_path/'input';path.write_bytes(raw)
    result = run_cli(path)
    assert result.returncode == 1 and result.stdout == b''
    assert result.stderr == b'company_test_retention_verification_failed\n'
    assert path.read_bytes() == raw


def test_cli_identification_is_bounded_prefix_not_unbounded_line(monkeypatch):
    spec = importlib.util.spec_from_file_location('retention_cli_under_test', CLI)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    raw = wire(capture(record(feedback_summary='x'*65536))).encode()
    requests = []

    class Reader(BytesIO):
        def read(self, size=-1):
            assert size > 0
            requests.append(size)
            return super().read(size)

        def readline(self, size=-1):
            pytest.fail('direct one-line artifact identification must not use readline')

    @contextmanager
    def source(_path):
        yield Reader(raw)

    monkeypatch.setattr(module, 'local_file', source)
    result = module.verify(SimpleNamespace(company_id=str(COMPANY), input='local', expected_source_capture=None))
    assert result['recordCount'] == 1 and requests == [4096, 64*1024*1024 + 1]


def test_actual_cli_succeeds_with_network_and_filesystem_writes_forbidden(tmp_path):
    path = tmp_path/'input';path.write_text(wire(capture(record())))
    wrapper = '''import os,runpy,sys
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','http.client.connect'):
        raise AssertionError('network forbidden')
    if event == 'open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
        raise AssertionError('filesystem writes forbidden')
sys.addaudithook(audit)
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
'''
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'apps/backend/src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', wrapper, str(CLI), '--input', str(path),
        '--company-id', str(COMPANY)], env=env, capture_output=True, timeout=15)
    assert result.returncode == 0 and result.stderr == b''
    assert json.loads(result.stdout)['status'] == ['STRUCTURAL_INTEGRITY_ONLY']
