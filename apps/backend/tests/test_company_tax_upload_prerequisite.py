"""Fresh intent attestation names the first original without rewriting it."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryMutationRequest,TaxDeliveryReadReference,TaxDeliveryUploadPrerequisite,TaxMutationKind,
    bind_tax_delivery_upload_prerequisite,build_tax_delivery_mutation_request,decode_tax_delivery_mutation_request,
    decode_tax_delivery_event,
)
from talli_backend.shared.kernel import CompanyId,IncomeYear,Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_observation import observation,original,instance_document
from test_company_tax_delivery_journal import INSTANCE


def prerequisite(review_basis):
    retained,approval,draft=observation(review_basis)
    fresh=replace(retained,observed_at=Timestamp(retained.observed_at.value+timedelta(seconds=5)))
    start=Timestamp(fresh.observed_at.value-timedelta(seconds=1));end=Timestamp(fresh.observed_at.value+timedelta(seconds=1))
    value=bind_tax_delivery_upload_prerequisite(approval,draft,retained=retained,fresh=fresh,observed_from=start,observed_until=end)
    return value,retained,fresh,approval,draft


def test_v1_request_canonical_bytes_remain_exactly_the_frozen_predecessor_codec():
    value=TaxDeliveryMutationRequest('10000000-0000-4000-8000-000000000002',CompanyId('10000000-0000-4000-8000-000000000001'),
        IncomeYear(2025),'999888777','a'*64,TaxMutationKind.UPLOAD_ENVELOPE,INSTANCE,'PGtub3duLz4=')
    expected='{"request":{"approval_sha256":"'+('a'*64)+'","body_base64":"PGtub3duLz4=","company_id":{"value":"10000000-0000-4000-8000-000000000001"},"filing_id":"10000000-0000-4000-8000-000000000002","income_year":{"value":2025},"kind":"upload_envelope","organization_number":"999888777","target_instance":"'+INSTANCE+'"},"version":"company-tax-delivery-mutation-request-v1"}'
    assert value.canonical_json==expected and value.sha256==hashlib.sha256(expected.encode()).hexdigest()
    assert decode_tax_delivery_mutation_request(expected,value.sha256)==value


def test_new_upload_intent_binds_exact_wire_bytes_and_fresh_reference_to_first_original(review_basis):
    proof,retained,fresh,approval,draft=prerequisite(review_basis)
    assert proof.instance_read.event_sha256==retained.sha256
    assert proof.instance_read.evidence_sha256==retained.evidence_sha256==fresh.evidence_sha256
    assert proof.instance_read.observed_at==fresh.observed_at and proof.instance_read.observed_at!=retained.observed_at
    proof.assert_retained(approval,draft,retained);proof.assert_current(proof.observed_until)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE,upload_prerequisite=proof)
    assert json.loads(request.canonical_json)['version']=='company-tax-delivery-mutation-request-v2'
    assert request.body_bytes==draft.envelope.envelope_xml.encode()
    assert request.intent(approval).request_sha256==request.sha256
    assert decode_tax_delivery_mutation_request(request.canonical_json,request.sha256)==request
    # Persistence/dispatch stays closed until the matching journal reader and
    # guarded store can validate this new codec and its retained prerequisites.
    with pytest.raises(ValueError):decode_tax_delivery_event(request.canonical_json,request.sha256,proof.observed_until,approval.approved_by)


@pytest.mark.parametrize('seconds',[-1,31])
def test_read_interval_and_current_age_are_bounded(review_basis,seconds):
    proof,_,_,_,_=prerequisite(review_basis)
    with pytest.raises(ValueError):replace(proof,observed_until=Timestamp(proof.observed_from.value+timedelta(seconds=seconds)))
    if seconds==-1:
        with pytest.raises(ValueError):proof.assert_current(Timestamp(proof.observed_until.value-timedelta(microseconds=1)))
    else:
        with pytest.raises(ValueError):proof.assert_current(Timestamp(proof.observed_from.value+timedelta(seconds=30,microseconds=1)))
    proof.assert_current(Timestamp(proof.observed_from.value+timedelta(seconds=30)))


@pytest.mark.parametrize('defect',['not-retained','changed-current','reused-old-time','unknown','has-file','confirmation','archived'])
def test_only_positive_empty_current_data_task_can_be_a_new_upload_prerequisite(review_basis,defect):
    proof,retained,fresh,approval,draft=prerequisite(review_basis)
    if defect=='not-retained':retained=replace(retained,observed_at=Timestamp(proof.observed_until.value+timedelta(seconds=1)))
    elif defect=='changed-current':fresh=replace(fresh,original=original(fresh.original.raw_bytes+b'\n'))
    elif defect=='reused-old-time':fresh=retained
    else:
        value=instance_document(draft)
        if defect=='unknown':value={}
        elif defect=='has-file':value['data']=[{'id':'00000000-0000-4000-8000-000000000177','dataType':'other','contentType':'application/xml','size':1,'fileScanResult':'Clean'}]
        elif defect=='confirmation':value['process']['currentTask']['altinnTaskType']='confirmation'
        elif defect=='archived':value['status']={'isArchived':True,'archived':'2026-10-26T00:00:00Z'};value['process']={'ended':'2026-10-26T00:00:00Z'}
        retained=replace(retained,original=original(json.dumps(value).encode()))
        fresh=replace(retained,observed_at=fresh.observed_at)
    with pytest.raises(ValueError):bind_tax_delivery_upload_prerequisite(approval,draft,retained=retained,fresh=fresh,
        observed_from=proof.observed_from,observed_until=proof.observed_until)


def test_concurrent_identical_read_can_finish_before_the_first_retained_original(review_basis):
    proof,retained,fresh,approval,draft=prerequisite(review_basis)
    retained=replace(retained,observed_at=Timestamp(fresh.observed_at.value+timedelta(milliseconds=1)))
    value=bind_tax_delivery_upload_prerequisite(approval,draft,retained=retained,fresh=fresh,
        observed_from=proof.observed_from,observed_until=proof.observed_until)
    assert value.instance_read.observed_at.value<retained.observed_at.value
    assert value.instance_read.event_sha256==retained.sha256


@pytest.mark.parametrize('defect',['null-proof','wrong-kind','foreign-instance','extra-field','future-time'])
def test_v2_request_decoder_cannot_strip_or_borrow_a_prerequisite(review_basis,defect):
    proof,_,_,approval,draft=prerequisite(review_basis)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE,upload_prerequisite=proof)
    value=json.loads(request.canonical_json)
    if defect=='null-proof':value['request']['upload_prerequisite']=None
    elif defect=='wrong-kind':value['request']['kind']='start_validation'
    elif defect=='foreign-instance':value['request']['target_instance']=INSTANCE.replace('123456/','654321/')
    elif defect=='extra-field':value['request']['upload_prerequisite']['retryUpload']=True
    else:value['request']['upload_prerequisite']['instance_read']['observed_at']['value']='2099-01-01T00:00:00Z'
    raw=json.dumps(value,sort_keys=True,separators=(',',':'))
    with pytest.raises(ValueError):decode_tax_delivery_mutation_request(raw,hashlib.sha256(raw.encode()).hexdigest())
