"""Known job/status/result binding retains uncertainty and exact originals."""
import base64
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation,TaxValidationJobStatus,
    TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryCompletionOrigin,TaxMutationKind,
    bind_tax_delivery_validation_prerequisite,build_tax_delivery_mutation_request,complete_tax_delivery_mutation,
    decode_tax_delivery_validation_job_observation,decode_tax_delivery_validation_result_observation,decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_validation_prerequisite import proof
from test_company_tax_validation_response_schemas import xml

JOB='storeDokument-known-v1'


def original(raw,purpose=TaxDeliveryOriginalPurpose.VALIDATION_JOB):
    return TaxDeliveryReadOriginal(purpose,base64.b64encode(raw).decode(),
        'application/json' if purpose is TaxDeliveryOriginalPurpose.VALIDATION_JOB else 'application/xml',200)


def started_job(review_basis,*,status='FERDIG',body=None):
    approval,draft,kwargs=proof(review_basis)
    prerequisite=bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.START_VALIDATION,
        target_instance=prerequisite.instance_id,validation_prerequisite=prerequisite)
    started=complete_tax_delivery_mutation(request,approval,draft,
        response_bytes=json.dumps({'jobbId':JOB,'jobbStatus':'OPPRETTET'}).encode(),
        observed_at=kwargs['observed_until'],origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    raw=b'\xef\xbb\xbf'+json.dumps({'jobbStatus':status,'forrigeStatus':'KJOERER',
        'sekunderSidenOpprettelse':10,'sekunderSidenEndring':9}).encode()+b'\n' if body is None else body
    value=TaxDeliveryValidationJobObservation(draft.filing_id,approval.company_id,approval.income_year,approval.approved_by,
        approval.sha256,draft.envelope.source.organization_number,request.target_instance,JOB,request.sha256,
        original(raw),Timestamp(started.observed_at.value+timedelta(seconds=1)))
    return value,approval,draft,request,started


def result_observation(review_basis,*,status='FERDIG',body=None):
    job,approval,draft,request,started=started_job(review_basis,status=status)
    validator=PinnedTaxValidationResponseSchemas()
    value=TaxDeliveryValidationResultObservation(draft.filing_id,approval.company_id,approval.income_year,approval.approved_by,
        approval.sha256,draft.envelope.source.organization_number,request.target_instance,JOB,request.sha256,
        job.evidence_sha256,validator.schema_sha256,
        original(b'\xef\xbb\xbf'+xml()+b'\n' if body is None else body,TaxDeliveryOriginalPurpose.VALIDATION_RESULT),
        Timestamp(job.observed_at.value+timedelta(seconds=1)))
    return value,job,approval,draft,request,started,validator


@pytest.mark.parametrize('status',['NY','KJOERER','VENTER','AVBRUTT','FEILET','FERDIG'])
def test_documented_statuses_are_known_without_becoming_validation_or_submission_success(review_basis,status):
    value,approval,draft,request,started=started_job(review_basis,status=status)
    value.assert_started(approval,draft,request,started)
    assert value.inspection.known and value.inspection.status.value==status
    assert value.inspection.seconds_since_creation==10 and value.inspection.seconds_since_change==9
    assert decode_tax_delivery_validation_job_observation(value.canonical_json,value.sha256)==value
    assert value.original.raw_bytes.startswith(b'\xef\xbb\xbf') and value.original.raw_bytes.endswith(b'\n')
    later=replace(value,observed_at=Timestamp(value.observed_at.value+timedelta(seconds=1)))
    assert later.evidence_sha256==value.evidence_sha256 and later.sha256!=value.sha256


@pytest.mark.parametrize('defect',['empty','duplicate','unknown-status','created-only','missing-field','boolean-age','negative',
    'change-exceeds-age','too-large-age','malformed-job-id','malformed-json'])
def test_malformed_or_ambiguous_status_remains_unknown_not_finished(review_basis,defect):
    raw={'jobbStatus':'FERDIG','forrigeStatus':'KJOERER','sekunderSidenOpprettelse':10,'sekunderSidenEndring':9}
    if defect=='empty':raw={}
    elif defect=='unknown-status':raw['jobbStatus']='submitted'
    elif defect=='created-only':raw['jobbStatus']='OPPRETTET'
    elif defect=='missing-field':raw.pop('sekunderSidenOpprettelse')
    elif defect=='boolean-age':raw['sekunderSidenOpprettelse']=True
    elif defect=='negative':raw['sekunderSidenEndring']=-1
    elif defect=='change-exceeds-age':raw['sekunderSidenEndring']=11
    elif defect=='too-large-age':raw['sekunderSidenOpprettelse']=2147483648
    elif defect=='malformed-job-id':raw['jobbId']=[]
    encoded=json.dumps(raw).encode()
    if defect=='duplicate':encoded=encoded[:-1]+b',"jobbStatus":"FERDIG"}'
    elif defect=='malformed-json':encoded=b'{'
    value,*_=started_job(review_basis,body=encoded)
    assert not value.inspection.known and value.inspection.status is None
    assert value.original.raw_bytes==encoded
    assert decode_tax_delivery_validation_job_observation(value.canonical_json,value.sha256)==value


def test_recognizable_foreign_job_is_rejected_and_unknown_create_cannot_invent_one(review_basis):
    with pytest.raises(ValueError):started_job(review_basis,body=b'{"jobbId":"another-known-job"}')
    value,approval,draft,request,started=started_job(review_basis)
    with pytest.raises(ValueError):value.assert_started(approval,draft,request,None)
    with pytest.raises(ValueError):replace(value,job_id='another-known-job').assert_started(approval,draft,request,started)
    for unsafe in ('../other','https://example.test/private','job?id=other','a/b','%2e%2e',''):
        with pytest.raises(ValueError):replace(value,job_id=unsafe)


@pytest.mark.parametrize('status',['NY','KJOERER','VENTER','AVBRUTT','FEILET','FERDIG'])
def test_result_xml_needs_exact_finished_known_job_predecessor(review_basis,status):
    value,job,approval,draft,request,started,validator=result_observation(review_basis,status=status)
    if status=='FERDIG':
        value.assert_status(approval,draft,request,started,job)
        inspected=value.inspect(validator)
        assert inspected.result_code.value=='validertOK'
        assert inspected.original_sha256==value.original.sha256
        assert decode_tax_delivery_validation_result_observation(value.canonical_json,value.sha256)==value
    else:
        with pytest.raises(ValueError):value.assert_status(approval,draft,request,started,job)


@pytest.mark.parametrize('defect',['status-reference','request-reference','job','scope','time','schema','malformed-xml'])
def test_a_valid_result_code_cannot_override_scope_reference_pin_or_time_drift(review_basis,defect):
    value,job,approval,draft,request,started,validator=result_observation(review_basis)
    if defect=='status-reference':value=replace(value,job_status_evidence_sha256='a'*64)
    elif defect=='request-reference':value=replace(value,start_request_sha256='a'*64)
    elif defect=='job':value=replace(value,job_id='another-known-job')
    elif defect=='scope':value=replace(value,approval_sha256='a'*64)
    elif defect=='time':value=replace(value,observed_at=Timestamp(job.observed_at.value-timedelta(microseconds=1)))
    elif defect=='schema':value=replace(value,schema_sha256='a'*64)
    else:value=replace(value,original=original(b'<unknown/>',TaxDeliveryOriginalPurpose.VALIDATION_RESULT))
    if defect in ('schema','malformed-xml'):
        with pytest.raises(Exception):value.inspect(validator)
    else:
        with pytest.raises(ValueError):value.assert_status(approval,draft,request,started,job)


def test_current_journal_stays_closed_to_both_new_read_codecs(review_basis):
    result,job,approval,*_=result_observation(review_basis)
    for value in (job,result):
        with pytest.raises(ValueError):decode_tax_delivery_event(value.canonical_json,value.sha256,value.observed_at,approval.approved_by,guarded_upload=True)
