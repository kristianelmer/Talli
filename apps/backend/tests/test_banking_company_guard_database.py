"""Banking company-first admission, actual waits and fail-closed rollback."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL, ROOT, insert
from test_banking_year_reconciliation_database import executor_authority, bank_owner
from test_rf1086_source_company_guard_database import waiting

pytestmark = pytest.mark.authority_database
MIGRATION = '20260929092425_banking_company_write_guards.sql'
WRITERS = (
    'accept_source_file_v1', 'apply_sync_page_v1', 'begin_connection_revocation_v1',
    'begin_connection_v1', 'claim_corporate_governance_transaction_v1',
    'claim_owner_dividend_transaction_v1', 'claim_tax_settlement_transaction_v1',
    'claim_transaction_for_external_action_v1', 'complete_connection_revocation_v1',
    'complete_connection_v1', 'complete_suggestion_acceptance_v1', 'complete_sync_v1',
    'fail_connection_v1', 'fail_sync_v1', 'import_statement_v1',
    'prepare_owner_dividend_transaction_v1', 'prepare_shareholder_loan_transaction_v1',
    'prepare_suggestion_acceptance_v1', 'prepare_sync_v1',
    'prepare_tax_settlement_transaction_v1', 'preview_source_file_v1', 'record_consent_redirect_v1',
)


def statement(name, fixture):
    with psycopg.connect(DATABASE_URL) as db:
        names, types = db.execute("select proargnames,oidvectortypes(proargtypes) from pg_proc where pronamespace='banking'::regnamespace and proname=%s", (name,)).fetchone()
    values = []
    for arg, kind in zip(names, types.split(', '), strict=True):
        if arg == 'p_request': value = Jsonb({'companyId': str(fixture['company'])})
        elif arg == 'p_company_id': value = fixture['company']
        elif arg in ('p_verified_subject','p_subject'): value = str(fixture['owner'])
        elif kind == 'uuid': value = uuid4()
        elif kind == 'jsonb': value = Jsonb({})
        else: value = 'guard-fixture'
        values.append(value)
    return sql.SQL('select banking.{}({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Placeholder() for _ in values)), values


async def blocked_writer(fixture, ready, query, args):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
        await db.execute('set local role banking_store_owner')
        actor = str(fixture['owner'])
        await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                         (actor,json.dumps({'sub':actor,'aal':'aal2'})))
        ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
        await db.execute(query,args)


@pytest.mark.parametrize('name', WRITERS)
def test_every_writer_waits_before_local_locks_and_rereads_revocation(admitted, name):
    query,args = statement(name, admitted)
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(blocked_writer(admitted,ready,query,args))
            pid = await ready
            try:
                await waiting(pid)
                assert not blocker.execute("select exists(select 1 from pg_locks where pid=%s and granted and (locktype='advisory' or locktype='tuple' or mode in ('RowShareLock','RowExclusiveLock')))", (pid,)).fetchone()[0]
                blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
            except BaseException:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                raise
        with pytest.raises(psycopg.errors.RaiseException,match='banking_forbidden'):
            await task
    asyncio.run(run())


def request(fixture):
    return {'companyId':str(fixture['company']),'incomeYear':2026,'idempotencyKey':str(uuid4()),
            'transactions':[{'transactionDate':'2026-01-01','text':'Synthetic bank fee','amount':'-1.00','sourceHash':uuid4().hex*2}]}


def import_statement(db, fixture, payload):
    bank_owner(db,fixture)
    db.execute('set local role banking_executor')
    return db.execute('select banking.import_statement_v1(%s,%s)',(Jsonb(payload),str(fixture['owner']))).fetchone()[0]


def test_import_replay_and_other_company_remain_available(admitted):
    other = globals()['admitted'].__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as blocker:
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("set local statement_timeout='2s'")
            payload=request(other)
            first=import_statement(db,other,payload)
            replay=import_statement(db,other,payload)
            assert first['importedCount']==1 and replay['replayed']


@pytest.mark.parametrize('isolation', ['repeatable read','serializable'])
def test_old_snapshot_writer_is_rejected(admitted,isolation):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
        with pytest.raises(psycopg.errors.RaiseException,match='banking_company_guard_requires_read_committed'):
            import_statement(db,admitted,request(admitted))


@pytest.fixture
def sync_fixture(admitted):
    connection,account,attempt=uuid4(),uuid4(),uuid4()
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db,admitted)
        insert(db,'banking.connections',{'id':connection,'company_id':admitted['company'],'connector_key':'fixture',
            'bank_key_sha256':'a'*64,'idempotency_key':str(uuid4()),'request_fingerprint':'b'*64,
            'status':'ACTIVE','connected_by':admitted['owner']})
        insert(db,'banking.accounts',{'id':account,'connection_id':connection,'company_id':admitted['company'],
            'masked_account':'****1234','currency':'NOK','account_kind':'business','display_name':'Fixture','status':'ACTIVE'})
        insert(db,'banking.sync_attempts',{'id':attempt,'company_id':admitted['company'],'connection_id':connection,
            'account_id':account,'actor_id':admitted['owner'],'income_year':2026,'mode':'ON_DEMAND',
            'interval_start':'2026-01-01','interval_end':'2026-01-31','idempotency_key':str(uuid4()),
            'request_fingerprint':'c'*64,'status':'STARTED'})
    return admitted,attempt


@pytest.mark.parametrize('name', ['complete_sync_v1','fail_sync_v1'])
def test_sync_cannot_guard_one_owned_company_and_mutate_another(sync_fixture,name):
    fixture,attempt=sync_fixture
    other=globals()['admitted'].__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as db:
        insert(db,'public.company_memberships',{'company_id':other['company'],'user_id':fixture['owner'],
                                               'role':'owner','accepted_at':other['now']})
    # The second owner also accepts this company's agreement, otherwise the
    # early owner guard would mask the attempt-company mismatch being tested.
    from test_annual_purchase_basis_runtime import legal_fields
    with psycopg.connect(DATABASE_URL) as db:
        insert(db,'public.customer_agreement_acceptances',other['acceptance_fields']|legal_fields()|{
            'id':uuid4(),'accepted_by':fixture['owner']})
    with psycopg.connect(DATABASE_URL) as blocker:
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(fixture['company'],))
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("set local statement_timeout='2s'")
            bank_owner(db,fixture)
            args=[Jsonb({'companyId':str(other['company'])}),attempt]
            if name=='fail_sync_v1':args.append('BANKING_FIXTURE_FAILURE')
            args.append(str(fixture['owner']))
            with pytest.raises(psycopg.errors.RaiseException,match='banking_sync_not_available'):
                db.execute(sql.SQL('select banking.{}({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Placeholder() for _ in args)),args)
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db,fixture)
        assert db.execute('select status from banking.sync_attempts where id=%s',(attempt,)).fetchone()==('STARTED',)


@pytest.mark.parametrize('name,status', [('complete_sync_v1','SUCCEEDED'),('fail_sync_v1','FAILED')])
def test_correct_sync_scope_still_completes(sync_fixture,name,status):
    fixture,attempt=sync_fixture
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db,fixture)
        args=[Jsonb({'companyId':str(fixture['company'])}),attempt]
        if name=='fail_sync_v1':args.append('BANKING_FIXTURE_FAILURE')
        args.append(str(fixture['owner']))
        db.execute(sql.SQL('select banking.{}({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Placeholder() for _ in args)),args)
        assert db.execute('select status from banking.sync_attempts where id=%s',(attempt,)).fetchone()==(status,)


def test_rollback_suspends_writers_and_replay_preserves_rows_and_authority(admitted):
    with psycopg.connect(DATABASE_URL) as db:
        import_statement(db,admitted,request(admitted))
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        def state():
            with db.transaction():
                bank_owner(db,admitted)
                facts=db.execute('select to_jsonb(t) from banking.transactions t where company_id=%s order by id',(admitted['company'],)).fetchall()
                assert len(facts)==1
            return (facts,db.execute("select oid,proowner,proacl::text,prosrc from pg_proc where pronamespace='banking'::regnamespace and proname=any(%s) order by oid",(list(WRITERS),)).fetchall(),
                    db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
                    db.execute("select nspowner,nspacl::text from pg_namespace where nspname='banking'").fetchall())
        before=state()
        for _ in range(2):
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert state()==before
            with pytest.raises(psycopg.errors.RaiseException,match='banking_company_guard_rollback'):
                with db.transaction(): import_statement(db,admitted,request(admitted))
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert state()==before
            with db.transaction():
                bank_owner(db,admitted)
                db.execute('select banking.acquire_company_write_guard_v1(%s,%s)',(admitted['company'],str(admitted['owner'])))


def test_catalogue_covers_all_banking_mutators_and_keeps_runtime_authority_narrow():
    with psycopg.connect(DATABASE_URL) as db:
        routines=db.execute("select proname,prosrc from pg_proc where pronamespace='banking'::regnamespace and prosecdef and provolatile='v'").fetchall()
        pure_or_helpers={'list_records_v1','list_connections_v1','suggestion_acceptance_replay_v1',
                         'acquire_company_write_guard_v1','lock_company_write_v1',
                         'read_year_reconciliation_evidence_v1'}
        assert {name for name,_ in routines if name not in pure_or_helpers}==set(WRITERS)
        assert {name for name,body in routines if 'rf193-banking-company-write-guard-v1' in body}==set(WRITERS)
        tables=db.execute("""select c.relname from pg_trigger t join pg_class c on c.oid=t.tgrelid
          where t.tgfoid='banking.lock_company_write_v1()'::regprocedure
           and t.tgname='aa_company_write_guard' and t.tgtype=31 and t.tgenabled='O' order by 1""").fetchall()
        assert {r[0] for r in tables}=={'transactions','suggestion_acceptances','connections','accounts',
                                      'coverage_intervals','sync_attempts','source_files','transaction_sources'}
        for role in ('anon','authenticated','service_role','banking_executor','banking_provider_executor',
                     'banking_workflow_executor','shareholder_register_filing_executor'):
            assert db.execute("select has_function_privilege(%s,'banking.acquire_company_write_guard_v1(uuid,text)','EXECUTE'),has_table_privilege(%s,'banking.transactions','UPDATE')",(role,role)).fetchone()==(False,False)


def test_direct_owner_write_backstop_waits_even_without_the_rpc(admitted):
    payload=request(admitted)
    with psycopg.connect(DATABASE_URL) as db:
        import_statement(db,admitted,payload)
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
            ready=asyncio.get_running_loop().create_future()
            task=asyncio.create_task(blocked_writer(admitted,ready,
                'update banking.transactions set warning_accepted=true where company_id=%s', (admitted['company'],)))
            pid=await ready
            try:
                await waiting(pid)
            except BaseException:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                raise
        await task
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db,admitted)
        assert db.execute('select warning_accepted from banking.transactions where company_id=%s',(admitted['company'],)).fetchone()==(True,)
