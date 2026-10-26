"""Owned PG17 guarded-upload proof storage; no provider dispatch claim."""
import asyncio
import base64
from dataclasses import replace
from datetime import UTC,datetime
import json

import psycopg
import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxDeliveryReadReference,TaxDeliveryUploadPrerequisite,
    TaxDeliveryInstanceObservation,TaxMutationKind,TaxDeliveryCompletionOrigin,TaxDeliveryUploadReadEvidence,
    TaxDeliveryEnvelopeObservation,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,
    bind_tax_delivery_upload_prerequisite,build_tax_delivery_mutation_request,complete_tax_delivery_mutation,
    reconcile_tax_delivery_upload,project_company_tax_source,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_current_draft import current_database,current_draft,current_session
from test_postgres_tax_delivery_events import events_database,enable,append,read,mutation,completion
from test_postgres_tax_delivery_observations import observation_database,enable_observations,seed,ROOT
from test_company_tax_delivery_observation import instance_document,original
from test_company_tax_delivery_envelope_observation import envelope_read
from test_company_tax_delivery_journal import INSTANCE,DATA

pytestmark=pytest.mark.company_tax_database
MIGRATION='20261026124307_company_tax_guarded_upload_v2.sql'


@pytest.fixture(scope='module')
def upload_database(observation_database):
    enable_observations(observation_database)
    with psycopg.connect(**observation_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.guarded_upload_enabled_v2()').fetchone()==(False,)
    return observation_database


def enable_upload(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.guarded_upload_enabled_v2() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


def now():return Timestamp(datetime.now(UTC))


def file_reads(draft,approval,*,body=None):
    raw=draft.envelope.envelope_xml.encode() if body is None else body
    metadata=instance_document(draft)
    metadata['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon','contentType':'application/xml',
        'size':len(raw),'fileScanResult':'Pending'}]
    instance=TaxDeliveryInstanceObservation(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,INSTANCE,original(json.dumps(metadata).encode()),now())
    envelope=TaxDeliveryEnvelopeObservation(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,INSTANCE,DATA,instance.evidence_sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ENVELOPE,base64.b64encode(raw).decode(),'application/xml',200),now())
    return instance,envelope


async def prepared(database,draft):
    draft,approval,admission=await seed(database,draft)
    await append(database,admission)
    create=mutation(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    await append(database,create);await append(database,completion(approval,draft,create))
    started=now()
    instance=TaxDeliveryInstanceObservation(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,INSTANCE,original(json.dumps(instance_document(draft)).encode()),now())
    retained=(await append(database,instance)).event.value
    proof=bind_tax_delivery_upload_prerequisite(approval,draft,retained=retained,fresh=instance,observed_from=started,observed_until=now())
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE,upload_prerequisite=proof)
    return draft,approval,instance,request


def test_closed_writer_and_positive_complete_v5_reader_precede_guarded_uploads(upload_database,current_draft):
    async def exercise():
        draft,approval,_,request=await prepared(upload_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(upload_database,request)
        journal=await read(upload_database,draft)
        assert journal.read_evidence and journal.guarded_upload
        assert len(journal.events)==5 and journal.progress.mutation_kind is TaxMutationKind.CREATE_INSTANCE
        query=CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with current_session(upload_database).transaction(snapshot=True) as tx:
            snapshot=await tx.journal_history_snapshot(query)
        assert snapshot.contract_version=='company-tax-source-v5'
        assert project_company_tax_source(query,snapshot).history_coverage.status=='complete'
    asyncio.run(exercise())


def test_only_bound_fresh_empty_instance_can_commit_the_exact_upload_body(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,approval,_,request=await prepared(upload_database,current_draft)
        legacy=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE)
        with pytest.raises(CompanyTaxError):await append(upload_database,legacy)
        bad=replace(request,upload_prerequisite=replace(request.upload_prerequisite,
            instance_read=replace(request.upload_prerequisite.instance_read,event_sha256='a'*64)))
        with pytest.raises(CompanyTaxError):await append(upload_database,bad)
        first=await append(upload_database,request)
        repeated=await append(upload_database,request)
        assert first.inserted and not repeated.inserted and repeated.event==first.event
        assert (await read(upload_database,draft)).events[-1].value==request
    asyncio.run(exercise())


def test_raw_duplicate_metadata_cannot_be_promoted_to_a_guarded_upload_proof(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,approval,instance,_=await prepared(upload_database,current_draft)
        raw=json.dumps(instance_document(draft)).encode();raw=raw[:-1]+b',"data":[null],"data":[]}'
        instance=replace(instance,original=original(raw),observed_at=now())
        assert not instance.inspection.known
        retained=(await append(upload_database,instance)).event.value
        time=now()
        proof=TaxDeliveryUploadPrerequisite(INSTANCE,TaxDeliveryReadReference(retained.sha256,retained.evidence_sha256,time),time,time)
        request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE,upload_prerequisite=proof)
        with pytest.raises(CompanyTaxError):await append(upload_database,request)
        assert not any(event.slot=='intent:upload_envelope' for event in (await read(upload_database,draft)).events)
    asyncio.run(exercise())


def test_exact_envelope_reads_dedup_and_inline_completion_preserves_both_originals(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,approval,_,request=await prepared(upload_database,current_draft)
        await append(upload_database,request)
        instance,envelope=file_reads(draft,approval)
        await append(upload_database,instance)
        first=await append(upload_database,envelope)
        repeated=await append(upload_database,replace(envelope,observed_at=now()))
        assert first.inserted and not repeated.inserted and first.event==repeated.event
        journal=await read(upload_database,draft)
        assert journal.progress.status=='uncertain' and journal.progress.mutation_kind is TaxMutationKind.UPLOAD_ENVELOPE
        result=reconcile_tax_delivery_upload(request,approval,draft,evidence=TaxDeliveryUploadReadEvidence(instance,envelope),observed_at=now())
        stored=await append(upload_database,result)
        assert stored.inserted and stored.event.value==result
        journal=await read(upload_database,draft)
        assert journal.progress.status=='mutation_completed'
        assert journal.events[-1].value.upload_read_evidence.instance.original.raw_bytes==instance.original.raw_bytes
        assert journal.events[-1].value.upload_read_evidence.envelope.original.raw_bytes==draft.envelope.envelope_xml.encode()
    asyncio.run(exercise())


def test_known_inline_upload_result_survives_revocation_mfa_and_all_containment_fences(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,approval,_,request=await prepared(upload_database,current_draft)
        await append(upload_database,request)
        instance,envelope=file_reads(draft,approval)
        result=reconcile_tax_delivery_upload(request,approval,draft,evidence=TaxDeliveryUploadReadEvidence(instance,envelope),observed_at=now())
        with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        enable_upload(upload_database,False);enable_observations(upload_database,False);enable(upload_database,False)
        try:
            stored=await append(upload_database,result,fresh=False)
            assert stored.inserted and (await append(upload_database,result,fresh=False)).event==stored.event
            # Equal normalized outcome with different undisclosed proof times
            # cannot expose the first winner through a late-result writer.
            changed=replace(result,observed_at=now())
            with pytest.raises(CompanyTaxError):await append(upload_database,changed,fresh=False)
        finally:
            with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
            enable_upload(upload_database);enable_observations(upload_database);enable(upload_database)
        assert (await read(upload_database,draft)).events[-1].value==result
    asyncio.run(exercise())


def test_original_intent_and_observation_fences_also_contain_new_guarded_families(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,approval,_,request=await prepared(upload_database,current_draft)
        enable(upload_database,False)
        try:
            with pytest.raises(CompanyTaxError):await append(upload_database,request)
        finally:enable(upload_database)
        await append(upload_database,request)
        instance,envelope=file_reads(draft,approval)
        await append(upload_database,instance)
        enable_observations(upload_database,False)
        try:
            with pytest.raises(CompanyTaxError):await append(upload_database,envelope)
        finally:enable_observations(upload_database)
        assert not any(event.slot.startswith('observation:envelope:') for event in (await read(upload_database,draft)).events)
    asyncio.run(exercise())


def test_new_upload_containment_fences_a_request_already_waiting_on_company_lock(upload_database,current_draft):
    enable_upload(upload_database)
    async def exercise():
        draft,_,_,request=await prepared(upload_database,current_draft)
        with psycopg.connect(**upload_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(append(upload_database,request))
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**upload_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
                    db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert not any(event.slot=='intent:upload_envelope' for event in (await read(upload_database,draft)).events)
            finally:
                blocker.rollback()
                if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                enable_upload(upload_database)
    asyncio.run(exercise())
