"""Closed capture adapter with real owner records and a restricted fixture login.

Claims are explicit fixtures. Only this login gets the staged RPC permissions;
the production transaction's runtime role remains closed. Byte preflight is
covered separately; these originals were retained through real Documents SQL.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
import json
import secrets
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest

from talli_backend.application.shareholder_register_source_workflow import _document_projection
from talli_backend.modules.documents import public as docs
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId, IdempotencyKey
from governance_register_evidence_amendment_fixture import verified
from rf1086_year_source_v2_database_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, closed_source_role,
    original_fixture, amend, inputs, rows, connection, DATABASE_URL, ROOT, APPEND, GOV_READER,
)
from test_rf1086_year_source_database import session as rf_session
from test_authority_connections_database_runtime import insert


pytestmark = pytest.mark.authority_database
GUARD = 'shareholder_register_filing.lock_year_source_capture_v2(uuid,integer)'
MIGRATION = '20261010111100_rf1086_closed_year_source_capture.sql'
CORRELATION = CorrelationId('closed-capture-owned-database')


@pytest.fixture
def capture_login(closed_source_role):
    """Inherit existing read contracts and grant closed ports only to this login."""
    name = 'rf_capture_v2_' + uuid4().hex
    password = secrets.token_urlsafe(32)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} login inherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls password {}').format(
            sql.Identifier(name), sql.Literal(password)))
        for role in (closed_source_role, 'shareholder_register_filing_executor'):
            db.execute(sql.SQL('grant {} to {} with inherit true,set false').format(sql.Identifier(role), sql.Identifier(name)))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant execute on function ' + GUARD + ' to {}').format(sql.Identifier(name)))
        db.execute('set local role corporate_governance_store_owner')
        db.execute(sql.SQL('grant execute on function ' + GOV_READER + ' to {}').format(sql.Identifier(name)))
    try:
        yield make_conninfo(DATABASE_URL, user=name, password=password)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke all on function ' + GUARD + ' from {}').format(sql.Identifier(name)))
            db.execute('set local role corporate_governance_store_owner')
            db.execute(sql.SQL('revoke all on function ' + GOV_READER + ' from {}').format(sql.Identifier(name)))
            db.execute('reset role')
            for role in (closed_source_role, 'shareholder_register_filing_executor'):
                db.execute(sql.SQL('revoke {} from {}').format(sql.Identifier(role), sql.Identifier(name)))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(name)))


def restricted_capture_session(item, login, *, actor=None, fresh=True):
    """Keep adapter/producers intact; replace only runtime-role selection fixture."""
    store = rf_session(item['seed'], login, actor=actor)
    store._verified = verified(item['seed'], actor, fresh=fresh)
    traces = []

    @asynccontextmanager
    async def transaction(*, snapshot=False, read_only=False):
        async with await psycopg.AsyncConnection.connect(login, row_factory=dict_row,
                options='-c statement_timeout=8000 -c lock_timeout=5000') as db, db.transaction():
            await db.execute('set transaction isolation level ' + ('repeatable read' if snapshot else 'read committed'))
            if read_only: await db.execute('set transaction read only')
            await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),"
                "set_config('request.jwt.claims',%s,true),set_config('talli.authorized_company_roles',%s,true)",
                (str(store.actor_id.subject), store._verified.claims_json, store._verified.claims_json,
                 json.dumps({str(item['seed']['company']): 'owner'})))
            traces.append(await (await db.execute('select current_user,pg_backend_pid() as pid')).fetchone())
            yield db
    store._transaction = transaction
    return store, traces


def complete_inputs(seed, role, withdrawal_role, kind, count):
    item = original_fixture(seed, role, withdrawal_role, kind=kind,
        phase='registered' if kind == 'cash_issue' else 'first_recognized_after_registration')
    originals = {row.document.document_id.value: row for row in (*item['gov_documents'], *item['original_rf_docs'])}
    for _ in range(count):
        item = amend(item)
        for row in (item['memo'], *item['replacement_docs']): originals[row.document.document_id.value] = row
    command, _ = inputs(item)
    values = tuple(originals[key] for key in sorted(originals))
    for row in values:
        assert sha256(row.content).hexdigest() == row.document.content_sha256
        assert len(row.content) == row.document.byte_length
    documents = tuple(_document_projection(docs.VerifiedDocumentEvidence(
        row.document, row.document.content_sha256, row.document.byte_length, row.document.status)) for row in values)
    return item, replace(command, documents=documents), tuple(row.receipt for row in values)


def capture(store, command, originals, key=None):
    return asyncio.run(store.record_year_source_v2(command, originals=originals,
        idempotency_key=key or IdempotencyKey(str(uuid4())), correlation_id=CORRELATION))


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('count', [0, 1, 2])
def test_atomic_capture_uses_real_complete_owner_evidence_and_exact_retained_original_union(
        admitted, closed_source_role, withdrawal_fixture_role, capture_login, kind, count):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, kind, count)
    store, traces = restricted_capture_session(item, capture_login)
    key = IdempotencyKey(str(uuid4()))
    source = capture(store, command, originals, key)
    rf.assert_rf1086_year_source_integrity_v2(source)
    assert source.command == command and source.governance_projection.chains[0].amendment_count == count
    assert len(traces) == 1 and traces[0]['current_user'].startswith('rf_capture_v2_')
    assert rows(item)[0][6] == rf.serialize_rf1086_year_source_v2(source)
    # A committed original returns before fresh original union and year admission.
    with psycopg.connect(DATABASE_URL) as db:
        insert(db, 'public.company_eligibility_assessments', admitted['assessment'] | {
            'id': uuid4(), 'operation_id': uuid4(), 'previous_assessment_id': admitted['current'],
            'trigger': 'before_filing', 'assessed_at': db.execute('select clock_timestamp()').fetchone()[0],
            'decision': 'blocked', 'consequential_operations_allowed': False})
    assert capture(store, command, (), key) == source
    assert len(rows(item)) == 1
    with pytest.raises(rf.Rf1086YearSourceError, match='idempotency_conflict'):
        capture(store, replace(command, paid_in_reviewed=False), (), key)


def test_production_runtime_role_cannot_activate_closed_capture(admitted, closed_source_role, withdrawal_fixture_role):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, 'loss_covering_reduction', 0)
    store = rf_session(admitted, DATABASE_URL)
    store._verified = verified(admitted)
    with pytest.raises(rf.ShareholderRegisterFilingError): capture(store, command, originals)
    assert rows(item) == []
    with connection(admitted, 'shareholder_register_filing_store_owner') as db:
        for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, GUARD)).fetchone()[0]
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, APPEND)).fetchone()[0]


@pytest.mark.parametrize('same_key', [True, False])
def test_two_real_atomic_captures_serialize_to_one_original_without_forking(
        admitted, closed_source_role, withdrawal_fixture_role, capture_login, same_key):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, 'loss_covering_reduction', 1)
    left, _ = restricted_capture_session(item, capture_login)
    right, _ = restricted_capture_session(item, capture_login)
    key = IdempotencyKey(str(uuid4()))
    async def race():
        return await asyncio.gather(*(store.record_year_source_v2(command, originals=originals,
            idempotency_key=operation, correlation_id=CORRELATION)
            for store, operation in ((left,key),(right,key if same_key else IdempotencyKey(str(uuid4()))))),
            return_exceptions=True)
    results = asyncio.run(race())
    passed = [value for value in results if type(value) is rf.Rf1086YearSourceSnapshotV2]
    assert len(passed) == (2 if same_key else 1)
    if same_key: assert passed[0] == passed[1]
    else:
        failures = [value for value in results if isinstance(value,rf.Rf1086YearSourceError)]
        assert len(failures) == 1 and str(failures[0]) == 'rf1086_source_predecessor_mismatch'
    assert len(rows(item)) == 1 and rows(item)[0][6] == rf.serialize_rf1086_year_source_v2(passed[0])


def test_real_current_owner_revocation_blocks_even_a_committed_capture_replay(
        admitted, closed_source_role, withdrawal_fixture_role, capture_login):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, 'loss_covering_reduction', 0)
    store, _ = restricted_capture_session(item, capture_login)
    key = IdempotencyKey(str(uuid4()))
    source = capture(store, command, originals, key)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
            (admitted['company'],admitted['owner']))
    with pytest.raises(psycopg.Error, match='rf1086_forbidden'): capture(store,command,(),key)
    # Privileged fixture observer may inspect retained data; revoked actor cannot.
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        with db.transaction(force_rollback=True):
            db.execute('alter table shareholder_register_filing.year_source_versions no force row level security')
            assert db.execute('select snapshot_text from shareholder_register_filing.year_source_versions where id=%s',
                (source.source_id.value,)).fetchone()[0] == rf.serialize_rf1086_year_source_v2(source)


@pytest.mark.parametrize('attack', ['wrong_actor', 'stale_mfa', 'missing_original', 'changed_metadata', 'bad_predecessor', 'after_retention'])
def test_real_capture_authority_original_or_late_failure_rolls_back_every_source_write(
        admitted, closed_source_role, withdrawal_fixture_role, capture_login, attack):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, 'loss_covering_reduction', 1)
    if attack == 'bad_predecessor': command = replace(command, supersedes_source_id=rf.Rf1086YearSourceId(str(uuid4())),
        supersedes_source_sha256='f'*64, correction_reason='Absent retained predecessor')
    if attack == 'missing_original': originals = originals[:-1]
    if attack == 'changed_metadata': originals = (replace(originals[0], metadata_sha256='f'*64), *originals[1:])
    store, _ = restricted_capture_session(item, capture_login,
        actor=admitted['outsider'] if attack == 'wrong_actor' else None, fresh=attack != 'stale_mfa')
    if attack == 'wrong_actor': command = replace(command, actor_id=store.actor_id)
    retention_completed = []
    if attack == 'after_retention':
        retain = store._retain_source_documents
        async def abort_after_retention(*args):
            await retain(*args)
            retention_completed.append(True)
            raise RuntimeError('owned failure after real retention')
        store._retain_source_documents = abort_after_retention
    expected, message = {
        'wrong_actor': (psycopg.errors.RaiseException, 'rf1086_not_found'),
        'stale_mfa': (psycopg.errors.RaiseException, 'company_access_forbidden'),
        'missing_original': (rf.Rf1086YearSourceError, 'rf1086_source_documents_unverified'),
        'changed_metadata': (rf.Rf1086YearSourceError, 'rf1086_source_documents_unverified'),
        'bad_predecessor': (rf.Rf1086YearSourceError, 'rf1086_source_predecessor_required'),
        'after_retention': (RuntimeError, 'owned failure after real retention'),
    }[attack]
    with pytest.raises(expected, match=message): capture(store, command, originals)
    assert rows(item) == []
    if attack == 'after_retention': assert retention_completed == [True]
    with connection(admitted, 'documents_store_owner') as db:
        assert db.execute("select count(*) from documents.evidence_references where company_id=%s and source_record_type='rf1086_year_source'",
            (admitted['company'],)).fetchone()[0] == 0


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_real_closed_capture_guard_rejects_stale_snapshot_before_any_owner_write(admitted, capture_login, isolation):
    with psycopg.connect(capture_login) as db:
        db.execute('set transaction isolation level ' + isolation)
        with pytest.raises(psycopg.Error, match='rf1086_source_capture_guard_required'):
            db.execute('select ' + GUARD.split('(')[0] + '(%s,%s)', (admitted['company'], 2026))


def test_populated_capture_guard_rollback_reapply_preserves_definition_oid_and_source_bytes(
        admitted, closed_source_role, withdrawal_fixture_role, capture_login):
    item, command, originals = complete_inputs(admitted, closed_source_role, withdrawal_fixture_role, 'loss_covering_reduction', 0)
    store, _ = restricted_capture_session(item, capture_login)
    source = capture(store, command, originals)
    before = rows(item)
    catalog = "select oid,proowner,prosrc,prosecdef,provolatile,proconfig from pg_proc where oid=%s::regprocedure"
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        original = db.execute(catalog, (GUARD,)).fetchone()
        for directory in ('rollback', 'migrations', 'rollback', 'migrations'):
            db.execute((ROOT/'supabase'/directory/MIGRATION).read_text())
            assert db.execute(catalog, (GUARD,)).fetchone() == original
            for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
                assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, GUARD)).fetchone()[0]
    assert rows(item) == before and before[0][6] == rf.serialize_rf1086_year_source_v2(source)
