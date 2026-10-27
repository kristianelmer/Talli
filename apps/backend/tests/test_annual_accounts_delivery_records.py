"""Finite system preparation cannot borrow the separately reviewed person port."""
import base64
from dataclasses import replace,FrozenInstanceError
from datetime import timedelta
from uuid import uuid4
import hashlib
import json

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsDeliveryBinding as Binding,AnnualAccountsDeliveryStage as Stage,
    AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryAction as Action,
    AnnualAccountsDeliveryReview as Review,AnnualAccountsFiniteAdmission as Admission,
    AnnualAccountsDeliveryIntent as Intent,AnnualAccountsDeliveryCompletion as Completion,
    AnnualAccountsDeliveryObservation as Observation,decode_annual_accounts_delivery_record,
)
from talli_backend.shared.kernel import IdempotencyKey,Timestamp
from test_annual_accounts_delivery_source import ACTOR,COMPANY,YEAR,prepare,read,source_inputs
from test_annual_accounts_delivery_originals import NOW,INSTANCE,MAIN,ACCOUNTS,original,Purpose,metadata


@pytest.fixture(scope='module')
def draft():
    inputs,app,_=source_inputs();return prepare(read(inputs,app))


def binding(draft):return Binding(draft.filing_id,COMPANY,YEAR,ACTOR,draft.sha256)


def review(draft,stage=Stage.PREPARE):return Review(binding(draft),stage,draft.source.sha256,'a'*64,True,True,
    IdempotencyKey(uuid4().hex),NOW)


def admission(draft,port=Port.SYSTEM_USER,approval=None):
    approval=approval or review(draft,Stage.SIGN if port is Port.PERSON else Stage.PREPARE)
    read=port is Port.KNOWN_READ
    stage=None if read else approval.stage
    return Admission(binding(draft),port,str(uuid4()),draft.source.organization_number,
        'http://127.0.0.1:23456','b'*64,'c'*64,NOW,Timestamp(NOW.value+timedelta(seconds=300)),
        64 if port is Port.SYSTEM_USER and stage is Stage.PREPARE else 16,None if read else approval.sha256,
        None if port is Port.SYSTEM_USER and stage is Stage.PREPARE else INSTANCE,stage,'d'*64 if read else None)


def intent(draft,action,review,admission):
    target=None if action is Action.CREATE_INSTANCE else INSTANCE;data=MAIN if action is Action.UPLOAD_MAIN_FORM else ACCOUNTS if action is Action.UPLOAD_COMPANY_ACCOUNTS else None
    raw=(b'{"instanceOwner":{"organisationNumber":"'+draft.source.organization_number.encode()+b'"}}' if action is Action.CREATE_INSTANCE else
        draft.main_form_xml.encode() if action is Action.UPLOAD_MAIN_FORM else draft.company_accounts_xml.encode() if action is Action.UPLOAD_COMPANY_ACCOUNTS else b'{"action":"confirm"}' if action is Action.CONFIRM else b'{"action":"sign"}')
    path='/brg/aarsregnskap-vanlig-202406/instances/'
    path+='create' if target is None else target+('/data/'+data if data else '/process/next')
    return Intent(binding(draft),action,review.sha256,admission.sha256,'d'*64,target,data,'POST' if target is None else 'PUT',path,
        'application/xml' if data else 'application/json',base64.b64encode(raw).decode())


def test_system_can_prepare_and_confirm_but_only_separate_person_can_sign(draft):
    initial=review(draft);system=admission(draft,approval=initial)
    for action,stage in ((Action.CREATE_INSTANCE,initial),(Action.UPLOAD_MAIN_FORM,initial),(Action.UPLOAD_COMPANY_ACCOUNTS,initial)):
        request=intent(draft,action,stage,system);request.assert_draft(draft,stage,system)
        assert not hasattr(request,'submitted') and request.slot=='intent:'+action.value
    confirmation=review(draft,Stage.CONFIRM);confirm_grant=admission(draft,approval=confirmation)
    intent(draft,Action.CONFIRM,confirmation,confirm_grant).assert_draft(draft,confirmation,confirm_grant)
    with pytest.raises(ValueError):intent(draft,Action.CONFIRM,confirmation,system).assert_draft(draft,confirmation,system)
    signing=review(draft,Stage.SIGN);person=admission(draft,Port.PERSON,signing)
    intent(draft,Action.SIGN,signing,person).assert_draft(draft,signing,person)
    for port in (system,admission(draft,Port.KNOWN_READ)):
        with pytest.raises(ValueError):intent(draft,Action.SIGN,signing,port).assert_draft(draft,signing,port)
    with pytest.raises(ValueError):intent(draft,Action.CREATE_INSTANCE,initial,person).assert_draft(draft,initial,person)
    with pytest.raises(ValueError):intent(draft,Action.CONFIRM,initial,system).assert_draft(draft,initial,system)


@pytest.mark.parametrize('defect',['origin','credentials','origin-path','origin-query','duration','budget','bool-budget','person-review','person-target','read-review'])
def test_admissions_cannot_escape_finite_role_scope(draft,defect):
    value=admission(draft)
    kwargs={'origin':'https://brg.apps.tt02.altinn.no'} if defect=='origin' else {'origin':'http://user:secret@127.0.0.1:23456'} if defect=='credentials' else {
        'origin':'http://127.0.0.1:23456/path'} if defect=='origin-path' else {'origin':'http://127.0.0.1:23456?x=1'} if defect=='origin-query' else {
        'expires_at':Timestamp(NOW.value+timedelta(seconds=301))} if defect=='duration' else {'maximum_requests':65} if defect=='budget' else {
        'maximum_requests':True} if defect=='bool-budget' else {'port':Port.PERSON,'stage':Stage.SIGN,'review_sha256':None,'maximum_requests':16,'known_instance':INSTANCE} if defect=='person-review' else {
        'port':Port.PERSON,'stage':Stage.SIGN,'maximum_requests':16,'review_sha256':'a'*64} if defect=='person-target' else {
        'port':Port.KNOWN_READ,'stage':None,'dependency_intent_sha256':'d'*64,'maximum_requests':16,'known_instance':INSTANCE,'review_sha256':'a'*64}
    with pytest.raises(ValueError):replace(value,**kwargs)


def test_admission_deadline_does_not_refresh_and_records_are_immutable(draft):
    value=admission(draft);value.assert_current(NOW)
    with pytest.raises(ValueError):value.assert_current(value.expires_at)
    with pytest.raises(ValueError):value.assert_current(Timestamp(NOW.value-timedelta(seconds=1)))
    for record in (value,review(draft)):
        assert not hasattr(record,'__dict__')
        with pytest.raises((FrozenInstanceError,TypeError)):record.codec_version='future'


@pytest.mark.parametrize('defect',['path','method','media','payload','target','review','draft','source'])
def test_changed_operation_or_review_cannot_dispatch_reviewed_documents(draft,defect):
    approval=review(draft);grant=admission(draft,approval=approval);request=intent(draft,Action.CREATE_INSTANCE,approval,grant)
    with pytest.raises(ValueError):
        if defect=='path':request=replace(request,request_path=request.request_path+'?x=1')
        elif defect=='method':request=replace(request,request_method='GET')
        elif defect=='media':request=replace(request,request_content_type='text/plain')
        elif defect=='payload':request=replace(request,request_body_base64=base64.b64encode(b'{"action":"sign"}').decode())
        elif defect=='target':request=replace(request,target_instance=INSTANCE)
        elif defect=='review':request=replace(request,review_sha256='f'*64)
        elif defect=='draft':request=replace(request,binding=replace(request.binding,draft_sha256='f'*64))
        else:approval=replace(approval,source_sha256='f'*64)
        request.assert_draft(draft,approval,grant)


def test_completion_retains_opaque_ack_or_uncertainty_without_effect_claim(draft):
    value=Completion(binding(draft),Action.CONFIRM,'a'*64,200,'application/octet-stream',base64.b64encode(b'\x00\xffACK').decode(),None)
    assert value.slot=='completion:confirm' and value.response_body_base64
    unknown=Completion(binding(draft),Action.CONFIRM,'a'*64,None,None,None,'connection_lost')
    assert unknown.http_status is None and unknown.response_body_base64 is None
    headerless=Completion(binding(draft),Action.CONFIRM,'a'*64,204,None,'',None)
    assert headerless.response_content_type is None and headerless.response_body_base64==''
    assert not any(hasattr(value,name) for name in ('signed','submitted','accepted','completed','success'))
    with pytest.raises(ValueError):replace(unknown,failure_code=None)


def records(draft):
    approval=review(draft);grant=admission(draft,approval=approval);request=intent(draft,Action.CREATE_INSTANCE,approval,grant)
    return (approval,grant,request,Completion(binding(draft),Action.CREATE_INSTANCE,request.sha256,None,None,None,'connection_lost'),
        Observation(binding(draft),str(uuid4()),grant.sha256,request.sha256,original(Purpose.INSTANCE,metadata())))


def test_known_record_generations_roundtrip_without_losing_original_bytes(draft):
    for record in records(draft):
        assert decode_annual_accounts_delivery_record(record.canonical_json,record.sha256)==record


@pytest.mark.parametrize('defect',['space','duplicate','unknown-field','unknown-version','bool-year','actor','binding-extra','nonfinite','depth'])
def test_rehashed_noncanonical_or_changed_record_shapes_fail(draft,defect):
    record=review(draft);raw=record.canonical_json;value=json.loads(raw);body=value['record']
    if defect=='space':raw+=' '
    elif defect=='duplicate':raw=raw.replace('"version":','"version":"ignored","version":')
    elif defect=='depth':raw='['*1100+']'*1100
    else:
        if defect=='unknown-field':body['unexpected']=True
        elif defect=='unknown-version':value['version']='future'
        elif defect=='bool-year':body['binding']['income_year']['value']=True
        elif defect=='actor':body['binding']['actor_id']['kind']='SYSTEM'
        elif defect=='binding-extra':body['binding']['ignored']=True
        elif defect=='nonfinite':body['source_sha256']=float('nan')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    with pytest.raises(ValueError):decode_annual_accounts_delivery_record(raw,hashlib.sha256(raw.encode()).hexdigest())
