"""Owned PG17 proof: scope-bound reads, immutable dedup and V4 enumeration."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxDeliveryAdmissionEvidence,TaxDeliveryOriginalPurpose,
    TaxDeliveryReadOriginal,TaxDeliveryInstanceObservation,TaxMutationKind,project_company_tax_source,
    TaxDeliveryAuthorityMode,archive_tax_delivery_journal,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database,session
from test_postgres_tax_current_draft import current_database,current_draft,current_session
from test_postgres_tax_delivery_events import events_database,enable,prepared,append,read,mutation,completion,ROOT
from test_company_tax_delivery_rehearsal import admitted
from test_company_tax_delivery_observation import instance_document,original

pytestmark=pytest.mark.company_tax_database
MIGRATION='20261026111629_company_tax_delivery_observations.sql'


@pytest.fixture(scope='module')
def observation_database(events_database):
    with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.delivery_observations_enabled_v1()').fetchone()==(False,)
    enable(events_database)
    return events_database


def enable_observations(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.delivery_observations_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


async def seed(database,current_draft):
    value,_=await prepared(database,current_draft)
    basis=dict(approval_id=str(uuid4()),draft=value,approved_by=ACTOR,expected_draft_sha256=value.sha256,
        expected_review_sha256=value.envelope.review_sha256,current_source=value.envelope.source,
        current_document=value.current_document,current_schema_sha256=value.envelope.schema_sha256,
        authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK)
    grant,_,_,approval,_=admitted(basis)
    await append(database,approval)
    evidence=TaxDeliveryAdmissionEvidence(value.filing_id,COMPANY,value.envelope.source.income_year,ACTOR,
        approval.sha256,original(grant.canonical_context.encode(),TaxDeliveryOriginalPurpose.ADMISSION))
    return value,approval,evidence


async def observed(database,value,approval,*,extra=None):
    created=mutation(approval,value,TaxMutationKind.CREATE_INSTANCE)
    await append(database,created);await append(database,completion(approval,value,created))
    document=instance_document(value)
    if extra is not None:document['fixtureRead']=extra
    raw=b'\xef\xbb\xbf'+json.dumps(document,indent=2).encode()+b'\n'
    return TaxDeliveryInstanceObservation(value.filing_id,COMPANY,value.envelope.source.income_year,ACTOR,
        approval.sha256,value.envelope.source.organization_number,document['id'],original(raw),
        value.current_document.response.observed_at)


def test_private_closed_writer_and_positive_reader_precede_any_observation(observation_database,current_draft):
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(observation_database,evidence)
        journal=await read(observation_database,value)
        assert journal.read_evidence and len(journal.events)==1
        query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
        async with current_session(observation_database).transaction(snapshot=True) as tx:
            snapshot=await tx.journal_history_snapshot(query)
        assert snapshot.contract_version=='company-tax-source-v4'
        assert project_company_tax_source(query,snapshot).history_coverage.status=='complete'
    asyncio.run(exercise())
    with psycopg.connect(**observation_database,user='postgres') as db:
        for role in ('anon','authenticated','service_role','snapshot_runtime'):
            assert db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')',(role,
                'company_tax_filing.append_delivery_observation_v1(text,text,text)')).fetchone()==(False,)
            assert db.execute('select has_table_privilege(%s,%s,\'INSERT,UPDATE,DELETE\')',(role,
                'company_tax_filing.delivery_events')).fetchone()==(False,)


def test_exact_originals_and_duplicate_poll_preserve_first_bytes_without_generation_churn(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        assert (await append(observation_database,evidence)).inserted
        observation=await observed(observation_database,value,approval)
        first=await append(observation_database,observation)
        with psycopg.connect(**observation_database,user='postgres') as db:
            before=db.execute('select generation from public.tax_draft_fixture_generation').fetchone()
        later=replace(observation,observed_at=Timestamp(observation.observed_at.value+timedelta(seconds=1)))
        repeated=await append(observation_database,later)
        assert not repeated.inserted and repeated.event==first.event
        with psycopg.connect(**observation_database,user='postgres') as db:
            assert db.execute('select generation from public.tax_draft_fixture_generation').fetchone()==before
        journal=await read(observation_database,value)
        assert journal.events[-1]==first.event and journal.progress.status=='mutation_completed'
        assert journal.progress.mutation_kind is TaxMutationKind.CREATE_INSTANCE
        assert journal.events[-1].value.original.raw_bytes==observation.original.raw_bytes
        query=CompanyTaxSourceQuery(COMPANY,value.envelope.source.income_year,ACTOR)
        async with current_session(observation_database).transaction(snapshot=True) as tx:
            snapshot=await tx.journal_history_snapshot(query)
        archive=archive_tax_delivery_journal(query,snapshot)
        assert archive.source_facts.history_coverage.status=='complete'
        assert first.event in archive.events
        with pytest.raises(CompanyTaxError):archive_tax_delivery_journal(query,snapshot,read_evidence=False)
        with pytest.raises(CompanyTaxError):project_company_tax_source(query,replace(snapshot,contract_version='company-tax-source-v3'))
    asyncio.run(exercise())


def test_more_than_nine_reads_are_complete_and_unknown_metadata_is_preserved(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        await append(observation_database,evidence)
        observation=await observed(observation_database,value,approval)
        for index in range(12):
            raw=json.dumps({'fixturePoll':index}).encode()
            result=await append(observation_database,replace(observation,original=original(raw)))
            assert result.inserted and not result.event.value.inspection.known
        journal=await read(observation_database,value)
        assert len(journal.events)==16 and len({event.slot for event in journal.events})==16
        assert journal.progress.status=='mutation_completed'
    asyncio.run(exercise())


def test_missing_admission_known_instance_or_current_mfa_cannot_append_reads(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        observation=await observed(observation_database,value,approval)
        with pytest.raises(CompanyTaxError):await append(observation_database,observation)
        await append(observation_database,evidence)
        with pytest.raises(CompanyTaxError):await append(observation_database,observation,fresh=False)
        with pytest.raises(CompanyTaxError):await append(observation_database,replace(evidence,approval_sha256='a'*64))
        # Known scope is immutable; another filing cannot borrow a read.
        other,other_approval,other_evidence=await seed(observation_database,current_draft)
        await append(observation_database,other_evidence)
        foreign=replace(observation,filing_id=other.filing_id,approval_sha256=other_approval.sha256)
        with pytest.raises(CompanyTaxError):await append(observation_database,foreign)
    asyncio.run(exercise())


def test_containment_preserves_all_existing_readers_and_first_originals(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        await append(observation_database,evidence)
        observation=await observed(observation_database,value,approval)
        await append(observation_database,observation)
        before=await read(observation_database,value)
        with psycopg.connect(**observation_database,user='postgres',autocommit=True) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert await read(observation_database,value)==before
        with pytest.raises(CompanyTaxError):await append(observation_database,replace(observation,original=original(b'{"new":true}')))
    asyncio.run(exercise())


def test_concurrent_identical_polls_keep_one_first_original_and_one_generation_change(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        await append(observation_database,evidence)
        observation=await observed(observation_database,value,approval)
        later=replace(observation,observed_at=Timestamp(observation.observed_at.value+timedelta(seconds=1)))
        with psycopg.connect(**observation_database,user='postgres') as db:
            before=db.execute('select generation from public.tax_draft_fixture_generation').fetchone()[0]
        first,second=await asyncio.gather(append(observation_database,observation),append(observation_database,later))
        assert sorted((first.inserted,second.inserted))==[False,True] and first.event==second.event
        assert first.event.value in (observation,later)
        with psycopg.connect(**observation_database,user='postgres') as db:
            assert db.execute('select generation from public.tax_draft_fixture_generation').fetchone()[0]==before+1
        assert len((await read(observation_database,value)).events)==5
    asyncio.run(exercise())


def test_containment_fences_a_read_already_waiting_for_company_lock(observation_database,current_draft):
    enable_observations(observation_database)
    async def exercise():
        value,approval,evidence=await seed(observation_database,current_draft)
        await append(observation_database,evidence)
        observation=await observed(observation_database,value,approval)
        with psycopg.connect(**observation_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(append(observation_database,observation))
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**observation_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**observation_database,user='postgres',autocommit=True) as db:
                    db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert len((await read(observation_database,value)).events)==4
            finally:
                blocker.rollback()
                if not task.done():
                    task.cancel();await asyncio.gather(task,return_exceptions=True)
                enable_observations(observation_database)
    asyncio.run(exercise())
