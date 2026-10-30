"""Accounts owner reviews, submit-once dispatch and known original recovery."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC,datetime
import base64
from uuid import uuid4

from talli_backend.application.annual_accounts_delivery_source import read_annual_accounts_delivery_source
from talli_backend.modules.annual_accounts_filing.delivery import annual_accounts_source_is_synthetic
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsSourceQuery,project_annual_accounts_source,
    AnnualAccountsDeliveryBinding as Binding,AnnualAccountsDeliveryStage as Stage,
    AnnualAccountsDeliveryAction as Action,AnnualAccountsFrameKind as Kind,AnnualAccountsReadPurpose as Purpose,
    AnnualAccountsDeliveryReview as Review,AnnualAccountsFiniteAdmission as Admission,
    AnnualAccountsDeliveryIntent as Intent,AnnualAccountsDeliveryObservation as Observation,
    AnnualAccountsDeliveryFrameRecord as Frame,StoredAnnualAccountsDeliveryEvent as Event,
    inspect_annual_accounts_delivery_journal,inspect_annual_accounts_delivery_frame,inspect_annual_accounts_instance,
    inspect_annual_accounts_delivery_history,
    AnnualAccountsCorrectionParentAdmission as ParentAdmission,AnnualAccountsCorrectionParentObservation as ParentObservation,
    AnnualAccountsCorrectionParentAttempt as ParentAttempt,
    AnnualAccountsCorrectionParentFrame as ParentFrame,
)
from talli_backend.shared.kernel import Timestamp

_KINDS={Action.CREATE_INSTANCE:Kind.CREATE_TARGET,Action.UPLOAD_MAIN_FORM:Kind.MAIN_UPLOADED,
    Action.UPLOAD_COMPANY_ACCOUNTS:Kind.UPLOAD_REVIEW,Action.CONFIRM:Kind.SIGN_REVIEW,Action.SIGN:Kind.ARCHIVE}
_STAGES={Action.CREATE_INSTANCE:Stage.PREPARE,Action.UPLOAD_MAIN_FORM:Stage.PREPARE,
    Action.UPLOAD_COMPANY_ACCOUNTS:Stage.PREPARE,Action.CONFIRM:Stage.CONFIRM,Action.SIGN:Stage.SIGN}


@dataclass(frozen=True,slots=True)
class AccountsDeliveryState:
    stored: object
    events: tuple[Event,...]
    inspection: object
    history_drafts: tuple=()
    history_events: tuple=()

    def slot(self,slot):return next((row for row in self.events if row.record.slot==slot),None)


class AnnualAccountsDeliveryWorkflow:
    def __init__(self,*,corporate,schemas,ports=None,now=None,synthetic_signoff=None):
        self._corporate,self._schemas,self._ports=corporate,schemas,ports
        self._synthetic_signoff=synthetic_signoff
        self._now=now or (lambda:Timestamp(datetime.now(UTC)))

    def _inspect(self,stored,events,commitment,*,history_drafts=(),history_events=()):
        try:
            if history_drafts:
                if commitment!={str(row.sequence):row.record.sha256 for row in events}:raise ValueError()
                combined=tuple(sorted((*[row for row in history_events if row.record.binding.filing_id!=stored.draft.filing_id],*events),key=lambda row:row.sequence))
                inspection=inspect_annual_accounts_delivery_history(history_drafts,combined,schemas=self._schemas,
                    expected_event_digests={str(row.sequence):row.record.sha256 for row in combined})[stored.draft.filing_id]
            else:
                combined=tuple(events)
                inspection=inspect_annual_accounts_delivery_journal(stored,events,schemas=self._schemas,expected_event_digests=commitment)
            return AccountsDeliveryState(stored,tuple(events),inspection,tuple(history_drafts),combined)
        except (ValueError,TypeError,KeyError,AttributeError):raise AnnualAccountsError.unavailable() from None

    async def _state(self,transaction,query,filing_id):
        snapshot=await transaction.filing_source_snapshot(query);facts=project_annual_accounts_source(query,snapshot)
        if snapshot.contract_version not in ('annual-accounts-source-v3','annual-accounts-source-v4') or facts.history_coverage.status!='complete':
            raise AnnualAccountsError.unavailable()
        stored=next((row for row in snapshot.delivery_drafts if row.draft.filing_id==filing_id),None)
        if stored is None:raise AnnualAccountsError.not_found()
        if stored.draft.prepared_by!=query.actor_id:raise AnnualAccountsError.forbidden()
        events=tuple(row for row in snapshot.delivery_events if row.record.binding.filing_id==filing_id)
        commitments=snapshot.coverage['deliveryEventDigests']
        return self._inspect(stored,events,{str(row.sequence):commitments[str(row.sequence)] for row in events},
            history_drafts=snapshot.delivery_drafts,history_events=snapshot.delivery_events)

    async def read(self,session,query,filing_id):
        if session.actor_id!=query.actor_id:raise AnnualAccountsError.forbidden()
        async with session.transaction(snapshot=True) as transaction:return await self._state(transaction,query,filing_id)

    @asynccontextmanager
    async def _guard(self,session,query,filing_id):
        if session.actor_id!=query.actor_id:raise AnnualAccountsError.forbidden()
        async with session.transaction() as guard:
            await guard.lock_delivery_archive(query)
            async with session.transaction(snapshot=True) as snapshot:state=await self._state(snapshot,query,filing_id)
            if annual_accounts_source_is_synthetic(state.stored.draft.source):raise AnnualAccountsError.forbidden()
            await guard.lock_delivery_archive(query)
            yield guard,state

    async def _current(self,session,query,state,correlation_id):
        # Called while the outer published company guard is held. The RR
        # snapshot starts afterwards; no owning write can race this comparison.
        async with session.transaction(snapshot=True) as snapshot:
            current=await read_annual_accounts_delivery_source(snapshot,query,corporate=self._corporate,
                correlation_id=correlation_id,synthetic_signoff=self._synthetic_signoff)
        if current!=state.stored.draft.source:raise AnnualAccountsError.draft_conflict()

    def _validate_draft(self,draft):
        try:
            inspection=self._schemas.validate_pair(draft.main_form_xml.encode(),draft.company_accounts_xml.encode(),
                organization_number=draft.source.organization_number,income_year=int(draft.source.income_year))
            if inspection!=draft.inspection:raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError):raise AnnualAccountsError.unavailable() from None

    def _binding(self,state):
        draft=state.stored.draft
        return Binding(draft.filing_id,draft.source.company_id,draft.source.income_year,draft.prepared_by,draft.sha256)

    def _query(self,session,binding):
        if type(binding) is not Binding or binding.actor_id!=session.actor_id:raise AnnualAccountsError.forbidden()
        return AnnualAccountsSourceQuery(binding.company_id,binding.income_year,binding.actor_id)

    @staticmethod
    def _assert_binding(binding,state):
        try:binding.assert_draft(state.stored.draft)
        except ValueError:raise AnnualAccountsError.draft_conflict() from None

    def _frame(self,state,kind):
        record=next((row.record for row in reversed(state.events) if type(row.record) is Frame and row.record.kind is kind),None)
        if record is None:return None,None
        observations=tuple(row.record for row in state.events if type(row.record) is Observation)
        return record,inspect_annual_accounts_delivery_frame(record,observations,draft=state.stored.draft,
            known_instance=state.inspection.known_instance,schemas=self._schemas)

    async def _append(self,transaction,state,record):
        # Validate the candidate graph before SQL; inspect again with the real
        # committed identity/time returned by the restricted immutable RPC.
        existing=state.slot(record.slot)
        if existing is not None:
            if existing.record!=record:raise AnnualAccountsError.draft_conflict()
        else:
            candidate=Event(max((row.sequence for row in state.history_events),default=0)+1,record,self._now())
            values=(*state.events,candidate)
            self._inspect(state.stored,values,{str(row.sequence):row.record.sha256 for row in values},
                history_drafts=state.history_drafts,history_events=state.history_events)
        stored,inserted=await transaction.append_delivery_event(record)
        values=(*state.events,stored) if inserted else state.events
        if not inserted and (existing is None or stored!=existing):raise AnnualAccountsError.unavailable()
        return self._inspect(state.stored,values,{str(row.sequence):row.record.sha256 for row in values},
            history_drafts=state.history_drafts,history_events=state.history_events),stored,inserted

    async def review(self,session,binding,*,stage,reviewed_evidence_sha256,documents_checked,action_confirmed,command_key,correlation_id):
        query=self._query(session,binding)
        async with self._guard(session,query,binding.filing_id) as (guard,state):
            self._assert_binding(binding,state)
            prior=state.slot('review:'+stage.value)
            if prior is not None:
                record=prior.record
                if (record.reviewed_evidence_sha256!=reviewed_evidence_sha256 or record.command_key!=command_key
                        or documents_checked is not True or action_confirmed is not True):raise AnnualAccountsError.draft_conflict()
                return state
            if state.inspection.state=='correction_parent_unknown':raise AnnualAccountsError.draft_conflict()
            await self._current(session,query,state,correlation_id)
            self._validate_draft(state.stored.draft)
            expected=state.stored.draft.sha256
            if stage is not Stage.PREPARE:
                _,frame=self._frame(state,Kind.UPLOAD_REVIEW if stage is Stage.CONFIRM else Kind.SIGN_REVIEW)
                if frame is None:raise AnnualAccountsError.draft_conflict()
                try:frame.assert_action(Action.CONFIRM if stage is Stage.CONFIRM else Action.SIGN)
                except ValueError:raise AnnualAccountsError.draft_conflict() from None
                expected=frame.review_sha256
            if reviewed_evidence_sha256!=expected:raise AnnualAccountsError.draft_conflict()
            try:record=Review(binding,stage,state.stored.draft.source.sha256,expected,documents_checked,action_confirmed,command_key,self._now())
            except ValueError:raise AnnualAccountsError.invalid_input() from None
            await guard.lock_delivery_archive(query)
            state,_,_=await self._append(guard,state,record)
        return state

    def _ports_required(self):
        if self._ports is None:raise AnnualAccountsError.unavailable()
        return self._ports

    def mutation_available(self,session,state,stage):
        if annual_accounts_source_is_synthetic(state.stored.draft.source):return False
        if self._ports is None or not self._ports.stage_available(session,state.stored.draft,stage):return False
        if state.inspection.next_action is Action.CREATE_INSTANCE and not self.correction_proof_fresh(state):return False
        if state.inspection.next_action is not Action.CREATE_INSTANCE:
            try:
                record=next(row.record for row in state.events if row.record.sha256==state.inspection.prerequisite_sha256)
                _,frame=self._frame(state,record.kind)
                previous=next(row for row in reversed(state.events) if type(row.record) is Intent)
                frame.assert_fresh(self._now(),after=previous.recorded_at)
            except (StopIteration,ValueError,AttributeError,AnnualAccountsError):return False
        retained=next((row.record for row in state.events if type(row.record) is Admission and row.record.stage is stage),None)
        if retained is None:return True
        try:
            port=self._ports.retained(session,retained);port.runtime.assert_available()
            used=sum(getattr(row.record,'admission_sha256',None)==retained.sha256 for row in state.events)
            return used<retained.maximum_requests
        except AnnualAccountsError:return False

    def correction_proof_fresh(self,state):
        if state.slot('correction:admission') is None:return True
        if state.inspection.state=='correction_parent_unknown':return False
        lineage=next((row.record for row in reversed(state.events) if type(row.record) is ParentFrame),None)
        attempt=next((row.record for row in reversed(state.events) if type(row.record) is ParentAttempt),None)
        if lineage is None or attempt is None or lineage.attempt_sha256!=attempt.sha256:return False
        selected=set(lineage.observation_sha256)
        began=min(row.record.original.requested_at.value for row in state.events
            if type(row.record) is ParentObservation and row.record.sha256 in selected)
        return 0<=(self._now().value-began).total_seconds()<=60

    def correction_refresh_available(self,session,state):
        if annual_accounts_source_is_synthetic(state.stored.draft.source):return False
        retained=state.slot('correction:admission')
        if self._ports is None or retained is None or type(retained.record) is not ParentAdmission:return False
        if state.slot('intent:create_instance') is not None or sum(type(row.record) is ParentAttempt for row in state.events)>=3:return False
        try:
            grant=retained.record.grant;port=self._ports.retained(session,grant);port.runtime.assert_available()
            used=sum(type(row.record) is ParentObservation for row in state.events)
            return min(grant.maximum_requests-used,port.runtime.requests_remaining)>=9
        except AnnualAccountsError:return False

    def reconciliation_available(self,session,state):
        if annual_accounts_source_is_synthetic(state.stored.draft.source):return False
        if self._ports is None or not self._ports.available(session,state.stored.draft.source.company_id,state.stored.draft.source.income_year):return False
        request=next((row for row in reversed(state.events) if type(row.record) is Intent),None)
        if request is None or state.inspection.known_instance is None:return False
        required={Kind.CREATE_TARGET:1,Kind.MAIN_UPLOADED:3,Kind.UPLOAD_REVIEW:5,Kind.SIGN_REVIEW:9,Kind.ARCHIVE:9}[_KINDS[request.record.action]]
        original=next((row.record for row in state.events if row.record.sha256==request.record.admission_sha256),None)
        recovery=next((row.record for row in state.events if type(row.record) is Admission and row.record.dependency_intent_sha256==request.record.sha256),None)
        for grant in (original,recovery):
            if grant is None:continue
            try:
                port=self._ports.retained(session,grant);port.runtime.assert_available()
                used=sum(getattr(row.record,'admission_sha256',None)==grant.sha256 for row in state.events)
                if min(grant.maximum_requests-used,port.runtime.requests_remaining)>=required:return True
            except AnnualAccountsError:pass
        return recovery is None

    async def _mutation_port(self,session,guard,state,stage):
        approval=state.slot('review:'+stage.value)
        if approval is None:raise AnnualAccountsError.draft_conflict()
        ports=self._ports_required()
        retained=next((row for row in state.events if type(row.record) is Admission and row.record.stage is stage),None)
        if retained is None:
            port=ports.issue(session,state.stored,review=approval,
                known_instance=None if stage is Stage.PREPARE else state.inspection.known_instance)
            state,_,_=await self._append(guard,state,port.runtime.admission)
        else:port=ports.retained(session,retained.record)
        port.runtime.assert_session(session);port.runtime.assert_available()
        return state,port,approval.record

    def _intent(self,state,action,review,grant,frame):
        draft=state.stored.draft;known=state.inspection.known_instance
        data=(frame.main_data_id if action is Action.UPLOAD_MAIN_FORM else frame.accounts_data_id if action is Action.UPLOAD_COMPANY_ACCOUNTS else None) if frame else None
        target=None if action is Action.CREATE_INSTANCE else known
        raw=(b'{"instanceOwner":{"organisationNumber":"'+draft.source.organization_number.encode()+b'"}}' if target is None else
            draft.main_form_xml.encode() if action is Action.UPLOAD_MAIN_FORM else draft.company_accounts_xml.encode() if action is Action.UPLOAD_COMPANY_ACCOUNTS else
            b'{"action":"confirm"}' if action is Action.CONFIRM else b'{"action":"sign"}')
        path='/brg/aarsregnskap-vanlig-202406/instances/'+('create' if target is None else target+('/data/'+data if data else '/process/next'))
        return Intent(self._binding(state),action,review.sha256,grant.sha256,frame.prerequisite_sha256 if frame else draft.sha256,
            target,data,'POST' if target is None else 'PUT',path,'application/xml' if data else 'application/json',base64.b64encode(raw).decode())

    async def advance(self,session,binding,*,action,correlation_id):
        query=self._query(session,binding)
        if type(action) is not Action:raise AnnualAccountsError.invalid_input()
        async with self._guard(session,query,binding.filing_id) as (guard,state):
            self._assert_binding(binding,state)
            # A repeated command never sends the retained request a second time,
            # including if its completion is unknown or the source has changed.
            if state.slot('intent:'+action.value) is not None:return state
            await self._current(session,query,state,correlation_id)
            self._validate_draft(state.stored.draft)
            if state.inspection.next_action is not action:raise AnnualAccountsError.draft_conflict()
            frame=None
            if action is not Action.CREATE_INSTANCE:
                prerequisite=state.inspection.prerequisite_sha256
                record=next(row.record for row in state.events if row.record.sha256==prerequisite)
                _,frame=self._frame(state,record.kind)
                previous=next(row for row in reversed(state.events) if type(row.record) is Intent)
                try:frame.assert_fresh(self._now(),after=previous.recorded_at)
                except ValueError:raise AnnualAccountsError.draft_conflict() from None
            state,port,review=await self._mutation_port(session,guard,state,_STAGES[action])
            request=self._intent(state,action,review,port.runtime.admission,frame)
            await guard.lock_delivery_archive(query)
            state,_,elected=await self._append(guard,state,request)
        if not elected:return state
        # All SQL contexts have committed/closed. The elected request alone may
        # cross this boundary. A transport failure leaves a retained unknown.
        completion=await port.execute(request,review,state.stored.draft)
        async with session.transaction() as transaction:await transaction.append_delivery_event(completion)
        return await self.read(session,query,binding.filing_id)

    async def _read_port(self,session,query,state,request,required_requests):
        ports=self._ports_required()
        admitted=next((row.record for row in state.events if row.record.sha256==request.record.admission_sha256),None)
        if admitted is not None:
            try:
                port=ports.retained(session,admitted);port.runtime.assert_available()
                # Reserve enough remaining *retained* request budget for the
                # largest supported bracket (two XML, four PDF, signature).
                used=sum(getattr(row.record,'admission_sha256',None)==admitted.sha256 for row in state.events)
                if min(admitted.maximum_requests-used,port.runtime.requests_remaining)>=required_requests:return state,port
            except AnnualAccountsError:pass
        async with self._guard(session,query,state.stored.draft.filing_id) as (guard,state):
            prior=next((row.record for row in state.events if type(row.record) is Admission
                and row.record.dependency_intent_sha256==request.record.sha256),None)
            if prior is None:
                port=ports.issue(session,state.stored,known_instance=state.inspection.known_instance,dependency=request)
                state,_,_=await self._append(guard,state,port.runtime.admission)
            else:port=ports.retained(session,prior)
            port.runtime.assert_available()
            admitted=port.runtime.admission
            used=sum(getattr(row.record,'admission_sha256',None)==admitted.sha256 for row in state.events)
            if min(admitted.maximum_requests-used,port.runtime.requests_remaining)<required_requests:raise AnnualAccountsError.unavailable()
        return state,port

    async def reconcile(self,session,binding):
        query=self._query(session,binding);state=await self.read(session,query,binding.filing_id)
        if annual_accounts_source_is_synthetic(state.stored.draft.source):raise AnnualAccountsError.forbidden()
        self._assert_binding(binding,state)
        if state.inspection.known_instance is None:return state
        request=next((row for row in reversed(state.events) if type(row.record) is Intent),None)
        if request is None:return state
        kind=_KINDS[request.record.action]
        required={Kind.CREATE_TARGET:1,Kind.MAIN_UPLOADED:3,Kind.UPLOAD_REVIEW:5,Kind.SIGN_REVIEW:9,Kind.ARCHIVE:9}[kind]
        state,port=await self._read_port(session,query,state,request,required);observations=[]
        async def fetch(purpose,data_id=None):
            # Verify current owner/MFA/history before beginning every new GET.
            # A result already in flight is retained without this fresh check.
            await self.read(session,query,binding.filing_id)
            original=await port.read(purpose=purpose,instance_id=state.inspection.known_instance,data_id=data_id)
            record=Observation(binding,str(uuid4()),port.runtime.admission.sha256,request.record.sha256,original)
            async with session.transaction() as transaction:await transaction.append_delivery_event(record)
            observations.append(record);return original
        first=await fetch(Purpose.INSTANCE)
        try:metadata=inspect_annual_accounts_instance(first,organization_number=state.stored.draft.source.organization_number)
        except (ValueError,TypeError,KeyError):return await self.read(session,query,binding.filing_id)
        if kind is not Kind.CREATE_TARGET:
            selected=[(Purpose.MAIN_FORM,row.data_id) for row in metadata.data if row.data_type=='Hovedskjema']
            if kind is not Kind.MAIN_UPLOADED:selected.extend((Purpose.COMPANY_ACCOUNTS,row.data_id) for row in metadata.data if row.data_type=='Underskjema')
            if kind in (Kind.UPLOAD_REVIEW,Kind.SIGN_REVIEW):selected.append((Purpose.VALIDATION,None))
            if kind in (Kind.SIGN_REVIEW,Kind.ARCHIVE):selected.extend((Purpose.PDF,row.data_id) for row in metadata.data if row.data_type=='ref-data-as-pdf')
            if kind is Kind.ARCHIVE:selected.extend((Purpose.SIGNATURE,row.data_id) for row in metadata.data if row.data_type=='signature')
            for purpose,data_id in selected:await fetch(purpose,data_id)
            await fetch(Purpose.INSTANCE)
        record=Frame(binding,str(uuid4()),kind,tuple(row.sha256 for row in observations))
        try:inspect_annual_accounts_delivery_frame(record,observations,draft=state.stored.draft,
            known_instance=state.inspection.known_instance,schemas=self._schemas)
        except (ValueError,TypeError,KeyError,AttributeError):return await self.read(session,query,binding.filing_id)
        async with session.transaction() as transaction:await transaction.append_delivery_event(record)
        return await self.read(session,query,binding.filing_id)
