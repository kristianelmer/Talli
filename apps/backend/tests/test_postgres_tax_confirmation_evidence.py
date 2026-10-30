"""Owned PG17 confirmation prerequisites, exact acknowledgments and read proof."""
import asyncio
import base64
from dataclasses import replace
import hashlib
import json

import psycopg
import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxMutationKind,TaxDeliveryProcessAcknowledgment,
    TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryConfirmationReadEvidence,
    bind_tax_delivery_confirmation_prerequisite,bind_tax_delivery_validation_prerequisite,
    build_tax_delivery_mutation_request,reconcile_tax_delivery_confirmation,project_company_tax_source,
)
from test_postgres_tax_validation_evidence import (
    database,draft_database,current_database,current_draft,events_database,observation_database,upload_database,
    validation_database,ready,completion,job_read,result_read,enable_validation,now,
)
from test_postgres_tax_current_draft import current_session
from test_postgres_tax_delivery_events import append,read
from test_postgres_tax_delivery_observations import ROOT
from test_postgres_tax_guarded_upload import file_reads
from test_company_tax_calculated_schemas import documents,result as calculated_result
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft

pytestmark=pytest.mark.company_tax_database
MIGRATION='20261026162340_company_tax_confirmation_evidence_v1.sql'


@pytest.fixture(scope='module')
def confirmation_database(validation_database):
    with psycopg.connect(**validation_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.confirmation_evidence_enabled_v1()').fetchone()==(False,)
        for role in ('company_tax_filing_workflow_executor','anon','authenticated','service_role'):
            for function in ('assert_confirmation_file_v1(jsonb,jsonb,jsonb,text,text)','assert_confirmation_calculated_v1(jsonb,jsonb)'):
                assert db.execute('select has_function_privilege(%s,%s,%s)',(role,'company_tax_filing.'+function,'EXECUTE')).fetchone()==(False,)
    return validation_database


def enable_confirmation(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.confirmation_evidence_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


def process_reads(draft,approval,*,task='data',element='Task_1',flow=1):
    instance,envelope=file_reads(draft,approval);raw=json.loads(instance.original.raw_bytes)
    raw['process']['currentTask']|={'altinnTaskType':task,'elementId':element,'flow':flow};raw['data'][0]['fileScanResult']='Clean'
    instance=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()),observed_at=now())
    envelope=replace(envelope,instance_evidence_sha256=instance.evidence_sha256,observed_at=now())
    return instance,envelope


async def confirmation_ready(database,draft):
    enable_validation(database)
    draft,approval,start_request=await ready(database,draft)
    await append(database,start_request);started=completion(draft,approval,start_request);await append(database,started)
    began=now();job=job_read(draft,approval,start_request);first_job=(await append(database,job)).event.value
    result=result_read(draft,approval,start_request,job)
    result=replace(result,original=calculated_result(documents(draft)),observed_at=now())
    first_result=(await append(database,result)).event.value
    file_began=now();instance,envelope=process_reads(draft,approval)
    first_instance=(await append(database,instance)).event.value;first_envelope=(await append(database,envelope)).event.value
    clean=bind_tax_delivery_validation_prerequisite(approval,draft,retained_instance=first_instance,retained_envelope=first_envelope,
        fresh_instance=instance,fresh_envelope=envelope,observed_from=file_began,observed_until=now())
    proof=bind_tax_delivery_confirmation_prerequisite(approval,draft,start_request,started,
        retained_job=first_job,retained_result=first_result,fresh_job=job,fresh_result=result,
        calculated=PinnedTax2025CalculatedSchemas().inspect(result.original,draft=draft),clean_file=clean,
        retained_instance=first_instance,retained_envelope=first_envelope,observed_from=began,observed_until=now())
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.PREPARE_CONFIRMATION,
        target_instance=proof.instance_id,confirmation_prerequisite=proof)
    return draft,approval,request


def acknowledgment(draft,approval,request,raw=b'\xef\xbb\xbf {"currentTask":{"altinnTaskType":"confirmation"}}\n'):
    return TaxDeliveryProcessAcknowledgment(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
        draft.envelope.source.organization_number,request.target_instance,request.sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.PROCESS_RESPONSE,base64.b64encode(raw).decode(),'application/json',200),now())


async def append_raw(database,value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False);digest=hashlib.sha256(raw.encode()).hexdigest()
    async with current_session(database).transaction() as tx:
        return await tx._delivery_row('select company_tax_filing.append_delivery_confirmation_event_v1(%s,%s,%s) as result',
            (raw,digest,str(ACTOR.subject)))


def test_positive_v7_readers_exist_before_default_closed_confirmation_intents(confirmation_database,current_draft):
    async def exercise():
        draft,_,request=await confirmation_ready(confirmation_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(confirmation_database,request)
        journal=await read(confirmation_database,draft)
        assert journal.confirmation_evidence and journal.validation_evidence
        query=CompanyTaxSourceQuery(COMPANY,draft.envelope.source.income_year,ACTOR)
        async with current_session(confirmation_database).transaction(snapshot=True) as tx:snapshot=await tx.journal_history_snapshot(query)
        assert snapshot.contract_version=='company-tax-source-v7'
        assert project_company_tax_source(query,snapshot).history_coverage.status=='complete'
    asyncio.run(exercise())


def test_exact_acknowledgment_stays_uncertain_until_complete_confirmation_read_proof(confirmation_database,current_draft):
    enable_confirmation(confirmation_database)
    async def exercise():
        draft,approval,request=await confirmation_ready(confirmation_database,current_draft)
        assert (await append(confirmation_database,request)).inserted
        ack=acknowledgment(draft,approval,request,raw=b'\xef\xbb\xbf not even JSON\n')
        assert (await append(confirmation_database,ack)).inserted
        journal=await read(confirmation_database,draft)
        assert journal.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION).status=='uncertain'
        instance,envelope=process_reads(draft,approval,task='confirmation',element='Task_2',flow=2)
        completed=reconcile_tax_delivery_confirmation(request,approval,draft,
            evidence=TaxDeliveryConfirmationReadEvidence(instance,envelope),observed_at=now())
        assert (await append(confirmation_database,completed)).inserted
        journal=await read(confirmation_database,draft)
        assert journal.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION).status=='mutation_completed'
        assert next(row.value for row in journal.events if row.slot=='acknowledgment:prepare_confirmation').original.raw_bytes==ack.original.raw_bytes
        assert next(row.value for row in journal.events if row.slot=='completion:prepare_confirmation')==completed
        assert not (await append(confirmation_database,completed)).inserted
    asyncio.run(exercise())


def test_known_acknowledgment_and_complete_read_result_survive_revocation_and_containment(confirmation_database,current_draft):
    enable_confirmation(confirmation_database)
    async def exercise():
        draft,approval,request=await confirmation_ready(confirmation_database,current_draft);await append(confirmation_database,request)
        ack=acknowledgment(draft,approval,request)
        instance,envelope=process_reads(draft,approval,task='confirmation',element='Task_2',flow=2)
        completed=reconcile_tax_delivery_confirmation(request,approval,draft,
            evidence=TaxDeliveryConfirmationReadEvidence(instance,envelope),observed_at=now())
        with psycopg.connect(**confirmation_database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        try:
            assert (await append(confirmation_database,ack,fresh=False)).inserted
            assert (await append(confirmation_database,completed,fresh=False)).inserted
            assert not (await append(confirmation_database,completed,fresh=False)).inserted
        finally:
            with psycopg.connect(**confirmation_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing',(str(COMPANY),str(ACTOR.subject)))
            enable_confirmation(confirmation_database)
        assert (await read(confirmation_database,draft)).events[-1].value==completed
    asyncio.run(exercise())


@pytest.mark.parametrize('defect',['derived-result','derived-count','derived-document','wrong-pin','wrong-party',
    'foreign-reference','wrong-stage','unapproved-bytes'])
def test_storage_does_not_trust_altered_projection_scope_or_original_references(confirmation_database,current_draft,defect):
    enable_confirmation(confirmation_database)
    async def exercise():
        draft,_,request=await confirmation_ready(confirmation_database,current_draft);value=json.loads(request.canonical_json)
        proof=value['request']['confirmation_prerequisite'];calculated=proof['calculated']
        if defect=='derived-result':calculated['response']['result_code']='validertMedFeil'
        elif defect=='derived-count':calculated['response']['guidance_count']=1
        elif defect=='derived-document':calculated['response']['calculated_documents'][0]['body_base64']=base64.b64encode(b'<different/>').decode()
        elif defect=='wrong-pin':calculated['schema_sha256']='d'*64
        elif defect=='wrong-party':calculated['party_number']='999999'
        elif defect=='foreign-reference':proof['result_read']['event_sha256']='d'*64
        elif defect=='wrong-stage':proof['clean_file']['instance_read']['event_sha256']='d'*64
        else:proof['envelope_sha256']='d'*64
        with pytest.raises(CompanyTaxError):await append_raw(confirmation_database,value)
        assert not any(event.slot=='intent:prepare_confirmation' for event in (await read(confirmation_database,draft)).events)
    asyncio.run(exercise())


def test_confirmation_containment_is_rechecked_after_waiting_for_company_lock(confirmation_database,current_draft):
    enable_confirmation(confirmation_database)
    async def exercise():
        draft,_,request=await confirmation_ready(confirmation_database,current_draft)
        with psycopg.connect(**confirmation_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(append(confirmation_database,request))
            try:
                waiting=False
                for _ in range(100):
                    with psycopg.connect(**confirmation_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory')").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**confirmation_database,user='postgres',autocommit=True) as db:
                    db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(CompanyTaxError):await task
                assert not any(event.slot=='intent:prepare_confirmation' for event in (await read(confirmation_database,draft)).events)
            finally:
                blocker.rollback()
                if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                enable_confirmation(confirmation_database)
    asyncio.run(exercise())


@pytest.mark.parametrize('defect',['float-flow','exponent-flow','null-observation'])
def test_post_transition_originals_need_exact_integer_flow_and_known_read_time(confirmation_database,current_draft,defect):
    enable_confirmation(confirmation_database)
    async def exercise():
        draft,approval,request=await confirmation_ready(confirmation_database,current_draft);await append(confirmation_database,request)
        instance,envelope=process_reads(draft,approval,task='confirmation',element='Task_2',flow=2)
        completion=reconcile_tax_delivery_confirmation(request,approval,draft,
            evidence=TaxDeliveryConfirmationReadEvidence(instance,envelope),observed_at=now())
        value=json.loads(completion.canonical_json);proof=value['completion']['confirmation_read_evidence']
        metadata=json.loads(proof['instance_canonical_json']);body=metadata['observation']
        if defect=='null-observation':body['observed_at']['value']=None
        else:
            raw=base64.b64decode(body['original']['body_base64'])
            changed=raw.replace(b'"flow": 2',b'"flow": 2.0' if defect=='float-flow' else b'"flow": 2e0')
            assert changed!=raw;body['original']['body_base64']=base64.b64encode(changed).decode()
        identity=hashlib.sha256(json.dumps(['tax-instance-read-identity-v1',draft.filing_id,str(COMPANY),2025,str(ACTOR.subject),
            approval.sha256,draft.envelope.source.organization_number,instance.instance_id,
            hashlib.sha256(base64.b64decode(body['original']['body_base64'])).hexdigest()],separators=(',',':')).encode()).hexdigest()
        proof['instance_canonical_json']=json.dumps(metadata,sort_keys=True,separators=(',',':'))
        proof['instance_sha256']=hashlib.sha256(proof['instance_canonical_json'].encode()).hexdigest()
        file=json.loads(proof['envelope_canonical_json']);file['observation']['instance_evidence_sha256']=identity
        proof['envelope_canonical_json']=json.dumps(file,sort_keys=True,separators=(',',':'))
        proof['envelope_sha256']=hashlib.sha256(proof['envelope_canonical_json'].encode()).hexdigest()
        with pytest.raises(CompanyTaxError):await append_raw(confirmation_database,value)
        assert not any(event.slot=='completion:prepare_confirmation' for event in (await read(confirmation_database,draft)).events)
    asyncio.run(exercise())
