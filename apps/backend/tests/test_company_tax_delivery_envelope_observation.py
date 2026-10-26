"""Remote file identity, exact bytes and clean scan are independent proofs."""
import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import httpx
import pytest

from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxDeliveryEnvelopeObservation,
    TaxDeliveryOriginalPurpose,TaxDeliveryReadOriginal,decode_tax_delivery_envelope_observation,
    TaxMutationKind,TaxDeliveryCompletionOrigin,build_tax_delivery_mutation_request,complete_tax_delivery_mutation,
    StoredTaxDeliveryEvent,
    decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_rehearsal import admitted
from test_company_tax_delivery_journal import INSTANCE,DATA
from test_company_tax_delivery_observation import observation,instance_document


def envelope_read(review_basis,*,scan='Pending',body=None,size=None,media='application/xml'):
    _,_,_,_,draft=admitted(review_basis)
    raw=draft.envelope.envelope_xml.encode() if body is None else body
    metadata=instance_document(draft)
    metadata['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon','contentType':media,
        'size':len(raw) if size is None else size,'fileScanResult':scan}]
    instance,approval,draft=observation(review_basis,json.dumps(metadata).encode())
    value=TaxDeliveryEnvelopeObservation(draft.filing_id,approval.company_id,approval.income_year,approval.approved_by,
        approval.sha256,draft.envelope.source.organization_number,INSTANCE,DATA,instance.evidence_sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ENVELOPE,base64.b64encode(raw).decode(),'application/xml',200),
        instance.observed_at)
    return value,instance,approval,draft


@pytest.mark.parametrize('scan',['Pending','Failed','Infected','Clean','Unknown'])
def test_exact_uploaded_bytes_do_not_imply_a_clean_scan(review_basis,scan):
    value,instance,approval,draft=envelope_read(review_basis,scan=scan)
    assert value.matches_approved_bytes(approval,draft,instance)
    assert value.has_clean_approved_envelope(approval,draft,instance)==(scan=='Clean')
    restored=decode_tax_delivery_envelope_observation(value.canonical_json,value.sha256)
    assert restored==value and restored.original.raw_bytes==draft.envelope.envelope_xml.encode()


@pytest.mark.parametrize('change',['bom','whitespace','different','size','media'])
def test_clean_metadata_cannot_certify_changed_bytes_size_or_media(review_basis,change):
    _,_,_,_,draft=admitted(review_basis);raw=draft.envelope.envelope_xml.encode()
    value,instance,approval,draft=envelope_read(review_basis,scan='Clean',**{
        'bom':{'body':b'\xef\xbb\xbf'+raw},'whitespace':{'body':raw+b'\n'},'different':{'body':b'<different/>'},
        'size':{'size':len(raw)+1},'media':{'media':'text/html'},
    }[change])
    assert not value.matches_approved_bytes(approval,draft,instance)
    assert not value.has_clean_approved_envelope(approval,draft,instance)
    assert decode_tax_delivery_envelope_observation(value.canonical_json,value.sha256).original.raw_bytes==value.original.raw_bytes


def test_unchanged_read_identity_keeps_time_separate_and_current_journal_refuses_unimplemented_codec(review_basis):
    value,instance,approval,draft=envelope_read(review_basis,scan='Clean',media='Application/XML; charset=utf-8')
    later=replace(value,observed_at=Timestamp(value.observed_at.value+timedelta(seconds=1)))
    assert later.evidence_sha256==value.evidence_sha256 and later.sha256!=value.sha256
    assert value.has_clean_approved_envelope(approval,draft,instance)
    with pytest.raises(ValueError):decode_tax_delivery_event(value.canonical_json,value.sha256,value.observed_at,approval.approved_by)


@pytest.mark.parametrize('change',['data','instance-proof','approval','unknown-instance'])
def test_envelope_requires_the_bound_positive_instance_metadata(review_basis,change):
    value,instance,approval,draft=envelope_read(review_basis)
    if change=='data':value=replace(value,data_id='00000000-0000-4000-8000-000000000199')
    elif change=='instance-proof':value=replace(value,instance_evidence_sha256='a'*64)
    elif change=='approval':value=replace(value,approval_sha256='a'*64)
    else:
        raw=base64.b64encode(b'{"metadata":"unavailable"}').decode()
        instance=replace(instance,original=replace(instance.original,body_base64=raw))
    with pytest.raises(ValueError):value.matches_approved_bytes(approval,draft,instance)


@pytest.mark.parametrize('defect',['digest','codec','extra','purpose','status','scope','raw-bytes','noncanonical'])
def test_decoder_rechecks_closed_shape_exact_bytes_and_types(review_basis,defect):
    value,_,_,_=envelope_read(review_basis);document=json.loads(value.canonical_json)
    if defect=='codec':document['version']='unknown'
    elif defect=='extra':document['observation']['retryUpload']=True
    elif defect=='purpose':document['observation']['original']['purpose']='instance'
    elif defect=='status':document['observation']['original']['http_status']=True
    elif defect=='scope':document['observation']['income_year']['value']=True
    elif defect=='raw-bytes':document['observation']['original']['body_base64']='/w=='
    raw=json.dumps(document,sort_keys=True,separators=(',',':'))
    if defect=='noncanonical':raw+='\n'
    digest='0'*64 if defect=='digest' else hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError):decode_tax_delivery_envelope_observation(raw,digest)


@pytest.mark.parametrize('media',['application/xml','text/xml; charset=utf-8'])
def test_transport_reads_only_known_file_fixed_path_and_preserves_original_bytes(review_basis,media):
    # Use one exact admission/approval across metadata and transport.
    grant,runtime,_,approval,draft=admitted(review_basis);calls=[]
    value,instance,_,_=envelope_read(review_basis,scan='Pending')
    instance=replace(instance,approval_sha256=approval.sha256)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    created=complete_tax_delivery_mutation(request,approval,draft,response_bytes=json.dumps({'id':INSTANCE}).encode(),
        observed_at=runtime.now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    async def authority(request):
        calls.append(request)
        assert request.method=='GET' and request.url.host=='127.0.0.1'
        assert request.url.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data/'+DATA
        assert request.headers['x-talli-rehearsal-run']==grant.run_id and 'authorization' not in request.headers
        return httpx.Response(200,content=value.original.raw_bytes,headers={'content-type':media})
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    result=asyncio.run(provider.observe_envelope(approval,draft,created,instance))
    assert result.original.raw_bytes==value.original.raw_bytes and result.matches_approved_bytes(approval,draft,instance)
    assert not result.has_clean_approved_envelope(approval,draft,instance)
    assert result.original.content_type==media.split(';',1)[0]
    assert len(calls)==1 and runtime.requests_used==1


def test_transport_never_fetches_an_unknown_file_or_retries_bad_media(review_basis):
    _,runtime,_,approval,draft=admitted(review_basis);calls=[]
    _,instance,_,_=envelope_read(review_basis)
    instance=replace(instance,approval_sha256=approval.sha256)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    created=complete_tax_delivery_mutation(request,approval,draft,response_bytes=json.dumps({'id':INSTANCE}).encode(),
        observed_at=runtime.now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    async def authority(request):calls.append(request);return httpx.Response(200,content=b'<unexpected/>',headers={'content-type':'text/html'})
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    unknown=replace(instance,original=replace(instance.original,body_base64=base64.b64encode(b'{}').decode()))
    with pytest.raises(CompanyTaxError):asyncio.run(provider.observe_envelope(approval,draft,created,unknown))
    assert not calls and runtime.requests_used==0
    with pytest.raises(CompanyTaxReturnAuthorityError):asyncio.run(provider.observe_envelope(approval,draft,created,instance))
    assert len(calls)==1 and runtime.requests_used==1
