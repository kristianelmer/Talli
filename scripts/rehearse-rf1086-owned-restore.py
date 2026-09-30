"""Restore an explicitly owned local RF database and verify retained evidence.

This is a disposable rehearsal, never an importer or hosted recovery command.
The restored database keeps captured identities. Optional file-backed Storage
recovery uses a fresh volume and service; cluster-wide role recovery is separate.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration
from talli_backend.application.shareholder_register_archive import (
    source_original_queries, feedback_original_queries, verify_archive_stream,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

# Reuse the established exact-workdir, pinned-container and live-session boundary.
spec = importlib.util.spec_from_file_location('owned_reporting_clone', ROOT / 'scripts/test-corporate-reporting-owned-clone.py')
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


@contextmanager
def restored_database(source_url, workdir):
    container, source_name = boundary.owned_source(workdir, source_url, boundary.inspect_container)
    boundary.verify_source_session(source_url, container)
    memberships = boundary.role_memberships(source_url)
    clone = 'rf193_restore_' + uuid4().hex
    created = False
    docker = ['docker', 'exec', '-i', container]
    with tempfile.TemporaryFile() as dump:
        subprocess.run(docker + ['pg_dump', '-U', 'supabase_admin', '--format=custom', '--dbname', source_name],
                       stdout=dump, check=True)
        try:
            subprocess.run(docker + ['createdb', '-U', 'supabase_admin', '--template=template0', clone], check=True)
            created = True
            dump.seek(0)
            subprocess.run(docker + ['pg_restore', '-U', 'supabase_admin', '--exit-on-error', '--dbname', clone],
                           stdin=dump, check=True)
            yield make_conninfo(source_url, dbname=clone)
        finally:
            if created:
                subprocess.run(docker + ['dropdb', '-U', 'supabase_admin', '--force', clone], check=True)
            if boundary.role_memberships(source_url) != memberships:
                raise RuntimeError('RF restore rehearsal changed cluster role memberships')


def owner_session(url, actor):
    claims = json.dumps({'sub': str(actor.subject), 'role': 'authenticated', 'aal': 'aal2'})
    return PostgresShareholderRegisterFilingSession(
        LedgerSupabaseConfiguration('https://local.example.test', '', url), _VerifiedActor(actor, claims),
        access_token='owned-local-restore-rehearsal', billing=None, documents=None, company_access=None)


def owner_read_url(source_url, reader_url, role='talli_ledger_backend'):
    source, reader = conninfo_to_dict(source_url), conninfo_to_dict(reader_url)
    endpoint = lambda info: {key: value for key, value in info.items() if key not in ('user', 'password')}
    if (role not in ('talli_ledger_backend', 'talli_company_access_backend')
            or reader.get('user') != role or endpoint(reader) != endpoint(source)):
        raise ValueError('RF reader must use the existing backend role on the owned source')
    return reader_url


async def canonical(url, query):
    store = owner_session(url, query.actor_id)
    archive = await store.archive_source(query)
    # Serialization rebuilds the complete RF source/approval/claim/journal policy.
    return rf.serialize_rf1086_archive(archive, query=query), archive


async def read_originals(url, actor, queries):
    contents = []
    async with await psycopg.AsyncConnection.connect(url, row_factory=dict_row) as connection, connection.transaction():
        await connection.execute('set local role documents_executor')
        await connection.execute("select set_config('talli.verified_actor_id',%s,true), set_config('request.jwt.claims',%s,true)",
                                 (str(actor.subject), json.dumps({'sub': str(actor.subject), 'role': 'authenticated'})))
        documents = PostgresDocumentOriginals(connection, actor)
        for query in queries:
            original = await documents.read_retained_evidence(query)
            # The owner adapter verifies scope, captured metadata, length and hash.
            contents.append(original)
    return contents


async def verify_restored(url, query, expected_canonical, expected_originals, queries):
    restored_canonical, archive = await canonical(url, query)
    if restored_canonical != expected_canonical:
        raise ValueError('Restored RF history differs from the downloaded archive')
    if await read_originals(url, query.actor_id, queries) != expected_originals:
        raise ValueError('Restored retained originals differ from source bytes')
    outsider = ActorId(ActorKind.USER, UserId(str(uuid4())))
    other_query = rf.Rf1086ArchiveQuery(query.company_id, query.income_year, outsider)
    try:
        await canonical(url, other_query)
    except rf.ShareholderRegisterFilingError as error:
        # The RF owner deliberately conceals companies outside membership.
        if error.code != rf.ShareholderRegisterFilingErrorCode.NOT_FOUND:
            raise
    else:
        raise ValueError('Restored RF archive admitted an unrelated actor')
    if queries:
        try:
            await read_originals(url, outsider, queries[:1])
        except psycopg.Error as error:
            if error.diag.message_primary != 'documents_forbidden':
                raise
        else:
            raise ValueError('Restored original admitted an unrelated actor')
    return archive


async def cancellation_evidence(url, query, cancellation_id):
    """Read through Company Access with the browser's real authenticated users."""
    adapter = SupabaseCompanyAccessAdapter(SupabaseConfiguration(
        url=os.environ['SUPABASE_URL'], anon_key=os.environ['SUPABASE_ANON_KEY'], database_url=url))
    rows = await adapter.cancellations(os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'], str(query.company_id))
    if (len(rows) != 1 or str(rows[0]['id']) != str(cancellation_id)
            or str(rows[0]['company_id']) != str(query.company_id)
            or str(rows[0]['requested_by']) != str(query.actor_id.subject)
            or rows[0]['status'] != 'retention_hold'
            or rows[0]['evidence']['archiveIncomeYear'] != int(query.income_year)):
        raise ValueError('Expected owner cancellation evidence is absent')
    if await adapter.cancellations(os.environ['TALLI_RF_RESTORE_OUTSIDER_TOKEN'], str(query.company_id)):
        raise ValueError('Restored cancellation admitted an unrelated owner')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--company-id', required=True, type=UUID)
    parser.add_argument('--income-year', required=True, type=int)
    parser.add_argument('--actor-id', required=True, type=UUID)
    parser.add_argument('--restore-storage', action='store_true')
    parser.add_argument('--cancellation-id', type=UUID)
    args = parser.parse_args()
    source_url = os.environ.get('DATABASE_URL')
    workdir = os.environ.get('TALLI_SUPABASE_WORKDIR')
    if not source_url or not workdir:
        raise ValueError('Explicit owned DATABASE_URL and TALLI_SUPABASE_WORKDIR required')
    reader_url = os.environ.get('TALLI_LEDGER_DATABASE_URL')
    if not reader_url:
        raise ValueError('Existing local TALLI_LEDGER_DATABASE_URL required for owner reads')
    reader_url = owner_read_url(source_url, reader_url)
    actor = ActorId(ActorKind.USER, UserId(str(args.actor_id)))
    query = rf.Rf1086ArchiveQuery(CompanyId(str(args.company_id)), IncomeYear(args.income_year), actor)
    with args.archive.open('rb') as stream:
        expected, sources, feedback = verify_archive_stream(stream, query=query,
            require_source_history=True, require_feedback_originals=True)
    expected_canonical = rf.serialize_rf1086_archive(expected, query=query)
    # Verify ownership before even the first application read against this URL.
    container, _ = boundary.owned_source(workdir, source_url, boundary.inspect_container)
    boundary.verify_source_session(source_url, container)
    before, _ = asyncio.run(canonical(reader_url, query))
    if before != expected_canonical:
        raise ValueError('Source database differs from downloaded RF archive')
    queries = source_original_queries(expected) + feedback_original_queries(expected, require_complete=True)
    originals = asyncio.run(read_originals(reader_url, actor, queries))
    storage_proof = {}
    cancellation_proof = {}
    if args.cancellation_id or args.restore_storage:
        access_url = owner_read_url(source_url, os.environ.get('TALLI_COMPANY_ACCESS_DATABASE_URL', ''),
                                    'talli_company_access_backend')
    if args.cancellation_id:
        cancellation_before = asyncio.run(cancellation_evidence(access_url, query, args.cancellation_id))
    if args.restore_storage:
        from rf1086_storage_restore import ordinary_originals, storage_source, restored_storage, verify_objects
        source_storage, storage_env, network = storage_source(workdir, source_url, boundary)
        # The browser is quiescent here. Authenticate its real sessions, read
        # restored memberships through Company Access and enforce Documents policy.
        ordinary = ordinary_originals(originals)
        source_documents = asyncio.run(verify_objects(reader_url, access_url, os.environ['SUPABASE_URL'], ordinary))
    with restored_database(source_url, workdir) as restored_url:
        restored_reader = make_conninfo(reader_url, dbname=conninfo_to_dict(restored_url)['dbname'])
        recovered = asyncio.run(verify_restored(restored_reader, query, expected_canonical, originals, queries))
        if args.cancellation_id or args.restore_storage:
            restored_access = make_conninfo(access_url, dbname=conninfo_to_dict(restored_url)['dbname'])
        if args.cancellation_id:
            if asyncio.run(cancellation_evidence(restored_access, query, args.cancellation_id)) != cancellation_before:
                raise ValueError('Restored cancellation differs from source')
            cancellation_proof = {'cancellationRestored': True, 'cancellationStatus': 'retention_hold'}
        if args.restore_storage:
            with restored_storage(source_storage, storage_env, network, restored_url, boundary) as gateway:
                restored_documents = asyncio.run(verify_objects(restored_reader, restored_access, gateway, ordinary,
                                                               storage_key=storage_env['SERVICE_KEY']))
                if restored_documents != source_documents:
                    raise ValueError('Restored ordinary document metadata differs from source')
            if asyncio.run(verify_objects(reader_url, access_url, os.environ['SUPABASE_URL'], ordinary)) != source_documents:
                raise ValueError('Restore rehearsal changed source document metadata')
            storage_proof = {'ordinaryObjects': len(ordinary), 'storageVolumeRemoved': True,
                             'storageAttributesRestored': True,
                             'storageSourceUnchanged': True, 'storageAuthenticatedDownloadsVerified': True,
                             'storageDirectReadsDenied': True, 'storageMfaEnforced': True}
    after, _ = asyncio.run(canonical(reader_url, query))
    if after != before:
        raise ValueError('Restore rehearsal changed source RF history')
    if args.cancellation_id:
        if asyncio.run(cancellation_evidence(access_url, query, args.cancellation_id)) != cancellation_before:
            raise ValueError('Restore rehearsal changed source cancellation')
    print(json.dumps({'status': 'verified_owned_rf_database_restore', 'databaseRestorePerformed': True,
        'retainedOriginalBytesRestored': True, 'objectStorageRestorePerformed': args.restore_storage,
        'sourceOriginals': sources, 'feedbackOriginals': feedback,
        'sourceVersions': len(recovered.source_history.year_sources),
        'submissions': len(recovered.production_submissions), 'crossOwnerReadsDenied': True,
        'sourceHistoryUnchanged': True, 'cloneRemoved': True, 'clusterMembershipsUnchanged': True,
        **storage_proof, **cancellation_proof}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
