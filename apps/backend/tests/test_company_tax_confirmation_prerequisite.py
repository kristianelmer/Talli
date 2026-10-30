"""A confirmed validation cannot skip fresh exact-file or stage proof."""
import base64
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.modules.company_tax_filing.delivery_confirmation_prerequisite import (
    bind_tax_delivery_confirmation_prerequisite,_decode_confirmation_prerequisite,
)
from talli_backend.modules.company_tax_filing.public import (
    TaxMutationKind,TaxDeliveryReadReference,TaxValidationResultCode,bind_tax_delivery_validation_prerequisite,
    build_tax_delivery_mutation_request,decode_tax_delivery_mutation_request,decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_validation_observations import result_observation
from test_company_tax_delivery_envelope_observation import envelope_read
from test_company_tax_calculated_schemas import documents,result as calculated_result


def prepared(review_basis,*,code='validertOK',before='',after=''):
    draft=review_basis['draft'];body=calculated_result(documents(draft),code=code,before=before,after=after).raw_bytes
    result,job,approval,draft,request,started,_=result_observation(review_basis,body=body)
    envelope,instance,_,_=envelope_read(review_basis,scan='Clean')
    instance=replace(instance,approval_sha256=approval.sha256)
    envelope=replace(envelope,approval_sha256=approval.sha256)
    instance_doc=json.loads(instance.original.raw_bytes);instance_doc['process']['currentTask']|={'elementId':'Task_1','flow':1}
    instance=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(json.dumps(instance_doc).encode()).decode()))
    envelope=replace(envelope,instance_evidence_sha256=instance.evidence_sha256)
    began=Timestamp(result.observed_at.value+timedelta(seconds=1))
    def time(n):return Timestamp(began.value+timedelta(milliseconds=n))
    fresh_job=replace(job,observed_at=time(1));fresh_result=replace(result,observed_at=time(2))
    fresh_instance=replace(instance,observed_at=time(3));fresh_envelope=replace(envelope,observed_at=time(4))
    clean=bind_tax_delivery_validation_prerequisite(approval,draft,retained_instance=instance,retained_envelope=envelope,
        fresh_instance=fresh_instance,fresh_envelope=fresh_envelope,observed_from=time(2),observed_until=time(5))
    calculated=PinnedTax2025CalculatedSchemas().inspect(fresh_result.original,draft=draft)
    kwargs=dict(retained_job=job,retained_result=result,fresh_job=fresh_job,fresh_result=fresh_result,
        calculated=calculated,clean_file=clean,retained_instance=instance,retained_envelope=envelope,
        observed_from=began,observed_until=time(6))
    return approval,draft,request,started,kwargs


def bind(values):
    approval,draft,request,started,kwargs=values
    return bind_tax_delivery_confirmation_prerequisite(approval,draft,request,started,**kwargs)


def test_confirmation_requires_known_job_exact_calculation_and_fresh_approved_clean_file(review_basis):
    values=prepared(review_basis,before='<veiledningEtterKontroll><veiledning><veiledningstype>review</veiledningstype>'
        '</veiledning></veiledningEtterKontroll>');approval,draft,request,started,kwargs=values
    proof=bind(values)
    assert proof.calculated.response.guidance_count==1
    assert proof.envelope_sha256==draft.envelope.envelope_sha256
    assert proof.job_read.event_sha256==kwargs['retained_job'].sha256
    assert proof.job_read.observed_at==kwargs['fresh_job'].observed_at
    proof.assert_retained(approval,draft,request,started,kwargs['retained_job'],kwargs['retained_result'],
        kwargs['retained_instance'],kwargs['retained_envelope'])
    proof.assert_current(Timestamp(proof.observed_from.value+timedelta(seconds=30)))
    for delta in (-1,30.000001):
        with pytest.raises(ValueError):proof.assert_current(Timestamp(proof.observed_from.value+timedelta(seconds=delta)))
    v4=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.PREPARE_CONFIRMATION,
        target_instance=proof.instance_id,confirmation_prerequisite=proof)
    assert v4.body_bytes==b'' and json.loads(v4.canonical_json)['version']=='company-tax-delivery-mutation-request-v4'
    assert decode_tax_delivery_mutation_request(v4.canonical_json,v4.sha256)==v4
    with pytest.raises(ValueError):decode_tax_delivery_event(v4.canonical_json,v4.sha256,proof.observed_until,approval.approved_by,
        guarded_upload=True,validation_evidence=True)
    assert decode_tax_delivery_event(v4.canonical_json,v4.sha256,proof.observed_until,approval.approved_by,
        guarded_upload=True,validation_evidence=True,confirmation_evidence=True).value==v4


@pytest.mark.parametrize('code,before,after',[
    ('validertMedFeil','',''),
    ('validertOK','<avvikVedValidering><avvik><avvikstype>hard-error</avvikstype></avvik></avvikVedValidering>',''),
    ('validertOK','','<aarsakTilValidertMedFeil>hard failure</aarsakTilValidertMedFeil>'),
])
def test_wrapper_success_cannot_clear_hard_errors_or_rejected_validation(review_basis,code,before,after):
    with pytest.raises(ValueError):bind(prepared(review_basis,code=code,before=before,after=after))


@pytest.mark.parametrize('defect',['foreign-job','foreign-result','changed-job','changed-result','wrong-calculated-pin',
    'wrong-response-pin','wrong-calculated-draft','wrong-original','stale-job','stale-result','long-window','reversed-reads',
    'unknown-job','no-known-start','confirmation-task','auditor-task','missing-element','boolean-flow','extra-root','extra-nested'])
def test_no_positive_confirmation_from_altered_scope_originals_timing_or_stage(review_basis,defect):
    approval,draft,request,started,kwargs=prepared(review_basis)
    if defect=='foreign-job':kwargs['fresh_job']=replace(kwargs['fresh_job'],job_id='other-job')
    elif defect=='foreign-result':kwargs['fresh_result']=replace(kwargs['fresh_result'],job_id='other-job')
    elif defect in ('changed-job','changed-result'):
        key='fresh_job' if defect=='changed-job' else 'fresh_result';value=kwargs[key]
        kwargs[key]=replace(value,original=replace(value.original,body_base64=base64.b64encode(value.original.raw_bytes+b'\n').decode()))
    elif defect=='wrong-calculated-pin':kwargs['calculated']=replace(kwargs['calculated'],schema_sha256='d'*64)
    elif defect=='wrong-response-pin':kwargs['calculated']=replace(kwargs['calculated'],response=replace(kwargs['calculated'].response,schema_sha256='d'*64))
    elif defect=='wrong-calculated-draft':kwargs['calculated']=replace(kwargs['calculated'],draft_sha256='d'*64)
    elif defect=='wrong-original':kwargs['calculated']=replace(kwargs['calculated'],response=replace(kwargs['calculated'].response,original_sha256='d'*64))
    elif defect=='stale-job':kwargs['fresh_job']=kwargs['retained_job']
    elif defect=='stale-result':kwargs['fresh_result']=kwargs['retained_result']
    elif defect=='long-window':kwargs['observed_until']=Timestamp(kwargs['observed_from'].value+timedelta(seconds=31))
    elif defect=='reversed-reads':kwargs['fresh_job']=replace(kwargs['fresh_job'],observed_at=kwargs['observed_until'])
    elif defect=='unknown-job':
        value=kwargs['fresh_job'];kwargs['fresh_job']=replace(value,original=replace(value.original,body_base64=base64.b64encode(b'{}').decode()))
    elif defect=='no-known-start':started=None
    elif defect in ('extra-root','extra-nested'):
        value=json.loads(build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.PREPARE_CONFIRMATION,
            target_instance=kwargs['clean_file'].instance_id,confirmation_prerequisite=bind((approval,draft,request,started,kwargs))).canonical_json)
        body=value['request']['confirmation_prerequisite']
        if defect=='extra-root':body['ready']=True
        else:body['calculated']['response']['calculated_documents'][0]['scopeVerified']=True
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        with pytest.raises(ValueError):decode_tax_delivery_mutation_request(raw,hashlib.sha256(raw.encode()).hexdigest())
        return
    else:
        value=kwargs['retained_instance'];raw=json.loads(value.original.raw_bytes);task=raw['process']['currentTask']
        if defect=='confirmation-task':task|={'altinnTaskType':'confirmation','elementId':'Task_2'}
        elif defect=='auditor-task':task|={'altinnTaskType':'confirmation','elementId':'Task_2Revisor'}
        elif defect=='missing-element':task.pop('elementId')
        else:task['flow']=True
        changed=replace(value,original=replace(value.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()))
        kwargs['retained_instance']=changed
    with pytest.raises(ValueError):bind_tax_delivery_confirmation_prerequisite(approval,draft,request,started,**kwargs)


def test_confirmation_codec_cannot_be_used_for_other_mutation_kind_or_changed_body(review_basis):
    approval,draft,request,started,kwargs=prepared(review_basis);proof=bind((approval,draft,request,started,kwargs))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.PREPARE_CONFIRMATION,
        target_instance=proof.instance_id,confirmation_prerequisite=proof)
    for change in ({'kind':TaxMutationKind.START_VALIDATION},{'body_base64':'e30='}):
        with pytest.raises(ValueError):replace(request,**change)
    assert not hasattr(proof,'submitted') and not hasattr(proof,'owner_confirmed')
