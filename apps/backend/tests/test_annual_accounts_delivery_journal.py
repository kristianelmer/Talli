"""Submit-once retained graph advances by known reads, including lost responses."""
import base64
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.modules.annual_accounts_filing.public import (
    StoredAnnualAccountsDeliveryDraft,StoredAnnualAccountsDeliveryEvent as Event,
    inspect_annual_accounts_delivery_journal,inspect_annual_accounts_delivery_frame,
)
from talli_backend.shared.kernel import Timestamp
from test_annual_accounts_delivery_records import draft,binding,review,admission,intent,Stage,Port,Action,Completion
from test_annual_accounts_delivery_frames import frame,Kind
from test_annual_accounts_delivery_originals import metadata,NOW,INSTANCE


class World:
    def __init__(self,draft):
        self.draft=draft;self.events=[];self.expected={};self.second=0;self.stored=StoredAnnualAccountsDeliveryDraft(draft,Timestamp(NOW.value-timedelta(seconds=1)))
        self.schemas=PinnedAnnualAccountsSchemas()
    @property
    def now(self):return Timestamp(NOW.value+timedelta(seconds=self.second))
    def append(self,record):
        event=Event(len(self.events)+1,record,self.now);self.events.append(event);self.expected[str(event.sequence)]=record.sha256;self.second+=1
        return record
    def review(self,stage=Stage.PREPARE,evidence=None):
        return self.append(replace(review(self.draft,stage),reviewed_at=self.now,reviewed_evidence_sha256=evidence or self.draft.sha256))
    def admit(self,approval,*,maximum=None):
        value=admission(self.draft,Port.PERSON if approval.stage is Stage.SIGN else Port.SYSTEM_USER,approval)
        return self.append(replace(value,issued_at=self.now,expires_at=Timestamp(self.now.value+timedelta(seconds=300)),
            maximum_requests=maximum or value.maximum_requests))
    def request(self,action,approval,grant,prerequisite=None):
        return self.append(replace(intent(self.draft,action,approval,grant),prerequisite_sha256=prerequisite.sha256 if prerequisite else self.draft.sha256))
    def create_result(self,request,body=None):
        if body is None:
            body=metadata();body['instanceOwner']['organisationNumber']=self.draft.source.organization_number
        return self.append(Completion(binding(self.draft),Action.CREATE_INSTANCE,request.sha256,201,'application/json',
            base64.b64encode(json.dumps(body).encode()).decode(),None))
    def frame(self,kind,request,grant):
        value,observations=frame(self.draft,kind);start=self.second
        selected=[]
        for index,row in enumerate(observations):
            row=replace(row,admission_sha256=grant.sha256,intent_sha256=request.sha256,
                original=replace(row.original,observed_at=Timestamp(NOW.value+timedelta(seconds=start+index)),requested_at=Timestamp(NOW.value+timedelta(seconds=start+index))))
            selected.append(self.append(row))
        value=self.append(replace(value,observation_sha256=tuple(row.sha256 for row in selected)))
        return value,inspect_annual_accounts_delivery_frame(value,selected,draft=self.draft,known_instance=INSTANCE,schemas=self.schemas)
    def inspect(self):return inspect_annual_accounts_delivery_journal(self.stored,self.events,schemas=self.schemas,expected_event_digests=self.expected)
    def create(self):
        approval=self.review();grant=self.admit(approval);request=self.request(Action.CREATE_INSTANCE,approval,grant)
        self.create_result(request)
        return approval,grant,request


def test_creation_without_returned_identity_is_unknown_and_cannot_be_mutated_again(draft):
    world=World(draft);approval=world.review();grant=world.admit(approval);request=world.request(Action.CREATE_INSTANCE,approval,grant)
    world.append(Completion(binding(draft),Action.CREATE_INSTANCE,request.sha256,None,None,None,'connection_lost'))
    result=world.inspect()
    assert result.state=='creation_unknown' and result.known_instance is None and result.next_action is None
    world.request(Action.UPLOAD_MAIN_FORM,approval,grant)
    with pytest.raises(ValueError):world.inspect()


def test_partial_scoped_creation_response_learns_only_a_known_read_target(draft):
    world=World(draft);approval=world.review();grant=world.admit(approval);request=world.request(Action.CREATE_INSTANCE,approval,grant)
    body=metadata();body['instanceOwner']['organisationNumber']=draft.source.organization_number;body.pop('data')
    world.create_result(request,body)
    result=world.inspect()
    assert result.known_instance==INSTANCE and result.next_action is None
    value,_=world.frame(Kind.CREATE_TARGET,request,grant)
    result=world.inspect()
    assert result.next_action is Action.UPLOAD_MAIN_FORM and result.prerequisite_sha256==value.sha256


def test_upload_acknowledgment_does_not_prove_original_bytes_were_stored(draft):
    world=World(draft);approval,grant,request=world.create();target,_=world.frame(Kind.CREATE_TARGET,request,grant)
    upload=world.request(Action.UPLOAD_MAIN_FORM,approval,grant,target)
    world.append(Completion(binding(draft),Action.UPLOAD_MAIN_FORM,upload.sha256,200,'application/octet-stream',base64.b64encode(b'opaque ACK').decode(),None))
    result=world.inspect()
    assert result.state=='main_upload_unknown' and result.next_action is None
    world.frame(Kind.MAIN_UPLOADED,upload,grant)
    assert world.inspect().next_action is Action.UPLOAD_COMPANY_ACCOUNTS


def complete_world(draft):
    world=World(draft);approval,grant,create=world.create();target,_=world.frame(Kind.CREATE_TARGET,create,grant)
    main=world.request(Action.UPLOAD_MAIN_FORM,approval,grant,target);main_frame,_=world.frame(Kind.MAIN_UPLOADED,main,grant)
    accounts=world.request(Action.UPLOAD_COMPANY_ACCOUNTS,approval,grant,main_frame);uploaded,info=world.frame(Kind.UPLOAD_REVIEW,accounts,grant)
    confirmation=world.review(Stage.CONFIRM,info.review_sha256);confirm_grant=world.admit(confirmation)
    confirm=world.request(Action.CONFIRM,confirmation,confirm_grant,uploaded);locked,info=world.frame(Kind.SIGN_REVIEW,confirm,confirm_grant)
    signing=world.review(Stage.SIGN,info.review_sha256);person=world.admit(signing)
    sign=world.request(Action.SIGN,signing,person,locked);world.frame(Kind.ARCHIVE,sign,person)
    return world


def test_all_known_effects_can_be_reconciled_after_lost_upload_and_process_responses(draft):
    world=complete_world(draft);result=world.inspect()
    assert result.state=='technical_archive' and result.next_action is None and result.known_instance==INSTANCE
    assert len(result.event_sha256)==len(world.events)
    assert not any(hasattr(result,name) for name in ('signed','submitted','accepted','ready'))
    # Late exact response retention does not request a second process mutation.
    sign=next(event.record for event in world.events if event.record.slot=='intent:sign')
    world.append(Completion(binding(draft),Action.SIGN,sign.sha256,200,'application/octet-stream','',None))
    assert world.inspect().state=='technical_archive'


def test_later_retained_metadata_cannot_authorize_an_earlier_file_request(draft):
    world=complete_world(draft)
    index=next(i for i,row in enumerate(world.events) if getattr(getattr(getattr(row.record,'original',None),'purpose',None),'value',None)=='pdf')
    event=world.events[index];record=event.record
    prior=next(row.record.original for row in reversed(world.events[:index])
        if getattr(getattr(row.record,'original',None),'purpose',None) is not None and row.record.original.purpose.value=='instance')
    changed=replace(record,original=replace(record.original,requested_at=Timestamp(prior.observed_at.value-timedelta(microseconds=1))))
    world.events[index]=replace(event,record=changed);world.expected[str(event.sequence)]=changed.sha256
    with pytest.raises(ValueError,match='known before its request'):world.inspect()


@pytest.mark.parametrize('defect',['missing-review','missing-admission','duplicate','out-of-order','wrong-prerequisite','wrong-known-file','expired','admission-before-review'])
def test_changed_or_incomplete_operation_graph_is_unavailable(draft,defect):
    world=complete_world(draft)
    if defect=='missing-review':world.events=world.events[1:]
    elif defect=='missing-admission':world.events=[event for event in world.events if not event.record.slot.startswith('admission:system_user:prepare')]
    elif defect=='duplicate':world.append(world.events[0].record)
    elif defect=='out-of-order':world.events[0],world.events[1]=world.events[1],world.events[0]
    else:
        for index,event in enumerate(world.events):
            if event.record.slot=='intent:upload_main_form':
                record=event.record
                if defect=='wrong-prerequisite':record=replace(record,prerequisite_sha256='f'*64)
                elif defect=='wrong-known-file':record=replace(record,target_data='40000000-0000-4000-8000-000000000004',
                    request_path=record.request_path.replace(record.target_data,'40000000-0000-4000-8000-000000000004'))
                elif defect=='expired':event=replace(event,recorded_at=Timestamp(NOW.value+timedelta(seconds=301)))
                else:
                    admission_index=next(i for i,e in enumerate(world.events) if e.record.slot=='admission:system_user:prepare')
                    prior=world.events[admission_index];world.events[admission_index]=replace(prior,record=replace(prior.record,
                        issued_at=Timestamp(NOW.value-timedelta(seconds=1)),expires_at=Timestamp(NOW.value+timedelta(seconds=299))))
                world.events[index]=replace(event,record=record);break
    with pytest.raises(ValueError):world.inspect()


def test_failed_known_read_is_retained_and_stays_unknown_without_spending_a_mutation_again(draft):
    world=World(draft);approval,grant,create=world.create()
    target,info=world.frame(Kind.CREATE_TARGET,create,grant);upload=world.request(Action.UPLOAD_MAIN_FORM,approval,grant,target)
    from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsDeliveryObservation as Observation
    from test_annual_accounts_delivery_originals import original,Purpose
    from uuid import uuid4
    response=replace(original(Purpose.INSTANCE,b'<html>temporary failure</html>'),content_type='text/html',http_status=503,observed_at=world.now,requested_at=world.now)
    world.append(Observation(binding(draft),str(uuid4()),grant.sha256,upload.sha256,response))
    result=world.inspect()
    assert result.state=='main_upload_unknown' and result.next_action is None


def test_retained_reads_and_mutations_cannot_exceed_the_finite_request_budget(draft):
    world=World(draft);approval=world.review();grant=world.admit(approval,maximum=1)
    create=world.request(Action.CREATE_INSTANCE,approval,grant);world.create_result(create)
    world.frame(Kind.CREATE_TARGET,create,grant)
    with pytest.raises(ValueError):world.inspect()


def test_global_sequence_gaps_are_valid_but_an_uncommitted_rescaling_or_omission_is_not(draft):
    world=complete_world(draft)
    changed=[replace(row,sequence=row.sequence*2) for row in world.events]
    with pytest.raises(ValueError):inspect_annual_accounts_delivery_journal(world.stored,changed,schemas=world.schemas,expected_event_digests=world.expected)
    # The underlying PG identity is shared across filings/companies. The
    # complete SQL enumeration commitment, not contiguous IDs, proves coverage.
    committed={str(row.sequence):row.record.sha256 for row in changed}
    assert inspect_annual_accounts_delivery_journal(world.stored,changed,schemas=world.schemas,expected_event_digests=committed).state=='technical_archive'
    with pytest.raises(ValueError):inspect_annual_accounts_delivery_journal(world.stored,world.events[:-1],schemas=world.schemas,expected_event_digests=world.expected)
    world.events[1]=replace(world.events[1],recorded_at=world.now)
    with pytest.raises(ValueError):world.inspect()


def test_unreferenced_file_observation_still_requires_a_prior_known_data_id(draft):
    from uuid import uuid4
    from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsDeliveryObservation as Observation
    from test_annual_accounts_delivery_originals import original,Purpose
    world=World(draft);approval,grant,request=world.create()
    value=replace(original(Purpose.PDF,b'opaque',data_id=str(uuid4()),media='application/pdf'),
        observed_at=world.now,requested_at=world.now)
    world.append(Observation(binding(draft),str(uuid4()),grant.sha256,request.sha256,value))
    with pytest.raises(ValueError):world.inspect()


def test_read_started_inside_finite_window_can_be_retained_after_its_deadline(draft):
    from uuid import uuid4
    from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsDeliveryObservation as Observation
    from test_annual_accounts_delivery_originals import original,Purpose
    world=World(draft);approval,grant,request=world.create()
    requested=Timestamp(grant.expires_at.value-timedelta(milliseconds=1))
    observed=Timestamp(grant.expires_at.value+timedelta(seconds=1));world.second=int((observed.value-NOW.value).total_seconds())
    value=replace(original(Purpose.INSTANCE,b'',media='application/octet-stream'),http_status=204,content_type=None,
        requested_at=requested,observed_at=observed)
    world.append(Observation(binding(draft),str(uuid4()),grant.sha256,request.sha256,value))
    assert world.inspect().state=='created'
