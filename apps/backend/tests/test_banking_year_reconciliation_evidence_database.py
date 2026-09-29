"""Exact Banking year evidence, held-guard currentness and RF read-only access."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL
from test_banking_year_reconciliation_database import executor_authority, bank_owner
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from talli_backend.adapters.supabase_banking import SupabaseBankingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.banking.public import BankingError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, UserId

pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = '20260929125448_banking_year_reconciliation_evidence.sql'
SIGNATURE = 'banking.read_year_reconciliation_evidence_v1(uuid,integer,text)'


def read(fixture, *, year=2026, company=None, actor=None):
    actor = str(actor or fixture['owner'])
    port = SupabaseBankingSession(DATABASE_URL, _VerifiedActor(
        ActorId(ActorKind.USER, UserId(actor)), json.dumps({'sub': actor, 'aal': 'aal2'})))
    return asyncio.run(port.read_year_reconciliation_evidence(
        actor_id=port.actor_id, company_id=CompanyId(str(company or fixture['company'])),
        income_year=IncomeYear(year), correlation_id=CorrelationId('year-evidence')))


def seed(fixture, count=1):
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, fixture)
        db.execute("""insert into banking.transactions(id,company_id,income_year,transaction_date,text,
         amount,source_hash,created_by,matched_action_reference,warning_accepted,transaction_state)
         select gen_random_uuid(),%s,2026,date '2026-01-01','Synthetic evidence',-1,
          lpad(to_hex(i),64,'0'),%s,'matched',false,'BOOKED' from generate_series(1,%s) i""",
          (fixture['company'],fixture['owner'],count))


def test_digest_binds_complete_facts_and_scope_without_observation_time(admitted):
    seed(admitted, 504)
    first, second = read(admitted), read(admitted)
    assert first.reconciliation.transaction_count == 504
    assert first.reconciliation.observed_at != second.reconciliation.observed_at
    assert first.source_sha256 == second.source_sha256
    empty = read(admitted, year=2025)
    assert empty.reconciliation.transaction_count == 0
    assert empty.source_sha256 != read(admitted,year=2024).source_sha256
    assert empty.source_sha256 != first.source_sha256
    assert empty.source_sha256 == read(admitted,year=2025).source_sha256


@pytest.mark.parametrize('change', [
    "text='Changed evidence'", "amount=-2", "balance=1", "matched_action_reference='another-match'",
    "source_hash=repeat('c',64)", "transaction_date=date '2026-01-02'", "value_date=date '2026-01-02'",
    "transaction_state='REVERSED'", "adapter_reference_sha256=repeat('d',64)",
    "created_at=created_at+interval '0.000001 seconds'",
])
def test_same_counts_cannot_hide_changed_transaction_evidence(admitted, change):
    seed(admitted)
    first = read(admitted)
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, admitted)
        db.execute('update banking.transactions set '+change+' where company_id=%s', (admitted['company'],))
    second = read(admitted)
    assert (first.reconciliation.transaction_count,first.reconciliation.unmatched_count,first.reconciliation.accepted_warning_count) == (
        second.reconciliation.transaction_count,second.reconciliation.unmatched_count,second.reconciliation.accepted_warning_count)
    assert first.source_sha256 != second.source_sha256


def test_accepted_warning_and_deletion_change_digest_and_counts(admitted):
    seed(admitted)
    first = read(admitted)
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, admitted)
        db.execute('update banking.transactions set warning_accepted=true where company_id=%s',(admitted['company'],))
    accepted = read(admitted)
    assert accepted.reconciliation.accepted_warning_count == 1
    assert accepted.source_sha256 != first.source_sha256
    with psycopg.connect(DATABASE_URL) as db:
        # Fixture-only deletion: production store-owner RLS intentionally has no DELETE policy.
        assert db.execute('select rolbypassrls from pg_roles where rolname=current_user').fetchone()[0]
        assert db.execute('delete from banking.transactions where company_id=%s returning id',(admitted['company'],)).fetchone()
    empty = read(admitted)
    assert empty.reconciliation.transaction_count == 0
    assert empty.source_sha256 not in (first.source_sha256, accepted.source_sha256)


@pytest.mark.parametrize('scope',['outsider','missing-company','revoked'])
def test_forbidden_scope_never_receives_empty_evidence(admitted, scope):
    options = {}
    if scope == 'outsider': options['actor'] = admitted['outsider']
    if scope == 'missing-company': options['company'] = uuid4()
    if scope == 'revoked':
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",(admitted['company'],admitted['owner']))
    with pytest.raises(BankingError) as caught: read(admitted, **options)
    assert caught.value.code == 'BANKING_FORBIDDEN'


@pytest.mark.parametrize('revoke',[False,True])
def test_wait_reads_committed_change_or_rejects_revoked_owner(admitted, revoke):
    seed(admitted)
    before = read(admitted)
    async def query(ready):
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
            await db.execute('set local role banking_executor')
            owner = str(admitted['owner'])
            await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                             (owner,json.dumps({'sub':owner,'aal':'aal2'})))
            ready.set_result((await(await db.execute('select pg_backend_pid()')).fetchone())[0])
            return await(await db.execute('select source_sha256 from banking.read_year_reconciliation_evidence_v1(%s,2026,%s)',(admitted['company'],owner))).fetchone()
    async def run():
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
                ready = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(query(ready))
                await waiting(await asyncio.wait_for(ready,3))
                if revoke:
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",(admitted['company'],admitted['owner']))
                else:
                    bank_owner(blocker,admitted)
                    blocker.execute("update banking.transactions set text='Committed while waiting' where company_id=%s",(admitted['company'],))
            if revoke:
                with pytest.raises(psycopg.errors.RaiseException,match='banking_forbidden'):
                    await asyncio.wait_for(task,3)
            else:
                assert (await asyncio.wait_for(task,3))[0] != before.source_sha256
        finally:
            if task is not None and not task.done(): task.cancel()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_rf_reads_evidence_on_its_held_guard_without_private_table_access(admitted, backend_url):
    seed(admitted)
    store = session(admitted,backend_url)
    query = rf.Rf1086SourceQuery(CompanyId(str(admitted['company'])),IncomeYear(2026),store.actor_id)
    async def run():
        async with store.source_admission(query) as scope:
            evidence = await scope.bank_year_evidence(CorrelationId('rf-bank-evidence'))
            assert evidence.reconciliation.transaction_count == 1
            assert evidence.source_sha256 == read_before.source_sha256
            with psycopg.connect(DATABASE_URL) as observer:
                assert not observer.execute('select pg_try_advisory_xact_lock(hashtextextended(%s,157))',(str(admitted['company']),)).fetchone()[0]
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.bank_year_evidence(CorrelationId('expired'))
    read_before = read(admitted)
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert not db.execute("select has_table_privilege('shareholder_register_filing_executor','banking.transactions','SELECT')").fetchone()[0]
        for role in ['anon','authenticated','service_role']:
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')',(role,SIGNATURE)).fetchone()[0]


def test_rollback_replay_preserves_evidence_memberships_and_count_api(admitted):
    seed(admitted)
    first = read(admitted)
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        def state():
            return (db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
                    db.execute("select nspowner,nspacl::text from pg_namespace where nspname='banking'").fetchall(),
                    db.execute("select oid,proowner,proacl::text,prosrc,proconfig from pg_proc where oid='banking.read_year_reconciliation_v1(uuid,integer,text)'::regprocedure").fetchall())
        before = state()
        for _ in range(2):
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert db.execute('select to_regprocedure(%s)',(SIGNATURE,)).fetchone() == (None,)
            assert state() == before
            with pytest.raises(BankingError): read(admitted)
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert state() == before
            assert read(admitted).source_sha256 == first.source_sha256


def test_digest_is_stable_across_session_timezone_and_physical_row_order(admitted):
    seed(admitted, 4)
    before = read(admitted)
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, admitted)
        # No-op updates move row versions without changing the committed facts.
        db.execute('update banking.transactions set text=text where company_id=%s',(admitted['company'],))
        for zone in ['Pacific/Auckland','America/Los_Angeles','UTC']:
            db.execute("select set_config('TimeZone',%s,true)",(zone,))
            actual = db.execute('select source_sha256 from banking.read_year_reconciliation_evidence_v1(%s,2026,%s)',
                                (admitted['company'],str(admitted['owner']))).fetchone()[0]
            assert actual == before.source_sha256
            assert db.execute("select current_setting('TimeZone')").fetchone()[0] == zone


@pytest.mark.parametrize('isolation',['repeatable read','serializable'])
def test_snapshot_from_before_a_guard_wait_is_not_accepted(admitted, isolation):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set transaction isolation level '+isolation)
        bank_owner(db, admitted)
        with pytest.raises(psycopg.errors.RaiseException,match='banking_company_guard_requires_read_committed'):
            db.execute('select * from banking.read_year_reconciliation_evidence_v1(%s,2026,%s)',
                       (admitted['company'],str(admitted['owner'])))


def test_verified_subject_mismatch_cannot_observe_evidence(admitted):
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, admitted)
        with pytest.raises(psycopg.errors.RaiseException,match='banking_forbidden'):
            db.execute('select * from banking.read_year_reconciliation_evidence_v1(%s,2026,%s)',
                       (admitted['company'],str(admitted['outsider'])))
