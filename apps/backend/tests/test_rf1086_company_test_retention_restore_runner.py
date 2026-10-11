"""Owned lifecycle ordering/failures with explicit doubles; no Auth or restore proof."""
import asyncio
import base64
from contextlib import contextmanager
from hashlib import sha256
import hmac
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from talli_backend.application import shareholder_register_company_test_retention_stream as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_company_test_retention import COMPANY, capture, record, wire

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('rf_company_inventory_restore_runner',
    ROOT / 'scripts/rehearse-rf1086-company-test-retention-restore.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from rf1086_company_test_inventory_identity_restore import CompanyTestInventoryRecoveryReport


def signed(payload, key='owned-synthetic-HS256-key', header=None):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=').decode()
    body = encode(header or {'alg': 'HS256', 'typ': 'JWT'}) + '.' + encode(payload)
    return body + '.' + base64.urlsafe_b64encode(hmac.digest(key.encode(), body.encode(), 'sha256')).rstrip(b'=').decode()


CLAIMS = {'sub': '00000000-0000-0000-0000-000000000002',
    'session_id': '00000000-0000-4000-8000-000000000005', 'role': 'authenticated',
    'iat': 1791660000, 'exp': 1791663600, 'aal': 'aal1'}


def test_stateless_fixture_verifies_captured_key_and_preserves_original_auth_claims():
    original = signed(CLAIMS)
    stateless = runner._stateless_owned_owner_token(original, {'GOTRUE_JWT_SECRET': 'owned-synthetic-HS256-key'})
    header, payload, signature = stateless.split('.')
    decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    assert json.loads(decode(payload)) == {key: value for key, value in CLAIMS.items() if key != 'session_id'}
    assert hmac.compare_digest(decode(signature), hmac.digest(b'owned-synthetic-HS256-key',
        (header + '.' + payload).encode(), 'sha256'))
    assert original == signed(CLAIMS)


@pytest.mark.parametrize('token,env', [
    (signed(CLAIMS), {}),
    (signed(CLAIMS), {'GOTRUE_JWT_SECRET': 'wrong-owned-key'}),
    (signed(CLAIMS, header={'alg': 'ES256'}), {'GOTRUE_JWT_SECRET': 'owned-synthetic-HS256-key'}),
    (signed({k:v for k,v in CLAIMS.items() if k != 'session_id'}), {'GOTRUE_JWT_SECRET': 'owned-synthetic-HS256-key'}),
])
def test_stateless_probe_cannot_infer_a_key_or_skip_its_required_signed_owner_baseline(token, env):
    with pytest.raises(ValueError):
        runner._stateless_owned_owner_token(token, env)


def _configure_owned_runner_double(monkeypatch, tmp_path, failure):
    expected = capture(record(), record(4, recorded_by='00000000-0000-0000-0000-000000000008'))
    saved = tmp_path/'source.ndjson';saved.write_bytes(b''.join(stream.stream_company_test_retention(
        capture(record()) if failure == 'stream-omission' else expected)))
    writer = tmp_path/'writer.json';writer.write_text(wire(capture(record()) if failure == 'writer-omission' else expected))
    args = SimpleNamespace(company_id=str(COMPANY), stream=str(saved), writer_expectation=str(writer))
    source_url = 'postgresql://postgres:owned@127.0.0.1:55001/postgres'
    reader_url = 'postgresql://talli_ledger_backend:owned-reader@127.0.0.1:55001/postgres'
    for key, value in {'DATABASE_URL': source_url, 'TALLI_SUPABASE_WORKDIR': '/owned-workdir',
            'TALLI_LEDGER_DATABASE_URL': reader_url, 'SUPABASE_URL': 'http://127.0.0.1:55002',
            'SUPABASE_ANON_KEY': 'owned-synthetic-anon', 'TALLI_RF_RESTORE_OWNER_TOKEN': signed(CLAIMS),
            'TALLI_RF_RESTORE_OUTSIDER_TOKEN': 'owned-synthetic-outsider'}.items():
        monkeypatch.setenv(key, value)
    events = []
    def stage(name):
        events.append(name)
        if failure == name:
            raise ValueError('synthetic-'+name)
    def source_boundary(*args):
        stage('source-boundary');return 'owned-source-container', 'postgres'
    monkeypatch.setattr(runner.owned.boundary, 'owned_source', source_boundary)
    monkeypatch.setattr(runner.owned.boundary, 'verify_source_session', lambda *args: stage('source-session'))
    old_reader = runner.owned.owner_read_url
    def reader(*args):
        stage('reader');return old_reader(*args)
    monkeypatch.setattr(runner.owned, 'owner_read_url', reader)
    def auth_binding(*args):
        stage('auth-binding');return {'Id': 'owned-source-container'}, {}, {'GOTRUE_JWT_SECRET': 'owned-synthetic-HS256-key'}
    monkeypatch.setattr(runner, 'owned_identity_source', auth_binding)
    fingerprints = []
    def fingerprint(*args):
        fingerprints.append('fingerprint');return {'source': 'changed' if failure == 'fingerprint' and len(fingerprints)==2 else 'original'}
    monkeypatch.setattr(runner, 'fingerprint', fingerprint)
    class Factory:
        def __init__(self, config):
            stage('factory');assert config.database_url == reader_url
    monkeypatch.setattr(runner, 'PostgresCompanyTestRetentionSessionFactory', Factory)
    captures = []
    async def capture_source(*args):
        name = 'source-capture' if not captures else 'source-post'
        captures.append(name);stage(name)
        return capture(*expected.records, observed_at='2026-10-12T01:02:03+00:00')
    monkeypatch.setattr(runner, 'capture_owned_company_test_retention', capture_source)
    @contextmanager
    def restore(url, workdir, boundary):
        assert url == source_url and boundary is runner.owned.boundary
        stage('enter-target')
        try:
            yield SimpleNamespace(proof={'synthetic-lifecycle-double': True})
        finally:
            stage('target-cleanup')
    monkeypatch.setattr(runner, 'restored_identity', restore)
    async def helper(recovery, company, source, source_sha, **kwargs):
        assert events[-1] == 'enter-target'
        assert company == COMPANY and source == expected and source_sha == sha256(wire(expected).encode()).hexdigest()
        assert kwargs['source_reader_url'] == reader_url
        stage('target-helper')
        if failure == 'cancelled':
            raise asyncio.CancelledError()
        return CompanyTestInventoryRecoveryReport(2, source.records_sha256, '2026-10-13T00:00:00+00:00',
            source_sha, True, True, True, True, True, True, 'blocked-by-preserved-historical-foreign-keys')
    monkeypatch.setattr(runner, 'verify_company_test_inventory_actor_recovery', helper)
    return args, events, fingerprints, expected, saved


@pytest.mark.parametrize('failure', [None, 'source-boundary', 'source-session', 'reader', 'auth-binding',
    'source-capture', 'writer-omission', 'stream-omission', 'target-helper', 'target-cleanup',
    'cancelled', 'source-post', 'fingerprint'])
def test_one_context_cannot_accept_a_report_before_cleanup_and_source_postchecks(monkeypatch, tmp_path, failure):
    args, events, fingerprints, expected, saved = _configure_owned_runner_double(monkeypatch, tmp_path, failure)
    if failure:
        with pytest.raises(asyncio.CancelledError if failure == 'cancelled' else (ValueError, rf.Rf1086ArchiveError)):
            runner.rehearse(args)
    else:
        result = runner.rehearse(args)
        assert result['independentRecoveryResourcesRemoved'] and result['sourceInventoryUnchanged']
        assert result['sourceObservationUnchanged'] and not result['legalCompanyArchiveReceipt']
        assert result['sourceArtifactSha256'] == sha256(wire(expected).encode()).hexdigest()
        assert events.index('target-cleanup') < events.index('source-post') and len(fingerprints)==2
    assert events.count('enter-target') <= 1
    if failure in ('target-helper', 'target-cleanup', 'cancelled'):
        assert events.count('target-cleanup') == 1 and 'source-post' not in events
    if failure in ('source-boundary','source-session','reader','auth-binding'):
        assert 'factory' not in events and 'source-capture' not in events and 'enter-target' not in events
    if failure in ('source-capture','writer-omission','stream-omission'):
        assert 'enter-target' not in events
    assert saved.read_bytes() == b''.join(stream.stream_company_test_retention(
        capture(record()) if failure == 'stream-omission' else expected))


@pytest.mark.parametrize('company', ['invalid', 'AAAAAAAA-0000-4000-8000-000000000001', '00000000-0000-0000-0000-000000000000'])
def test_invalid_company_cannot_reach_source_or_auth(monkeypatch, company):
    monkeypatch.setattr(runner.owned.boundary, 'owned_source', lambda *args: pytest.fail('reached source'))
    with pytest.raises(ValueError):
        runner.rehearse(SimpleNamespace(company_id=company))


@pytest.mark.parametrize('phase', ['acquisition', 'active', 'cleanup', 'cleanup-failure'])
def test_subprocess_sigterm_unwinds_owned_scope_without_accepting_report(tmp_path, phase):
    # Actual process signal and entry point, but explicit resource-free context/Auth doubles.
    child = r"""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import signal
import sys
import time
import pytest
import test_rf1086_company_test_retention_restore_runner as fixture

root, phase = Path(sys.argv[1]), sys.argv[2]
patch = pytest.MonkeyPatch()
args, events, _, _, _ = fixture._configure_owned_runner_double(patch, root, None)
runner = fixture.runner

def event(name):
    with (root/'events').open('a') as output:
        output.write(name+'\n')

def pause(name):
    (root/name).touch()
    deadline = time.monotonic()+10
    while not (root/(name+'-release')).exists():
        if time.monotonic()>deadline:
            raise RuntimeError('process oracle release deadline')
        time.sleep(.01)

original_capture = runner.capture_owned_company_test_retention
async def capture(*args):
    event('capture')
    return await original_capture(*args)
patch.setattr(runner, 'capture_owned_company_test_retention', capture)

@contextmanager
def restore(*args):
    event('acquiring')
    if phase == 'acquisition':
        pause('ready')
    event('registered')
    try:
        yield type('Recovery', (), {'proof': {'resource-free-double': True}})()
    finally:
        event('cleanup-start')
        if phase in ('cleanup', 'cleanup-failure'):
            pause('ready')
        event('cleanup-finished')
        if phase == 'cleanup-failure':
            raise RuntimeError('synthetic owned cleanup failure')
patch.setattr(runner, 'restored_identity', restore)

async def helper(*args, **kwargs):
    event('helper')
    if phase == 'active':
        (root/'ready').touch()
        await asyncio.sleep(10)
    return fixture.CompanyTestInventoryRecoveryReport(2, 'a'*64, '2026-10-13T00:00:00+00:00',
        'b'*64, True, True, True, True, True, True, 'blocked-by-preserved-historical-foreign-keys')
patch.setattr(runner, 'verify_company_test_inventory_actor_recovery', helper)
previous = lambda signum, frame: None
signal.signal(signal.SIGTERM, previous)
sys.argv = ['runner', '--company-id', args.company_id, '--stream', args.stream,
    '--writer-expectation', args.writer_expectation]
code = runner.main()
assert signal.getsignal(signal.SIGTERM) is previous
(root/'handler-restored').touch()
patch.undo()
raise SystemExit(code)
"""
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join([str(ROOT/'apps/backend/src'), str(ROOT/'apps/backend/tests')])
    process = subprocess.Popen([sys.executable, '-c', child, str(tmp_path), phase],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic()+10
        while not (tmp_path/'ready').exists():
            assert process.poll() is None, 'child exited before cancellation stage'
            assert time.monotonic()<deadline, 'child did not reach cancellation stage'
            time.sleep(.01)
        process.send_signal(signal.SIGTERM)
        if phase != 'active':
            # Repeated termination must not interrupt registration or finally.
            process.send_signal(signal.SIGTERM)
            (tmp_path/'ready-release').touch()
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert process.returncode == (1 if phase == 'cleanup-failure' else 143)
    assert stdout == ''
    assert stderr.strip() == ('owned_company_test_inventory_restore_failed\n'
        'owned_company_test_inventory_restore_diagnostic stage=independent-recovery fingerprint=unclassified' if phase == 'cleanup-failure'
        else 'owned_company_test_inventory_restore_cancelled')
    events = (tmp_path/'events').read_text().splitlines()
    assert events.count('registered') == 1
    assert events.count('cleanup-start') == events.count('cleanup-finished') == 1
    assert events.count('capture') == 1  # no postcheck or accepted report after cancellation
    assert ('helper' in events) is (phase != 'acquisition')
    assert (tmp_path/'handler-restored').exists()


@pytest.mark.parametrize('components', ['roles', 'catalog', 'auth', 'companyMemberships',
    'roles,catalog,auth,companyMemberships'])
def test_failure_diagnostic_exposes_only_fixed_fingerprint_component_labels(components):
    error=ValueError('Independent recovery roles, ownership, ACLs or Auth rows differ; components='+components)
    assert runner._failure_diagnostic(error, {'stage':'independent-recovery'}) == (
        'stage=independent-recovery fingerprint='+components)


@pytest.mark.parametrize('error', [RuntimeError('secret-token raw-auth-row'),
    ValueError('Independent recovery roles, ownership, ACLs or Auth rows differ; components=secret-token'),
    ValueError('Independent recovery roles, ownership, ACLs or Auth rows differ; components=auth,roles'),
    ValueError('Independent recovery roles, ownership, ACLs or Auth rows differ; components=roles\nsecret-token'),
    ValueError('secret-token', 'raw-auth-row')])
def test_failure_diagnostic_never_echoes_unknown_exception_or_caller_stage(error):
    assert runner._failure_diagnostic(error, {'stage':'secret-token'}) == (
        'stage=unclassified fingerprint=unclassified')


def test_main_failure_reports_bounded_progress_and_no_exception_text(monkeypatch,capsys):
    def failed(args, *, progress):
        progress['stage']='source-artifacts'
        raise ValueError('secret-token raw-company-row')
    monkeypatch.setattr(runner,'rehearse',failed)
    monkeypatch.setattr(sys,'argv',['runner','--company-id',str(COMPANY),'--stream','owned-stream',
        '--writer-expectation','owned-writer'])
    assert runner.main()==1
    result=capsys.readouterr()
    assert result.out == ''
    assert result.err == ('owned_company_test_inventory_restore_failed\n'
        'owned_company_test_inventory_restore_diagnostic stage=source-artifacts fingerprint=unclassified\n')
