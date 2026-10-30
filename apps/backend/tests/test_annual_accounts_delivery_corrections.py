"""Correction lineage never replaces a technical parent or borrows its grants."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsCorrectionReadGrant as ParentGrant,AnnualAccountsCorrectionParentAdmission as ParentAdmission,AnnualAccountsCorrectionParentAttempt as ParentAttempt,AnnualAccountsCorrectionParentObservation as ParentObservation,
    AnnualAccountsCorrectionParentFrame as ParentFrame,AnnualAccountsFiniteAdmission as Admission,
    AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryObservation as Observation,
    AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
    AnnualAccountsDeliveryIntent as Intent,AnnualAccountsDeliveryAction as Action,
    StoredAnnualAccountsDeliveryDraft as Stored,StoredAnnualAccountsDeliveryEvent as Event,
    decode_annual_accounts_delivery_record_v2 as decode,inspect_annual_accounts_delivery_history as inspect,
    annual_accounts_delivery_digest,assert_annual_accounts_correction_source,
)
from talli_backend.shared.kernel import Timestamp
from talli_backend.modules.annual_accounts_filing.delivery import _canonical
from test_annual_accounts_delivery_records import draft,binding,review,admission,intent
from test_annual_accounts_delivery_source import prepare
from test_annual_accounts_delivery_journal import complete_world,World
from test_annual_accounts_delivery_originals import NOW


def changed_source(source):
    # Unit fixture: changed interview and a distinct historical signed closure.
    annual=json.loads(_canonical(source.annual_data))
    annual['annual_full_time_equivalents']=1
    snapshots=json.loads(_canonical(source.owning_snapshots))
    snapshots['annual'][0]['annualFullTimeEquivalents']=1
    corporate=snapshots['corporate'];ready=corporate['readiness']
    old=ready['decision_id'];new={'value':str(uuid4())}
    ready.update(decision_id=new,decision_hash='f'*64,finalization_id={'value':str(uuid4())},
        signed_artifact_hashes={key:'e'*64 for key in ready['signed_artifact_hashes']})
    for decision in corporate['snapshot']['decisions']:
        if decision['decision_id']==old:decision.update(decision_id=new,decision_hash=ready['decision_hash'])
    for final in corporate['snapshot']['finalizations']:
        if final['decision_id']==old:final.update(decision_id=new,decision_hash=ready['decision_hash'],
            finalization_id=ready['finalization_id'],signed_artifact_hashes=ready['signed_artifact_hashes'])
    return replace(source,annual_data=annual,owning_snapshots=snapshots,
        upstream_sha256={key:annual_accounts_delivery_digest(value) for key,value in snapshots.items()})


class Correction:
    def __init__(self,parent,*,after=None):
        self.parent=parent;self.child=prepare(changed_source(parent.draft.source));self.events=[]
        self.now=Timestamp((after or parent.now).value+timedelta(seconds=5));self.stored=Stored(self.child,self.now)
        self.start=len(parent.events)+10
        sign=next(row.record for row in parent.events if type(row.record) is Intent and row.record.action is Action.SIGN)
        self.archive=next(row.record for row in reversed(parent.events) if type(row.record) is Frame and row.record.kind is Kind.ARCHIVE)
        issued=Timestamp(self.now.value+timedelta(seconds=1))
        self.grant=ParentGrant(binding(self.child),Port.KNOWN_READ,str(uuid4()),self.child.source.organization_number,
            'http://127.0.0.1:23456','b'*64,'a'*64,issued,Timestamp(issued.value+timedelta(seconds=300)),
            27,None,parent.inspect().known_instance,None,sign.sha256)
        self.admitted=self.append(ParentAdmission(binding(self.child),binding(parent.draft),sign.sha256,self.archive.sha256,self.grant))
    def append(self,record):
        self.now=Timestamp(self.now.value+timedelta(seconds=1))
        event=Event(self.start+len(self.events),record,self.now);self.events.append(event);return record
    def begin(self):
        self.current_attempt=self.append(ParentAttempt(binding(self.child),str(uuid4()),self.admitted.sha256,self.now))
        return self.current_attempt
    def observe(self):
        self.begin()
        self.attempt=[]
        originals={row.record.sha256:row.record.original for row in self.parent.events if type(row.record) is Observation}
        for ref in self.archive.observation_sha256:
            at=Timestamp(self.now.value+timedelta(seconds=1))
            self.attempt.append(self.append(ParentObservation(binding(self.child),str(uuid4()),self.admitted.sha256,self.current_attempt.sha256,
                replace(originals[ref],requested_at=at,observed_at=at))))
    def finish(self):
        return self.append(ParentFrame(binding(self.child),str(uuid4()),self.current_attempt.sha256,binding(self.parent.draft),self.archive.sha256,
            tuple(row.sha256 for row in self.attempt)))
    def inspect(self,*,more=()):
        events=tuple(sorted((*self.parent.events,*self.events,*more),key=lambda row:row.sequence))
        return inspect((self.parent.stored,self.stored),events,schemas=self.parent.schemas,
            expected_event_digests={str(row.sequence):row.record.sha256 for row in events})


def test_exact_new_record_generations_roundtrip_and_predecessor_bytes_stay_unchanged(draft):
    child=Correction(complete_world(draft));child.observe();child.finish()
    for row in (*child.parent.events,*child.events):assert decode(row.record.canonical_json,row.record.sha256)==row.record
    assert child.inspect()[draft.filing_id].state=='technical_archive'
    assert child.inspect()[child.child.filing_id].state=='draft'
    assert child.grant.port is Port.KNOWN_READ and child.grant.binding.filing_id!=draft.filing_id


@pytest.mark.parametrize('defect',['unknown-field','duplicate-key','unknown-version','noncanonical','bool-year','nested-grant','parent-actor'])
def test_correction_codec_rejects_rehashed_lossy_or_ambiguous_records(draft,defect):
    child=Correction(complete_world(draft));record=child.admitted;value=json.loads(record.canonical_json)
    if defect=='unknown-field':value['record']['authority']=True
    elif defect=='unknown-version':value['version']='future'
    elif defect=='bool-year':value['record']['binding']['income_year']['value']=True
    elif defect=='nested-grant':value['record']['grant']['maximum_requests']=64
    elif defect=='parent-actor':value['record']['parent_binding']['actor_id']['kind']='SYSTEM'
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    if defect=='noncanonical':raw+=' '
    if defect=='duplicate-key':raw=raw.replace('"version":','"version":"discarded","version":')
    with pytest.raises(ValueError):decode(raw,hashlib.sha256(raw.encode()).hexdigest())


def test_incomplete_parent_read_is_retained_but_cannot_admit_a_child_creation(draft):
    child=Correction(complete_world(draft));child.observe()
    assert child.inspect()[child.child.filing_id].state=='correction_parent_unknown'
    ordinary=World(child.child);ordinary.second=int((child.now.value-NOW.value).total_seconds())+1
    ordinary.review();approval=ordinary.events[-1].record;grant=ordinary.admit(approval)
    ordinary.request(Action.CREATE_INSTANCE,approval,grant)
    rows=tuple(replace(row,sequence=child.start+len(child.events)+index) for index,row in enumerate(ordinary.events))
    with pytest.raises(ValueError,match='committed parent proof'):child.inspect(more=rows)


@pytest.mark.parametrize('defect',['source-unchanged','same-corporate','unknown-parent','missing-admission','wrong-parent-instance',
    'early-file','changed-file','missing-original','old-frame','stale-frame','expired-request','over-budget'])
def test_correction_requires_complete_fresh_same_parent_originals_and_new_signed_source(draft,defect):
    child=Correction(complete_world(draft));child.observe();child.finish()
    if defect=='source-unchanged':
        with pytest.raises(ValueError,match='changed owning source'):assert_annual_accounts_correction_source(draft.source,draft.source)
        return
    elif defect=='same-corporate':
        changed=changed_source(draft.source);snapshots=dict(changed.owning_snapshots)|{'corporate':draft.source.owning_snapshots['corporate']}
        changed=replace(changed,owning_snapshots=snapshots,upstream_sha256={key:annual_accounts_delivery_digest(value) for key,value in snapshots.items()})
        with pytest.raises(ValueError,match='new finalized'):assert_annual_accounts_correction_source(draft.source,changed)
        return
    elif defect=='unknown-parent':
        row=child.events[0];changed=replace(row.record,parent_binding=replace(row.record.parent_binding,filing_id=str(uuid4())))
        child.events[0]=replace(row,record=changed)
    elif defect=='missing-admission':child.events=child.events[1:]
    elif defect in ('early-file','changed-file','wrong-parent-instance','expired-request'):
        index=next(i for i,row in enumerate(child.events) if type(row.record) is ParentObservation and row.record.original.data_id is not None)
        row=child.events[index];original=row.record.original
        if defect=='early-file':original=replace(original,requested_at=child.stored.recorded_at)
        elif defect=='changed-file':original=replace(original,body_base64='Y2hhbmdlZA==')
        elif defect=='wrong-parent-instance':original=replace(original,instance_id='12345678/'+str(uuid4()))
        else:original=replace(original,requested_at=child.grant.expires_at,observed_at=child.grant.expires_at)
        child.events[index]=replace(row,record=replace(row.record,original=original))
    elif defect=='missing-original':child.events=child.events[:2]+child.events[3:]
    elif defect=='old-frame':child.events[-1]=replace(child.events[-1],record=replace(child.events[-1].record,parent_archive_frame_sha256='0'*64))
    elif defect=='stale-frame':child.events[-1]=replace(child.events[-1],recorded_at=Timestamp(child.now.value+timedelta(seconds=61)))
    else:
        child.events.pop()
        for _ in range(24):
            row=next(event.record for event in child.events if type(event.record) is ParentObservation);at=Timestamp(child.now.value+timedelta(seconds=1))
            child.append(replace(row,observation_id=str(uuid4()),original=replace(row.original,requested_at=at,observed_at=at)))
    with pytest.raises(ValueError):child.inspect()


def test_complete_history_rejects_missing_rows_multiple_roots_and_forked_corrections(draft):
    parent=complete_world(draft);child=Correction(parent);child.observe();child.finish();events=(*parent.events,*child.events)
    with pytest.raises(ValueError):inspect((parent.stored,child.stored),events[:-1],schemas=parent.schemas,
        expected_event_digests={str(row.sequence):row.record.sha256 for row in events})
    second=complete_world(prepare(changed_source(draft.source)),start_second=int((child.now.value-NOW.value).total_seconds())+1)
    offset=len(events)+100
    second_events=tuple(replace(row,sequence=row.sequence+offset) for row in second.events)
    all_events=(*events,*second_events)
    with pytest.raises(ValueError,match='more than one root'):inspect((parent.stored,child.stored,second.stored),all_events,schemas=parent.schemas,
        expected_event_digests={str(row.sequence):row.record.sha256 for row in all_events})
    fork=Correction(parent,after=child.now);fork.observe();fork.finish()
    fork_events=tuple(replace(row,sequence=row.sequence+offset) for row in fork.events)
    all_events=(*events,*fork_events)
    with pytest.raises(ValueError,match='forks'):inspect((parent.stored,child.stored,fork.stored),all_events,schemas=parent.schemas,
        expected_event_digests={str(row.sequence):row.record.sha256 for row in all_events})


@pytest.mark.parametrize('delay',[1,61])
def test_child_creation_requires_its_own_review_and_fresh_committed_parent_proof(draft,delay):
    child=Correction(complete_world(draft));child.observe();child.finish()
    ordinary=World(child.child);ordinary.second=int((child.now.value-NOW.value).total_seconds())+delay
    approval=ordinary.review();lease=ordinary.admit(approval);ordinary.request(Action.CREATE_INSTANCE,approval,lease)
    rows=tuple(replace(row,sequence=child.start+len(child.events)+index) for index,row in enumerate(ordinary.events))
    if delay==61:
        with pytest.raises(ValueError,match='stale parent proof'):child.inspect(more=rows)
    else:
        result=child.inspect(more=rows)
        assert result[child.child.filing_id].state=='creation_unknown'
        assert result[draft.filing_id].state=='technical_archive'


def test_later_parent_reconciliation_preserves_committed_child_lineage(draft):
    parent=complete_world(draft);child=Correction(parent);child.observe();child.finish()
    newer=replace(child.archive,frame_id=str(uuid4()))
    event=Event(child.events[-1].sequence+10,newer,Timestamp(child.now.value+timedelta(seconds=5)))
    parent.events.append(event);parent.expected[str(event.sequence)]=newer.sha256
    assert child.inspect()[child.child.filing_id].state=='draft'
    assert child.inspect()[draft.filing_id].state=='technical_archive'


def test_failed_first_get_and_explicit_refresh_preserve_review_without_renewing_the_grant(draft):
    child=Correction(complete_world(draft));child.observe()
    first=child.events[2].record;child.events=child.events[:2]
    child.append(replace(first,original=replace(first.original,body_base64=None,content_type=None,http_status=None,failure_code='connection_lost')))
    child.observe();child.finish()
    checked=replace(review(child.child),reviewed_evidence_sha256=child.child.sha256,reviewed_at=child.now)
    child.append(checked)
    child.now=Timestamp(child.now.value+timedelta(seconds=70))
    child.observe();child.finish()
    lease=replace(admission(child.child,approval=checked),issued_at=child.now,expires_at=Timestamp(child.now.value+timedelta(seconds=300)))
    child.append(lease);child.append(replace(intent(child.child,Action.CREATE_INSTANCE,checked,lease),prerequisite_sha256=child.child.sha256))
    assert child.inspect()[child.child.filing_id].state=='creation_unknown'
    assert sum(type(row.record) is ParentAdmission for row in child.events)==1


@pytest.mark.parametrize('result',['in-flight','failed','changed-pdf','late-same-attempt'])
def test_latest_parent_attempt_blocks_creation_even_when_older_proof_is_still_fresh(draft,result):
    child=Correction(complete_world(draft));child.observe();old_proof=child.finish()
    checked=replace(review(child.child),reviewed_evidence_sha256=child.child.sha256,reviewed_at=child.now);child.append(checked)
    if result!='late-same-attempt':child.begin()
    if result in ('failed','late-same-attempt'):
        old=next(row.record.original for row in child.events if type(row.record) is ParentObservation)
        at=Timestamp(child.now.value+timedelta(seconds=1))
        child.append(ParentObservation(binding(child.child),str(uuid4()),child.admitted.sha256,child.current_attempt.sha256,
            replace(old,requested_at=at,observed_at=at,http_status=None,content_type=None,body_base64=None,failure_code='connection_lost')))
    elif result=='changed-pdf':
        # A complete new bracket with changed bytes cannot replace the bound archive.
        child.events.pop();child.observe()
        index=next(i for i,row in enumerate(child.attempt) if row.original.purpose.value=='pdf')
        old=child.attempt[index];changed=replace(old,original=replace(old.original,body_base64='JVBERi1jaGFuZ2Vk'))
        child.attempt[index]=changed
        child.events=[replace(row,record=changed) if row.record is old else row for row in child.events]
    current=child.inspect()[child.child.filing_id]
    assert current.state=='correction_parent_unknown' and current.next_action is None
    lease=replace(admission(child.child,approval=checked),issued_at=child.now,expires_at=Timestamp(child.now.value+timedelta(seconds=300)))
    child.append(lease);child.append(replace(intent(child.child,Action.CREATE_INSTANCE,checked,lease),prerequisite_sha256=child.child.sha256))
    with pytest.raises(ValueError,match='committed parent proof'):child.inspect()
    child.events=child.events[:-2]
    child.append(replace(old_proof,frame_id=str(uuid4())))
    with pytest.raises(ValueError,match='latest'):child.inspect()


def test_late_response_from_an_older_attempt_does_not_poison_a_newer_complete_proof(draft):
    child=Correction(complete_world(draft));child.observe();child.finish();old=child.attempt[0]
    child.observe();child.finish();at=Timestamp(child.now.value+timedelta(seconds=1))
    child.append(replace(old,observation_id=str(uuid4()),original=replace(old.original,requested_at=at,observed_at=at,
        http_status=None,content_type=None,body_base64=None,failure_code='connection_lost')))
    assert child.inspect()[child.child.filing_id].state=='draft'
