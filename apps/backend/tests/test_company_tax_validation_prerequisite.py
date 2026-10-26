"""Upload existence and historical Clean reads cannot authorize validation."""
from dataclasses import replace
from datetime import timedelta,datetime,UTC
import base64
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    bind_tax_delivery_validation_prerequisite,build_tax_delivery_mutation_request,decode_tax_delivery_mutation_request,
    TaxMutationKind,TaxDeliveryMutationRequest,TaxDeliveryUploadPrerequisite,TaxDeliveryReadReference,
    complete_tax_delivery_mutation,TaxDeliveryCompletionOrigin,decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp,CompanyId,IncomeYear
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_envelope_observation import envelope_read


def proof(review_basis,*,scan='Clean',body=None):
    envelope,instance,approval,draft=envelope_read(review_basis,scan=scan,body=body)
    start=Timestamp(instance.observed_at.value+timedelta(seconds=2))
    fresh_instance=replace(instance,observed_at=Timestamp(start.value+timedelta(milliseconds=1)))
    fresh_envelope=replace(envelope,observed_at=Timestamp(start.value+timedelta(milliseconds=2)))
    end=Timestamp(start.value+timedelta(milliseconds=3))
    kwargs=dict(retained_instance=instance,retained_envelope=envelope,fresh_instance=fresh_instance,
        fresh_envelope=fresh_envelope,observed_from=start,observed_until=end)
    return approval,draft,kwargs


def test_fresh_clean_pair_names_first_originals_and_keeps_current_read_times_separate(review_basis):
    approval,draft,kwargs=proof(review_basis)
    value=bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)
    assert value.instance_read.event_sha256==kwargs['retained_instance'].sha256
    assert value.envelope_read.event_sha256==kwargs['retained_envelope'].sha256
    assert value.instance_read.observed_at==kwargs['fresh_instance'].observed_at
    assert value.envelope_read.observed_at==kwargs['fresh_envelope'].observed_at
    value.assert_retained(approval,draft,kwargs['retained_instance'],kwargs['retained_envelope'])
    value.assert_current(Timestamp(value.observed_from.value+timedelta(seconds=30)))
    with pytest.raises(ValueError):value.assert_current(Timestamp(value.observed_from.value+timedelta(seconds=30,microseconds=1)))


@pytest.mark.parametrize('scan',['Pending','Failed','Infected','Unknown','clean',''])
def test_anything_other_than_exact_clean_cannot_start_validation(review_basis,scan):
    if not scan:
        # Empty scan metadata is unknown, with the file still retained.
        approval,draft,kwargs=proof(review_basis)
        current=kwargs['fresh_instance'];raw=json.loads(current.original.raw_bytes)
        raw['data'][0]['fileScanResult']=''
        changed=replace(current,original=replace(current.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()))
        kwargs['fresh_instance']=changed
    else:approval,draft,kwargs=proof(review_basis,scan=scan)
    with pytest.raises(ValueError):bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)


@pytest.mark.parametrize('defect',['bom','whitespace','different','stale-metadata','stale-file','wrong-time-order','long-window',
    'changed-metadata','changed-file','unreviewed-extra-file','confirmation','archived','wrong-reference'])
def test_byte_scope_reference_and_freshness_drift_prevent_validation(review_basis,defect):
    approval,draft,kwargs=proof(review_basis)
    if defect in ('bom','whitespace','different'):
        body={'bom':b'\xef\xbb\xbf'+draft.envelope.envelope_xml.encode(),
            'whitespace':draft.envelope.envelope_xml.encode()+b'\n','different':b'<different/>'}[defect]
        approval,draft,kwargs=proof(review_basis,body=body)
    elif defect=='stale-metadata':kwargs['fresh_instance']=kwargs['retained_instance']
    elif defect=='stale-file':kwargs['fresh_envelope']=kwargs['retained_envelope']
    elif defect=='wrong-time-order':kwargs['fresh_envelope']=replace(kwargs['fresh_envelope'],observed_at=kwargs['observed_from'])
    elif defect=='long-window':kwargs['observed_until']=Timestamp(kwargs['observed_from'].value+timedelta(seconds=31))
    elif defect=='changed-metadata':
        current=kwargs['fresh_instance'];kwargs['fresh_instance']=replace(current,original=replace(current.original,body_base64=base64.b64encode(current.original.raw_bytes+b'\n').decode()))
    elif defect=='changed-file':
        current=kwargs['fresh_envelope'];kwargs['fresh_envelope']=replace(current,original=replace(current.original,body_base64=base64.b64encode(current.original.raw_bytes+b'\n').decode()))
    elif defect=='wrong-reference':kwargs['retained_envelope']=replace(kwargs['retained_envelope'],instance_evidence_sha256='a'*64)
    else:
        current=kwargs['fresh_instance'];raw=json.loads(current.original.raw_bytes)
        if defect=='unreviewed-extra-file':raw['data'].append(raw['data'][0]|{'id':'00000000-0000-4000-8000-000000000177','dataType':'other'})
        elif defect=='confirmation':raw['process']['currentTask']['altinnTaskType']='confirmation'
        else:raw['status']={'isArchived':True,'archived':'2026-10-26T00:00:00Z'};raw['process']={'ended':'2026-10-26T00:00:00Z'}
        changed=replace(current,original=replace(current.original,body_base64=base64.b64encode(json.dumps(raw).encode()).decode()))
        file=replace(kwargs['fresh_envelope'],instance_evidence_sha256=changed.evidence_sha256)
        kwargs.update(fresh_instance=changed,retained_instance=changed,fresh_envelope=file,retained_envelope=file)
    with pytest.raises(ValueError):bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)


def test_concurrent_identical_reads_do_not_require_retention_order_to_match_read_order(review_basis):
    approval,draft,kwargs=proof(review_basis)
    later=Timestamp(kwargs['fresh_envelope'].observed_at.value+timedelta(microseconds=1))
    kwargs['retained_instance']=replace(kwargs['retained_instance'],observed_at=later)
    kwargs['retained_envelope']=replace(kwargs['retained_envelope'],observed_at=later)
    value=bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)
    assert value.instance_read.observed_at.value<kwargs['retained_instance'].observed_at.value


def test_v2_upload_request_digest_remains_frozen_before_the_validation_successor():
    time=Timestamp(datetime(2026,10,26,tzinfo=UTC));instance='123456/10000000-0000-4000-8000-000000000004'
    prerequisite=TaxDeliveryUploadPrerequisite(instance,TaxDeliveryReadReference('b'*64,'c'*64,time),time,time)
    request=TaxDeliveryMutationRequest('10000000-0000-4000-8000-000000000002',CompanyId('10000000-0000-4000-8000-000000000001'),
        IncomeYear(2025),'999888777','a'*64,TaxMutationKind.UPLOAD_ENVELOPE,instance,'PGtub3duLz4=',prerequisite)
    assert request.sha256=='baf3fdc2611a2880b44131594c26b658ba9dcac01ccbe7a98d19d97ece9392f5'
    assert decode_tax_delivery_mutation_request(request.canonical_json,request.sha256)==request


def test_v3_request_binds_clean_pair_and_existing_journal_stays_closed(review_basis):
    approval,draft,kwargs=proof(review_basis)
    prerequisite=bind_tax_delivery_validation_prerequisite(approval,draft,**kwargs)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.START_VALIDATION,
        target_instance=prerequisite.instance_id,validation_prerequisite=prerequisite)
    raw=json.loads(request.canonical_json)
    assert raw['version']=='company-tax-delivery-mutation-request-v3'
    assert 'upload_prerequisite' not in raw['request']
    assert json.loads(request.body_bytes)=={'appId':'skd/formueinntekt-skattemelding-v2','instansId':prerequisite.instance_id}
    assert decode_tax_delivery_mutation_request(request.canonical_json,request.sha256)==request
    with pytest.raises(ValueError):decode_tax_delivery_event(request.canonical_json,request.sha256,kwargs['observed_until'],approval.approved_by,guarded_upload=True)
    for status in (None,'NY','FERDIG','OPPRETTET'):
        body=json.dumps({'jobbId':'storeDokument-known-v1',**({} if status is None else {'jobbStatus':status})}).encode()
        if status=='OPPRETTET':
            completed=complete_tax_delivery_mutation(request,approval,draft,response_bytes=body,observed_at=kwargs['observed_until'],origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
            assert completed.result['jobId']=='storeDokument-known-v1'
        else:
            with pytest.raises(ValueError):complete_tax_delivery_mutation(request,approval,draft,response_bytes=body,observed_at=kwargs['observed_until'],origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
