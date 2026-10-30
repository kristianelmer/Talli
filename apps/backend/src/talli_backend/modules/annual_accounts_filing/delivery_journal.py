"""Retained operation graph: acknowledgments never replace observed byte effects."""
from dataclasses import dataclass
from collections.abc import Mapping
import base64

from talli_backend.shared.kernel import Timestamp
from .delivery import StoredAnnualAccountsDeliveryDraft
from .delivery_events import (
    AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryStage as Stage,AnnualAccountsDeliveryAction as Action,
    AnnualAccountsDeliveryReview as Review,AnnualAccountsFiniteAdmission as Admission,AnnualAccountsDeliveryIntent as Intent,
    AnnualAccountsDeliveryCompletion as Completion,AnnualAccountsDeliveryObservation as Observation,
    AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
)
from .delivery_originals import APP_ID,_json_original,_inspect_instance_bytes,_instance
from .delivery_frames import inspect_annual_accounts_delivery_frame

_RECORDS=(Review,Admission,Intent,Completion,Observation,Frame)
_PREVIOUS={Action.UPLOAD_MAIN_FORM:Action.CREATE_INSTANCE,Action.UPLOAD_COMPANY_ACCOUNTS:Action.UPLOAD_MAIN_FORM,
    Action.CONFIRM:Action.UPLOAD_COMPANY_ACCOUNTS,Action.SIGN:Action.CONFIRM}
_FRAME_AFTER={Kind.CREATE_TARGET:Action.CREATE_INSTANCE,Kind.MAIN_UPLOADED:Action.UPLOAD_MAIN_FORM,
    Kind.UPLOAD_REVIEW:Action.UPLOAD_COMPANY_ACCOUNTS,Kind.SIGN_REVIEW:Action.CONFIRM,Kind.ARCHIVE:Action.SIGN}


@dataclass(frozen=True,slots=True)
class StoredAnnualAccountsDeliveryEvent:
    sequence: int
    record: object
    recorded_at: Timestamp

    def __post_init__(self):
        from .delivery_corrections import CORRECTION_RECORDS
        if (type(self.sequence) is not int or self.sequence<1 or type(self.record) not in (*_RECORDS,*CORRECTION_RECORDS)
                or type(self.recorded_at) is not Timestamp):raise ValueError('Accounts retained event identity is invalid.')


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryJournalInspection:
    filing_id: str
    draft_sha256: str
    known_instance: str | None
    state: str
    next_action: Action | None
    prerequisite_sha256: str | None
    event_sha256: tuple[str,...]


def _created(completion,draft,observed_at):
    if (completion.action is not Action.CREATE_INSTANCE or completion.http_status not in (200,201)
            or type(completion.response_content_type) is not str or completion.response_content_type.split(';',1)[0].strip().lower()!='application/json'
            or completion.response_body_base64 is None):return None,None
    try:
        raw=base64.b64decode(completion.response_body_base64,validate=True);value=_json_original(raw)
        identity=value['id'];party,_=_instance(identity);owner=value['instanceOwner']
        if (value.get('appId')!=APP_ID or type(owner) is not dict or owner.get('organisationNumber')!=draft.source.organization_number
                or type(owner.get('partyId')) not in (int,str) or str(owner['partyId'])!=party):return None,None
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return None,None
    try:return identity,_inspect_instance_bytes(raw,identity,draft.source.organization_number,observed_at)
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return identity,None


def inspect_annual_accounts_delivery_journal(stored,events,*,schemas,expected_event_digests):
    """Validate complete retained links; current source/admission is checked at use."""
    if type(stored) is not StoredAnnualAccountsDeliveryDraft or not isinstance(events,(tuple,list)):raise ValueError()
    if any(type(row) is not StoredAnnualAccountsDeliveryEvent for row in events):raise ValueError('Accounts event enumeration has an unknown row type.')
    if (not isinstance(expected_event_digests,Mapping) or expected_event_digests!={str(row.sequence):row.record.sha256 for row in events}):
        raise ValueError('Accounts journal differs from its complete stored enumeration commitment.')
    draft=stored.draft;by_hash={};by_slot={};intents={};frames={};observations=[];known=None;root_ids=None;previous_sequence=0;usage={}
    def use(admission):
        count=usage.get(admission.sha256,0)+1
        if count>admission.maximum_requests:raise ValueError('Accounts retained requests exceed their finite admission budget.')
        usage[admission.sha256]=count
    previous_time=stored.recorded_at
    known_references={}
    def learn_references(metadata,observed_at):
        for item in metadata.data:
            reference=(item.data_id,item.data_type)
            prior=known_references.get(reference)
            if prior is None or observed_at.value<prior.value:known_references[reference]=observed_at
    for event in events:
        if type(event) is not StoredAnnualAccountsDeliveryEvent or event.sequence<=previous_sequence:raise ValueError('Accounts event enumeration is ambiguous.')
        previous_sequence=event.sequence;record=event.record
        if event.recorded_at.value<previous_time.value:raise ValueError('Accounts commit order contradicts its event sequence.')
        previous_time=event.recorded_at
        record.binding.assert_draft(draft)
        if (record.sha256 in by_hash or record.slot in by_slot or event.recorded_at.value<stored.recorded_at.value):raise ValueError('Accounts event history is incomplete or duplicated.')
        if type(record) is Review:
            record.assert_draft(draft)
            if record.reviewed_at.value>event.recorded_at.value:raise ValueError('Accounts review time is in the future.')
            if record.stage is Stage.PREPARE:
                if record.reviewed_evidence_sha256!=draft.sha256 or intents:raise ValueError('Accounts preparation review differs from its exact draft.')
            else:
                kind=Kind.UPLOAD_REVIEW if record.stage is Stage.CONFIRM else Kind.SIGN_REVIEW
                matches=[value for value in frames.values() if value.kind is kind and value.review_sha256==record.reviewed_evidence_sha256]
                if not matches:raise ValueError('Accounts process review lacks retained complete read evidence.')
                matches[-1].assert_action(Action.CONFIRM if record.stage is Stage.CONFIRM else Action.SIGN)
        elif type(record) is Admission:
            if record.organization_number!=draft.source.organization_number:raise ValueError('Accounts admission organization differs.')
            record.assert_current(event.recorded_at)
            if record.port is Port.KNOWN_READ:
                dependency=by_hash.get(record.dependency_intent_sha256)
                if dependency is None or type(dependency.record) is not Intent or known is None or record.known_instance!=known:
                    raise ValueError('Accounts read admission has no retained known target.')
            else:
                review=by_hash.get(record.review_sha256)
                if review is None or type(review.record) is not Review or review.record.stage is not record.stage:
                    raise ValueError('Accounts admission must follow its retained owner review.')
                if record.issued_at.value<review.recorded_at.value:raise ValueError('Accounts admission predates its committed review.')
                if record.stage is not Stage.PREPARE and (known is None or record.known_instance!=known):raise ValueError('Accounts admission target is unknown.')
        elif type(record) is Intent:
            review=by_hash.get(record.review_sha256);admission=by_hash.get(record.admission_sha256)
            if review is None or admission is None or type(review.record) is not Review or type(admission.record) is not Admission:raise ValueError('Accounts intent lacks review/admission originals.')
            record.assert_draft(draft,review.record,admission.record);admission.record.assert_current(event.recorded_at)
            use(admission.record)
            if record.action is Action.CREATE_INSTANCE:
                if intents or record.prerequisite_sha256!=draft.sha256:raise ValueError('Accounts creation has no exact initial prerequisite.')
            else:
                predecessor=intents.get(_PREVIOUS[record.action]);frame=frames.get(record.prerequisite_sha256)
                if predecessor is None or frame is None or known is None or record.target_instance!=known:raise ValueError('Accounts operation predecessor is unknown.')
                frame.assert_action(record.action);frame.assert_fresh(event.recorded_at,after=predecessor.recorded_at)
                if root_ids is None or (frame.main_data_id,frame.accounts_data_id)!=root_ids:
                    raise ValueError('Accounts structured data identities changed after creation.')
                if record.action in (Action.CONFIRM,Action.SIGN) and review.record.reviewed_evidence_sha256!=frame.review_sha256:
                    raise ValueError('Accounts process documents changed after owner review.')
                if record.action is Action.UPLOAD_MAIN_FORM and record.target_data!=frame.main_data_id:raise ValueError()
                if record.action is Action.UPLOAD_COMPANY_ACCOUNTS and record.target_data!=frame.accounts_data_id:raise ValueError()
            intents[record.action]=event
        elif type(record) is Completion:
            request=by_hash.get(record.intent_sha256)
            if request is None or type(request.record) is not Intent or request.record.action is not record.action:
                raise ValueError('Accounts completion has no retained matching intent.')
            if record.action is Action.CREATE_INSTANCE:
                known,root=_created(record,draft,event.recorded_at)
                if root is not None:
                    root_ids=tuple(next(item.data_id for item in root.data if item.data_type==kind) for kind in ('Hovedskjema','Underskjema'))
                    learn_references(root,event.recorded_at)
        elif type(record) is Observation:
            request=by_hash.get(record.intent_sha256);admission=by_hash.get(record.admission_sha256)
            if (request is None or type(request.record) is not Intent or admission is None or type(admission.record) is not Admission
                    or known is None or record.original.instance_id!=known):raise ValueError('Accounts read does not follow a known retained target.')
            original=record.original
            if original.data_id is not None:
                expected={'main_form':'Hovedskjema','company_accounts':'Underskjema','pdf':'ref-data-as-pdf','signature':'signature'}[original.purpose.value]
                learned=known_references.get((original.data_id,expected))
                if learned is None or learned.value>original.requested_at.value:
                    raise ValueError('Accounts file observation has no metadata reference known before its request.')
            if (record.original.observed_at.value>event.recorded_at.value
                    or record.original.requested_at.value<request.recorded_at.value):raise ValueError('Accounts read observation does not follow its intent.')
            if admission.record.port is Port.KNOWN_READ:
                if admission.record.dependency_intent_sha256!=request.record.sha256:raise ValueError('Accounts recovery read belongs to another frontier.')
            elif admission.record.known_instance is not None and admission.record.known_instance!=known:raise ValueError()
            admission.record.assert_current(record.original.requested_at)
            use(admission.record)
            observations.append(record)
            if original.purpose.value=='instance':
                from .delivery_originals import inspect_annual_accounts_instance
                try:
                    current=inspect_annual_accounts_instance(original,organization_number=draft.source.organization_number)
                    learn_references(current,original.observed_at)
                except (ValueError,KeyError,TypeError,AttributeError):pass
        else:
            predecessor=intents.get(_FRAME_AFTER[record.kind])
            if predecessor is None or known is None:raise ValueError('Accounts frame has no preceding operation.')
            if any(reference not in by_hash or type(by_hash[reference].record) is not Observation for reference in record.observation_sha256):
                raise ValueError('Accounts frame references missing retained originals.')
            frame=inspect_annual_accounts_delivery_frame(record,observations,draft=draft,known_instance=known,schemas=schemas)
            if frame.first_requested_at.value<predecessor.recorded_at.value:raise ValueError('Accounts frame predates its operation.')
            if record.kind is Kind.CREATE_TARGET:
                if root_ids is not None and root_ids!=(frame.main_data_id,frame.accounts_data_id):raise ValueError('Accounts initial structured data identities changed.')
                root_ids=(frame.main_data_id,frame.accounts_data_id)
            frames[record.sha256]=frame
        by_hash[record.sha256]=event;by_slot[record.slot]=event
    def latest(kind):return next((value for value in reversed(tuple(frames.values())) if value.kind is kind),None)
    def result(state,action=None,frame=None):return AnnualAccountsDeliveryJournalInspection(draft.filing_id,draft.sha256,known,state,action,
        frame.prerequisite_sha256 if frame else None,tuple(by_hash))
    if Action.CREATE_INSTANCE not in intents:return result('reviewed' if 'review:prepare' in by_slot else 'draft',Action.CREATE_INSTANCE)
    if known is None:return result('creation_unknown')
    if Action.UPLOAD_MAIN_FORM not in intents:
        frame=latest(Kind.CREATE_TARGET)
        return result('created',Action.UPLOAD_MAIN_FORM if frame else None,frame)
    if Action.UPLOAD_COMPANY_ACCOUNTS not in intents:
        frame=latest(Kind.MAIN_UPLOADED)
        return result('main_uploaded' if frame else 'main_upload_unknown',Action.UPLOAD_COMPANY_ACCOUNTS if frame else None,frame)
    if Action.CONFIRM not in intents:
        frame=latest(Kind.UPLOAD_REVIEW)
        if frame is None:return result('accounts_upload_unknown')
        if frame.has_validation_errors is not False:return result('validation_blocked',frame=frame)
        return result('confirmation_review',Action.CONFIRM,frame)
    if Action.SIGN not in intents:
        frame=latest(Kind.SIGN_REVIEW)
        if frame is None:return result('confirmation_unknown')
        if frame.has_validation_errors is not False:return result('validation_blocked',frame=frame)
        return result('person_review',Action.SIGN,frame)
    frame=latest(Kind.ARCHIVE)
    return result('technical_archive' if frame else 'signing_unknown',frame=frame)
