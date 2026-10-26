"""Guarded finite Tax review and first mutation, with durable submit-once intent.

All authority I/O follows closed SQL contexts. A committed uncertain create has
no documented lookup proof and remains reconciliation-only. Later mutation
stages stay closed until their retained read prerequisites are implemented.
"""
from __future__ import annotations

import base64
from uuid import NAMESPACE_URL,uuid5

from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalRuntime
from talli_backend.application.company_tax_delivery_source import read_company_tax_delivery_source
from talli_backend.application.company_tax_filing_session import CompanyTaxSession
from talli_backend.modules.company_tax_filing.public import (
    ApproveTaxDeliveryDraft,AdvanceTaxDelivery,CompanyTaxError,CompanyTaxSourceQuery,
    CompanyTaxReturnAuthorityError,TaxDeliveryAuthorityMode,TaxDeliverySchemaValidator,
    TaxDeliveryMutationAuthority,TaxDeliveryJournal,TaxDeliveryMutationCompletion,TaxDeliveryEventAppend,
    TaxMutationKind,TaxMutationDisposition,assert_tax_delivery_attempt_history,
    approve_tax_delivery_review,build_tax_delivery_mutation_request,
    TaxDeliveryAdmissionEvidence,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryInstanceObservation,
)


def _query(session,command):
    if command.actor_id!=session.actor_id:raise CompanyTaxError.forbidden()
    return CompanyTaxSourceQuery(command.company_id,command.income_year,session.actor_id)


def _approval_id(command):
    return str(uuid5(NAMESPACE_URL,':'.join(('talli-tax-review-v1',str(command.company_id),
        str(int(command.income_year)),str(command.filing_id),str(command.actor_id.subject),str(command.command_key)))))


def _review_replay(journal,command):
    approval=journal.approval
    if approval is None:return None
    if (approval.approval_id!=_approval_id(command) or approval.approved_by!=command.actor_id
            or approval.draft_sha256!=command.expected_draft_sha256
            or approval.review_sha256!=command.expected_review_sha256):
        raise CompanyTaxError.draft_conflict()
    return TaxDeliveryJournal(journal.draft,(journal.events[0],)).progress


def _approved(journal,command):
    if journal.approval is None:raise CompanyTaxError.draft_conflict()
    if journal.approval.approved_by!=command.actor_id:raise CompanyTaxError.forbidden()
    if journal.approval.sha256!=command.expected_approval_sha256:raise CompanyTaxError.draft_conflict()


class CompanyTaxDeliverySubmission:
    def __init__(self,runtime: TaxDeliveryRehearsalRuntime,authority: TaxDeliveryMutationAuthority,
                 schemas: TaxDeliverySchemaValidator):
        if type(runtime) is not TaxDeliveryRehearsalRuntime:raise ValueError('Finite Tax runtime is required.')
        self._runtime,self._authority,self._schemas=runtime,authority,schemas

    async def _history(self,transaction,query,filing_id):
        snapshot=await transaction.journal_history_snapshot(query)
        return assert_tax_delivery_attempt_history(query,snapshot,str(filing_id))

    async def _guarded_history(self,session,query,filing_id):
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as transaction:
                journal=await self._history(transaction,query,filing_id)
            await guard.lock_delivery_draft_archive(query)
        return journal

    async def _source(self,session,query,command):
        async with session.transaction(snapshot=True) as transaction:
            return await read_company_tax_delivery_source(transaction,query,correlation_id=command.correlation_id)

    def _admit(self,journal,actor):
        context=self._runtime.authorize(journal.draft,actor)
        if journal.draft.envelope.schema_sha256!=self._schemas.schema_sha256:raise CompanyTaxError.draft_conflict()
        return context

    async def _current(self,journal):
        source=journal.draft.envelope.source
        try:
            response=await self._authority.fetch_current_document(income_year=int(source.income_year),
                company_org_number=source.organization_number)
            return self._schemas.inspect_current(response)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None

    def _review(self,journal,source,current,*,actor,approval_id,context):
        try:
            return approve_tax_delivery_review(approval_id=approval_id,draft=journal.draft,approved_by=actor,
                expected_draft_sha256=journal.draft.sha256,expected_review_sha256=journal.draft.envelope.review_sha256,
                current_source=source,current_document=current,current_schema_sha256=self._schemas.schema_sha256,
                authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK,authority_context_sha256=context)
        except (ValueError,TypeError):
            raise CompanyTaxError.draft_conflict() from None

    @staticmethod
    def _append(journal,result,value):
        if type(result) is not TaxDeliveryEventAppend or result.event.value!=value:raise CompanyTaxError.unavailable()
        return TaxDeliveryJournal(journal.draft,journal.events+(result.event,),journal.read_evidence)

    def _admission(self,journal):
        approval=journal.approval
        value=TaxDeliveryAdmissionEvidence(journal.draft.filing_id,approval.company_id,approval.income_year,
            approval.approved_by,approval.sha256,TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ADMISSION,
                base64.b64encode(self._runtime.admission.canonical_context.encode('utf-8')).decode('ascii'),'application/json',None))
        value.assert_approval(approval,journal.draft)
        return value

    async def _retain_admission(self,transaction,journal):
        if not journal.read_evidence:raise CompanyTaxError.unavailable()
        value=self._admission(journal)
        prior=next((event for event in journal.events if event.slot=='admission'),None)
        if prior is not None:
            if prior.value!=value:raise CompanyTaxError.draft_conflict()
            return journal
        return self._append(journal,await transaction.append_delivery_event(value),value)

    async def approve(self,session: CompanyTaxSession,command: ApproveTaxDeliveryDraft):
        if type(command) is not ApproveTaxDeliveryDraft:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session)
        query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id)
        replay=_review_replay(journal,command)
        if replay is not None:return replay
        if not journal.read_evidence:raise CompanyTaxError.unavailable()
        if (journal.draft.sha256!=command.expected_draft_sha256
                or journal.draft.envelope.review_sha256!=command.expected_review_sha256):
            raise CompanyTaxError.draft_conflict()
        context=self._admit(journal,session.actor_id)
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        # Enumeration can outlast MFA. The current RC guard must follow it and
        # close before authority GET; concurrent exact review replay precedes GET.
        latest=await self._guarded_history(session,query,command.filing_id)
        replay=_review_replay(latest,command)
        if replay is not None:return replay
        if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
        current=await self._current(journal)
        approval=self._review(journal,source,current,actor=session.actor_id,approval_id=_approval_id(command),context=context)
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
                replay=_review_replay(latest,command)
                if replay is not None:return replay
                fresh=await read_company_tax_delivery_source(snapshot,query,correlation_id=command.correlation_id)
            if fresh!=source or latest.draft!=journal.draft:raise CompanyTaxError.draft_conflict()
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(approval)
            retained=self._append(latest,result,approval)
            retained=await self._retain_admission(guard,retained)
        return _review_replay(retained,command)

    async def advance(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session)
        query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id)
        _approved(journal,command)
        request=build_tax_delivery_mutation_request(journal.approval,journal.draft,TaxMutationKind.CREATE_INSTANCE)
        if journal.plan(request) is not TaxMutationDisposition.EXECUTE:return journal.progress
        if not journal.read_evidence:raise CompanyTaxError.unavailable()
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        latest=await self._guarded_history(session,query,command.filing_id)
        _approved(latest,command)
        if latest.plan(request) is not TaxMutationDisposition.EXECUTE:return latest.progress
        if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
        current=await self._current(journal)
        reviewed=self._review(journal,source,current,actor=session.actor_id,
            approval_id=journal.approval.approval_id,context=context)
        if reviewed!=journal.approval:raise CompanyTaxError.draft_conflict()
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
                _approved(latest,command)
                if latest.plan(request) is not TaxMutationDisposition.EXECUTE:return latest.progress
                fresh=await read_company_tax_delivery_source(snapshot,query,correlation_id=command.correlation_id)
            if fresh!=source or latest.draft!=journal.draft:raise CompanyTaxError.draft_conflict()
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            latest=await self._retain_admission(guard,latest)
            result=await guard.append_delivery_event(request)
            retained=self._append(latest,result,request)
        # Only an acknowledged committed insertion can elect this caller. A
        # lost COMMIT acknowledgment propagates before this point; retry sees
        # the retained intent and cannot execute another mutation.
        if not result.inserted:return retained.progress
        try:
            self._admit(retained,session.actor_id)
            completion=await self._authority.execute(request,retained.approval,retained.draft)
            if type(completion) is not TaxDeliveryMutationCompletion:raise ValueError()
            completion.assert_request(request,retained.approval)
        except (CompanyTaxReturnAuthorityError,CompanyTaxError,ValueError,TypeError,RecursionError,OverflowError):
            return retained.progress
        # No owner/MFA reauthorization discards an already observed effect. The
        # restricted RPC permits only the original actor's exact bound result.
        async with session.transaction() as transaction:
            result=await transaction.append_delivery_event(completion)
            completed=self._append(retained,result,completion)
        return completed.progress

    async def reconcile(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session)
        journal=await self._guarded_history(session,_query(session,command),command.filing_id)
        _approved(journal,command)
        # No generic lookup exists for a create whose response reference was
        # lost. Do not invent one, lease-reset it, or create another filing.
        created=next((event.value for event in journal.events if event.slot=='completion:create_instance'),None)
        if created is None or not journal.read_evidence:return journal.progress
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        query=_query(session,command)
        # Only a known create reference can be observed. Missing response IDs
        # never trigger provider lookups or a second create. Close SQL before GET.
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            await self._retain_admission(guard,latest)
        try:
            observation=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(observation) is not TaxDeliveryInstanceObservation:raise ValueError()
            observation.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(observation)
            if type(result) is not TaxDeliveryEventAppend or type(result.event.value) is not TaxDeliveryInstanceObservation:
                raise CompanyTaxError.unavailable()
            if result.event.value.evidence_sha256!=observation.evidence_sha256 or result.event.value.original!=observation.original:
                raise CompanyTaxError.unavailable()
            prior=next((event for event in latest.events if event.slot==result.event.slot),None)
            if prior is not None:
                if prior!=result.event:raise CompanyTaxError.unavailable()
                return latest.progress
            retained=TaxDeliveryJournal(latest.draft,latest.events+(result.event,),latest.read_evidence)
        return retained.progress
