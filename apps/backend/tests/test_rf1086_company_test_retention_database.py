"""Full-schema RF inventory/writer/RLS; synthetic verified claims, no live Auth proof.

Owner-written synthetic rows remain until disposable database teardown. No new
SQL, trigger, grant, object, provider or production activation is introduced.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import _company_test_retention_read_sql
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId
from governance_register_evidence_amendment_fixture import admitted, connection
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access, insert, DATABASE_URL
from test_rf1086_year_source_database import session

pytestmark = pytest.mark.authority_database


@pytest.fixture
def retained(admitted, backend_url):
    return dict(seed=admitted, store=session(admitted, backend_url))


def query(item, store=None, company=None):
    store = store or item['store']
    return rf.Rf1086CompanyTestRetentionQuery(CompanyId(str(company or item['seed']['company'])), store.actor_id)


def read(item, store=None):
    store = store or item['store']
    return asyncio.run(store.read_company_test_retention(query(item, store)))


def write(item, *, actor=None, **changes):
    data = dict(environment='manual_evidence', status='accepted', test_reference='Owned '+str(uuid4()),
        feedback_summary='Exact ø historical feedback', receipt_reference=None,
        archive_reference='opaque-owned-reference', evidence_url='https://unreachable.invalid/original', payload_hash=None)
    data.update(changes)
    # backend_url already grants SET RFexecutor to this restricted login; the
    # primary fixture admin needs no undeclared executor edge or superuser power.
    writer = session(item['seed'], item['store']._configuration.database_url, actor)
    async def execute():
        async with writer._transaction() as db:
            role = await (await db.execute('select current_user as role')).fetchone()
            assert role['role'] == 'shareholder_register_filing_executor'
            row = await (await db.execute('select shareholder_register_filing.record_test_evidence_v1(%s,%s) as record',
                (item['seed']['company'], Jsonb(data)))).fetchone()
            return row['record']
    return asyncio.run(execute())


def oracle(item):
    with connection(item['seed'], 'shareholder_register_filing_store_owner') as db:
        with db.cursor(row_factory=dict_row) as cursor:
            cursor.execute("select * from shareholder_register_filing.authority_test_runs where company_id=%s and obligation='aksjonaerregisteroppgaven' order by id", (item['seed']['company'],))
            return tuple(item['store']._wire_record(rf.Rf1086TestEvidenceRecord, row) for row in cursor)


def catalog(db):
    return dict(
        table=db.execute("select oid,relowner,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where oid='shareholder_register_filing.authority_test_runs'::regclass").fetchone(),
        triggers=db.execute("select oid,tgenabled,pg_get_triggerdef(oid) from pg_trigger where tgrelid='shareholder_register_filing.authority_test_runs'::regclass order by oid").fetchall(),
        functions=db.execute("select p.oid,p.proowner,p.proacl::text,p.prosrc,p.proconfig,p.prosecdef from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' order by p.oid").fetchall(),
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall())


def test_actual_owner_writer_all_actors_environments_statuses_and_independent_oracle(retained):
    item = retained; seed = item['seed']
    with psycopg.connect(DATABASE_URL) as db:
        insert(db, 'public.company_memberships', dict(company_id=seed['company'], user_id=seed['outsider'], role='owner', accepted_at=seed['now']))
        before = catalog(db)
    identifiers = set()
    for number, status in enumerate(['accepted','rejected','blocked','pending']):
        row = write(item, actor=seed['outsider'] if number%2 else seed['owner'],
            environment='test' if number%2 else 'manual_evidence', status=status, payload_hash='a'*64 if number%2 else None)
        identifiers.add(row['id'])
    snapshot = read(item)
    assert snapshot.records == oracle(item) and snapshot.record_count == 4
    assert {row.id for row in snapshot.records} == identifiers
    assert {row.recorded_by for row in snapshot.records} == {str(seed['owner']),str(seed['outsider'])}
    assert rf.parse_rf1086_company_test_retention(rf.serialize_rf1086_company_test_retention(snapshot), company_id=query(item).company_id) == snapshot
    with psycopg.connect(DATABASE_URL) as db: assert catalog(db) == before


@pytest.mark.parametrize('original', [None, 'a'*64, 'A'*64, 'sha256:provider/ø', 'x', '', ' original hash '])
def test_actual_restricted_writer_preserves_opaque_original_payload_hash(retained, original):
    saved = write(retained, payload_hash=original)
    snapshot = read(retained)
    assert snapshot.record_count == 1 and snapshot.records == oracle(retained)
    assert snapshot.records[0].id == saved['id'] and snapshot.records[0].payload_hash == original
    parsed = rf.parse_rf1086_company_test_retention(rf.serialize_rf1086_company_test_retention(snapshot), company_id=query(retained).company_id)
    assert parsed.records[0].payload_hash == original
    rf.assert_company_test_retention_source_capture_matches(parsed, snapshot)


@pytest.mark.parametrize('role', ['owner','reviewer','read_only'])
def test_actual_current_accepted_members_read_even_with_expired_mfa(retained, role):
    item = retained; seed = item['seed']; write(item)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('update public.company_memberships set role=%s where company_id=%s and user_id=%s', (role, seed['company'], seed['owner']))
    claims = json.loads(item['store']._verified.claims_json); claims['amr'][0]['timestamp'] = 1
    item['store']._verified = replace(item['store']._verified, claims_json=json.dumps(claims))
    assert read(item).records == oracle(item)


@pytest.mark.parametrize('relationship', ['unaccepted','revoked','foreign'])
def test_actual_unaccepted_revoked_or_foreign_actor_cannot_receive_fake_complete_zero(retained, relationship):
    item = retained; seed = item['seed']; write(item)
    if relationship != 'foreign':
        with psycopg.connect(DATABASE_URL) as db:
            insert(db, 'public.company_memberships', dict(company_id=seed['company'], user_id=seed['outsider'],
                role='read_only', accepted_at=None if relationship=='unaccepted' else seed['now']))
            if relationship == 'revoked':
                db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (seed['company'],seed['outsider']))
    outsider = session(seed, item['store']._configuration.database_url, seed['outsider'])
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied: read(item, outsider)
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.NOT_FOUND


def test_actual_authorized_zero_is_complete_and_scoped(retained):
    snapshot = read(retained)
    assert snapshot.coverage == 'complete' and snapshot.record_count == 0 and snapshot.records == ()
    assert snapshot.observed_at is not None and oracle(retained) == ()
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied:
        asyncio.run(retained['store'].read_company_test_retention(query(retained, company=uuid4())))
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.NOT_FOUND


def test_actual_two_megabyte_owner_written_feedback_never_crosses_inventory_cursor(retained):
    item = retained
    with psycopg.connect(DATABASE_URL) as db: before = catalog(db)
    saved = write(item, feedback_summary='x'*(2*1024*1024))
    async def inspect():
        async with item['store']._transaction(snapshot=True, read_only=True) as db:
            async with db.cursor(name='retention_oversize_fixture') as cursor:
                await cursor.execute(_company_test_retention_read_sql(rf.rf1086_company_test_retention_bounds()), (str(item['seed']['company']),))
                rows = [row async for row in cursor]
                assert len(rows) == 1 and rows[0]['_retention_oversize'] is True
                assert all(value is None for key,value in rows[0].items() if key!='_retention_oversize')
    asyncio.run(inspect())
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied: read(item)
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    original = oracle(item)
    assert original[0].id == saved['id'] and original[0].feedback_summary == 'x'*(2*1024*1024)
    with psycopg.connect(DATABASE_URL) as db: assert catalog(db) == before


@pytest.mark.parametrize('text', ['x'*65536, 'ø'*32768])
def test_actual_text_byte_boundary_and_plus_one_stays_unavailable_without_partial_complete(retained, text):
    item = retained; write(item, feedback_summary=text)
    before = read(item); assert before.record_count == 1
    write(item, feedback_summary=text+'x')
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied: read(item)
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert len(oracle(item)) == 2


def test_actual_multiple_cursor_batches_and_repeatable_read_concurrent_insert(retained):
    item = retained
    for number in range(33): write(item, test_reference='Owned batch '+str(number))
    before = oracle(item)
    original_transaction = item['store']._transaction
    inserted = None
    @asynccontextmanager
    async def transaction(**options):
        async with original_transaction(**options) as db:
            await db.execute('select shareholder_register_filing.assert_member_v1(%s)', (str(item['seed']['company']),))
            # Materialize RR before a separate owner commits another test row.
            await db.execute('select count(*) from shareholder_register_filing.authority_test_runs where company_id=%s', (str(item['seed']['company']),))
            nonlocal inserted
            inserted = await asyncio.to_thread(write, item, test_reference='Owned concurrent row')
            yield db
    item['store']._transaction = transaction
    try: snapshot = read(item)
    finally: item['store']._transaction = original_transaction
    assert snapshot.records == before and snapshot.record_count == 33
    after = read(item)
    assert after.record_count == 34 and after.records == oracle(item)
    assert inserted['id'] in {row.id for row in after.records} - {row.id for row in snapshot.records}
    rf.assert_company_test_retention_target_inventory_matches(snapshot, replace(snapshot, observed_at=after.observed_at))


@pytest.mark.parametrize('extra', [0,1])
def test_actual_raw_transfer_sum_boundary_preserves_row_or_returns_null_sentinel(retained, extra):
    item = retained; bounds = rf.rf1086_company_test_retention_bounds()
    fixed = len('aksjonaerregisteroppgaven') + len('manual_evidence') + len('accepted')
    remaining = bounds.max_raw_transfer_bytes - 256 - fixed - 3*65536
    write(item, test_reference='x'*65536, feedback_summary='x'*65536,
        receipt_reference='x'*65536, archive_reference='x'*(remaining+extra), evidence_url=None)
    async def inspect():
        async with item['store']._transaction(snapshot=True, read_only=True) as db:
            async with db.cursor(name='retention_sum_fixture') as cursor:
                await cursor.execute(_company_test_retention_read_sql(bounds), (str(item['seed']['company']),))
                result = [row async for row in cursor]
                assert len(result) == 1 and result[0]['_retention_oversize'] is bool(extra)
                if extra: assert all(value is None for key,value in result[0].items() if key!='_retention_oversize')
                else: assert result[0]['feedback_summary'] == 'x'*65536
    asyncio.run(inspect())
    # Raw-transfer allowance and canonical JSON record cap are separate gates.
    # Even the raw boundary may expand beyond256KiB when keys/escaping are added.
    with pytest.raises(rf.ShareholderRegisterFilingError): read(item)
    assert len(oracle(item)) == 1


def test_actual_canonical_control_expansion_cannot_emit_complete(retained):
    # PostgreSQL TEXT cannot contain NUL; SOH is legal and JSON expands it6x.
    write(retained, feedback_summary='\x01'*50000)
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied: read(retained)
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert oracle(retained)[0].feedback_summary == '\x01'*50000


def test_actual_retention_hold_preserves_company_history_without_filing_freshness(retained):
    from test_rf1086_retained_archive_generations import begin, identify
    item = retained; write(item); before = read(item)
    # Existing synthetic complete-export prerequisite fixture; it is not proof
    # that the new standalone artifact is a complete legal company export.
    begin(item['seed'], complete=True)
    with psycopg.connect(DATABASE_URL) as db:
        identify(db, item['seed'])
        status = db.execute('select status from public.company_access_request_cancellation(%s,%s,2026,%s)',
            (uuid4(),item['seed']['company'],'Owned synthetic retention inventory fixture')).fetchone()[0]
        assert status == 'retention_hold'
    after = read(item)
    rf.assert_company_test_retention_target_inventory_matches(before, after)
    assert after.records == oracle(item)


def test_actual_cursor_cancellation_closes_connection_without_partial_snapshot(retained, monkeypatch):
    item = retained; write(item); original = item['store']._transaction; connections = []; ready = asyncio.Event()
    # Delay the actual servercursor FETCH, then cancel while PostgreSQL is asleep.
    monkeypatch.setattr('talli_backend.adapters.postgres_shareholder_register_filing._company_test_retention_read_sql',
        lambda _: "select false as _retention_oversize,t.*,pg_sleep(30) from shareholder_register_filing.authority_test_runs t where t.company_id=%s::uuid")
    @asynccontextmanager
    async def transaction(**options):
        async with original(**options) as db:
            connections.append(db);ready.set();yield db
    item['store']._transaction = transaction
    async def cancel():
        task = asyncio.create_task(item['store'].read_company_test_retention(query(item)))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            pid = connections[0].info.backend_pid
            for _ in range(100):
                with psycopg.connect(DATABASE_URL) as observer:
                    sleeping = observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='PgSleep')", (pid,)).fetchone()[0]
                if sleeping: break
                await asyncio.sleep(.01)
            else: raise AssertionError('owned inventory cursor did not enter delayed FETCH')
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        finally:
            if not task.done():
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
    try: asyncio.run(cancel())
    finally: item['store']._transaction = original
    assert len(connections) == 1 and connections[0].closed
    monkeypatch.undo()
    assert read(item).records == oracle(item)
