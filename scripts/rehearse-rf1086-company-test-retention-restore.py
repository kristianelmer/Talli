"""One explicitly owned local company inventory + independent Auth rehearsal.

No hosted target, reusable clone, public runtime activation or filing authority.
Portable hashes remain integrity claims, separate from current source Auth.
"""
from rf1086_actual_replay_package import start_export_clock

start_export_clock()

import argparse
import asyncio
import base64
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import hmac
import importlib.util
from io import BytesIO
import json
import os
import signal
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from rf1086_identity_restore import fingerprint, owned_identity_source, restored_identity
from rf1086_stateless_owner_fixture import stateless_es256_owner_token
from rf1086_company_test_inventory_identity_restore import verify_company_test_inventory_actor_recovery
from verify_rf1086_company_test_retention import artifact_capture, local_file
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresCompanyTestRetentionSessionFactory
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.application.shareholder_register_company_test_retention_bundle import (
    pack_company_test_retention, verify_company_test_retention_bundle)
from talli_backend.application.shareholder_register_company_test_retention_stream import verify_company_test_retention_stream
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId

# Reuse only the exact existing ownership boundary and restricted-reader validator.
spec = importlib.util.spec_from_file_location('rf_owned_restore_boundary', ROOT / 'scripts/rehearse-rf1086-owned-restore.py')
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)


async def capture_owned_company_test_retention(factory, owner_token, company_id):
    session = await factory.session(owner_token)
    return await session.read_company_test_retention(rf.Rf1086CompanyTestRetentionQuery(company_id, session.actor_id))


def _stateless_owned_owner_token(token, source_auth_environment):
    """Fixed local HS256 negative fixture; verify its captured signing key first.

    Unsupported signing configurations fail closed rather than silently omitting the
    required signed stateless check. No new session or privileged role is minted.
    """
    header, payload, signature = token.split('.')
    decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    key = source_auth_environment.get('GOTRUE_JWT_SECRET')
    if json.loads(decode(header)).get('alg') != 'HS256' or not isinstance(key, str) or not key:
        raise ValueError('Owned stateless fixture requires captured HS256 signing configuration')
    expected_signature = hmac.digest(key.encode(), (header + '.' + payload).encode(), 'sha256')
    if not hmac.compare_digest(expected_signature, decode(signature)):
        raise ValueError('Owned stateless fixture signing key differs from the authenticated owner token')
    claims = json.loads(decode(payload))
    if 'session_id' not in claims:
        raise ValueError('Original owned owner token has no live session')
    del claims['session_id']
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
    body = header + '.' + encode(json.dumps(claims, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    return body + '.' + encode(hmac.digest(key.encode(), body.encode(), 'sha256'))


def _signed_stateless_owned_owner_token(token, source_auth_environment):
    """Route a bounded ES256 header to independent captured-key verification."""
    header = token[:4097].partition('.')[0] if type(token) is str else ''
    if len(header) <= 4096:
        try:
            value = json.loads(base64.b64decode(header + '=' * (-len(header) % 4),
                altchars=b'-_', validate=True))
        except (ValueError, UnicodeError, RecursionError):
            value = None
        if type(value) is dict and value.get('alg') == 'ES256':
            return stateless_es256_owner_token(token, source_auth_environment)
    return _stateless_owned_owner_token(token, source_auth_environment)


def _stateless_diagnostic_metadata(token, source_auth_environment):
    """Bounded header and field-presence labels; never signing authority."""
    algorithm = 'unclassified'
    if type(token) is str:
        # Inspect only a bounded header prefix, never the payload or signature.
        header = token[:4097].partition('.')[0]
        if len(header) <= 4096 and '.' in token[:4097]:
            try:
                def unique_fields(pairs):
                    fields = {}
                    for key, value in pairs:
                        if key in fields:
                            raise ValueError('Duplicate header field')
                        fields[key] = value
                    return fields
                decoded = base64.b64decode(header + '=' * (-len(header) % 4), altchars=b'-_', validate=True)
                fields = json.loads(decoded, object_pairs_hook=unique_fields)
                value = fields.get('alg') if type(fields) is dict else None
                if type(value) is str and value in ('HS256', 'ES256', 'RS256'):
                    algorithm = value.lower()
            except (ValueError, TypeError, UnicodeError, RecursionError):
                pass
    signing_fields = 'unclassified'
    if type(source_auth_environment) is dict:
        present = ('GOTRUE_JWT_SECRET' in source_auth_environment, 'GOTRUE_JWT_KEYS' in source_auth_environment)
        signing_fields = {(True, False): 'secret-only', (False, True): 'keys-only',
            (True, True): 'both', (False, False): 'missing'}[present]
    return {'statelessAlgorithm': algorithm, 'statelessSigningFields': signing_fields}


def _stateless_failure_diagnostic(error, progress):
    """Closed error labels only; unknown types, shapes and metadata stay private."""
    cause = 'unclassified'
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str:
        cause = {
            'Owned stateless fixture requires captured HS256 signing configuration': 'unsupported-signing-configuration',
            'Owned stateless fixture requires captured ES256 signing configuration': 'unsupported-signing-configuration',
            'Owned stateless fixture signing key differs from the authenticated owner token': 'signature-mismatch',
            'Original owned owner token has no live session': 'live-session-missing',
        }.get(error.args[0], 'unclassified')
    def label(key, allowed):
        value = progress.get(key) if type(progress) is dict else None
        return value if type(value) is str and value in allowed else 'unclassified'
    algorithm = label('statelessAlgorithm', ('hs256', 'es256', 'rs256'))
    signing_fields = label('statelessSigningFields', ('secret-only', 'keys-only', 'both', 'missing'))
    return 'cause=' + cause + ' algorithm=' + algorithm + ' signing-fields=' + signing_fields


class _TerminationRequested(BaseException):
    """SIGTERM cancels acceptance while allowing the sole owner to clean up."""


class _Termination:
    def __init__(self):
        self.pending = False
        self.interruptible = True

    def receive(self, signum, frame):
        self.pending = True
        if self.interruptible:
            self.check()

    def check(self):
        if self.pending:
            raise _TerminationRequested()


@contextmanager
def _termination_scope():
    termination = _Termination()
    previous = signal.signal(signal.SIGTERM, termination.receive)
    try:
        yield termination
    finally:
        signal.signal(signal.SIGTERM, previous)


def rehearse(args, *, progress=None):
    with _termination_scope() as termination:
        return _rehearse(args, termination, progress)


def _rehearse(args, termination, progress=None):
    def stage(name):
        if progress is not None:
            progress['stage'] = name
    stage('source-boundary')
    if str(UUID(args.company_id)) != args.company_id or UUID(args.company_id).int == 0:
        raise ValueError('Canonical nonzero company required')
    company_id = CompanyId(args.company_id)
    source_url, workdir = os.environ['DATABASE_URL'], os.environ['TALLI_SUPABASE_WORKDIR']
    # Exact source/container/live-session/Auth binding BEFORE any capture/package/Auth I/O.
    container, _ = owned.boundary.owned_source(workdir, source_url, owned.boundary.inspect_container)
    owned.boundary.verify_source_session(source_url, container)
    reader = owned.owner_read_url(source_url, os.environ['TALLI_LEDGER_DATABASE_URL'])
    db, _, auth_environment = owned_identity_source(workdir, source_url, owned.boundary)
    if db['Id'] != container:
        raise ValueError('Owned inventory source changed identity')
    before_identity = fingerprint(container)
    owner_token = os.environ['TALLI_RF_RESTORE_OWNER_TOKEN']
    outsider_token = os.environ['TALLI_RF_RESTORE_OUTSIDER_TOKEN']
    anon_key = os.environ['SUPABASE_ANON_KEY']
    factory = PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration(
        os.environ['SUPABASE_URL'], anon_key, reader))
    stage('source-capture')
    before = asyncio.run(capture_owned_company_test_retention(factory, owner_token, company_id))
    stage('source-artifacts')
    with local_file(args.stream) as source:
        captured = verify_company_test_retention_stream(source, company_id=company_id)
    with local_file(args.writer_expectation) as source:
        writer_expectation = artifact_capture(source, company_id)
    # Fresh owning reads have their own observation time. Never rewrite saved SOURCE bytes.
    rf.assert_company_test_retention_target_inventory_matches(captured, writer_expectation)
    rf.assert_company_test_retention_target_inventory_matches(captured, before)
    source_raw = rf.serialize_rf1086_company_test_retention(captured).encode('utf-8')
    source_sha = sha256(source_raw).hexdigest()
    package = pack_company_test_retention(captured)
    verified = verify_company_test_retention_bundle(BytesIO(package), company_id=company_id)
    rf.assert_company_test_retention_source_capture_matches(verified, captured)
    stage('stateless-token')
    if progress is not None:
        progress.update(_stateless_diagnostic_metadata(owner_token, auth_environment))
    stateless_token = _signed_stateless_owned_owner_token(owner_token, auth_environment)
    # Sole lifecycle owner. No target credentials, factory or live handle escapes.
    # Defer termination through acquisition: the old owner must register resources
    # before interruption. Defer through cleanup too, including repeated SIGTERM.
    termination.check()
    termination.interruptible = False
    stage('independent-recovery')
    with restored_identity(source_url, workdir, owned.boundary) as recovery:
        try:
            termination.interruptible = True
            termination.check()
            identity_proof = dict(recovery.proof)
            target_report = asyncio.run(verify_company_test_inventory_actor_recovery(
                recovery, company_id, captured, source_sha, source_reader_url=reader,
                anon_key=anon_key, owner_token=owner_token, outsider_token=outsider_token,
                stateless_owner_token=stateless_token))
        finally:
            termination.interruptible = False
    termination.interruptible = True
    termination.check()
    # Any context cleanup/fingerprint failure raises before a report can be accepted.
    stage('source-postcheck')
    after = asyncio.run(capture_owned_company_test_retention(factory, owner_token, company_id))
    rf.assert_company_test_retention_target_inventory_matches(captured, after)
    if (sha256(rf.serialize_rf1086_company_test_retention(captured).encode()).hexdigest() != source_sha
            or fingerprint(container) != before_identity):
        raise ValueError('Inventory restore changed the original SOURCE capture or identity')
    return {'status': 'verified_owned_company_test_inventory_restore',
        'sourceArtifactSha256': source_sha, 'bundleSha256': sha256(package).hexdigest(),
        'bundleBytes': len(package), 'sourceObservationUnchanged': True,
        'sourceInventoryUnchanged': True, 'sourceIdentityAndRolesUnchanged': True,
        'independentRecoveryResourcesRemoved': True,
        'sourceOrigin': 'OWNED_CURRENT_AUTH_AND_INDEPENDENT_WRITER_EXPECTATION_MATCH',
        'legalCompanyArchiveReceipt': False, 'hostedKeyRecoveryVerified': False,
        'identity': identity_proof, 'inventory': asdict(target_report)}


def _failure_diagnostic(error, progress):
    """Finite labels only. Never print exception text, credentials or captured rows."""
    stages = ('source-boundary', 'source-capture', 'source-artifacts', 'stateless-token',
        'independent-recovery', 'source-postcheck')
    stage = progress.get('stage') if type(progress) is dict else None
    if stage not in stages:
        stage = 'unclassified'
    components = 'unclassified'
    prefix = 'Independent recovery roles, ownership, ACLs or Auth rows differ; components='
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str:
        message = error.args[0]
        names = ('roles', 'catalog', 'auth', 'companyMemberships')
        allowed = {','.join(name for index, name in enumerate(names) if mask & (1 << index))
            for mask in range(1, 16)}
        if message.startswith(prefix) and message[len(prefix):] in allowed:
            components = message[len(prefix):]
    return 'stage=' + stage + ' fingerprint=' + components


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--stream', required=True)
    parser.add_argument('--writer-expectation', required=True)
    args = parser.parse_args()
    progress = {}
    try:
        result = rehearse(args, progress=progress)
    except _TerminationRequested:
        print('owned_company_test_inventory_restore_cancelled', file=sys.stderr)
        return 143
    except Exception as error:
        print('owned_company_test_inventory_restore_failed', file=sys.stderr)
        print('owned_company_test_inventory_restore_diagnostic ' + _failure_diagnostic(error, progress), file=sys.stderr)
        if progress.get('stage') == 'stateless-token':
            print('owned_company_test_inventory_restore_stateless_diagnostic ' + _stateless_failure_diagnostic(error, progress), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
