"""Only exact known-instance metadata plus approved file bytes resolve upload."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryUploadReadEvidence,TaxMutationKind,TaxDeliveryCompletionOrigin,
    build_tax_delivery_mutation_request,reconcile_tax_delivery_upload,
    decode_tax_delivery_mutation_completion,decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp
from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_envelope_observation import envelope_read
from test_company_tax_delivery_journal import INSTANCE
from test_company_tax_delivery_observation import original


def recovered(review_basis,**changes):
    envelope,instance,approval,draft=envelope_read(review_basis,**changes)
    evidence=TaxDeliveryUploadReadEvidence(instance,envelope)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE)
    result=reconcile_tax_delivery_upload(request,approval,draft,evidence=evidence,observed_at=envelope.observed_at)
    return result,request,evidence,approval,draft


@pytest.mark.parametrize('scan',['Pending','Clean','Infected'])
def test_matching_file_read_resolves_only_upload_and_keeps_scan_truth_separate(review_basis,scan):
    result,request,evidence,approval,draft=recovered(review_basis,scan=scan)
    assert result.intent.kind is TaxMutationKind.UPLOAD_ENVELOPE
    assert result.origin is TaxDeliveryCompletionOrigin.ENVELOPE_READ
    assert result.result['envelopeSha256']==draft.envelope.envelope_sha256
    assert result.upload_read_evidence.envelope.has_clean_approved_envelope(approval,draft,evidence.instance)==(scan=='Clean')
    result.assert_request(request,approval)
    assert result.response_base64 is None and result.response_bytes==evidence.instance.original.raw_bytes
    value=json.loads(result.canonical_json)
    assert value['version']=='company-tax-delivery-mutation-completion-v2'
    assert 'response_base64' not in value['completion']
    assert value['completion']['upload_read_evidence']['instance_canonical_json']==evidence.instance.canonical_json
    assert value['completion']['upload_read_evidence']['envelope_canonical_json']==evidence.envelope.canonical_json
    restored=decode_tax_delivery_mutation_completion(result.canonical_json,result.sha256)
    assert restored==result and restored.canonical_json==result.canonical_json
    # The current journal deliberately has no V2 completion admission yet.
    with pytest.raises(ValueError):decode_tax_delivery_event(result.canonical_json,result.sha256,result.observed_at,approval.approved_by)


@pytest.mark.parametrize('change',['bytes','size','media','metadata-reference','scope','time','wrong-request'])
def test_unknown_or_foreign_read_pair_cannot_clear_the_committed_upload(review_basis,change):
    envelope,instance,approval,draft=envelope_read(review_basis)
    if change=='bytes':envelope,instance,approval,draft=envelope_read(review_basis,body=b'<different/>')
    elif change=='size':envelope,instance,approval,draft=envelope_read(review_basis,size=1)
    elif change=='media':envelope,instance,approval,draft=envelope_read(review_basis,media='text/html')
    elif change=='metadata-reference':envelope=replace(envelope,instance_evidence_sha256='a'*64)
    elif change=='scope':envelope=replace(envelope,approval_sha256='a'*64)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE if change=='wrong-request' else TaxMutationKind.UPLOAD_ENVELOPE,
        target_instance=None if change=='wrong-request' else INSTANCE)
    observed=envelope.observed_at if change!='time' else Timestamp(instance.observed_at.value-timedelta(microseconds=1))
    with pytest.raises(ValueError):
        evidence=TaxDeliveryUploadReadEvidence(instance,envelope)
        reconcile_tax_delivery_upload(request,approval,draft,evidence=evidence,observed_at=observed)


@pytest.mark.parametrize('change',['proof-missing','hash','nested-hash','nested-bytes','origin','result','actor','duplicate-carrier'])
def test_completion_decoder_rechecks_both_originals_without_an_opaque_success_flag(review_basis,change):
    result,_,_,_,_=recovered(review_basis)
    value=json.loads(result.canonical_json)
    if change=='proof-missing':del value['completion']['upload_read_evidence']
    elif change=='nested-hash':value['completion']['upload_read_evidence']['envelope_sha256']='0'*64
    elif change=='nested-bytes':value['completion']['upload_read_evidence']['instance_canonical_json']+='\n'
    elif change=='origin':value['completion']['origin']='mutation_response'
    elif change=='result':value['completion']['result']['envelopeSha256']='0'*64
    elif change=='actor':value['completion']['intent']['approved_by']['subject']['value']='20000000-0000-4000-8000-000000000099'
    elif change=='duplicate-carrier':value['completion']['response_base64']='e30='
    raw=json.dumps(value,sort_keys=True,separators=(',',':'))
    digest='0'*64 if change=='hash' else hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError):decode_tax_delivery_mutation_completion(raw,digest)


def test_two_bounded_read_originals_can_exceed_the_legacy_single_original_codec_limit(review_basis):
    old=review_basis['draft']
    envelope=replace(old.envelope,envelope_xml=old.envelope.envelope_xml+'\n<!--'+('x'*(5*1024*1024))+'-->')
    draft=replace(old,envelope=envelope,validation=PinnedTax2025Schemas().validate(envelope,current_document=old.current_document))
    basis=review_basis|{'draft':draft,'expected_draft_sha256':draft.sha256,'expected_review_sha256':draft.envelope.review_sha256}
    envelope_read_value,instance,approval,draft=envelope_read(basis)
    metadata=json.loads(instance.original.raw_bytes);metadata['fixturePadding']='x'*(5*1024*1024)
    instance=replace(instance,original=original(json.dumps(metadata).encode()))
    envelope_read_value=replace(envelope_read_value,instance_evidence_sha256=instance.evidence_sha256)
    evidence=TaxDeliveryUploadReadEvidence(instance,envelope_read_value)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE)
    result=reconcile_tax_delivery_upload(request,approval,draft,evidence=evidence,observed_at=envelope_read_value.observed_at)
    raw=result.canonical_json
    assert 12*1024*1024+16384<len(raw.encode())<24*1024*1024
    restored=decode_tax_delivery_mutation_completion(raw,result.sha256)
    assert restored.response_bytes==instance.original.raw_bytes
    assert restored.upload_read_evidence.envelope.original.raw_bytes==draft.envelope.envelope_xml.encode()
