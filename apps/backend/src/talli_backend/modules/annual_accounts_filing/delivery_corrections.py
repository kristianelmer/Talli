"""A correction starts from a fresh read of one retained technical archive.

The successor records add no mutation authority. The child still needs
its own exact draft, owner reviews, finite grants and submit-once journal.
"""
from dataclasses import dataclass,fields
from datetime import datetime
import hashlib
import json

from talli_backend.shared.kernel import Timestamp,CompanyId,IncomeYear,ActorId,ActorKind,UserId
from .delivery import _canonical,_approval
from .delivery_events import (
    _Record,_sha,AnnualAccountsDeliveryBinding as Binding,AnnualAccountsFiniteAdmission as Admission,
    AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryObservation as Observation,
    AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
    AnnualAccountsDeliveryIntent as Intent,AnnualAccountsDeliveryAction as Action,
    decode_annual_accounts_delivery_record,
)
from .delivery_originals import _uuid,AnnualAccountsDeliveryOriginal as Original,AnnualAccountsReadPurpose as Purpose,inspect_annual_accounts_instance
from .delivery_frames import inspect_annual_accounts_delivery_frame


@dataclass(frozen=True,slots=True)
class AnnualAccountsCorrectionReadGrant(Admission):
    """Up to three archive brackets in one lease; no mutation or renewal."""
    codec_version='annual-accounts-correction-read-grant-v1'

    def __post_init__(self):
        if (self.port is not Port.KNOWN_READ or type(self.maximum_requests) is not int
                or not 1<=self.maximum_requests<=27):raise ValueError('Accounts parent read grant exceeds its finite budget.')
        value={field.name:getattr(self,field.name) for field in fields(Admission)}
        Admission(**(value|{'maximum_requests':min(self.maximum_requests,16)}))


@dataclass(frozen=True,slots=True)
class AnnualAccountsCorrectionParentAdmission(_Record):
    binding: Binding
    parent_binding: Binding
    parent_sign_intent_sha256: str
    parent_archive_frame_sha256: str
    grant: AnnualAccountsCorrectionReadGrant
    codec_version='annual-accounts-correction-parent-admission-v1'

    def __post_init__(self):
        _sha(self.parent_sign_intent_sha256)
        _sha(self.parent_archive_frame_sha256)
        if (type(self.binding) is not Binding or type(self.parent_binding) is not Binding
                or type(self.grant) is not AnnualAccountsCorrectionReadGrant or self.grant.binding!=self.binding
                or self.grant.dependency_intent_sha256!=self.parent_sign_intent_sha256
                or self.binding.filing_id==self.parent_binding.filing_id
                or (self.binding.company_id,self.binding.income_year,self.binding.actor_id)
                    !=(self.parent_binding.company_id,self.parent_binding.income_year,self.parent_binding.actor_id)):
            raise ValueError('Accounts correction admission differs from its child or parent.')

    @property
    def slot(self):return 'correction:admission'


@dataclass(frozen=True,slots=True)
class AnnualAccountsCorrectionParentAttempt(_Record):
    binding: Binding
    attempt_id: str
    admission_sha256: str
    requested_at: Timestamp
    codec_version='annual-accounts-correction-parent-attempt-v1'

    def __post_init__(self):
        _uuid(self.attempt_id);_sha(self.admission_sha256)
        if type(self.binding) is not Binding or type(self.requested_at) is not Timestamp:raise ValueError()

    @property
    def slot(self):return 'correction:attempt:'+self.attempt_id


@dataclass(frozen=True,slots=True)
class AnnualAccountsCorrectionParentObservation(_Record):
    binding: Binding
    observation_id: str
    admission_sha256: str
    attempt_sha256: str
    original: Original
    codec_version='annual-accounts-correction-parent-observation-v1'

    def __post_init__(self):
        _uuid(self.observation_id);_sha(self.admission_sha256);_sha(self.attempt_sha256)
        if type(self.binding) is not Binding or type(self.original) is not Original:raise ValueError()

    @property
    def slot(self):return 'correction:observation:'+self.observation_id


@dataclass(frozen=True,slots=True)
class AnnualAccountsCorrectionParentFrame(_Record):
    binding: Binding
    frame_id: str
    attempt_sha256: str
    parent_binding: Binding
    parent_archive_frame_sha256: str
    observation_sha256: tuple[str,...]
    codec_version='annual-accounts-correction-parent-frame-v1'

    def __post_init__(self):
        _uuid(self.frame_id);_sha(self.attempt_sha256);_sha(self.parent_archive_frame_sha256)
        if (type(self.binding) is not Binding or type(self.parent_binding) is not Binding
                or not isinstance(self.observation_sha256,(tuple,list)) or not 5<=len(self.observation_sha256)<=10):raise ValueError()
        object.__setattr__(self,'observation_sha256',tuple(self.observation_sha256))
        if len(set(self.observation_sha256))!=len(self.observation_sha256):raise ValueError()
        for value in self.observation_sha256:_sha(value)

    @property
    def slot(self):return 'correction:parent:'+self.frame_id


CORRECTION_RECORDS=(AnnualAccountsCorrectionParentAdmission,AnnualAccountsCorrectionParentAttempt,
    AnnualAccountsCorrectionParentObservation,AnnualAccountsCorrectionParentFrame)


def decode_annual_accounts_delivery_record_v2(raw,expected_sha256):
    """Accept predecessor bytes unchanged; decode only these exact new shapes."""
    def obj(value,keys):
        if type(value) is not dict or set(value)!=set(keys):raise ValueError()
        return value
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError()
            result[key]=value
        return result
    def scalar(value):return obj(value,('value',))['value']
    def binding(value):
        value=obj(value,(field.name for field in fields(Binding)))
        actor=obj(value['actor_id'],('kind','subject'));year=scalar(value['income_year'])
        if type(year) is not int:raise ValueError()
        return Binding(value['filing_id'],CompanyId(scalar(value['company_id'])),IncomeYear(year),
            ActorId(ActorKind(actor['kind']),UserId(scalar(actor['subject']))),value['draft_sha256'])
    def constant(_):raise ValueError()
    try:
        if (type(raw) is not str or len(raw.encode())>32*1024*1024
                or hashlib.sha256(raw.encode()).hexdigest()!=expected_sha256):raise ValueError()
        root=obj(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version','record'))
        classes={kind.codec_version:kind for kind in CORRECTION_RECORDS}
        if root['version'] not in classes:return decode_annual_accounts_delivery_record(raw,expected_sha256)
        cls=classes[root['version']];value=obj(root['record'],(field.name for field in fields(cls)))
        value=value|{'binding':binding(value['binding'])}
        if cls is AnnualAccountsCorrectionParentAdmission:
            value['parent_binding']=binding(value['parent_binding'])
            grant=obj(value['grant'],(field.name for field in fields(AnnualAccountsCorrectionReadGrant)))
            value['grant']=AnnualAccountsCorrectionReadGrant(**(grant|{'binding':binding(grant['binding']),
                'port':Port(grant['port']),'issued_at':Timestamp(datetime.fromisoformat(scalar(grant['issued_at']))),
                'expires_at':Timestamp(datetime.fromisoformat(scalar(grant['expires_at'])))}))
        elif cls is AnnualAccountsCorrectionParentFrame:value['parent_binding']=binding(value['parent_binding'])
        elif cls is AnnualAccountsCorrectionParentAttempt:value['requested_at']=Timestamp(datetime.fromisoformat(scalar(value['requested_at'])))
        else:
            original=obj(value['original'],(field.name for field in fields(Original)))
            value['original']=Original(**(original|{'purpose':Purpose(original['purpose']),
                'requested_at':Timestamp(datetime.fromisoformat(scalar(original['requested_at']))),
                'observed_at':Timestamp(datetime.fromisoformat(scalar(original['observed_at'])))}))
        result=cls(**value)
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Accounts correction record is invalid or its exact bytes changed.') from None


def assert_annual_accounts_correction_source(parent,child):
    """A caller contact/date change cannot create a new financial filing."""
    if ((parent.company_id,parent.income_year,parent.organization_number)!=(child.company_id,child.income_year,child.organization_number)
            or parent.sha256==child.sha256):raise ValueError('Accounts correction needs changed owning source.')
    _approval(parent);_approval(child)
    before=parent.owning_snapshots['corporate']['readiness'];after=child.owning_snapshots['corporate']['readiness']
    if (any(before[key]==after[key] for key in ('decision_id','decision_hash','finalization_id'))
            or before['signed_artifact_hashes']==after['signed_artifact_hashes']):
        raise ValueError('Accounts correction requires a new finalized signed Corporate decision.')


def inspect_annual_accounts_correction_parent(child,parent,parent_events,child_events,*,schemas):
    """Inspect a possibly incomplete read attempt; return its terminal lineage.

    Failed and late responses remain retainable. Only a complete fresh frame
    whose original bytes match the parent's latest archive permits a child.
    """
    from .delivery_journal import inspect_annual_accounts_delivery_journal
    terminal=inspect_annual_accounts_delivery_journal(parent,parent_events,schemas=schemas,
        expected_event_digests={str(row.sequence):row.record.sha256 for row in parent_events})
    if terminal.state!='technical_archive' or terminal.known_instance is None:raise ValueError('Accounts correction parent has no technical archive.')
    admissions=[row for row in child_events if type(row.record) is AnnualAccountsCorrectionParentAdmission]
    if len(admissions)!=1:raise ValueError('Accounts correction parent admission is missing or duplicated.')
    admitted=admissions[0];admission=admitted.record;admission.binding.assert_draft(child.draft);admission.parent_binding.assert_draft(parent.draft)
    grant=admission.grant
    sign=next(row for row in parent_events if type(row.record) is Intent and row.record.action is Action.SIGN)
    archives=[row for row in parent_events if type(row.record) is Frame and row.record.kind is Kind.ARCHIVE and row.sequence<admitted.sequence]
    if not archives:raise ValueError('Accounts parent archive did not precede its admission.')
    archive=archives[-1]
    if (admission.parent_sign_intent_sha256!=sign.record.sha256 or grant.known_instance!=terminal.known_instance
            or admission.parent_archive_frame_sha256!=archive.record.sha256
            or grant.organization_number!=parent.draft.source.organization_number
            or grant.issued_at.value<max(child.recorded_at.value,archive.recorded_at.value)
            or grant.issued_at.value>admitted.recorded_at.value):raise ValueError('Accounts correction admission predates its retained prerequisites.')
    grant.assert_current(admitted.recorded_at)
    observations=[];references={};lineages=[];attempts={}
    for event in child_events:
        record=event.record
        record.binding.assert_draft(child.draft)
        if type(record) not in CORRECTION_RECORDS:continue
        if type(record) is AnnualAccountsCorrectionParentAdmission:continue
        if event.sequence<=admitted.sequence:raise ValueError('Accounts correction read predates its committed admission.')
        if type(record) is AnnualAccountsCorrectionParentAttempt:
            if (record.admission_sha256!=admission.sha256 or len(attempts)>=3
                    or not admitted.recorded_at.value<=record.requested_at.value<=event.recorded_at.value):
                raise ValueError('Accounts parent read attempt is not independently committed within its admission.')
            grant.assert_current(event.recorded_at);attempts[record.sha256]=event
        elif type(record) is AnnualAccountsCorrectionParentObservation:
            original=record.original
            attempt=attempts.get(record.attempt_sha256)
            if (record.admission_sha256!=admission.sha256 or original.instance_id!=terminal.known_instance
                    or attempt is None or original.requested_at.value<attempt.recorded_at.value
                    or original.observed_at.value>event.recorded_at.value):
                raise ValueError('Accounts correction original differs from its finite known parent read.')
            grant.assert_current(original.requested_at)
            if len(observations)>=grant.maximum_requests:raise ValueError('Accounts correction read budget exhausted.')
            if original.data_id is not None:
                kind={Purpose.MAIN_FORM:'Hovedskjema',Purpose.COMPANY_ACCOUNTS:'Underskjema',Purpose.PDF:'ref-data-as-pdf',Purpose.SIGNATURE:'signature'}[original.purpose]
                learned=references.get((original.data_id,kind))
                if learned is None or learned.value>original.requested_at.value:raise ValueError('Accounts correction file was unknown before its request.')
            observations.append(record)
            if original.purpose is Purpose.INSTANCE:
                try:metadata=inspect_annual_accounts_instance(original,organization_number=parent.draft.source.organization_number)
                except (ValueError,TypeError,KeyError,AttributeError):continue
                for item in metadata.data:
                    key=(item.data_id,item.data_type);previous=references.get(key)
                    if previous is None or previous.value>original.observed_at.value:references[key]=original.observed_at
        else:
            if len(lineages)>=3:raise ValueError('Accounts correction parent proof attempts exceed their finite bound.')
            attempt=attempts.get(record.attempt_sha256)
            if attempt is None or attempt is not next(reversed(attempts.values())):
                raise ValueError('Accounts correction proof does not cover the latest committed read attempt.')
            record.parent_binding.assert_draft(parent.draft)
            if record.parent_archive_frame_sha256!=archive.record.sha256:raise ValueError('Accounts correction does not bind the latest retained parent archive.')
            selected={row.sha256:row for row in observations}
            if any(ref not in selected for ref in record.observation_sha256):raise ValueError('Accounts correction parent original is missing.')
            if (any(selected[ref].attempt_sha256!=record.attempt_sha256 for ref in record.observation_sha256)
                    or record.observation_sha256[-1]!=next(row.sha256 for row in reversed(observations) if row.attempt_sha256==record.attempt_sha256)):
                raise ValueError('Accounts correction proof omits the latest result of its read attempt.')
            # Reuse the archive byte inspector with explicit parent bindings.
            originals=tuple(Observation(admission.parent_binding,row.observation_id,grant.sha256,sign.record.sha256,row.original)
                for row in (selected[ref] for ref in record.observation_sha256))
            fresh=Frame(admission.parent_binding,record.frame_id,Kind.ARCHIVE,tuple(row.sha256 for row in originals))
            inspected=inspect_annual_accounts_delivery_frame(fresh,originals,draft=parent.draft,known_instance=terminal.known_instance,schemas=schemas)
            inspected.assert_fresh(event.recorded_at,after=attempt.recorded_at)
            retained=inspect_annual_accounts_delivery_frame(archive.record,tuple(row.record for row in parent_events if type(row.record) is Observation),
                draft=parent.draft,known_instance=terminal.known_instance,schemas=schemas)
            if inspected.review_sha256!=retained.review_sha256:raise ValueError('Accounts correction parent originals changed after its retained archive.')
            assert_annual_accounts_correction_source(parent.draft.source,child.draft.source)
            lineages.append(event)
    return tuple(lineages)


def inspect_annual_accounts_delivery_history(stored_drafts,events,*,schemas,expected_event_digests):
    """A positive complete enumeration must describe one finite, unforked chain."""
    from .delivery_journal import inspect_annual_accounts_delivery_journal
    drafts={row.draft.filing_id:row for row in stored_drafts}
    if (len(drafts)!=len(stored_drafts) or not 1<=len(drafts)<=64
            or expected_event_digests!={str(row.sequence):row.record.sha256 for row in events}
            or len(expected_event_digests)!=len(events)):raise ValueError('Accounts complete history enumeration differs.')
    first=next(iter(drafts.values())).draft
    for stored in drafts.values():
        if (stored.draft.source.company_id,stored.draft.source.income_year)!=(first.source.company_id,first.source.income_year):raise ValueError()
    previous=0;previous_time=None;slots=set();hashes=set();grouped={key:[] for key in drafts}
    for event in events:
        record=event.record;key=record.binding.filing_id
        if (key not in drafts or event.sequence<=previous or previous_time is not None and event.recorded_at.value<previous_time
                or (key,record.slot) in slots or record.sha256 in hashes or event.recorded_at.value<drafts[key].recorded_at.value):raise ValueError('Accounts history contains missing, duplicated or out of order events.')
        record.binding.assert_draft(drafts[key].draft)
        grouped[key].append(event);slots.add((key,record.slot));hashes.add(record.sha256)
        previous=event.sequence;previous_time=event.recorded_at.value
    inspections={};parents={};children={};roots=[]
    for key,stored in drafts.items():
        rows=grouped[key];ordinary=tuple(row for row in rows if type(row.record) not in CORRECTION_RECORDS)
        inspections[key]=inspect_annual_accounts_delivery_journal(stored,ordinary,schemas=schemas,
            expected_event_digests={str(row.sequence):row.record.sha256 for row in ordinary})
        corrections=tuple(row for row in rows if type(row.record) in CORRECTION_RECORDS)
        create=next((row for row in ordinary if type(row.record) is Intent and row.record.action is Action.CREATE_INSTANCE),None)
        if corrections:
            admission=next((row.record for row in corrections if type(row.record) is AnnualAccountsCorrectionParentAdmission),None)
            if admission is None or admission.parent_binding.filing_id not in drafts:raise ValueError('Accounts correction parent is missing.')
            parent_key=admission.parent_binding.filing_id
            if parent_key in children:raise ValueError('Accounts correction history forks.')
            children[parent_key]=key;parents[key]=parent_key
            parent_rows=tuple(row for row in grouped[parent_key] if type(row.record) not in CORRECTION_RECORDS)
            lineages=inspect_annual_accounts_correction_parent(stored,drafts[parent_key],parent_rows,corrections,schemas=schemas)
            latest_attempt=next((row for row in reversed(corrections) if type(row.record) is AnnualAccountsCorrectionParentAttempt
                and (create is None or row.sequence<create.sequence)),None)
            lineage=next((row for row in reversed(lineages) if latest_attempt is not None
                and row.record.attempt_sha256==latest_attempt.record.sha256),None)
            if lineage is not None and any(type(row.record) is AnnualAccountsCorrectionParentObservation
                    and row.record.attempt_sha256==lineage.record.attempt_sha256 and row.sequence>lineage.sequence
                    and (create is None or row.sequence<create.sequence) for row in corrections):lineage=None
            if not lineages and ordinary:raise ValueError('Accounts child operation precedes its committed parent proof.')
            if create is not None and any(type(row.record) is AnnualAccountsCorrectionParentAttempt and row.sequence>=create.sequence for row in corrections):
                raise ValueError('Accounts parent read attempt starts after child creation.')
            if create is not None and (lineage is None or any(row.sequence>=create.sequence for row in lineages)):raise ValueError('Accounts child creation precedes its committed parent proof.')
            if lineage is not None:
                if any(row.sequence<=lineages[0].sequence for row in ordinary):raise ValueError('Accounts child operation precedes its committed parent proof.')
                if create is not None:
                    selected=set(lineage.record.observation_sha256)
                    started=min(row.record.original.requested_at.value for row in corrections
                        if type(row.record) is AnnualAccountsCorrectionParentObservation and row.record.sha256 in selected)
                    if not 0<=(create.recorded_at.value-started).total_seconds()<=60:raise ValueError('Accounts child creation has stale parent proof.')
                    latest=next(row.record for row in reversed(parent_rows) if type(row.record) is Frame and row.record.kind is Kind.ARCHIVE and row.sequence<create.sequence)
                    bound=next(row.record for row in parent_rows if row.record.sha256==admission.parent_archive_frame_sha256)
                    originals=tuple(row.record for row in parent_rows if type(row.record) is Observation)
                    inspections_at_create=[inspect_annual_accounts_delivery_frame(item,originals,draft=drafts[parent_key].draft,
                        known_instance=admission.grant.known_instance,schemas=schemas) for item in (latest,bound)]
                    if inspections_at_create[0].review_sha256!=inspections_at_create[1].review_sha256:raise ValueError('Accounts parent archive changed before child creation.')
            else:
                from dataclasses import replace
                inspections[key]=replace(inspections[key],state='correction_parent_unknown',next_action=None)
        elif create is not None:roots.append(key)
    if len(roots)>1:raise ValueError('Accounts history has more than one root creation.')
    for child in parents:
        visited=set();key=child
        while key in parents:
            if key in visited:raise ValueError('Accounts correction history cycles.')
            visited.add(key);key=parents[key]
        if key not in roots:raise ValueError('Accounts correction lineage has no created root.')
    known=[row.known_instance for row in inspections.values() if row.known_instance is not None]
    if len(set(known))!=len(known):raise ValueError('Accounts correction reused an existing instance identity.')
    return inspections
