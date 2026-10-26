"""Journal originals preserve approved wire bytes and cannot invent completion."""
import base64
from dataclasses import replace
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryCompletionOrigin, TaxMutationKind, TaxMutationIntent, TaxMutationRecord,
    TaxMutationDisposition, plan_tax_mutation, approve_tax_delivery_review,
    build_tax_delivery_mutation_request, complete_tax_delivery_mutation,
    decode_tax_delivery_mutation_request, decode_tax_delivery_mutation_completion,
    StoredTaxDeliveryEvent, TaxDeliveryJournal, decode_tax_delivery_event,
)
from talli_backend.shared.kernel import ActorId, ActorKind, IncomeYear, Timestamp, UserId
from test_company_tax_delivery_approval import review_basis

INSTANCE='123456/00000000-0000-4000-8000-000000000155'
DATA='00000000-0000-4000-8000-000000000156'


@pytest.fixture(scope='module')
def approved(review_basis):
    return approve_tax_delivery_review(**review_basis),review_basis['draft']


def request(approved,kind):
    approval,draft=approved
    return build_tax_delivery_mutation_request(approval,draft,kind,
        target_instance=None if kind is TaxMutationKind.CREATE_INSTANCE else INSTANCE)


def response(kind):
    value={
        TaxMutationKind.CREATE_INSTANCE:{'id':INSTANCE},
        TaxMutationKind.UPLOAD_ENVELOPE:{'id':DATA,'fileScanResult':'Pending'},
        TaxMutationKind.START_VALIDATION:{'jobbId':'job-2025-1','jobbStatus':'queued'},
        TaxMutationKind.PREPARE_CONFIRMATION:{'id':INSTANCE,'process':{'currentTask':{'altinnTaskType':'confirmation'}}},
    }[kind]
    return b'\xef\xbb\xbf'+json.dumps(value,ensure_ascii=False,indent=2).encode()+b'\n'


def complete(approved,kind,**changes):
    approval,draft=approved
    return complete_tax_delivery_mutation(request(approved,kind),approval,draft,**(
        dict(response_bytes=response(kind),observed_at=draft.current_document.response.observed_at,
            origin=TaxDeliveryCompletionOrigin.INSTANCE_READ if kind is TaxMutationKind.PREPARE_CONFIRMATION
                else TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)|changes))


@pytest.mark.parametrize('kind',list(TaxMutationKind))
def test_exact_approved_request_and_original_response_survive_retention(approved,kind):
    approval,draft=approved;value=request(approved,kind)
    assert decode_tax_delivery_mutation_request(value.canonical_json,value.sha256)==value
    value.assert_draft(approval,draft)
    if kind is TaxMutationKind.CREATE_INSTANCE:
        assert value.body_bytes==json.dumps({'instanceOwner':{'organisationNumber':draft.envelope.source.organization_number},
            'appId':'skd/formueinntekt-skattemelding-v2','dataValues':{'inntektsaar':2025}},separators=(',',':')).encode()
    elif kind is TaxMutationKind.UPLOAD_ENVELOPE:assert value.body_bytes==draft.envelope.envelope_xml.encode()
    elif kind is TaxMutationKind.START_VALIDATION:
        assert json.loads(value.body_bytes)=={'appId':'skd/formueinntekt-skattemelding-v2','instansId':INSTANCE}
    else:assert value.body_bytes==b''
    result=complete(approved,kind)
    restored=decode_tax_delivery_mutation_completion(result.canonical_json,result.sha256)
    assert restored==result and restored.response_bytes==response(kind)
    restored.assert_request(value,approval)
    assert plan_tax_mutation(value.intent(approval),TaxMutationRecord(value.intent(approval),'completed',result.result)) is TaxMutationDisposition.REPLAY
    with pytest.raises(TypeError):restored.result['instanceId']='changed'


@pytest.mark.parametrize('kind',list(TaxMutationKind))
def test_uncertain_intent_cannot_be_reissued_or_rebound(approved,kind):
    approval,_=approved;value=request(approved,kind);intent=value.intent(approval)
    assert plan_tax_mutation(intent,TaxMutationRecord(intent,'uncertain')) is TaxMutationDisposition.RECONCILE
    altered=replace(value,body_base64=base64.b64encode(value.body_bytes+b' ').decode())
    with pytest.raises(ValueError):altered.assert_draft(*approved)
    with pytest.raises(ValueError):plan_tax_mutation(altered.intent(approval),TaxMutationRecord(intent,'uncertain'))


@pytest.mark.parametrize('kind',list(TaxMutationKind))
def test_wrong_response_origin_does_not_clear_uncertainty(approved,kind):
    origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE if kind is TaxMutationKind.PREPARE_CONFIRMATION else TaxDeliveryCompletionOrigin.INSTANCE_READ
    with pytest.raises(ValueError):complete(approved,kind,origin=origin)


@pytest.mark.parametrize('body',[b'',b'{}',b'[]',b'null',b'not json',b'{"id":"x","id":"y"}',
    b'{"id":NaN}',b'\xff',b'{"id":"123456/00000000-0000-4000-8000-000000000155"}\n{}'])
def test_missing_malformed_or_ambiguous_response_is_not_completion(approved,body):
    with pytest.raises(ValueError):complete(approved,TaxMutationKind.CREATE_INSTANCE,response_bytes=body)


@pytest.mark.parametrize('change',['task','instance','empty-put','unknown-origin','result','intent','response'])
def test_confirmation_requires_a_bound_read_and_decoder_rechecks_originals(approved,change):
    value=complete(approved,TaxMutationKind.PREPARE_CONFIRMATION)
    if change in ('task','instance','empty-put'):
        raw=json.loads(value.response_bytes.decode('utf-8-sig'))
        if change=='task':raw['process']['currentTask']['altinnTaskType']='data'
        elif change=='instance':raw['id']=INSTANCE.replace('123456/','999999/')
        with pytest.raises(ValueError):complete(approved,TaxMutationKind.PREPARE_CONFIRMATION,
            response_bytes=b'' if change=='empty-put' else json.dumps(raw).encode())
        return
    data=json.loads(value.canonical_json)
    if change=='unknown-origin':data['completion']['origin']='guessed'
    elif change=='result':data['completion']['result']['instanceId']=INSTANCE.replace('123456/','999999/')
    elif change=='intent':data['completion']['intent']['approved_by']['kind']='SYSTEM'
    elif change=='response':data['completion']['response_base64']=base64.b64encode(b'{}').decode()
    raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    with pytest.raises(ValueError):decode_tax_delivery_mutation_completion(raw,hashlib.sha256(raw.encode()).hexdigest())


@pytest.mark.parametrize('codec',['request','completion'])
@pytest.mark.parametrize('change',['space','duplicate','version','unknown','hash'])
def test_recomputed_hash_cannot_accept_noncanonical_or_unknown_records(approved,codec,change):
    value=request(approved,TaxMutationKind.CREATE_INSTANCE) if codec=='request' else complete(approved,TaxMutationKind.CREATE_INSTANCE)
    decode=decode_tax_delivery_mutation_request if codec=='request' else decode_tax_delivery_mutation_completion
    raw=value.canonical_json;data=json.loads(raw)
    if change=='space':raw+=' '
    elif change=='duplicate':raw=raw.replace('"version":','"version":"ignored","version":')
    elif change!='hash':
        if change=='version':data['version']='future'
        else:data[codec]['unknown']=True
        raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    digest='f'*64 if change=='hash' else hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError):decode(raw,digest)


@pytest.mark.parametrize('change',['actor','kind','company','year','year-type','approval','target','organization'])
def test_request_or_intent_cannot_use_an_untyped_or_foreign_scope(approved,change):
    approval,draft=approved;value=request(approved,TaxMutationKind.UPLOAD_ENVELOPE)
    if change in ('actor','kind','company','year','year-type'):
        values={'actor':{'approved_by':ActorId(ActorKind.SYSTEM,approval.approved_by.subject)},
            'kind':{'kind':'upload_envelope'},'company':{'company_id':str(approval.company_id)},
            'year':{'income_year':2025},'year-type':{'income_year':IncomeYear(2025.0)}}[change]
        with pytest.raises(ValueError):replace(value.intent(approval),**values)
    elif change=='approval':
        with pytest.raises(ValueError):replace(value,approval_sha256='a'*64).intent(approval)
    elif change=='target':
        other=replace(value,target_instance=INSTANCE.replace('123456/','999999/'))
        with pytest.raises(ValueError):complete(approved,TaxMutationKind.UPLOAD_ENVELOPE).assert_request(other,approval)
    else:
        with pytest.raises(ValueError):replace(value,organization_number='999999999').assert_draft(approval,draft)


def retained_events(approved):
    approval,draft=approved;at=draft.current_document.response.observed_at
    values=[approval,request(approved,TaxMutationKind.CREATE_INSTANCE),complete(approved,TaxMutationKind.CREATE_INSTANCE)]
    return tuple(StoredTaxDeliveryEvent(value,Timestamp(at.value+timedelta(seconds=i)),approval.approved_by)
        for i,value in enumerate(values))


def test_retained_events_reconstruct_one_bound_journal_with_exact_original_decoding(approved):
    approval,draft=approved;events=retained_events(approved)
    for event in events:
        assert decode_tax_delivery_event(event.value.canonical_json,event.value.sha256,event.recorded_at,event.recorded_by)==event
    journal=TaxDeliveryJournal(draft,events)
    assert journal.plan(request(approved,TaxMutationKind.CREATE_INSTANCE)) is TaxMutationDisposition.REPLAY
    assert journal.plan(request(approved,TaxMutationKind.UPLOAD_ENVELOPE)) is TaxMutationDisposition.EXECUTE
    with pytest.raises(ValueError):journal.plan(request(approved,TaxMutationKind.START_VALIDATION))


@pytest.mark.parametrize('change',['missing-review','missing-intent','duplicate','order','recorder','time','foreign-draft','unknown-request'])
def test_incomplete_reordered_or_rebound_history_cannot_authorize_mutation(approved,change):
    approval,draft=approved;events=list(retained_events(approved))
    if change=='missing-review':events=events[1:]
    elif change=='missing-intent':events=[events[0],events[2]]
    elif change=='duplicate':events.insert(1,events[0])
    elif change=='order':events=[events[0],events[2],events[1]]
    elif change=='recorder':events[1]=replace(events[1],recorded_by=ActorId(ActorKind.USER,UserId(str(uuid4()))))
    elif change=='time':events[1]=replace(events[1],recorded_at=Timestamp(events[0].recorded_at.value-timedelta(seconds=1)))
    elif change=='foreign-draft':draft=replace(draft,filing_id=str(uuid4()))
    elif change=='unknown-request':events.append(StoredTaxDeliveryEvent(request(approved,TaxMutationKind.START_VALIDATION),events[-1].recorded_at,approval.approved_by))
    with pytest.raises(ValueError):TaxDeliveryJournal(draft,events)


@pytest.mark.parametrize('body',[b'{"id":"123456/00000000-0000-4000-8000-000000000155","process":null}',
    b'{"id":"123456/00000000-0000-4000-8000-000000000155","process":{"currentTask":[]}}'])
def test_malformed_confirmation_process_is_not_a_completion(approved,body):
    with pytest.raises(ValueError):complete(approved,TaxMutationKind.PREPARE_CONFIRMATION,response_bytes=body)
