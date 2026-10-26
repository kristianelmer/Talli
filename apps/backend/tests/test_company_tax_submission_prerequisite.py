"""Explicit reviewed-content commitment and known submission read proofs."""
import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxMutationKind,TaxDeliveryOriginalPurpose,TaxDeliveryReadOriginal,TaxDeliveryOwnerConfirmation,
    confirm_tax_delivery_owner_review,TaxDeliverySubmissionPrerequisite,bind_tax_delivery_submission_prerequisite,
    TaxDeliverySubmissionReadEvidence,TaxDeliveryFeedbackObservation,decode_tax_delivery_feedback_observation,
    build_tax_delivery_mutation_request,reconcile_tax_delivery_submission,complete_tax_delivery_mutation,
    decode_tax_delivery_mutation_request,decode_tax_delivery_mutation_completion,TaxDeliveryCompletionOrigin,
    TaxDeliveryMutationCompletion,TaxDeliveryProcessAcknowledgment,decode_tax_delivery_process_acknowledgment,
    TaxDeliveryInstanceObservation,TaxDeliveryEnvelopeObservation,TaxDeliveryValidationJobObservation,
    TaxDeliveryValidationResultObservation,TaxDeliveryJournal,StoredTaxDeliveryEvent,decode_tax_delivery_event,
    TaxMutationDisposition,TaxMutationRecord,plan_tax_mutation,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_confirmation_workflow import confirmation_workflow
from test_company_tax_delivery_owner_review import prepared

pytestmark=pytest.mark.parametrize('workflow',[80],indirect=True)


async def submission_basis(fixture):
    session,service,_,_,_,clock,*_=fixture
    query=await prepared(fixture);review=await service.owner_review(session,query)
    confirmation=confirm_tax_delivery_owner_review(review,expected_owner_review_sha256=review.sha256,
        documents_confirmed=True,warnings_acknowledged=True)
    events={event.slot:event.value for event in session.events}
    approval=events['review'];draft=session.draft;start=events['intent:start_validation'];started=events['completion:start_validation']
    preparation=events['intent:prepare_confirmation'];completed=events['completion:prepare_confirmation']
    clock[0]=Timestamp(max(clock[0].value,session.events[-1].recorded_at.value)+timedelta(seconds=1));began=service._runtime.now()
    job=await service._authority.observe_validation_job(approval,draft,start,started)
    result=await service._authority.observe_validation_result(approval,draft,start,started,job,schema_sha256=service._response_schemas.schema_sha256)
    instance=await service._authority.observe_instance(approval,draft,events['completion:create_instance'])
    envelope=await service._authority.observe_envelope(approval,draft,events['completion:create_instance'],instance)
    retained=[]
    for value in (job,result,instance,envelope):
        _,first=await service._retain_read(session,query,query,value)
        retained.append(first)
    proof=bind_tax_delivery_submission_prerequisite(approval,draft,preparation,completed,start,started,
        owner_confirmation=confirmation,retained_job=retained[0],retained_result=retained[1],retained_instance=retained[2],retained_envelope=retained[3],
        fresh_job=job,fresh_result=result,fresh_instance=instance,fresh_envelope=envelope,observed_from=began,observed_until=service._runtime.now())
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CONFIRM_SUBMISSION,target_instance=instance.instance_id,submission_prerequisite=proof)
    return dict(session=session,service=service,review=review,confirmation=confirmation,approval=approval,draft=draft,
        preparation=preparation,prepared=completed,start=start,started=started,job=job,result=result,instance=instance,envelope=envelope,
        retained=retained,proof=proof,request=request,now=service._runtime.now())


def metadata(basis,*,task='feedback',element='Task_3',flow=1,terminal=False,receipt=False):
    original=json.loads(basis['instance'].original.raw_bytes)
    original['process']['currentTask']={'altinnTaskType':task,'elementId':element,'flow':flow}
    if terminal:
        original['process']['currentTask']=None;original['process']['ended']=basis['now'].value.isoformat()
        original['status']={'isArchived':True,'archived':basis['now'].value.isoformat()}
    raw=b'\xef\xbb\xbf <opaque-receipt>unclassified</opaque-receipt>\n'
    if receipt:original['data'].append({'id':'00000000-0000-4000-8000-000000009999','dataType':'tilbakemelding',
        'fileScanResult':'Clean','contentType':'text/xml','size':len(raw)})
    instance=replace(basis['instance'],original=replace(basis['instance'].original,
        body_base64=base64.b64encode(json.dumps(original).encode()).decode()),observed_at=basis['now'])
    envelope=replace(basis['envelope'],instance_evidence_sha256=instance.evidence_sha256,observed_at=basis['now'])
    feedback=None if not receipt else TaxDeliveryFeedbackObservation(instance.filing_id,instance.company_id,instance.income_year,
        instance.approved_by,instance.approval_sha256,instance.organization_number,instance.instance_id,
        original['data'][-1]['id'],instance.evidence_sha256,TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.FEEDBACK,
            base64.b64encode(raw).decode(),'text/xml',200),instance.observed_at)
    return instance,envelope,feedback


def test_explicit_owner_commitment_and_v5_request_preserve_exact_known_preparation(confirmation_workflow):
    async def exercise():
        b=await submission_basis(confirmation_workflow);request=b['request'];proof=b['proof']
        assert request.body_bytes==b'' and json.loads(request.canonical_json)['version'].endswith('-v5')
        assert decode_tax_delivery_mutation_request(request.canonical_json,request.sha256)==request
        assert proof.owner_confirmation.owner_review_sha256==b['review'].sha256
        assert proof.owner_confirmation.response_original_sha256==b['result'].original.sha256
        request.assert_draft(b['approval'],b['draft'])
        for documents,warnings in [(False,True),(True,False),(1,True),(True,'true')]:
            with pytest.raises(ValueError):confirm_tax_delivery_owner_review(b['review'],expected_owner_review_sha256=b['review'].sha256,
                documents_confirmed=documents,warnings_acknowledged=warnings)
        with pytest.raises(ValueError):confirm_tax_delivery_owner_review(b['review'],expected_owner_review_sha256='d'*64,
            documents_confirmed=True,warnings_acknowledged=True)
        with pytest.raises(ValueError):replace(request,submission_prerequisite=None)
        with pytest.raises(ValueError):replace(request,body_base64='e30=')
        with pytest.raises(ValueError):replace(request,kind=TaxMutationKind.PREPARE_CONFIRMATION)
        with pytest.raises(ValueError):proof.assert_current(Timestamp(b['now'].value+timedelta(seconds=31)))
        record=TaxMutationRecord(request.intent(b['approval']),'uncertain')
        assert plan_tax_mutation(record.intent,record) is TaxMutationDisposition.RECONCILE
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['response','pin','preparation','metadata','file','freshness'])
def test_submission_proof_rejects_changed_review_preparation_or_fresh_read_originals(confirmation_workflow,change):
    async def exercise():
        b=await submission_basis(confirmation_workflow);proof=b['proof'];job,result,instance,envelope=b['retained']
        if change=='response':result=replace(result,original=replace(result.original,body_base64=base64.b64encode(result.original.raw_bytes+b'\n').decode()))
        elif change=='pin':result=replace(result,schema_sha256='d'*64)
        elif change=='preparation':proof=replace(proof,owner_confirmation=replace(proof.owner_confirmation,preparation_result_sha256='d'*64))
        elif change=='metadata':instance=metadata(b,task='confirmation',element='Task_2Revisor')[0]
        elif change=='file':envelope=replace(envelope,original=replace(envelope.original,body_base64='Y2hhbmdlZA=='))
        else:proof=replace(proof,job_read=replace(proof.job_read,event_sha256='d'*64))
        with pytest.raises(ValueError):proof.assert_retained(b['approval'],b['draft'],b['preparation'],b['prepared'],
            b['start'],b['started'],job,result,instance,envelope)
    asyncio.run(exercise())


@pytest.mark.parametrize('terminal',[False,True])
def test_submission_completion_requires_complete_known_reads_and_receipt_for_terminal_recovery(confirmation_workflow,terminal):
    async def exercise():
        b=await submission_basis(confirmation_workflow);instance,envelope,feedback=metadata(b,terminal=terminal,receipt=terminal)
        proof=TaxDeliverySubmissionReadEvidence(instance,envelope,feedback)
        completion=reconcile_tax_delivery_submission(b['request'],b['approval'],b['draft'],evidence=proof,observed_at=b['now'])
        assert json.loads(completion.canonical_json)['version'].endswith('-v4')
        assert decode_tax_delivery_mutation_completion(completion.canonical_json,completion.sha256)==completion
        assert completion.response_bytes==instance.original.raw_bytes
        assert dict(completion.result)=={'instanceId':instance.instance_id,'processTask':'feedback'}
        if terminal:
            assert decode_tax_delivery_feedback_observation(feedback.canonical_json,feedback.sha256)==feedback
            assert feedback.original.raw_bytes.startswith(b'\xef\xbb\xbf')
            assert not any(hasattr(feedback,key) for key in ('accepted','assessed','ready','outcome'))
            with pytest.raises(ValueError):TaxDeliverySubmissionReadEvidence(instance,envelope)
        with pytest.raises(ValueError):complete_tax_delivery_mutation(b['request'],b['approval'],b['draft'],
            response_bytes=instance.original.raw_bytes,observed_at=b['now'],origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        assert plan_tax_mutation(completion.intent,TaxMutationRecord(completion.intent,'completed',completion.result)) is TaxMutationDisposition.REPLAY
    asyncio.run(exercise())


@pytest.mark.parametrize('task,element,flow',[('confirmation','Task_2',1),('confirmation','Task_2Revisor',1),('data','Task_1',1),
    ('feedback','Task_3',1.0),('feedback','Task_unknown',1),('feedback','Task_3',None)])
def test_other_or_ambiguous_process_stages_cannot_resolve_submission(confirmation_workflow,task,element,flow):
    async def exercise():
        b=await submission_basis(confirmation_workflow);instance,envelope,_=metadata(b,task=task,element=element,flow=flow)
        with pytest.raises(ValueError):TaxDeliverySubmissionReadEvidence(instance,envelope)
    asyncio.run(exercise())


def test_new_submission_codecs_need_positive_reader_and_old_ack_bytes_stay_unchanged(confirmation_workflow):
    async def exercise():
        b=await submission_basis(confirmation_workflow);request=b['request'];flags=dict(guarded_upload=True,validation_evidence=True,confirmation_evidence=True)
        with pytest.raises(ValueError):decode_tax_delivery_event(request.canonical_json,request.sha256,b['now'],b['approval'].approved_by,**flags)
        assert decode_tax_delivery_event(request.canonical_json,request.sha256,b['now'],b['approval'].approved_by,
            **flags,submission_evidence=True).value==request
        old=next(event.value for event in b['session'].events if event.slot=='acknowledgment:prepare_confirmation')
        assert 'kind' not in json.loads(old.canonical_json)['acknowledgment']
        ack=replace(old,kind=TaxMutationKind.CONFIRM_SUBMISSION,request_sha256=request.sha256,observed_at=b['now'])
        ack.assert_request(request,b['approval'],b['draft'])
        assert json.loads(ack.canonical_json)['version'].endswith('-v2')
        assert decode_tax_delivery_process_acknowledgment(ack.canonical_json,ack.sha256)==ack
        assert StoredTaxDeliveryEvent(ack,b['now'],b['approval'].approved_by).slot=='acknowledgment:confirm_submission'
        events=tuple(b['session'].events)+(StoredTaxDeliveryEvent(request,b['now'],b['approval'].approved_by),)
        with pytest.raises(ValueError):TaxDeliveryJournal(b['draft'],events,True,True,True,True)
        journal=TaxDeliveryJournal(b['draft'],events,True,True,True,True,True)
        assert journal.plan(request) is TaxMutationDisposition.RECONCILE
    asyncio.run(exercise())
