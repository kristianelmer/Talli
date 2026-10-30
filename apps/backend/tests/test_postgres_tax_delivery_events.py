"""Restricted PG17 journal: intent election, immutable replay and late results.

The owned component fixture does not replace full Company Access topology or
prove provider dispatch, runtime admission, common readiness or browser approval.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, CompanyTaxSourceQuery, TaxDeliveryAuthorityMode, TaxMutationKind,
    TaxMutationDisposition, TaxDeliveryCompletionOrigin, approve_tax_delivery_review,
    build_tax_delivery_mutation_request, complete_tax_delivery_mutation, project_company_tax_source,
)
from talli_backend.shared.kernel import IdempotencyKey
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_company_tax_delivery_journal import INSTANCE,response
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database,session
from test_postgres_tax_current_draft import current_database,current_draft,current_session

pytestmark=pytest.mark.company_tax_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261026100000_company_tax_delivery_events.sql'


@pytest.fixture(scope='module')
def events_database(current_database):
    with psycopg.connect(**current_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.delivery_event_intents_enabled_v1()').fetchone()==(False,)
    return current_database


def enable(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.delivery_event_intents_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


async def prepared(database,original):
    value=replace(original,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))
    async with current_session(database).transaction() as tx:await tx.store_delivery_draft(value)
    approval=approve_tax_delivery_review(approval_id=str(uuid4()),draft=value,approved_by=ACTOR,
        expected_draft_sha256=value.sha256,expected_review_sha256=value.envelope.review_sha256,
        current_source=value.envelope.source,current_document=value.current_document,
        current_schema_sha256=value.envelope.schema_sha256,authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK,
        authority_context_sha256='c'*64)
    return value,approval


async def append(database,value,*,fresh=True):
    async with (current_session(database) if fresh else session(database)).transaction() as tx:
        result=await tx.append_delivery_event(value)
    # An insertion is exposed to a caller only after this transaction commits.
    return result


async def read(database,value):
    query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
    async with current_session(database).transaction(snapshot=True) as tx:
        return await tx.delivery_journal(query,value.filing_id)


def mutation(approval,draft,kind):
    return build_tax_delivery_mutation_request(approval,draft,kind,
        target_instance=None if kind is TaxMutationKind.CREATE_INSTANCE else INSTANCE)


def completion(approval,draft,request):
    return complete_tax_delivery_mutation(request,approval,draft,response_bytes=response(request.kind),
        observed_at=draft.current_document.response.observed_at,
        origin=TaxDeliveryCompletionOrigin.INSTANCE_READ if request.kind is TaxMutationKind.PREPARE_CONFIRMATION
            else TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)


def test_default_closed_and_old_source_extents_never_claim_complete_after_new_table(events_database,current_draft):
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(events_database,approval)
        assert not (await read(events_database,value)).events
        query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
        async with current_session(events_database).transaction(snapshot=True) as tx:
            snapshot=await tx.delivery_history_snapshot(query)
        assert project_company_tax_source(query,snapshot).history_coverage.status=='incomplete'
    asyncio.run(exercise())


def test_concurrent_intent_elects_once_and_lost_commit_acknowledgement_reconciles(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        assert (await append(events_database,approval)).inserted
        request=mutation(approval,value,TaxMutationKind.CREATE_INSTANCE)
        first,second=await asyncio.gather(append(events_database,request),append(events_database,request))
        assert sorted([first.inserted,second.inserted])==[False,True]
        assert first.event==second.event
        # Caller lost the winning commit response. A replay never reelects it.
        assert (await append(events_database,request)).inserted is False
        journal=await read(events_database,value)
        assert len(journal.events)==2 and journal.plan(request) is TaxMutationDisposition.RECONCILE
        with pytest.raises(CompanyTaxError):await append(events_database,replace(request,organization_number='999999999'))
    asyncio.run(exercise())


def test_complete_journal_keeps_all_exact_originals_and_replays_each_operation(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        await append(events_database,approval)
        originals=[approval]
        for kind in (TaxMutationKind.CREATE_INSTANCE,TaxMutationKind.UPLOAD_ENVELOPE,
                TaxMutationKind.START_VALIDATION,TaxMutationKind.PREPARE_CONFIRMATION):
            request=mutation(approval,value,kind)
            assert (await read(events_database,value)).plan(request) is TaxMutationDisposition.EXECUTE
            assert (await append(events_database,request)).inserted
            result=completion(approval,value,request)
            first=await append(events_database,result);second=await append(events_database,result)
            assert first.inserted and not second.inserted and first.event==second.event
            assert (await read(events_database,value)).plan(request) is TaxMutationDisposition.REPLAY
            originals.extend([request,result])
        journal=await read(events_database,value)
        assert len(journal.events)==9
        assert [x.value.canonical_json for x in journal.events]==[x.canonical_json for x in originals]
    asyncio.run(exercise())


def test_late_bound_result_survives_owner_revocation_mfa_expiry_and_containment(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        await append(events_database,approval)
        request=mutation(approval,value,TaxMutationKind.CREATE_INSTANCE)
        await append(events_database,request)
        result=completion(approval,value,request)
        with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        enable(events_database,False)
        try:
            assert (await append(events_database,result,fresh=False)).inserted
            assert not (await append(events_database,result,fresh=False)).inserted
            with pytest.raises(CompanyTaxError):await read(events_database,value)
            with pytest.raises(CompanyTaxError):await append(events_database,mutation(approval,value,TaxMutationKind.UPLOAD_ENVELOPE))
        finally:
            with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
            enable(events_database)
        assert (await read(events_database,value)).plan(request) is TaxMutationDisposition.REPLAY
    asyncio.run(exercise())


def test_missing_intent_changed_result_and_unapproved_predecessor_are_rejected(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        await append(events_database,approval)
        create=mutation(approval,value,TaxMutationKind.CREATE_INSTANCE)
        with pytest.raises(CompanyTaxError):await append(events_database,completion(approval,value,create))
        with pytest.raises(CompanyTaxError):await append(events_database,mutation(approval,value,TaxMutationKind.UPLOAD_ENVELOPE))
        await append(events_database,create)
        first=completion(approval,value,create);await append(events_database,first)
        changed=complete_tax_delivery_mutation(create,approval,value,
            response_bytes=json.dumps({'id':INSTANCE.replace('123456/','999999/')}).encode(),
            observed_at=value.current_document.response.observed_at,origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        with pytest.raises(CompanyTaxError):await append(events_database,changed)
        with pytest.raises(CompanyTaxError):await append(events_database,mutation(approval,value,TaxMutationKind.START_VALIDATION))
    asyncio.run(exercise())


def test_old_mfa_cannot_approve_and_runtime_cannot_modify_or_delete_events(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(events_database,approval,fresh=False)
        await append(events_database,approval)
        query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
        with pytest.raises(CompanyTaxError):
            async with session(events_database).transaction(snapshot=True) as tx:await tx.delivery_journal(query,value.filing_id)
    asyncio.run(exercise())
    for statement in ['select * from company_tax_filing.delivery_events','update company_tax_filing.delivery_events set event_sha256=event_sha256','delete from company_tax_filing.delivery_events']:
        with psycopg.connect(**events_database,user='snapshot_runtime') as db:
            db.execute('set local role company_tax_filing_workflow_executor')
            with pytest.raises(psycopg.errors.InsufficientPrivilege):db.execute(statement)


def test_positive_v3_coverage_binds_uncertainty_and_refuses_omission_or_untracked_writes(events_database,current_draft):
    enable(events_database)
    async def snapshot(value):
        query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
        async with current_session(events_database).transaction(snapshot=True) as tx:
            return query,await tx.journal_history_snapshot(query)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        await append(events_database,approval)
        await append(events_database,mutation(approval,value,TaxMutationKind.CREATE_INSTANCE))
        query,retained=await snapshot(value)
        facts=project_company_tax_source(query,retained)
        assert facts.history_coverage.status=='complete'
        fact=next(x for x in facts.delivery_journals if x.filing_id==value.filing_id)
        assert fact.status=='uncertain' and fact.authority_mode is TaxDeliveryAuthorityMode.FINITE_LOOPBACK
        assert not facts.production_attempts and facts.readiness_status=='blocked'
        omitted=replace(retained,delivery_events=tuple(e for e in retained.delivery_events if e.binding.filing_id!=value.filing_id))
        assert project_company_tax_source(query,omitted).history_coverage.status=='incomplete'
        with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
            db.execute('alter table company_tax_filing.delivery_events disable trigger company_archive_track_tax_delivery_events')
        try:
            query,untracked=await snapshot(value)
            assert project_company_tax_source(query,untracked).history_coverage.status=='incomplete'
        finally:
            with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
                db.execute('alter table company_tax_filing.delivery_events enable trigger company_archive_track_tax_delivery_events')
    asyncio.run(exercise())


def test_containment_fences_an_intent_already_waiting_for_the_company_lock(events_database,current_draft):
    enable(events_database)
    async def exercise():
        value,approval=await prepared(events_database,current_draft)
        await append(events_database,approval)
        request=mutation(approval,value,TaxMutationKind.CREATE_INSTANCE)
        with psycopg.connect(**events_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(append(events_database,request))
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**events_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
                    db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert len((await read(events_database,value)).events)==1
            finally:
                blocker.rollback()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
                enable(events_database)
    asyncio.run(exercise())
