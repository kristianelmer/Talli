"""Owned PG17 component proof; full Company Access topology is a separate gate."""
import asyncio
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.company_tax_filing.public import CompanyTaxError, CompanyTaxSourceQuery, project_company_tax_source
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, IdempotencyKey
from test_company_tax_delivery import ACTOR, COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database

pytestmark = pytest.mark.company_tax_database
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = '20261026062315_company_tax_delivery_journal.sql'


@pytest.fixture(scope='module')
def draft_database(database):
    with psycopg.connect(**database, user='postgres', autocommit=True) as db:
        db.execute('''
          create role anon nologin; create role authenticated nologin; create role service_role nologin;
          create role company_tax_filing_store_owner nologin noinherit nobypassrls;
          create role company_archive_projection_executor nologin noinherit nobypassrls;
          create schema extensions; create extension pgcrypto schema extensions;
          grant usage on schema extensions to company_tax_filing_store_owner;
          create schema company_tax_filing authorization company_tax_filing_store_owner;
          grant usage on schema company_tax_filing to company_tax_filing_workflow_executor;
          create table public.tax_draft_fixture_owner(company uuid primary key, actor uuid);
          create table backend_system.company_tax_return_migration_state(phase text);
          insert into backend_system.company_tax_return_migration_state values('contracted');
          create function public.company_access_auth_uid_v1() returns uuid language sql
            as $$ select current_setting('talli.verified_actor_id',true)::uuid $$;
          create function public.company_access_is_accepted_owner_v1(company uuid) returns boolean
            language sql volatile security definer set search_path='' as $$
            select exists(select 1 from public.tax_draft_fixture_owner o
              where o.company=$1 and o.actor=public.company_access_auth_uid_v1()) $$;
          create function public.company_archive_lock_company_v1(company uuid) returns void
            language sql volatile as $$ select pg_advisory_xact_lock(hashtextextended($1::text,157)) $$;
          revoke all on function public.company_archive_lock_company_v1(uuid) from public;
          create table public.tax_draft_fixture_generation(company_id uuid,income_year int,generation int,
            primary key(company_id,income_year));
          grant all on public.tax_draft_fixture_generation to company_archive_projection_executor;
          create function public.company_archive_track_source_write_v1() returns trigger
            language plpgsql security definer set search_path='' as $$ begin
            insert into public.tax_draft_fixture_generation values(new.company_id,new.income_year,1)
             on conflict(company_id,income_year) do update set generation=tax_draft_fixture_generation.generation+1;
            return new; end $$;
          alter function public.company_archive_track_source_write_v1() owner to company_archive_projection_executor;
          revoke all on function public.company_archive_track_source_write_v1() from public;
          create function public.company_access_has_fresh_mfa_v1() returns boolean language sql volatile
            as $$ select (current_setting('talli.verified_actor_claims',true)::jsonb)->>'aal'='aal2' $$;
          set role company_tax_filing_store_owner;
          create function company_tax_filing.assert_return_available_v1(subject text) returns uuid
            language plpgsql volatile set search_path='' as $$ begin
            if subject is null or subject is distinct from current_setting('talli.verified_actor_id',true)
              or subject is distinct from (current_setting('talli.verified_actor_claims',true)::jsonb)->>'sub'
              or (current_setting('talli.verified_actor_claims',true)::jsonb)->>'role' is distinct from 'authenticated'
              then raise exception 'company_tax_return_forbidden'; end if;
            return subject::uuid; end $$;
          create function company_tax_filing.verified_filing_actor_v1(subject text) returns uuid
            language sql volatile as $$ select company_tax_filing.assert_return_available_v1($1) $$;
          create table company_tax_filing.settlements(id uuid);
          create table company_tax_filing.filing_previews(id uuid);
          create table company_tax_filing.filing_submissions(id uuid);
          create table company_tax_filing.filing_overrides(id uuid);
          create table company_tax_filing.filing_review_comments(id uuid);
          create table company_tax_filing.authority_permissions(id uuid);
          create table company_tax_filing.authority_test_runs(id uuid);
          reset role;
        ''')
        db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)', (str(COMPANY),str(ACTOR.subject)))
        # This small predecessor models only source coverage shape; it is not a
        # replacement for the real migration reconciliation/Company Access gate.
        from test_company_tax_source_facts import source
        raw = source(True)
        raw.update(companyId=str(COMPANY), incomeYear=2025)
        raw['workspace'] = {key: [] for key in raw['workspace']}
        raw['coverage'].update(companyId=str(COMPANY), incomeYear=2025, retainedSubmissionIds=[],
            familyCounts={key:0 for key in raw['coverage']['familyCounts']})
        db.execute('create table public.tax_draft_fixture_source(body jsonb)')
        db.execute('insert into public.tax_draft_fixture_source values(%s)',(Jsonb(raw),))
        db.execute('grant select on public.tax_draft_fixture_source to company_tax_filing_store_owner')
        db.execute('''set role company_tax_filing_store_owner;
          create function company_tax_filing.read_source_snapshot_v1(company uuid,year integer,subject text)
          returns jsonb language plpgsql volatile security definer set search_path='' as $$
          declare result jsonb; extent boolean; begin
           perform company_tax_filing.assert_return_available_v1(subject);
           if not public.company_access_is_accepted_owner_v1(company) then raise exception 'company_tax_return_not_found'; end if;
           if current_setting('transaction_isolation')<>'repeatable read' then raise exception 'company_tax_return_unavailable'; end if;
           select count(*)=7 into extent from pg_class c join pg_namespace n on n.oid=c.relnamespace
             where n.nspname='company_tax_filing' and c.relkind in ('r','p');
           select body into result from public.tax_draft_fixture_source;
           return result||jsonb_build_object('asOf',transaction_timestamp(),'coverage',
             (result->'coverage')||jsonb_build_object('declaredExtentValid',extent));
          end $$;
          revoke all on function company_tax_filing.read_source_snapshot_v1(uuid,integer,text) from public;
          grant execute on function company_tax_filing.read_source_snapshot_v1(uuid,integer,text) to company_tax_filing_workflow_executor;
          reset role;''')
        members = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before = db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall() == before
    return database


def session(database, actor=ACTOR):
    verified = _VerifiedActor(actor, json.dumps({'sub':str(actor.subject),'role':'authenticated','aal':'aal1'}))
    return PostgresCompanyTaxSession(make_conninfo(**database,user='snapshot_runtime'), verified)


def test_concurrent_exact_replay_persists_one_immutable_draft(draft_database,draft):
    async def exercise():
        async def store():
            async with session(draft_database).transaction() as tx:
                return await tx.store_delivery_draft(draft)
        first,second = await asyncio.gather(store(),store())
        assert first == second and first.draft == draft
        query = CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with session(draft_database).transaction() as tx:
            assert await tx.delivery_draft_by_key(query,draft.command_key) == first
        with pytest.raises(CompanyTaxError):
            async with session(draft_database).transaction() as tx:
                await tx.store_delivery_draft(replace(draft,filing_id=str(uuid4())))
    asyncio.run(exercise())
    with psycopg.connect(**draft_database,user='postgres') as db:
        assert db.execute('select count(*) from company_tax_filing.delivery_drafts').fetchone() == (1,)
        assert db.execute('select generation from public.tax_draft_fixture_generation').fetchone() == (1,)
        assert db.execute("select has_function_privilege('company_tax_filing_store_owner','public.company_archive_track_source_write_v1()','execute')").fetchone() == (False,)


def test_new_source_v2_covers_drafts_while_v1_refuses_complete_history(draft_database,draft):
    async def exercise():
        async with session(draft_database).transaction() as tx:
            await tx.store_delivery_draft(draft)
        query = CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with session(draft_database).transaction(snapshot=True) as tx:
            current = project_company_tax_source(query,await tx.filing_source_snapshot(query))
            new = project_company_tax_source(query,await tx.delivery_history_snapshot(query))
        assert current.evidence.digest == new.evidence.digest
        assert current.delivery_drafts == new.delivery_drafts
        assert new.evidence.version.startswith('company-tax-source-v2:')
        with psycopg.connect(**draft_database,user='postgres') as db:
            db.execute('set transaction isolation level repeatable read')
            db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                (str(ACTOR.subject),json.dumps({'sub':str(ACTOR.subject),'role':'authenticated'})))
            legacy = db.execute('select company_tax_filing.read_source_snapshot_v1(%s,2025,%s)',
                (str(COMPANY),str(ACTOR.subject))).fetchone()[0]
            assert legacy['coverage']['declaredExtentValid'] is False
        assert new.history_coverage.status == 'complete',new.history_coverage.reasons
        assert new.delivery_drafts[0].filing_id == draft.filing_id
        assert new.production_attempts == () and new.readiness_status == 'blocked'
    asyncio.run(exercise())


def test_raw_table_access_is_denied_and_owner_cannot_update_or_delete_drafts(draft_database):
    with psycopg.connect(**draft_database,user='snapshot_runtime') as db:
        db.execute('set local role company_tax_filing_workflow_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('select canonical_json from company_tax_filing.delivery_drafts')
    with psycopg.connect(**draft_database,user='postgres') as db:
        db.execute('set local role company_tax_filing_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(ACTOR.subject),))
        assert db.execute('update company_tax_filing.delivery_drafts set command_key=command_key returning id').fetchall() == []
        assert db.execute('delete from company_tax_filing.delivery_drafts returning id').fetchall() == []


def test_forged_actor_foreign_owner_and_repeatable_write_are_rejected(draft_database,draft):
    async def exercise():
        outsider = ActorId(ActorKind.USER,UserId(str(uuid4())))
        for tx_session,changed in ((session(draft_database,outsider),draft),
                (session(draft_database,outsider),replace(draft,prepared_by=outsider))):
            with pytest.raises(CompanyTaxError):
                async with tx_session.transaction() as tx: await tx.store_delivery_draft(changed)
        with pytest.raises(CompanyTaxError):
            async with session(draft_database).transaction(snapshot=True) as tx:
                await tx.store_delivery_draft(draft)
    asyncio.run(exercise())


def test_owner_revoked_while_waiting_for_company_lock_cannot_store(draft_database,draft):
    async def exercise():
        changed = replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey('revoked-tax-draft-command'))
        with psycopg.connect(**draft_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            async def store():
                async with session(draft_database).transaction() as tx: await tx.store_delivery_draft(changed)
            task = asyncio.create_task(store())
            try:
                for _ in range(100):
                    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as probe:
                        waiting = probe.execute("select count(*) from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory'").fetchone()[0]
                    if waiting: break
                    await asyncio.sleep(.01)
                assert waiting, 'The test must observe the actual guarded wait.'
                blocker.execute('update public.tax_draft_fixture_owner set actor=null where company=%s',(str(COMPANY),))
                blocker.commit()
                with pytest.raises(CompanyTaxError): await task
            finally:
                blocker.rollback()
                if not task.done(): task.cancel()
                with psycopg.connect(**draft_database,user='postgres',autocommit=True) as restore:
                    restore.execute('update public.tax_draft_fixture_owner set actor=%s where company=%s',(str(ACTOR.subject),str(COMPANY)))
    asyncio.run(exercise())


def test_added_undeclared_store_stops_v2_completeness(draft_database,draft):
    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as db:
        db.execute('create table company_tax_filing.undeclared_draft_test(id uuid)')
        try:
            async def exercise():
                query = CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
                async with session(draft_database).transaction(snapshot=True) as tx:
                    facts = project_company_tax_source(query,await tx.delivery_history_snapshot(query))
                assert facts.history_coverage.status == 'incomplete'
                assert 'declaredDeliveryExtentValid_unproven' in facts.history_coverage.reasons
            asyncio.run(exercise())
        finally: db.execute('drop table company_tax_filing.undeclared_draft_test')


def test_containment_rollback_stops_writes_but_keeps_exact_originals_and_history(draft_database,draft):
    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as db:
        members = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before = db.execute(members).fetchall()
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert db.execute(members).fetchall() == before
        try:
            async def exercise():
                with pytest.raises(CompanyTaxError):
                    async with session(draft_database).transaction() as tx: await tx.store_delivery_draft(draft)
                query = CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
                async with session(draft_database).transaction(snapshot=True) as tx:
                    stored = await tx.delivery_draft_by_key(query,draft.command_key)
                    assert stored.draft.canonical_json == draft.canonical_json
                    facts = project_company_tax_source(query,await tx.delivery_history_snapshot(query))
                    assert facts.history_coverage.status == 'complete'
            asyncio.run(exercise())
        finally:
            # The expansion is immutable. Reopening its contained writer needs
            # the private fence and exact grant, never table recreation or data copying.
            db.execute('set role company_tax_filing_store_owner')
            db.execute("""create or replace function company_tax_filing.delivery_draft_writes_enabled_v1()
              returns boolean language plpgsql volatile security invoker set search_path='' as $$ begin return true; end $$""")
            db.execute('grant execute on function company_tax_filing.store_delivery_draft_v1(text,text,text) to company_tax_filing_workflow_executor')
            db.execute('reset role')


def test_containment_fences_a_writer_already_waiting_on_the_company_lock(draft_database,draft):
    async def exercise():
        changed = replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey('contained-waiting-draft-command'))
        with psycopg.connect(**draft_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            async def store():
                async with session(draft_database).transaction() as tx: await tx.store_delivery_draft(changed)
            task = asyncio.create_task(store())
            try:
                for _ in range(100):
                    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as probe:
                        waiting = probe.execute("select count(*) from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory'").fetchone()[0]
                    if waiting: break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**draft_database,user='postgres',autocommit=True) as containment:
                    containment.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError): await task
                assert blocker.execute('select count(*) from company_tax_filing.delivery_drafts where id=%s',
                    (changed.filing_id,)).fetchone() == (0,)
            finally:
                blocker.rollback()
                if not task.done(): task.cancel()
                with psycopg.connect(**draft_database,user='postgres',autocommit=True) as restore:
                    restore.execute('set role company_tax_filing_store_owner')
                    restore.execute("""create or replace function company_tax_filing.delivery_draft_writes_enabled_v1()
                      returns boolean language plpgsql volatile security invoker set search_path='' as $$ begin return true; end $$""")
                    restore.execute('grant execute on function company_tax_filing.store_delivery_draft_v1(text,text,text) to company_tax_filing_workflow_executor')
    asyncio.run(exercise())


def test_observation_time_covers_a_draft_committed_after_begin_before_first_snapshot(draft_database,draft):
    from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxTransaction
    async def exercise():
        changed = replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey('snapshot-start-race-draft-command'))
        verified = _VerifiedActor(ACTOR,json.dumps({'sub':str(ACTOR.subject),'role':'authenticated','aal':'aal1'}))
        async with await psycopg.AsyncConnection.connect(**draft_database,user='snapshot_runtime',
                row_factory=psycopg.rows.dict_row) as connection:
            async with connection.transaction():
                await connection.execute('set transaction isolation level repeatable read')
                async with session(draft_database).transaction() as tx:
                    stored = await tx.store_delivery_draft(changed)
                # No snapshot-taking query ran on the reader before that commit.
                await connection.execute('set local role company_tax_filing_workflow_executor')
                await connection.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                    (str(ACTOR.subject),verified.claims_json))
                tx = PostgresCompanyTaxTransaction(verified,connection)
                query = CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
                snapshot = await tx.delivery_history_snapshot(query)
                facts = project_company_tax_source(query,snapshot)
                cursor = await connection.execute('select transaction_timestamp() as start')
                assert (await cursor.fetchone())['start'] < stored.recorded_at.value <= snapshot.as_of.value
                assert facts.history_coverage.status == 'complete'
    asyncio.run(exercise())
