"""Owned PG17 validation proof storage; no authority dispatch claim."""
import asyncio
import base64
from dataclasses import replace
from datetime import UTC,datetime
import json

import psycopg
import pytest

from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxMutationKind,TaxDeliveryCompletionOrigin,
    TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,
    bind_tax_delivery_validation_prerequisite,build_tax_delivery_mutation_request,complete_tax_delivery_mutation,project_company_tax_source,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_current_draft import current_database,current_draft,current_session
from test_postgres_tax_delivery_events import events_database,enable,append,read
from test_postgres_tax_delivery_observations import observation_database,enable_observations,ROOT
from test_postgres_tax_guarded_upload import upload_database,enable_upload,prepared,file_reads
from test_company_tax_delivery_journal import DATA
from test_company_tax_validation_response_schemas import xml

pytestmark=pytest.mark.company_tax_database
MIGRATION='20261026143210_company_tax_validation_evidence_v1.sql'
JOB='storeDokument-known-native-v1'


@pytest.fixture(scope='module')
def validation_database(upload_database):
    enable(upload_database);enable_observations(upload_database);enable_upload(upload_database)
    with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.validation_evidence_enabled_v1()').fetchone()==(False,)
        for function in ('validation_read_bytes_v1(jsonb,text)','validation_job_identity_v1(jsonb)','validation_json_text_v1(bytea)'):
            assert db.execute('select has_function_privilege(%s,%s,%s)',('company_tax_filing_workflow_executor','company_tax_filing.'+function,'EXECUTE')).fetchone()==(False,)
    return upload_database


def enable_validation(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.validation_evidence_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


def now():return Timestamp(datetime.now(UTC))


async def ready(database,draft):
    draft,approval,_,upload=await prepared(database,draft)
    await append(database,upload)
    await append(database,complete_tax_delivery_mutation(upload,approval,draft,response_bytes=json.dumps({'id':DATA}).encode(),
        observed_at=now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE))
    began=now();instance,envelope=file_reads(draft,approval)
    raw=json.loads(instance.original.raw_bytes);raw['data'][0]['fileScanResult']='Clean'
    instance=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()),observed_at=now())
    envelope=replace(envelope,instance_evidence_sha256=instance.evidence_sha256,observed_at=now())
    first_instance=(await append(database,instance)).event.value;first_envelope=(await append(database,envelope)).event.value
    proof=bind_tax_delivery_validation_prerequisite(approval,draft,retained_instance=first_instance,retained_envelope=first_envelope,
        fresh_instance=instance,fresh_envelope=envelope,observed_from=began,observed_until=now())
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.START_VALIDATION,
        target_instance=instance.instance_id,validation_prerequisite=proof)
    return draft,approval,request


def completion(draft,approval,request):
    return complete_tax_delivery_mutation(request,approval,draft,response_bytes=json.dumps({'jobbId':JOB,'jobbStatus':'OPPRETTET'}).encode(),
        observed_at=now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)


def job_read(draft,approval,request,*,status='FERDIG',body=None):
    raw=json.dumps({'jobbStatus':status,'forrigeStatus':'KJOERER','sekunderSidenOpprettelse':10,'sekunderSidenEndring':1}).encode() if body is None else body
    return TaxDeliveryValidationJobObservation(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,request.target_instance,JOB,request.sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.VALIDATION_JOB,base64.b64encode(raw).decode(),'application/json',200),now())


def result_read(draft,approval,request,job):
    return TaxDeliveryValidationResultObservation(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,request.target_instance,JOB,request.sha256,job.evidence_sha256,
        PinnedTaxValidationResponseSchemas().schema_sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.VALIDATION_RESULT,base64.b64encode(b'\xef\xbb\xbf'+xml()+b'\n').decode(),'application/xml',200),now())


def test_default_closed_validation_writer_has_positive_v6_readers_first(validation_database,current_draft):
    async def exercise():
        draft,_,request=await ready(validation_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(validation_database,request)
        journal=await read(validation_database,draft)
        assert journal.validation_evidence and journal.guarded_upload and journal.read_evidence
        query=CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with current_session(validation_database).transaction(snapshot=True) as tx:snapshot=await tx.journal_history_snapshot(query)
        assert snapshot.contract_version=='company-tax-source-v6'
        assert project_company_tax_source(query,snapshot).history_coverage.status=='complete'
    asyncio.run(exercise())


def test_only_exact_bound_clean_file_pair_can_commit_one_start(validation_database,current_draft):
    enable_validation(validation_database)
    async def exercise():
        draft,_,request=await ready(validation_database,current_draft)
        changed=replace(request,validation_prerequisite=replace(request.validation_prerequisite,
            envelope_read=replace(request.validation_prerequisite.envelope_read,event_sha256='a'*64)))
        with pytest.raises(CompanyTaxError):await append(validation_database,changed)
        first=await append(validation_database,request);second=await append(validation_database,request)
        assert first.inserted and not second.inserted and first.event==second.event
        assert (await read(validation_database,draft)).events[-1].value==request
    asyncio.run(exercise())


@pytest.mark.parametrize('status',['KJOERER','FERDIG','malformed','float','exponent','huge-extra','double-bom'])
def test_known_status_and_exact_result_are_linked_without_promoting_unknown_status(validation_database,current_draft,status):
    enable_validation(validation_database)
    async def exercise():
        draft,approval,request=await ready(validation_database,current_draft)
        await append(validation_database,request);await append(validation_database,completion(draft,approval,request))
        bodies={
            'malformed':b'{"jobbStatus":"FERDIG","jobbId":[],"forrigeStatus":"KJOERER","sekunderSidenOpprettelse":10,"sekunderSidenEndring":1}',
            'float':b'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":10.0,"sekunderSidenEndring":1}',
            'exponent':b'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":1e1,"sekunderSidenEndring":1}',
            'double-bom':b'\xef\xbb\xbf\xef\xbb\xbf{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":10,"sekunderSidenEndring":1}',
            'huge-extra':b'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":10,"sekunderSidenEndring":1,"unhandled":1e200000}',
        }
        job=job_read(draft,approval,request,status=status,body=bodies.get(status))
        first=await append(validation_database,job);again=await append(validation_database,replace(job,observed_at=now()))
        assert first.inserted and first.event==again.event and not again.inserted
        result=result_read(draft,approval,request,job)
        if status in ('FERDIG','huge-extra'):
            stored=await append(validation_database,result)
            assert stored.inserted and stored.event.value.original.raw_bytes==result.original.raw_bytes
            assert not (await append(validation_database,replace(result,observed_at=now()))).inserted
            journal=await read(validation_database,draft)
            assert journal.events[-1].value.inspect(PinnedTaxValidationResponseSchemas()).result_code.value=='validertOK'
            assert journal.progress.mutation_kind is TaxMutationKind.START_VALIDATION and journal.progress.status=='mutation_completed'
        else:
            with pytest.raises(CompanyTaxError):await append(validation_database,result)
    asyncio.run(exercise())


def test_known_start_result_survives_revocation_but_rejects_noncreated_response(validation_database,current_draft):
    enable_validation(validation_database)
    async def exercise():
        draft,approval,request=await ready(validation_database,current_draft);await append(validation_database,request)
        result=completion(draft,approval,request)
        wrong=replace(result,response_base64=base64.b64encode(json.dumps({'jobbId':JOB,'jobbStatus':'FERDIG'}).encode()).decode())
        with pytest.raises(CompanyTaxError):await append(validation_database,wrong)
        with psycopg.connect(**validation_database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        enable_validation(validation_database,False);enable(validation_database,False)
        try:
            stored=await append(validation_database,result,fresh=False)
            assert stored.inserted and (await append(validation_database,result,fresh=False)).event==stored.event
        finally:
            with psycopg.connect(**validation_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
            enable_validation(validation_database);enable(validation_database)
        assert (await read(validation_database,draft)).events[-1].value==result
    asyncio.run(exercise())


def test_validation_containment_fences_an_intent_already_waiting_on_company_lock(validation_database,current_draft):
    enable_validation(validation_database)
    async def exercise():
        draft,_,request=await ready(validation_database,current_draft)
        with psycopg.connect(**validation_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(append(validation_database,request))
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**validation_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**validation_database,user='postgres',autocommit=True) as db:db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert not any(event.slot=='intent:start_validation' for event in (await read(validation_database,draft)).events)
            finally:
                blocker.rollback()
                if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                enable_validation(validation_database)
    asyncio.run(exercise())


def test_bom_start_completion_preserves_exact_original_and_known_job_id(validation_database,current_draft):
    enable_validation(validation_database)
    async def exercise():
        draft,approval,request=await ready(validation_database,current_draft);await append(validation_database,request)
        raw=b'\xef\xbb\xbf \n'+json.dumps({'jobbId':JOB,'jobbStatus':'OPPRETTET'}).encode()+b'\n'
        result=complete_tax_delivery_mutation(request,approval,draft,response_bytes=raw,observed_at=now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        stored=await append(validation_database,result)
        assert stored.inserted and stored.event.value.response_bytes==raw
        assert (await read(validation_database,draft)).events[-1].value.result['jobId']==JOB
    asyncio.run(exercise())
