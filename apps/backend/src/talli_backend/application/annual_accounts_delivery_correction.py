"""Commit an inert child, then re-read its one known terminal parent."""
from uuid import uuid4

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsSourceQuery,AnnualAccountsDeliveryIntent as Intent,
    AnnualAccountsDeliveryAction as Action,AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
    AnnualAccountsReadPurpose as Purpose,AnnualAccountsCorrectionParentAdmission as ParentAdmission,
    AnnualAccountsCorrectionParentAttempt as ParentAttempt,
    AnnualAccountsCorrectionParentObservation as ParentObservation,AnnualAccountsCorrectionParentFrame as ParentFrame,
    assert_annual_accounts_correction_source,inspect_annual_accounts_instance,
)


class AnnualAccountsDeliveryCorrection:
    def __init__(self,preparation,workflow):self._preparation,self._workflow=preparation,workflow

    def _parent(self,state,binding):
        binding.assert_draft(state.stored.draft)
        if state.inspection.state!='technical_archive' or state.inspection.known_instance is None:raise AnnualAccountsError.draft_conflict()
        sign=next(row.record for row in state.events if type(row.record) is Intent and row.record.action is Action.SIGN)
        archived=next(row for row in reversed(state.events) if type(row.record) is Frame and row.record.kind is Kind.ARCHIVE)
        return sign,archived

    async def prepare(self,session,command,parent_binding):
        workflow=self._workflow;query=AnnualAccountsSourceQuery(command.company_id,command.income_year,command.actor_id)
        if (parent_binding.actor_id!=session.actor_id or parent_binding.company_id!=command.company_id
                or parent_binding.income_year!=command.income_year or parent_binding.filing_id==str(command.filing_id)):
            raise AnnualAccountsError.draft_conflict()
        parent=await workflow.read(session,query,parent_binding.filing_id)
        try:self._parent(parent,parent_binding)
        except (ValueError,StopIteration):raise AnnualAccountsError.draft_conflict() from None
        # Existing Draft v1 remains inert: no parent IDs in its frozen bytes.
        child=await self._preparation.prepare(session,command)
        try:assert_annual_accounts_correction_source(parent.stored.draft.source,child.draft.source)
        except (ValueError,TypeError,KeyError):raise AnnualAccountsError.draft_conflict() from None
        async with workflow._guard(session,query,child.draft.filing_id) as (guard,state):
            if any(type(row.record) is ParentAttempt for row in state.events):return state
            # The accepted Source v4 contract is required for this successor.
            async with session.transaction(snapshot=True) as transaction:
                snapshot=await transaction.filing_source_snapshot(query)
            if snapshot.contract_version!='annual-accounts-source-v4' or snapshot.coverage.get('deliveryCorrectionsEnabled') is not True:
                raise AnnualAccountsError.unavailable()
            await workflow._current(session,query,state,command.correlation_id)
            workflow._validate_draft(child.draft)
            parent=await workflow.read(session,query,parent_binding.filing_id)
            try:sign,archived=self._parent(parent,parent_binding)
            except (ValueError,StopIteration):raise AnnualAccountsError.draft_conflict() from None
            ports=workflow._ports_required();prior=state.slot('correction:admission')
            if prior is None:
                if any(type(row.record) is ParentAdmission and row.record.parent_binding.filing_id==parent_binding.filing_id
                        for row in state.history_events):raise AnnualAccountsError.draft_conflict()
                port=ports.issue_parent(session,child,parent_binding=parent_binding,parent_sign_intent=sign,
                    known_instance=parent.inspection.known_instance,parent_archived_at=archived.recorded_at,parent_archive_frame_sha256=archived.record.sha256)
                admission=ParentAdmission(workflow._binding(state),parent_binding,sign.sha256,archived.record.sha256,port.runtime.admission)
                state,_,_=await workflow._append(guard,state,admission)
            else:
                admission=prior.record
                if type(admission) is not ParentAdmission or admission.parent_binding!=parent_binding:raise AnnualAccountsError.draft_conflict()
                port=ports.retained(session,admission.grant)
            port.runtime.assert_session(session);port.runtime.assert_available()
            used=sum(type(row.record) is ParentObservation for row in state.events)
            if min(admission.grant.maximum_requests-used,port.runtime.requests_remaining)<9:raise AnnualAccountsError.unavailable()
            state,attempt,_=await workflow._append(guard,state,ParentAttempt(workflow._binding(state),str(uuid4()),admission.sha256,workflow._now()))
        return await self._collect(session,query,state,parent,admission,attempt,port,command.correlation_id)

    async def refresh(self,session,binding,*,correlation_id):
        workflow=self._workflow;query=workflow._query(session,binding)
        async with workflow._guard(session,query,binding.filing_id) as (guard,state):
            workflow._assert_binding(binding,state)
            if any(type(row.record) is Intent and row.record.action is Action.CREATE_INSTANCE for row in state.events):
                raise AnnualAccountsError.draft_conflict()
            admitted=state.slot('correction:admission')
            if admitted is None or type(admitted.record) is not ParentAdmission:raise AnnualAccountsError.draft_conflict()
            admission=admitted.record
            await workflow._current(session,query,state,correlation_id)
            port=workflow._ports_required().retained(session,admission.grant)
            port.runtime.assert_session(session);port.runtime.assert_available()
            used=sum(type(row.record) is ParentObservation for row in state.events)
            if (sum(type(row.record) is ParentAttempt for row in state.events)>=3
                    or min(admission.grant.maximum_requests-used,port.runtime.requests_remaining)<9):raise AnnualAccountsError.unavailable()
            parent=await workflow.read(session,query,admission.parent_binding.filing_id)
            state,attempt,_=await workflow._append(guard,state,ParentAttempt(workflow._binding(state),str(uuid4()),admission.sha256,workflow._now()))
        return await self._collect(session,query,state,parent,admission,attempt,port,correlation_id)

    async def _collect(self,session,query,state,parent,admission,attempt,port,correlation_id):
        workflow=self._workflow;child=state.stored;parent_binding=admission.parent_binding
        # Every response commits independently after all pre-request SQL closes.
        # A response begun during the lease remains retainable after revocation.
        observations=[]
        async def fetch(purpose,data_id=None):
            current=await workflow.read(session,query,child.draft.filing_id)
            if current.slot('intent:create_instance') is not None:raise AnnualAccountsError.draft_conflict()
            original=await port.read(purpose=purpose,instance_id=parent.inspection.known_instance,data_id=data_id)
            record=ParentObservation(workflow._binding(state),str(uuid4()),admission.sha256,attempt.record.sha256,original)
            async with session.transaction() as transaction:await transaction.append_delivery_event(record)
            observations.append(record);return original
        first=await fetch(Purpose.INSTANCE)
        try:metadata=inspect_annual_accounts_instance(first,organization_number=child.draft.source.organization_number)
        except (ValueError,TypeError,KeyError):return await workflow.read(session,query,child.draft.filing_id)
        selected=[]
        for purpose,kind in ((Purpose.MAIN_FORM,'Hovedskjema'),(Purpose.COMPANY_ACCOUNTS,'Underskjema'),(Purpose.PDF,'ref-data-as-pdf'),(Purpose.SIGNATURE,'signature')):
            selected.extend((purpose,row.data_id) for row in metadata.data if row.data_type==kind)
        for purpose,data_id in selected:await fetch(purpose,data_id)
        await fetch(Purpose.INSTANCE)
        async with workflow._guard(session,query,child.draft.filing_id) as (guard,state):
            await workflow._current(session,query,state,correlation_id)
            lineage=ParentFrame(workflow._binding(state),str(uuid4()),attempt.record.sha256,parent_binding,admission.parent_archive_frame_sha256,tuple(row.sha256 for row in observations))
            try:
                from talli_backend.modules.annual_accounts_filing.public import StoredAnnualAccountsDeliveryEvent
                candidate=StoredAnnualAccountsDeliveryEvent(max(row.sequence for row in state.history_events)+1,lineage,workflow._now())
                values=(*state.events,candidate)
                workflow._inspect(state.stored,values,{str(row.sequence):row.record.sha256 for row in values},
                    history_drafts=state.history_drafts,history_events=state.history_events)
            except AnnualAccountsError:return state
            state,_,_=await workflow._append(guard,state,lineage)
        return state
