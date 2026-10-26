"""Exact read evidence cannot turn unavailable metadata into negative proof."""
import base64
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryAdmissionEvidence,TaxDeliveryInstanceObservation,TaxDeliveryOriginalPurpose,
    TaxDeliveryReadOriginal,decode_tax_delivery_observation,tax_delivery_digest,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_rehearsal import admitted
from test_company_tax_delivery_journal import INSTANCE,DATA


def original(raw,purpose=TaxDeliveryOriginalPurpose.INSTANCE):
    return TaxDeliveryReadOriginal(purpose,base64.b64encode(raw).decode(),'application/json',
        None if purpose is TaxDeliveryOriginalPurpose.ADMISSION else 200)


def instance_document(draft):
    return {'id':INSTANCE,'appId':'skd/formueinntekt-skattemelding-v2',
        'instanceOwner':{'organisationNumber':draft.envelope.source.organization_number},
        'dataValues':{'inntektsaar':2025},'process':{'currentTask':{'altinnTaskType':'data'}},
        'status':{'isArchived':False},'data':[]}


def observation(review_basis,raw=None,**changes):
    _,_,_,approval,draft=admitted(review_basis)
    if raw is None:raw=json.dumps(instance_document(draft),indent=2).encode()
    return TaxDeliveryInstanceObservation(**(dict(filing_id=draft.filing_id,company_id=approval.company_id,
        income_year=approval.income_year,approved_by=approval.approved_by,approval_sha256=approval.sha256,
        organization_number=draft.envelope.source.organization_number,instance_id=INSTANCE,
        original=original(raw),observed_at=draft.current_document.response.observed_at)|changes)),approval,draft


def test_admission_original_resolves_existing_review_hash_without_recording_secrets(review_basis):
    grant,_,_,approval,draft=admitted(review_basis)
    value=TaxDeliveryAdmissionEvidence(draft.filing_id,approval.company_id,approval.income_year,
        approval.approved_by,approval.sha256,original(grant.canonical_context.encode(),TaxDeliveryOriginalPurpose.ADMISSION))
    value.assert_approval(approval,draft)
    assert value.original.sha256==grant.context_sha256==tax_delivery_digest(json.loads(grant.canonical_context))
    assert grant.credential not in value.canonical_json
    assert decode_tax_delivery_observation(value.canonical_json,value.sha256)==value
    with pytest.raises(ValueError):replace(value,approval_sha256='a'*64).assert_approval(approval,draft)
    with pytest.raises(ValueError):replace(value,original=original(b'{}',TaxDeliveryOriginalPurpose.ADMISSION))


@pytest.mark.parametrize('origin',['http://127.0.0.1:999','http://127.0.0.1:65536',
    'http://127.0.0.1:01024','http://127.0.0.1:12345/','http://localhost:12345',
    'http://user:password@127.0.0.1:12345','https://127.0.0.1:12345'])
def test_retained_admission_decoder_rejects_nonfinite_or_ambiguous_origins(review_basis,origin):
    grant,_,_,approval,draft=admitted(review_basis)
    context=json.loads(grant.canonical_context);context['origin']=origin
    raw=json.dumps(context,sort_keys=True,separators=(',',':')).encode()
    with pytest.raises(ValueError):TaxDeliveryAdmissionEvidence(draft.filing_id,approval.company_id,approval.income_year,
        approval.approved_by,approval.sha256,original(raw,TaxDeliveryOriginalPurpose.ADMISSION))


def test_exact_instance_original_roundtrips_bom_whitespace_and_stable_poll_identity(review_basis):
    _,_,_,_,draft=admitted(review_basis)
    raw=b'\xef\xbb\xbf'+json.dumps(instance_document(draft),indent=2).encode()+b'\n'
    value,approval,draft=observation(review_basis,raw)
    value.assert_approval(approval,draft,INSTANCE)
    restored=decode_tax_delivery_observation(value.canonical_json,value.sha256)
    assert restored==value and restored.original.raw_bytes==raw
    assert restored.inspection.known and restored.inspection.empty_data
    later=replace(value,observed_at=Timestamp(value.observed_at.value+timedelta(seconds=1)))
    assert later.sha256!=value.sha256 and later.evidence_sha256==value.evidence_sha256
    assert '_inspection' not in value.canonical_json
    with pytest.raises(ValueError):value.assert_approval(replace(approval,approval_id='00000000-0000-4000-8000-000000000188'),draft,INSTANCE)


@pytest.mark.parametrize('defect',['missing-data','null-data','missing-owner','missing-year','missing-status',
    'malformed-id','malformed-app','malformed-organization','malformed-year',
    'missing-task','duplicate-data','duplicate-type','invalid-size','bool-size','missing-scan','archived-without-ended',
    'malformed-json','duplicate-key','deep-json'])
def test_missing_malformed_or_ambiguous_metadata_never_proves_empty_instance(review_basis,defect):
    _,_,_,_,draft=admitted(review_basis);document=instance_document(draft)
    data={'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon','contentType':'application/xml','size':12,'fileScanResult':'Clean'}
    if defect=='missing-data':del document['data']
    elif defect=='null-data':document['data']=None
    elif defect=='missing-owner':del document['instanceOwner']
    elif defect=='missing-year':document['dataValues']={}
    elif defect=='malformed-id':document['id']=None
    elif defect=='malformed-app':document['appId']=[]
    elif defect=='malformed-organization':document['instanceOwner']['organisationNumber']=None
    elif defect=='malformed-year':document['dataValues']['inntektsaar']={}
    elif defect=='missing-status':document['status']={}
    elif defect=='missing-task':document['process']={}
    elif defect=='duplicate-data':document['data']=[data,data]
    elif defect=='duplicate-type':document['data']=[data,data|{'id':'00000000-0000-4000-8000-000000000199'}]
    elif defect=='invalid-size':document['data']=[data|{'size':8*1024*1024+1}]
    elif defect=='bool-size':document['data']=[data|{'size':True}]
    elif defect=='missing-scan':document['data']=[{key:value for key,value in data.items() if key!='fileScanResult'}]
    elif defect=='archived-without-ended':document['status']={'isArchived':True,'archived':'2026-10-26T12:00:00+00:00'}
    raw=json.dumps(document).encode()
    if defect=='malformed-json':raw=b'not json'
    elif defect=='duplicate-key':raw=b'{"data":[],"data":null}'
    elif defect=='deep-json':
        raw=b'{"nested":'+b'['*10000+b'0'+b']'*10000+b'}'
        with pytest.raises(RecursionError):json.loads(raw)
    value,_,_=observation(review_basis,raw)
    assert not value.inspection.known and not value.inspection.empty_data
    assert value.inspection.error_code=='instance_response_unavailable'
    assert decode_tax_delivery_observation(value.canonical_json,value.sha256).original.raw_bytes==raw


@pytest.mark.parametrize('foreign',['id','app','company','year'])
def test_explicit_foreign_scope_cannot_be_retained_under_the_admitted_filing(review_basis,foreign):
    _,_,_,_,draft=admitted(review_basis);document=instance_document(draft)
    if foreign=='id':document['id']=INSTANCE.replace('123456/','999999/')
    elif foreign=='app':document['appId']='another/app'
    elif foreign=='company':document['instanceOwner']['organisationNumber']='999999999'
    else:document['dataValues']['inntektsaar']=2026
    with pytest.raises(ValueError):observation(review_basis,json.dumps(document).encode())


def test_known_scan_and_final_process_metadata_keep_originals_and_scope(review_basis):
    _,_,_,_,draft=admitted(review_basis);document=instance_document(draft)
    document['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon','contentType':'application/xml',
        'size':len(draft.envelope.envelope_xml.encode()),'fileScanResult':'Clean'}]
    value,_,_=observation(review_basis,json.dumps(document).encode())
    assert value.inspection.envelope.data_id==DATA and value.inspection.envelope.scan_result=='Clean'
    assert not value.inspection.empty_data and value.inspection.feedback is None
    document['process']={'ended':'2026-10-26T12:00:00+00:00'}
    document['status']={'isArchived':True,'archived':'2026-10-26T12:00:01+00:00'}
    value,_,_=observation(review_basis,json.dumps(document).encode())
    assert value.inspection.known and value.inspection.archived and value.inspection.process_task is None


@pytest.mark.parametrize('defect',['hash','unknown-version','extra-field','wrong-actor','noncanonical','wrong-purpose','status'])
def test_decoder_rechecks_exact_closed_shape_and_semantics(review_basis,defect):
    value,_,_=observation(review_basis);document=json.loads(value.canonical_json)
    if defect=='unknown-version':document['version']='future'
    elif defect=='extra-field':document['observation']['mayRetry']=True
    elif defect=='wrong-actor':document['observation']['approved_by']['kind']='SYSTEM'
    elif defect=='wrong-purpose':document['observation']['original']['purpose']='envelope'
    elif defect=='status':document['observation']['original']['http_status']=True
    raw=json.dumps(document,sort_keys=True,separators=(',',':'))
    if defect=='noncanonical':raw+='\n'
    digest='0'*64 if defect=='hash' else hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError):decode_tax_delivery_observation(raw,digest)
