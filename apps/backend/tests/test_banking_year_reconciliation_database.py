"""Owner isolation and positive enumeration in the disposable full-schema lane."""
import asyncio
import json
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL
from talli_backend.adapters.supabase_banking import SupabaseBankingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.banking.public import BankingError
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, UserId

pytestmark = pytest.mark.authority_database


def read(fixture, actor=None, year=2026, company=None):
    actor = str(actor or fixture['owner'])
    session = SupabaseBankingSession(DATABASE_URL, _VerifiedActor(
        ActorId(ActorKind.USER, UserId(actor)), json.dumps({'sub': actor, 'aal': 'aal2'})))
    return asyncio.run(session.read_year_reconciliation(
        actor_id=session.actor_id, company_id=CompanyId(str(company or fixture['company'])),
        income_year=IncomeYear(year), correlation_id=CorrelationId('bank-year-database')))


@pytest.fixture(scope='module', autouse=True)
def executor_authority():
    assert DATABASE_URL, 'DATABASE_URL must identify the disposable test database'
    borrowed = []
    with psycopg.connect(DATABASE_URL) as db:
        principal = db.execute('select current_user').fetchone()[0]
        for role in ('banking_executor', 'banking_store_owner'):
            if not db.execute("select pg_has_role(current_user,%s,'SET')", (role,)).fetchone()[0]:
                prior = db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid=%s::regrole and member=current_user::regrole and grantor=member", (role,)).fetchone()
                db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(
                    sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
                borrowed.append((role, prior))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for role, prior in reversed(borrowed):
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(
                    sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(
                        sql.Identifier(role),sql.Identifier(principal),*(sql.SQL(str(v).lower()) for v in prior),sql.Identifier(principal)))


def bank_owner(db, fixture):
    """Seed/read private fixtures as their owner, including its forced RLS."""
    db.execute('set local role banking_store_owner')
    actor = str(fixture['owner'])
    db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
               (actor,json.dumps({'sub':actor,'aal':'aal2'})))


def test_full_year_counts_exceed_list_limit_and_keep_pending_reversed_warnings(admitted):
    with psycopg.connect(DATABASE_URL) as db:
        bank_owner(db, admitted)
        db.execute("""insert into banking.transactions(id,company_id,income_year,transaction_date,text,
          amount,source_hash,created_by,matched_action_reference,warning_accepted,transaction_state)
          select gen_random_uuid(),%s,2026,date '2026-01-01','Synthetic reconciliation',-1,
           lpad(to_hex(i),64,'0'),%s,
           case when i in (502,504) then 'already-matched' end,i in (503,504),
           case when i=1 then 'PENDING' when i=2 then 'REVERSED' else 'BOOKED' end
          from generate_series(1,504) i""", (admitted['company'],admitted['owner']))
    result = read(admitted)
    assert (result.transaction_count,result.unmatched_count,result.accepted_warning_count) == (504,501,2)
    assert (result.company_id,result.income_year) == (CompanyId(str(admitted['company'])),IncomeYear(2026))
    # Only 2026 can be admitted; another year's read must exclude all 504 facts.
    assert read(admitted,year=2025).transaction_count == 0
    assert read(admitted,year=2024).transaction_count == 0
    with pytest.raises(BankingError) as error:
        read(admitted,actor=admitted['outsider'])
    assert error.value.code == 'BANKING_FORBIDDEN'
    with pytest.raises(BankingError) as error:
        read(admitted,company=uuid4())
    assert error.value.code == 'BANKING_FORBIDDEN'
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                   (admitted['company'],admitted['owner']))
    with pytest.raises(BankingError) as error:
        read(admitted)
    assert error.value.code == 'BANKING_FORBIDDEN'


def test_projection_is_narrow_and_does_not_grant_filing_or_browser_table_access():
    with psycopg.connect(DATABASE_URL) as db:
        row = db.execute("""select pg_get_userbyid(p.proowner),p.prosecdef,p.provolatile,p.proconfig,
          has_function_privilege('banking_executor',p.oid,'EXECUTE'),
          has_function_privilege('banking_workflow_executor',p.oid,'EXECUTE'),
          has_function_privilege('authenticated',p.oid,'EXECUTE'),
          has_function_privilege('shareholder_register_filing_executor',p.oid,'EXECUTE'),
          has_table_privilege('banking_executor','banking.transactions','SELECT')
          from pg_proc p where p.oid='banking.read_year_reconciliation_v1(uuid,integer,text)'::regprocedure""").fetchone()
    assert row == ('banking_store_owner',True,'s',['search_path=""'],True,True,False,False,False)


def test_projection_rollback_replay_preserves_bank_facts_and_authority(admitted):
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    name = '20260929073756_banking_year_reconciliation_projection.sql'
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        with db.transaction():
            bank_owner(db, admitted)
            db.execute("""insert into banking.transactions(id,company_id,income_year,transaction_date,text,
              amount,source_hash,created_by) values(gen_random_uuid(),%s,2026,date '2026-01-01','Replay fact',-1,repeat('b',64),%s)""",
              (admitted['company'],admitted['owner']))
        def authority():
            with db.transaction():
                bank_owner(db, admitted)
                facts = db.execute('select id,company_id,income_year,source_hash from banking.transactions where company_id=%s order by id',
                                   (admitted['company'],)).fetchall()
                assert len(facts) == 1
            return (db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall(),
                    db.execute("select nspowner,nspacl::text from pg_namespace where nspname='banking'").fetchall(),
                    facts)
        before = authority()
        for _ in range(2):
            db.execute((root/'supabase/rollback'/name).read_text())
            assert db.execute("select to_regprocedure('banking.read_year_reconciliation_v1(uuid,integer,text)')").fetchone() == (None,)
            assert authority() == before
            db.execute((root/'supabase/migrations'/name).read_text())
            assert authority() == before
    test_projection_is_narrow_and_does_not_grant_filing_or_browser_table_access()
