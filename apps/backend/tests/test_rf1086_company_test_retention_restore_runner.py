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

@pytest.mark.parametrize('message,cause', [
    ('Owned stateless fixture requires captured HS256 signing configuration', 'unsupported-signing-configuration'),
    ('Owned stateless fixture signing key differs from the authenticated owner token', 'signature-mismatch'),
    ('Original owned owner token has no live session', 'live-session-missing'),
])
def test_stateless_diagnostic_classifies_only_exact_owned_failure(message, cause):
    progress = {'statelessAlgorithm': 'es256', 'statelessSigningFields': 'both'}
    expected = 'cause=' + cause + ' algorithm=es256 signing-fields=both'
    assert runner._stateless_failure_diagnostic(ValueError(message), progress) == expected
    class OtherValueError(ValueError):
        pass
    for error in (OtherValueError(message), RuntimeError(message), ValueError(message, 'secret-token'),
            ValueError(message + '\nprivate-key'), ValueError()):
        assert runner._stateless_failure_diagnostic(error, progress) == (
            'cause=unclassified algorithm=es256 signing-fields=both')


@pytest.mark.parametrize('algorithm', ['HS256', 'ES256', 'RS256'])
@pytest.mark.parametrize('env,fields', [({}, 'missing'), ({'GOTRUE_JWT_SECRET': 'private-secret'}, 'secret-only'),
    ({'GOTRUE_JWT_KEYS': 'private-JWK'}, 'keys-only'),
    ({'GOTRUE_JWT_SECRET': '', 'GOTRUE_JWT_KEYS': 'private-JWK'}, 'both')])
def test_stateless_metadata_reports_header_algorithm_and_field_presence_without_claims_or_keys(algorithm, env, fields):
    header = base64.urlsafe_b64encode(json.dumps({'alg': algorithm, 'kid': 'private-kid'}).encode()).rstrip(b'=').decode()
    token = header + '.THIS-IS-NOT-JSON-CLAIMS.private-signature'
    original_env = dict(env)
    assert runner._stateless_diagnostic_metadata(token, env) == {
        'statelessAlgorithm': algorithm.lower(), 'statelessSigningFields': fields}
    assert env == original_env
    assert token == header + '.THIS-IS-NOT-JSON-CLAIMS.private-signature'


@pytest.mark.parametrize('header', [b'[]', b'null', b'1', b'{"alg":7}', b'{"alg":"PRIVATE-ALG"}',
    b'{"alg":"HS256","alg":"ES256"}', b'{"alg":"HS256"}private', b'\xff', b'[' * 2000])
def test_stateless_metadata_malformed_unknown_or_duplicate_header_is_unclassified(header):
    encoded = base64.urlsafe_b64encode(header).rstrip(b'=').decode()
    assert runner._stateless_diagnostic_metadata(encoded + '.private-claims.private-signature', {}) == {
        'statelessAlgorithm': 'unclassified', 'statelessSigningFields': 'missing'}


@pytest.mark.parametrize('token', [None, {}, 'private-token', '!' + '.private.private',
    'A' * 4097 + '.private.private', 'A' * 100000 + '.private.private'])
def test_stateless_metadata_bounds_header_and_rejects_invalid_input_without_echo(token):
    assert runner._stateless_diagnostic_metadata(token, None) == {
        'statelessAlgorithm': 'unclassified', 'statelessSigningFields': 'unclassified'}


def test_stateless_formatter_never_echoes_unknown_metadata_or_exception():
    for progress in (None, {'statelessAlgorithm': 'private-token', 'statelessSigningFields': 'private-key'},
            {'statelessAlgorithm': [], 'statelessSigningFields': {}}):
        assert runner._stateless_failure_diagnostic(ValueError('private-subject private-session'), progress) == (
            'cause=unclassified algorithm=unclassified signing-fields=unclassified')


def test_stateless_failure_diagnostic_reaches_entry_point_without_recovery_or_secret_output(monkeypatch, tmp_path, capsys):
    args, events, _, _, _ = _configure_owned_runner_double(monkeypatch, tmp_path, None)
    monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN', signed(CLAIMS, header={'alg': 'ES256', 'kid': 'private-kid'}))
    monkeypatch.setattr(sys, 'argv', ['runner', '--company-id', args.company_id, '--stream', args.stream,
        '--writer-expectation', args.writer_expectation])
    assert runner.main() == 1
    result = capsys.readouterr()
    assert result.out == ''
    assert result.err == ('owned_company_test_inventory_restore_failed\n'
        'owned_company_test_inventory_restore_diagnostic stage=stateless-token fingerprint=unclassified\n'
        'owned_company_test_inventory_restore_stateless_diagnostic cause=unsupported-signing-configuration '
        'algorithm=es256 signing-fields=secret-only\n')
    assert 'enter-target' not in events and 'source-post' not in events


# Fresh synthetic ES256 inputs exercise crypto only; no Auth/session proof.
def _es_fixture(*, header=None, claims=None, key=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    private = key or ec.generate_private_key(ec.SECP256R1())
    numbers = private.private_numbers()
    encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    jwk = {'kty': 'EC', 'crv': 'P-256', 'alg': 'ES256', 'kid': 'synthetic-owned-key',
        'use': 'sig', 'key_ops': ['sign', 'verify'],
        'x': encode(numbers.public_numbers.x.to_bytes(32, 'big')),
        'y': encode(numbers.public_numbers.y.to_bytes(32, 'big')),
        'd': encode(numbers.private_value.to_bytes(32, 'big'))}
    selected_header = {'alg': 'ES256', 'typ': 'JWT', 'kid': jwk['kid']} if header is None else header
    selected_claims = dict(CLAIMS, iss='synthetic-owned-issuer', aud=['authenticated'],
        app_metadata={'nested': [True, None, 1.25]}) if claims is None else claims
    body = encode(json.dumps(selected_header, separators=(',', ':')).encode()) + '.' + encode(
        json.dumps(selected_claims, separators=(',', ':')).encode())
    first, second = utils.decode_dss_signature(private.sign(body.encode(), ec.ECDSA(hashes.SHA256())))
    return private, jwk, body + '.' + encode(first.to_bytes(32, 'big') + second.to_bytes(32, 'big'))


def _es_sign_body(private, body):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    first, second = utils.decode_dss_signature(private.sign(body.encode(), ec.ECDSA(hashes.SHA256())))
    return body + '.' + base64.urlsafe_b64encode(first.to_bytes(32, 'big') + second.to_bytes(32, 'big')).rstrip(b'=').decode()


def _es_verify(private, token):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    header, payload, signature = token.split('.')
    decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    raw = decode(signature)
    assert len(raw) == 64
    private.public_key().verify(utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'),
        int.from_bytes(raw[32:], 'big')), (header + '.' + payload).encode(), ec.ECDSA(hashes.SHA256()))
    return json.loads(decode(payload))


@pytest.mark.parametrize('optional_metadata', [True, False])
def test_es256_fixture_proves_original_key_preserves_header_and_all_other_claims(optional_metadata):
    private, jwk, token = _es_fixture()
    if not optional_metadata:
        for field in ('alg', 'use', 'key_ops'):
            del jwk[field]
    _, other, _ = _es_fixture()
    other['kid'] = 'unrelated-owned-key'
    environment = {'GOTRUE_JWT_KEYS': json.dumps([other, jwk]), 'GOTRUE_JWT_SECRET': 'unused-synthetic-secret'}
    before = dict(environment)
    original = _es_verify(private, token)
    result = runner._signed_stateless_owned_owner_token(token, environment)
    assert result.split('.')[0] == token.split('.')[0]
    assert _es_verify(private, result) == {key: value for key, value in original.items() if key != 'session_id'}
    assert _es_verify(private, token) == original and environment == before


def test_es256_dispatch_retains_exact_hs256_result_and_unsupported_algorithm_refusal():
    token = signed(CLAIMS)
    environment = {'GOTRUE_JWT_SECRET': 'owned-synthetic-HS256-key', 'GOTRUE_JWT_KEYS': 'private-unused-keyset'}
    assert runner._signed_stateless_owned_owner_token(token, environment) == runner._stateless_owned_owner_token(token, environment)
    with pytest.raises(ValueError, match='requires captured HS256'):
        runner._signed_stateless_owned_owner_token(signed(CLAIMS, header={'alg': 'RS256'}), environment)


@pytest.mark.parametrize('mutation', [
    'wrong-public', 'wrong-scalar', 'off-curve', 'zero-scalar', 'short-coordinate', 'missing-private',
    'wrong-type', 'wrong-curve', 'wrong-algorithm', 'wrong-use', 'verify-only', 'wrong-operations',
    'duplicate-operations', 'nonstring-operations', 'missing-kid', 'duplicate-kid', 'unknown-kid',
    'empty-keyset', 'object-keyset', 'nondict-key', 'malformed-keyset', 'duplicate-key-field',
    'oversized-keyset', 'too-many-keys', 'padded-coordinate', 'noncanonical-coordinate',
    'tampered-payload', 'tampered-header', 'tampered-signature', 'short-signature', 'long-signature',
    'padded-signature', 'noncanonical-signature', 'missing-sid', 'empty-sid', 'numeric-sid',
    'array-claims', 'duplicate-claims', 'nan-claims', 'infinite-claims', 'overflow-claims',
    'malformed-claims', 'noncanonical-payload', 'noncanonical-header', 'oversized-token',
    'oversized-header', 'oversized-kid', 'duplicate-header', 'missing-header-kid', 'empty-header-kid',
    'jwk', 'jku', 'x5u', 'x5c', 'crit', 'b64', 'helper-wrong-algorithm', 'utf16-header', 'utf16-claims',
])
def test_es256_fixture_refuses_unproven_keys_tokens_claims_and_bounds_privately(mutation):
    from rf1086_stateless_owner_fixture import stateless_es256_owner_token
    private, jwk, token = _es_fixture()
    keys = [jwk]
    header, payload, signature = token.split('.')
    encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    claims = _es_verify(private, token)
    changes = {'wrong-type': ('kty', 'RSA'), 'wrong-curve': ('crv', 'P-384'),
        'wrong-algorithm': ('alg', 'HS256'), 'wrong-use': ('use', 'enc'),
        'verify-only': ('key_ops', ['verify']), 'wrong-operations': ('key_ops', ['sign', 'deriveKey']),
        'duplicate-operations': ('key_ops', ['sign', 'sign']), 'nonstring-operations': ('key_ops', ['sign', 1])}
    if mutation in changes:
        field, value = changes[mutation];jwk[field] = value
    elif mutation in ('wrong-public', 'wrong-scalar'):
        _, other, _ = _es_fixture()
        for field in (('x', 'y') if mutation == 'wrong-public' else ('d',)):
            jwk[field] = other[field]
    elif mutation in ('off-curve', 'zero-scalar', 'short-coordinate'):
        jwk['x' if mutation == 'off-curve' else 'd'] = encode(b'\0' * (31 if mutation == 'short-coordinate' else 32))
    elif mutation == 'missing-private':del jwk['d']
    elif mutation == 'missing-kid':del jwk['kid']
    elif mutation == 'duplicate-kid':keys = [jwk, dict(jwk)]
    elif mutation == 'unknown-kid':jwk['kid'] = 'different-synthetic-key'
    elif mutation == 'empty-keyset':keys = []
    elif mutation == 'object-keyset':keys = {'keys': [jwk]}
    elif mutation == 'nondict-key':keys = [jwk, None]
    elif mutation == 'too-many-keys':keys = [dict(jwk, kid='unrelated-' + str(i)) for i in range(32)] + [jwk]
    elif mutation == 'padded-coordinate':jwk['d'] += '='
    elif mutation == 'noncanonical-coordinate':jwk['d'] = encode(b'\0'*32)[:-1] + 'B'
    elif mutation == 'tampered-payload':payload = encode(json.dumps(dict(claims, role='synthetic-escalation')).encode())
    elif mutation == 'tampered-header':header = encode(b'{"alg":"ES256","kid":"synthetic-owned-key","typ":"tampered"}')
    elif mutation == 'tampered-signature':signature = encode(b'\0'*64)
    elif mutation == 'short-signature':signature = encode(b'\0'*63)
    elif mutation == 'long-signature':signature = encode(b'\0'*65)
    elif mutation == 'padded-signature':signature += '=='
    elif mutation == 'noncanonical-signature':signature = encode(b'\0'*64)[:-1] + 'B'
    elif mutation in ('missing-sid', 'empty-sid', 'numeric-sid'):
        claims.pop('session_id')
        if mutation != 'missing-sid':claims['session_id'] = '' if mutation == 'empty-sid' else 1
        token = _es_sign_body(private, header + '.' + encode(json.dumps(claims).encode()))
    elif mutation in ('array-claims', 'duplicate-claims', 'nan-claims', 'infinite-claims', 'overflow-claims', 'malformed-claims'):
        raw = {'array-claims': b'[]', 'duplicate-claims': b'{"session_id":"synthetic-session","role":"a","role":"b"}',
            'nan-claims': b'{"session_id":"synthetic-session","value":NaN}',
            'infinite-claims': b'{"session_id":"synthetic-session","value":Infinity}',
            'overflow-claims': b'{"session_id":"synthetic-session","value":1e9999}',
            'malformed-claims': b'{private-captured-value'}[mutation]
        token = _es_sign_body(private, header + '.' + encode(raw))
    elif mutation == 'utf16-header':token = _es_sign_body(private, encode(json.dumps({'alg':'ES256','kid':jwk['kid']}).encode('utf-16')) + '.' + payload)
    elif mutation == 'utf16-claims':token = _es_sign_body(private, header + '.' + encode(json.dumps(claims).encode('utf-16')))
    elif mutation == 'noncanonical-payload':token = _es_sign_body(private, header + '.' + payload + '=')
    elif mutation == 'noncanonical-header':token = _es_sign_body(private, header + '=.' + payload)
    elif mutation == 'oversized-token':token = header + '.' + 'A' * (128 * 1024) + '.' + signature
    elif mutation == 'oversized-header':token = _es_sign_body(private, encode(json.dumps({'alg':'ES256','kid':jwk['kid'],'padding':'x'*4096}).encode()) + '.' + payload)
    elif mutation in ('oversized-kid', 'duplicate-header', 'missing-header-kid', 'empty-header-kid', 'helper-wrong-algorithm', 'jwk', 'jku', 'x5u', 'x5c', 'crit', 'b64'):
        fields = {'alg': 'ES256', 'kid': jwk['kid']}
        if mutation == 'oversized-kid':fields['kid'] = jwk['kid'] = 'x'*513
        elif mutation == 'missing-header-kid':del fields['kid']
        elif mutation == 'empty-header-kid':fields['kid'] = ''
        elif mutation == 'helper-wrong-algorithm':fields['alg'] = 'HS256'
        elif mutation in ('jwk', 'jku', 'x5u', 'x5c', 'crit', 'b64'):fields[mutation] = 'synthetic-external-authority'
        raw = b'{"alg":"ES256","alg":"ES256","kid":"synthetic-owned-key"}' if mutation == 'duplicate-header' else json.dumps(fields).encode()
        token = _es_sign_body(private, encode(raw) + '.' + payload)
    if mutation in ('tampered-payload','tampered-header','tampered-signature','short-signature','long-signature','padded-signature','noncanonical-signature'):
        token = header + '.' + payload + '.' + signature
    keyset = json.dumps(keys)
    if mutation == 'malformed-keyset':keyset = '[private-captured-key'
    elif mutation == 'duplicate-key-field':keyset = '[' + json.dumps(jwk)[:-1] + ',"kid":"synthetic-owned-key"}]'
    elif mutation == 'oversized-keyset':keyset += ' ' * (256 * 1024)
    environment = {'GOTRUE_JWT_KEYS': keyset, 'GOTRUE_JWT_SECRET': 'private-unused-secret'}
    with pytest.raises(ValueError) as rejected:
        stateless_es256_owner_token(token, environment)
    assert str(rejected.value) == 'Owned ES256 stateless fixture verification failed'
    assert rejected.value.__suppress_context__
    assert all(value not in str(rejected.value) for value in (jwk.get('d', 'synthetic-private'), token, 'private-unused-secret'))


@pytest.mark.parametrize('keyset', [None, '', 3])
def test_es256_missing_captured_keyset_has_fixed_configuration_label_without_hs_fallback(keyset):
    _, _, token = _es_fixture()
    environment = {'GOTRUE_JWT_SECRET': 'synthetic-hs-secret'}
    if keyset is not None:environment['GOTRUE_JWT_KEYS'] = keyset
    with pytest.raises(ValueError) as rejected:
        runner._signed_stateless_owned_owner_token(token, environment)
    assert str(rejected.value) == 'Owned stateless fixture requires captured ES256 signing configuration'
    assert runner._stateless_failure_diagnostic(rejected.value,
        {'statelessAlgorithm':'es256','statelessSigningFields':'secret-only'}) == (
            'cause=unsupported-signing-configuration algorithm=es256 signing-fields=secret-only')


def test_es256_fixture_accepts_exact_input_limits_without_alternate_authority():
    from rf1086_stateless_owner_fixture import stateless_es256_owner_token
    private, jwk, _ = _es_fixture()
    jwk['kid'] = 'k' * 512
    header = {'alg': 'ES256', 'kid': jwk['kid'], 'padding': ''}
    header['padding'] = 'h' * (3072 - len(json.dumps(header, separators=(',', ':')).encode()))
    encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    encoded_header = encode(json.dumps(header, separators=(',', ':')).encode())
    assert len(encoded_header) == 4096
    claims = dict(CLAIMS, padding='')
    payload_bytes = (128 * 1024 - len(encoded_header) - 2 - 86) * 3 // 4
    claims['padding'] = 'p' * (payload_bytes - len(json.dumps(claims, separators=(',', ':')).encode()))
    body = encoded_header + '.' + encode(json.dumps(claims, separators=(',', ':')).encode())
    token = _es_sign_body(private, body)
    assert len(token) == 128 * 1024
    keys = [dict(jwk, kid='other-' + str(i)) for i in range(31)] + [jwk]
    keyset = json.dumps(keys)
    keyset += ' ' * (256 * 1024 - len(keyset))
    result = stateless_es256_owner_token(token, {'GOTRUE_JWT_KEYS': keyset})
    assert result.split('.')[0] == encoded_header
    assert _es_verify(private, result) == {key: value for key, value in claims.items() if key != 'session_id'}


def test_es256_output_interoperates_with_node_webcrypto_without_private_key_transfer():
    private, jwk, token = _es_fixture()
    result = runner._signed_stateless_owned_owner_token(token, {'GOTRUE_JWT_KEYS': json.dumps([jwk])})
    public = {key: value for key, value in jwk.items() if key not in ('d', 'key_ops')}
    script = '''
        import { webcrypto } from 'node:crypto';
        const chunks = [];
        for await (const chunk of process.stdin) chunks.push(chunk);
        const { key, tokens } = JSON.parse(Buffer.concat(chunks).toString());
        const publicKey = await webcrypto.subtle.importKey('jwk', key,
            { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
        const valid = [];
        for (const token of tokens) {
            const [header, payload, signature] = token.split('.');
            valid.push(await webcrypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' },
                publicKey, Buffer.from(signature, 'base64url'), Buffer.from(header + '.' + payload)));
        }
        process.stdout.write(JSON.stringify(valid));
    '''
    tampered = result.split('.')
    tampered[1] = base64.urlsafe_b64encode(b'{"role":"synthetic-tamper"}').rstrip(b'=').decode()
    checked = subprocess.run(['node', '--input-type=module', '-e', script],
        input=json.dumps({'key': public, 'tokens': [token, result, '.'.join(tampered)]}),
        text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(checked.stdout) == [True, True, False]


@pytest.mark.parametrize('overflow', [False, True])
def test_es256_captured_keyset_budget_counts_utf8_bytes_before_parsing(overflow, monkeypatch):
    import rf1086_stateless_owner_fixture as fixture
    private, jwk, token = _es_fixture()
    jwk['synthetic_metadata'] = 'é' * 100000
    keyset = json.dumps([jwk], ensure_ascii=False)
    keyset += ' ' * (256 * 1024 - len(keyset.encode('utf-8')) + int(overflow))
    assert len(keyset) < 256 * 1024
    assert len(keyset.encode('utf-8')) == 256 * 1024 + int(overflow)
    environment = {'GOTRUE_JWT_KEYS': keyset}
    before = dict(environment)
    if overflow:
        def must_not_parse(value):
            pytest.fail('Byte budget refusal must precede JSON parsing and crypto')
        monkeypatch.setattr(fixture, '_object', must_not_parse)
        with pytest.raises(ValueError) as rejected:
            fixture.stateless_es256_owner_token(token, environment)
        assert str(rejected.value) == 'Owned ES256 stateless fixture verification failed'
        assert rejected.value.__suppress_context__
    else:
        result = fixture.stateless_es256_owner_token(token, environment)
        assert _es_verify(private, result) == {k:v for k,v in CLAIMS.items() if k != 'session_id'} | {
            'iss':'synthetic-owned-issuer','aud':['authenticated'],'app_metadata':{'nested':[True,None,1.25]}}
    assert environment == before
