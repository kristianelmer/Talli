"""Owned PG17 storage for explicit owner-confirmed submission and exact reads."""
import asyncio
import base64
from dataclasses import replace
from hashlib import sha256
import json
import concurrent.futures
import time
from datetime import timedelta

import psycopg
import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxMutationKind,TaxDeliveryConfirmationReadEvidence,reconcile_tax_delivery_confirmation,
    build_tax_delivery_owner_review,confirm_tax_delivery_owner_review,bind_tax_delivery_submission_prerequisite,
    build_tax_delivery_mutation_request,TaxDeliverySubmissionReadEvidence,reconcile_tax_delivery_submission,
    TaxDeliveryFeedbackObservation,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryProcessAcknowledgment,
)
from test_postgres_tax_confirmation_evidence import (
    database,draft_database,current_database,current_draft,events_database,observation_database,upload_database,
    validation_database,confirmation_database,confirmation_ready,process_reads,enable_confirmation,now,
)
from test_postgres_tax_current_draft import current_session
from test_postgres_tax_delivery_events import append,read
from test_postgres_tax_delivery_observations import ROOT
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft

pytestmark=pytest.mark.company_tax_database
MIGRATION='20261026180325_company_tax_submission_evidence_v1.sql'


@pytest.fixture(scope='module')
def submission_database(confirmation_database):
    with psycopg.connect(**confirmation_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall();db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.submission_evidence_enabled_v1()').fetchone()==(False,)
        functions=('submission_embedded_original_v1(text,text,text)','submission_feedback_bytes_v1(jsonb)',
            'assert_submission_feedback_v1(jsonb,jsonb,jsonb)','assert_submission_result_v1(jsonb,jsonb,jsonb,jsonb)')
        for role in ('company_tax_filing_workflow_executor','anon','authenticated','service_role'):
            for function in functions:
                assert db.execute('select has_function_privilege(%s,%s,%s)',(role,'company_tax_filing.'+function,'EXECUTE')).fetchone()==(False,)
    return confirmation_database


def enable_submission(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.submission_evidence_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


def feedback_reads(draft,approval,receipt=b'\xef\xbb\xbf <opaque-receipt/>\n\xff'):
    instance,envelope=process_reads(draft,approval,task='feedback',element='Task_3',flow=3)
    raw=json.loads(instance.original.raw_bytes)
    raw['process']['currentTask']=None;raw['process']['ended']=now().value.isoformat()
    raw['status']={'isArchived':True,'archived':now().value.isoformat()}
    raw['data'].append({'id':'00000000-0000-4000-8000-000000009999','dataType':'tilbakemelding',
        'fileScanResult':'Clean','contentType':'text/xml','size':len(receipt)})
    instance=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()),observed_at=now())
    envelope=replace(envelope,instance_evidence_sha256=instance.evidence_sha256,observed_at=now())
    feedback=TaxDeliveryFeedbackObservation(instance.filing_id,instance.company_id,instance.income_year,instance.approved_by,
        instance.approval_sha256,instance.organization_number,instance.instance_id,raw['data'][-1]['id'],instance.evidence_sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.FEEDBACK,base64.b64encode(receipt).decode(),'text/xml',200),now())
    return instance,envelope,feedback


async def submission_ready(database,draft):
    enable_confirmation(database)
    draft,approval,preparation=await confirmation_ready(database,draft);await append(database,preparation)
    instance,envelope=process_reads(draft,approval,task='confirmation',element='Task_2',flow=2)
    prepared=reconcile_tax_delivery_confirmation(preparation,approval,draft,
        evidence=TaxDeliveryConfirmationReadEvidence(instance,envelope),observed_at=now())
    await append(database,prepared)
    journal=await read(database,draft)
    start=next(event.value for event in journal.events if event.slot=='intent:start_validation')
    started=next(event.value for event in journal.events if event.slot=='completion:start_validation')
    first_job=next(event.value for event in journal.events if event.value.sha256==preparation.confirmation_prerequisite.job_read.event_sha256)
    first_result=next(event.value for event in journal.events if event.value.sha256==preparation.confirmation_prerequisite.result_read.event_sha256)
    review=build_tax_delivery_owner_review(approval,draft,preparation,prepared,first_result,
        calculated=PinnedTax2025CalculatedSchemas().review_documents(first_result.original,draft=draft),
        response=PinnedTaxValidationResponseSchemas().review(first_result.original))
    confirmation=confirm_tax_delivery_owner_review(review,expected_owner_review_sha256=review.sha256,documents_confirmed=True,warnings_acknowledged=True)
    began=now();job=replace(first_job,observed_at=now());result=replace(first_result,observed_at=now())
    instance,envelope=process_reads(draft,approval,task='confirmation',element='Task_2',flow=2)
    first_instance=(await append(database,instance)).event.value;first_envelope=(await append(database,envelope)).event.value
    proof=bind_tax_delivery_submission_prerequisite(approval,draft,preparation,prepared,start,started,owner_confirmation=confirmation,
        retained_job=first_job,retained_result=first_result,retained_instance=first_instance,retained_envelope=first_envelope,
        fresh_job=job,fresh_result=result,fresh_instance=instance,fresh_envelope=envelope,observed_from=began,observed_until=now())
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CONFIRM_SUBMISSION,
        target_instance=instance.instance_id,submission_prerequisite=proof)
    return draft,approval,request


async def append_raw(database,value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False);digest=sha256(raw.encode()).hexdigest()
    async with current_session(database).transaction() as tx:
        return await tx._delivery_row('select company_tax_filing.append_delivery_submission_event_v1(%s,%s,%s) as result',
            (raw,digest,str(ACTOR.subject)))


def test_source8_and_journal6_are_positive_before_default_closed_submission_intents(submission_database,current_draft):
    async def exercise():
        draft,_,request=await submission_ready(submission_database,current_draft)
        with pytest.raises(CompanyTaxError):await append(submission_database,request)
        journal=await read(submission_database,draft)
        assert journal.submission_evidence and journal.confirmation_evidence
    asyncio.run(exercise())


@pytest.mark.parametrize('terminal',[False,True])
def test_native_submission_replays_exact_reads_and_terminal_receipt_bytes(submission_database,current_draft,terminal):
    async def exercise():
        draft,approval,request=await submission_ready(submission_database,current_draft);enable_submission(submission_database)
        try:
            first=await append(submission_database,request)
            assert first.inserted and not (await append(submission_database,request)).inserted
            instance,envelope=process_reads(draft,approval,task='feedback',element='Task_3',flow=3);feedback=None
            if terminal:
                instance,envelope,feedback=feedback_reads(draft,approval);receipt=feedback.original.raw_bytes
            complete=reconcile_tax_delivery_submission(request,approval,draft,
                evidence=TaxDeliverySubmissionReadEvidence(instance,envelope,feedback),observed_at=now())
            assert (await append(submission_database,complete)).inserted
            assert not (await append(submission_database,complete)).inserted
            journal=await read(submission_database,draft)
            assert journal.mutation_progress(TaxMutationKind.CONFIRM_SUBMISSION).status=='mutation_completed'
            restored=next(event.value for event in journal.events if event.slot=='completion:confirm_submission')
            assert restored==complete
            if terminal:assert restored.submission_read_evidence.feedback.original.raw_bytes==receipt
        finally:enable_submission(submission_database,False)
    asyncio.run(exercise())


@pytest.mark.parametrize('field',['documents_confirmed','warnings_acknowledged','preparation_result_sha256','response_original_sha256'])
def test_sql_rejects_forged_confirmation_even_with_a_consistently_rehashed_request(submission_database,current_draft,field):
    async def exercise():
        _,_,request=await submission_ready(submission_database,current_draft);enable_submission(submission_database)
        try:
            value=json.loads(request.canonical_json);decision=value['request']['submission_prerequisite']['owner_confirmation']
            decision[field]=False if field in ('documents_confirmed','warnings_acknowledged') else 'd'*64
            with pytest.raises(CompanyTaxError):await append_raw(submission_database,value)
        finally:enable_submission(submission_database,False)
    asyncio.run(exercise())


def test_known_ack_receipt_and_complete_result_survive_revocation_and_containment(submission_database,current_draft):
    async def exercise():
        draft,approval,request=await submission_ready(submission_database,current_draft);enable_submission(submission_database)
        await append(submission_database,request)
        instance,envelope,feedback=feedback_reads(draft,approval)
        await append(submission_database,instance)
        complete=reconcile_tax_delivery_submission(request,approval,draft,
            evidence=TaxDeliverySubmissionReadEvidence(instance,envelope,feedback),observed_at=now())
        ack=TaxDeliveryProcessAcknowledgment(draft.filing_id,COMPANY,draft.envelope.source.income_year,ACTOR,approval.sha256,
            draft.envelope.source.organization_number,request.target_instance,request.sha256,
            TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.PROCESS_RESPONSE,base64.b64encode(b'\xef\xbb\xbf unknown acknowledgment').decode(),
                'application/json',200),now(),TaxMutationKind.CONFIRM_SUBMISSION)
        with psycopg.connect(**submission_database,user='postgres',autocommit=True) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        try:
            assert (await append(submission_database,ack)).inserted
            assert (await append(submission_database,feedback)).inserted
            assert not (await append(submission_database,replace(feedback,observed_at=now()))).inserted
            assert (await append(submission_database,complete)).inserted
            with pytest.raises(CompanyTaxError):await read(submission_database,draft)
        finally:
            with psycopg.connect(**submission_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing',(str(COMPANY),str(ACTOR.subject)))
        journal=await read(submission_database,draft)
        assert journal.submission_evidence and journal.mutation_progress(TaxMutationKind.CONFIRM_SUBMISSION).status=='mutation_completed'
    asyncio.run(exercise())


def test_submission_fence_is_rechecked_after_waiting_for_the_company_lock(submission_database,current_draft):
    _,_,request=asyncio.run(submission_ready(submission_database,current_draft));enable_submission(submission_database)
    with psycopg.connect(**submission_database,user='postgres') as blocker:
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(lambda:asyncio.run(append(submission_database,request)))
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with psycopg.connect(**submission_database,user='postgres',autocommit=True) as db:
                    waiting=db.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like '%append_delivery_submission_event_v1%' and pid<>pg_backend_pid())").fetchone()[0]
                if waiting:break
                time.sleep(.02)
            assert waiting
            enable_submission(submission_database,False);blocker.commit()
            with pytest.raises(CompanyTaxError):pending.result(timeout=10)


@pytest.mark.parametrize('change',['flow-float','flow-exponent','flow-string','auditor','file','metadata-time','terminal-no-receipt','terminal-future'])
def test_sql_rechecks_rehashed_inline_submission_originals(submission_database,current_draft,change):
    async def exercise():
        draft,approval,request=await submission_ready(submission_database,current_draft);enable_submission(submission_database)
        try:
            await append(submission_database,request)
            instance,envelope=process_reads(draft,approval,task='feedback',element='Task_3',flow=3)
            complete=reconcile_tax_delivery_submission(request,approval,draft,
                evidence=TaxDeliverySubmissionReadEvidence(instance,envelope),observed_at=now())
            value=json.loads(complete.canonical_json);proof=value['completion']['submission_read_evidence'];feedback=None
            if change.startswith('terminal'):
                instance,envelope,feedback=feedback_reads(draft,approval)
            metadata=json.loads(instance.original.raw_bytes)
            if change=='flow-float':metadata['process']['currentTask']['flow']=3.0
            elif change=='flow-string':metadata['process']['currentTask']['flow']='3'
            elif change=='auditor':metadata['process']['currentTask']|={'altinnTaskType':'confirmation','elementId':'Task_2Revisor'}
            elif change=='terminal-future':metadata['status']['archived']=(now().value+timedelta(days=1)).isoformat()
            raw=json.dumps(metadata)
            if change=='flow-exponent':raw=raw.replace('"flow": 3','"flow": 3e0')
            instance=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(raw.encode()).decode()))
            envelope=replace(envelope,instance_evidence_sha256=instance.evidence_sha256,observed_at=now())
            if change=='file':envelope=replace(envelope,original=replace(envelope.original,body_base64=base64.b64encode(b'changed').decode()))
            instance_raw=instance.canonical_json
            if change=='metadata-time':
                metadata_value=json.loads(instance_raw);metadata_value['observation']['observed_at']['value']=None
                instance_raw=json.dumps(metadata_value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            proof|={'instance_canonical_json':instance_raw,'instance_sha256':sha256(instance_raw.encode()).hexdigest(),
                'envelope_canonical_json':envelope.canonical_json,'envelope_sha256':envelope.sha256}
            if feedback is not None and change!='terminal-no-receipt':
                feedback=replace(feedback,instance_evidence_sha256=instance.evidence_sha256,observed_at=now())
                proof|={'feedback_canonical_json':feedback.canonical_json,'feedback_sha256':feedback.sha256}
            value['completion']['observed_at']['value']=now().value.isoformat()
            with pytest.raises(CompanyTaxError):await append_raw(submission_database,value)
        finally:enable_submission(submission_database,False)
    asyncio.run(exercise())
