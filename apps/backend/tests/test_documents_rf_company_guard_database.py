"""Real SQL guard ordering and exact current evidence under narrow executor roles.

Requires the owned disposable authority database. No provider or storage I/O.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url as rf_backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import DATABASE_URL, session
from test_rf1086_register_observation_database import inputs, capture, correction, cleanup_owned_fixture
from test_document_originals_database import original, retain, connect

pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = '20260924080249_documents_rf_consequential_company_guards.sql'
ASSERTION = 'shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)'


@pytest.fixture(scope="module")
def backend_url(rf_backend_url):
    # This generated, disposable login needs only SET authority for the caller
    # being exercised. Restore it before the owner fixture drops the login.
    from psycopg.conninfo import conninfo_to_dict
    from psycopg import sql
    username = conninfo_to_dict(rf_backend_url)["user"]
    assert username.startswith("rf_test_")
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL("grant corporate_governance_workflow_executor to {} with inherit false,set true").format(sql.Identifier(username)))
    try:
        yield rf_backend_url
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL("revoke corporate_governance_workflow_executor from {}").format(sql.Identifier(username)))


async def waiting(pid):
    for _ in range(100):
        with psycopg.connect(DATABASE_URL) as observer:
            if observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]:
                return
        await asyncio.sleep(.01)
    raise AssertionError('Exact writer never waited on the common company guard')


async def assert_observation(store, snapshot, *, override=None, ready=None, isolation='read committed'):
    # Use the actual Governance SQL role, without RF table privileges.
    async with await psycopg.AsyncConnection.connect(store._configuration.database_url) as db:
        await db.execute('set transaction isolation level '+isolation)
        await db.execute('set local role corporate_governance_workflow_executor')
        await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                         (str(store.actor_id.subject), store._verified.claims_json))
        args = [snapshot.observation_id.value, str(snapshot.command.company_id), int(snapshot.command.income_year),
                snapshot.version, snapshot.fact_sha256, str(store.actor_id.subject)]
        if override:
            index, value = override
            args[index] = value
        if ready:
            ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
        await db.execute('select shareholder_register_filing.assert_current_register_observation_v1(%s::uuid,%s::uuid,%s,%s,%s,%s)', args)


def test_governance_assertion_accepts_exact_current_observation_and_rejects_superseded(admitted, backend_url):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    first = capture(store, command, context)
    asyncio.run(assert_observation(store, first))
    second = capture(store, correction(command, first), context)
    with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'):
        asyncio.run(assert_observation(store, first))
    asyncio.run(assert_observation(store, second))


@pytest.mark.parametrize('index,value', [(0, str(uuid4())), (2, 2025), (3, 2), (4, 'f'*64), (5, str(uuid4()))], ids=['identity','year','revision','hash','actor'])
def test_governance_assertion_rejects_forged_identity_scope_revision_hash_and_actor(admitted, backend_url, index, value):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    observed = capture(store, command, context)
    with pytest.raises(psycopg.Error, match='rf1086_(register_predecessor_mismatch|forbidden)'):
        asyncio.run(assert_observation(store, observed, override=(index,value)))


def test_governance_assertion_refreshes_membership_after_guard_wait(admitted, backend_url):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    observed = capture(store, command, context)
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(assert_observation(store, observed, ready=ready))
            await waiting(await ready)
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
        with pytest.raises(psycopg.Error, match='rf1086_forbidden'):
            await task
    asyncio.run(run())


@pytest.mark.parametrize('isolation', ['repeatable read','serializable'])
def test_consequential_assertion_refuses_a_stale_snapshot_protocol(admitted, backend_url, isolation):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    observed = capture(store, command, context)
    with pytest.raises(psycopg.Error, match='rf1086_guard_requires_read_committed'):
        asyncio.run(assert_observation(store, observed, isolation=isolation))


def test_document_removal_waits_before_row_lock_and_rechecks_revocation(original):
    async def remove(ready):
        db, _ = await connect(original)
        async with db:
            ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
            await db.execute('select * from documents.mark_removed_v1(%s::uuid,%s,%s)',
                (original['document'].document_id.value, 'Reviewed removal', str(original['owner'])))
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (original['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(remove(ready))
            await waiting(await ready)
            with psycopg.connect(DATABASE_URL) as observer:
                observer.execute('set local role documents_store_owner')
                observer.execute("select set_config('talli.verified_actor_id',%s,true)", (str(original['owner']),))
                observer.execute("select set_config('talli.authorized_company_roles',%s,true)",
                    ('{"'+str(original['company'])+'":"owner"}',))
                assert observer.execute('select id from public.documents where id=%s for update nowait',
                    (original['document'].document_id.value,)).fetchone()
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (original['company'],))
        with pytest.raises(psycopg.Error, match='documents_forbidden'):
            await task
    asyncio.run(run())


def test_governance_can_assert_retained_original_without_reading_documents_tables(original):
    receipt = retain(original)
    async def run():
        db, adapter = await connect(original, role='corporate_governance_workflow_executor')
        async with db:
            await adapter.assert_retained_original(receipt)
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        for table in ('documents.retained_originals','shareholder_register_filing.register_observations'):
            assert not db.execute("select has_table_privilege('corporate_governance_workflow_executor',%s,'SELECT')", (table,)).fetchone()[0]
        assert db.execute("select has_function_privilege('corporate_governance_workflow_executor',%s,'EXECUTE')", (ASSERTION,)).fetchone()[0]
        for role in ('anon','authenticated','service_role','documents_executor'):
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role,ASSERTION)).fetchone()[0]


def authority_state(db):
    functions = db.execute("select oid,proowner,proacl::text,proconfig,prosrc from pg_proc where pronamespace in ('documents'::regnamespace,'shareholder_register_filing'::regnamespace) and (prosrc like '%rf193-company-guard-v1%' or proname in ('lock_company_write_v1','lock_preview_write_v1','assert_current_register_observation_v1')) order by oid").fetchall()
    memberships = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
    archive_acl = db.execute("select proacl::text from pg_proc where oid='public.company_archive_track_source_write_v1()'::regprocedure").fetchone()
    return functions,memberships,archive_acl


def test_exact_replay_and_fail_closed_rollback_preserve_authority_and_originals(original):
    receipt = retain(original)
    with psycopg.connect(DATABASE_URL) as db:
        before = authority_state(db)
        assert len([r for r in before[0] if 'rf193-company-guard-v1' in r[-1]]) == 18
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert authority_state(db) == before
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        with pytest.raises(psycopg.Error, match='documents_guard_suspended'):
            retain(original)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert authority_state(db) == before
    assert retain(original) == receipt


@pytest.mark.parametrize('relation', ['documents.evidence_references','documents.retained_originals',
    'shareholder_register_filing.filing_overrides','public.filing_overrides','public.filing_readiness_snapshots'])
def test_new_backstops_cover_every_row_mutation(relation):
    with psycopg.connect(DATABASE_URL) as db:
        row = db.execute("select tgtype,tgenabled from pg_trigger where tgrelid=%s::regclass and tgname='consequential_company_guard'", (relation,)).fetchone()
        assert row == (31,'O')


def wrapper_syntax_probe(migration):
    """Exercise the shipped normalizer against a real PL/pgSQL body ending LF."""
    import re
    source = (ROOT / 'supabase/migrations' / migration).read_text()
    variable, record = ('body', 'before_row') if migration == MIGRATION else ('original', 'routine')
    normalizer = re.search(
        rf"{variable}:=pg_catalog\.rtrim\({record}\.prosrc[^;]*;\s*"
        rf"if pg_catalog\.right\({variable},1\)<>'.*?end if;", source, re.S,
    )
    assert normalizer, 'The actual migration normalizer must be exercised'
    return f"""
    create temporary table if not exists rf193_wrapper_syntax_scope(id integer);
    create or replace function pg_temp.rf193_wrapper_syntax_probe() returns integer
    language plpgsql as $original$
    declare answer integer := 7;
    begin
      return answer;
    end;
    $original$;
    do $probe$
    declare {record} record; {variable} text; definition text; wrapped text;
    begin
      select prosrc,oid into {record} from pg_proc
      where oid='pg_temp.rf193_wrapper_syntax_probe()'::regprocedure;
      {normalizer.group(0)}
      definition:=pg_get_functiondef({record}.oid);
      wrapped:=E'begin\\n perform 1;\\n'||{variable}||E'\\nend;\\n';
      execute replace(definition,{record}.prosrc,wrapped);
      if pg_temp.rf193_wrapper_syntax_probe()<>7 then
        raise exception 'wrapper changed original return behavior';
      end if;
    end; $probe$;
    """


@pytest.mark.parametrize('migration', [MIGRATION, '20260924080355_governance_ledger_company_write_guards.sql'])
def test_shipped_wrapper_normalizer_compiles_newline_terminated_original(migration):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(wrapper_syntax_probe(migration))


def test_rf_admission_reads_governance_on_its_guarded_connection_and_expires(admitted, backend_url):
    from talli_backend.shared.kernel import CompanyId, IncomeYear, CorrelationId
    store = session(admitted, backend_url)
    query = rf.Rf1086SourceQuery(CompanyId(str(admitted['company'])), IncomeYear(2026), store.actor_id)
    async def run():
        async with store.source_admission(query) as scope:
            identity = await scope.company_identity()
            assert identity.company.org_number == admitted['org']
            assert await scope.current_source() is None
            view = await scope.governance_evidence(CorrelationId('same-connection-admission'))
            assert view.company_id == query.company_id and view.income_year == query.income_year
            assert view.dividends == view.supported_events == view.ledger_amendments == ()
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.company_identity()
    asyncio.run(run())


def test_rf_admission_holds_membership_writer_until_consumer_finishes(admitted, backend_url):
    from talli_backend.shared.kernel import CompanyId, IncomeYear
    store = session(admitted, backend_url)
    query = rf.Rf1086SourceQuery(CompanyId(str(admitted['company'])), IncomeYear(2026), store.actor_id)
    async def mutate(ready):
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
            ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
            await db.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
    async def run():
        async with store.source_admission(query) as scope:
            ready=asyncio.get_running_loop().create_future()
            task=asyncio.create_task(mutate(ready))
            await waiting(await ready)
            assert not task.done()
            assert await scope.current_source() is None
        await task
        with pytest.raises(rf.ShareholderRegisterFilingError):
            async with store.source_admission(query):
                pytest.fail('Revoked owner was admitted')
    asyncio.run(run())
