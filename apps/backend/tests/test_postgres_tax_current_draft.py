"""Owned PG17: V2 current originals preserve V1 replay and rollback containment."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.company_tax_filing.public import CompanyTaxError, CompanyTaxSourceQuery, project_company_tax_source
from talli_backend.shared.kernel import IdempotencyKey
from test_company_tax_delivery import ACTOR, COMPANY
from test_company_tax_delivery_draft import draft
from test_company_tax_current_document import response
from test_postgres_tax_delivery_draft import draft_database,session
from test_postgres_tax_source_snapshot import database

pytestmark=pytest.mark.company_tax_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261026074827_company_tax_current_draft_v2.sql'


def current_session(database):
    actor=_VerifiedActor(ACTOR,json.dumps({'sub':str(ACTOR.subject),'role':'authenticated','aal':'aal2'}))
    return PostgresCompanyTaxSession(make_conninfo(**database,user='snapshot_runtime'),actor)


@pytest.fixture(scope='module')
def current_database(draft_database):
    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.current_draft_writes_enabled_v2()').fetchone()==(False,)
        reopen(db)
        assert db.execute(members).fetchall()==before
    return draft_database


@pytest.fixture(scope='module')
def current_draft(draft):
    schemas=PinnedTax2025Schemas()
    original=replace(response(schemas,tax=draft.envelope.tax_xml.encode(),bom=True),
        organization_number=draft.envelope.source.organization_number)
    current=schemas.inspect_current(original)
    schemas.validate(draft.envelope,current_document=current)
    return replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey('current-original-store-command'),
        current_document=current)


def test_both_storage_codecs_keep_exact_bytes_and_concurrent_v2_replay_is_single(current_database,draft,current_draft):
    async def exercise():
        async with session(current_database).transaction() as tx:
            legacy=await tx.store_delivery_draft(draft)
        async def store():
            async with current_session(current_database).transaction() as tx:return await tx.store_delivery_draft(current_draft)
        first,second=await asyncio.gather(store(),store())
        assert first==second and first.draft.canonical_json==current_draft.canonical_json
        query=CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with session(current_database).transaction(snapshot=True) as tx:
            assert (await tx.delivery_draft_by_key(query,draft.command_key)).draft.canonical_json==legacy.draft.canonical_json
            snapshot=await tx.delivery_history_snapshot(query)
            facts=project_company_tax_source(query,snapshot)
        assert facts.history_coverage.status=='complete'
        assert len(facts.delivery_drafts)==2
        assert {row.draft.filing_id:row.draft.sha256 for row in snapshot.delivery_drafts}=={
            draft.filing_id:draft.sha256,current_draft.filing_id:current_draft.sha256}
    asyncio.run(exercise())
    with psycopg.connect(**current_database,user='postgres') as db:
        assert db.execute('select generation from public.tax_draft_fixture_generation').fetchone()==(2,)


def test_codecs_cannot_be_swapped_and_generic_writer_is_private(current_database,draft,current_draft):
    async def exercise():
        for rpc,value in [('store_delivery_draft_v1',current_draft),('store_delivery_draft_v2',draft)]:
            with pytest.raises(CompanyTaxError):
                async with session(current_database).transaction() as tx:
                    await tx._delivery_row('select company_tax_filing.'+rpc+'(%s,%s,%s)',
                        (value.canonical_json,value.sha256,str(ACTOR.subject)))
    asyncio.run(exercise())
    with psycopg.connect(**current_database,user='snapshot_runtime') as db:
        db.execute('set local role company_tax_filing_workflow_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('select company_tax_filing.store_delivery_draft_record_v1(%s,%s,%s,%s)',
                (draft.canonical_json,draft.sha256,str(ACTOR.subject),'company-tax-delivery-draft-v1'))


def reopen(db):
    db.execute('set role company_tax_filing_store_owner')
    db.execute("""create or replace function company_tax_filing.current_draft_writes_enabled_v2() returns boolean
      language plpgsql volatile security invoker set search_path='' as $$ begin return true; end $$""")
    db.execute('grant execute on function company_tax_filing.store_delivery_draft_v2(text,text,text) to company_tax_filing_workflow_executor')
    db.execute('reset role')


def test_v2_containment_preserves_originals_and_the_unchanged_v1_writer(current_database,draft,current_draft):
    with psycopg.connect(**current_database,user='postgres',autocommit=True) as db:
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        try:
            async def exercise():
                with pytest.raises(CompanyTaxError):
                    async with current_session(current_database).transaction() as tx:await tx.store_delivery_draft(current_draft)
                legacy=replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey('v1-after-v2-containment-command'))
                query=CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
                async with session(current_database).transaction() as tx:
                    assert (await tx.store_delivery_draft(legacy)).draft==legacy
                    retained=await tx.delivery_draft_by_key(query,current_draft.command_key)
                    assert retained.draft.canonical_json==current_draft.canonical_json
            asyncio.run(exercise())
        finally:reopen(db)


def test_v2_containment_fences_an_already_waiting_preparation(current_database,current_draft):
    async def exercise():
        pending=replace(current_draft,filing_id=str(uuid4()),command_key=IdempotencyKey('contained-current-draft-command'))
        with psycopg.connect(**current_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            async def store():
                async with current_session(current_database).transaction() as tx:await tx.store_delivery_draft(pending)
            task=asyncio.create_task(store())
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**current_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**current_database,user='postgres',autocommit=True) as containment:
                    containment.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert blocker.execute('select count(*) from company_tax_filing.delivery_drafts where id=%s',
                    (pending.filing_id,)).fetchone()==(0,)
            finally:
                blocker.rollback()
                if not task.done():task.cancel()
                with psycopg.connect(**current_database,user='postgres',autocommit=True) as restore:reopen(restore)
    asyncio.run(exercise())
