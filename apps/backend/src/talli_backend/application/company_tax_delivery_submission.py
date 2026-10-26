"""Guarded finite Tax review, create and upload with durable submit-once intents.

All authority I/O follows closed SQL contexts. A committed uncertain create has
no documented lookup proof and remains reconciliation-only. Unknown uploads
resolve only through exact known-instance reads. Validation requires positive
V6 proof and fresh Clean/file originals. Confirmation remains closed.
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
    TaxDeliveryEnvelopeObservation,TaxDeliveryUploadReadEvidence,bind_tax_delivery_upload_prerequisite,reconcile_tax_delivery_upload,
    TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation,TaxValidationJobStatus,
    bind_tax_delivery_validation_prerequisite,
    TaxValidationResponseValidator,TaxCalculatedDocumentValidator,TaxDeliveryProcessAcknowledgment,
    bind_tax_delivery_confirmation_prerequisite,TaxDeliveryConfirmationReadEvidence,reconcile_tax_delivery_confirmation,
    is_tax_delivery_owner_confirmation_instance,
    TaxDeliveryOwnerReviewQuery,build_tax_delivery_owner_review,
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
                 schemas: TaxDeliverySchemaValidator,*,response_schemas: TaxValidationResponseValidator | None=None,
                 calculated_schemas: TaxCalculatedDocumentValidator | None=None):
        if type(runtime) is not TaxDeliveryRehearsalRuntime:raise ValueError('Finite Tax runtime is required.')
        self._runtime,self._authority,self._schemas=runtime,authority,schemas
        self._response_schemas=response_schemas
        self._calculated_schemas=calculated_schemas

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
        return TaxDeliveryJournal(journal.draft,journal.events+(result.event,),journal.read_evidence,journal.guarded_upload,journal.validation_evidence,journal.confirmation_evidence)

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

    async def _retain_read(self,session,query,command,value):
        if type(value) not in (TaxDeliveryInstanceObservation,TaxDeliveryEnvelopeObservation,
                TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation):raise CompanyTaxError.invalid_input()
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(value)
            if type(result) is not TaxDeliveryEventAppend or type(result.event.value) is not type(value):raise CompanyTaxError.unavailable()
            if result.event.value.evidence_sha256!=value.evidence_sha256 or result.event.value.original!=value.original:
                raise CompanyTaxError.unavailable()
            prior=next((event for event in latest.events if event.slot==result.event.slot),None)
            if prior is not None:
                if prior!=result.event:raise CompanyTaxError.unavailable()
                return latest,result.event.value
            retained=TaxDeliveryJournal(latest.draft,latest.events+(result.event,),latest.read_evidence,latest.guarded_upload,latest.validation_evidence,latest.confirmation_evidence)
        return retained,result.event.value

    @staticmethod
    def _upload_original(journal):
        return next((event.value for event in journal.events if event.slot=='intent:upload_envelope'),None)

    @staticmethod
    def _validation_original(journal):
        return next((event.value for event in journal.events if event.slot=='intent:start_validation'),None)

    @staticmethod
    def _created(journal):
        value=next((event.value for event in journal.events if event.slot=='completion:create_instance'),None)
        if type(value) is not TaxDeliveryMutationCompletion:raise CompanyTaxError.draft_conflict()
        return value

    async def _record_read_completion(self,session,query,command,retained,request,completion):
        kind=request.kind
        if kind not in (TaxMutationKind.UPLOAD_ENVELOPE,TaxMutationKind.PREPARE_CONFIRMATION):raise CompanyTaxError.invalid_input()
        try:
            async with session.transaction() as transaction:
                result=await transaction.append_delivery_event(completion)
                completed=self._append(retained,result,completion)
            return completed.mutation_progress(kind)
        except CompanyTaxError as error:
            if error.code not in ('COMPANY_TAX_INVALID_INPUT','COMPANY_TAX_DRAFT_CONFLICT'):raise
            # Another caller can have committed different exact read originals
            # for this same intent. The narrow late-result writer cannot reveal
            # them: only a separate current owner/MFA history read may do so.
            latest=await self._guarded_history(session,query,command.filing_id)
            _approved(latest,command)
            if (next((event.value for event in latest.events if event.slot=='intent:'+kind.value),None)!=request
                    or not any(event.slot=='completion:'+kind.value for event in latest.events)):raise
            return latest.mutation_progress(kind)

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
        if journal.plan(request) is not TaxMutationDisposition.EXECUTE:return journal.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
        if not journal.read_evidence:raise CompanyTaxError.unavailable()
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        latest=await self._guarded_history(session,query,command.filing_id)
        _approved(latest,command)
        if latest.plan(request) is not TaxMutationDisposition.EXECUTE:return latest.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
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
                if latest.plan(request) is not TaxMutationDisposition.EXECUTE:return latest.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
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
        if not result.inserted:return retained.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
        try:
            self._admit(retained,session.actor_id)
            completion=await self._authority.execute(request,retained.approval,retained.draft)
            if type(completion) is not TaxDeliveryMutationCompletion:raise ValueError()
            completion.assert_request(request,retained.approval)
        except (CompanyTaxReturnAuthorityError,CompanyTaxError,ValueError,TypeError,RecursionError,OverflowError):
            return retained.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
        # No owner/MFA reauthorization discards an already observed effect. The
        # restricted RPC permits only the original actor's exact bound result.
        async with session.transaction() as transaction:
            result=await transaction.append_delivery_event(completion)
            completed=self._append(retained,result,completion)
        return completed.mutation_progress(TaxMutationKind.CREATE_INSTANCE)

    async def reconcile(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session)
        journal=await self._guarded_history(session,_query(session,command),command.filing_id)
        _approved(journal,command)
        # No generic lookup exists for a create whose response reference was
        # lost. Do not invent one, lease-reset it, or create another filing.
        created=next((event.value for event in journal.events if event.slot=='completion:create_instance'),None)
        if created is None:return journal.progress
        if not journal.read_evidence or self._upload_original(journal) is not None:
            return journal.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
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
            if self._upload_original(latest) is not None:
                return latest.mutation_progress(TaxMutationKind.CREATE_INSTANCE)
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            await self._retain_admission(guard,latest)
        try:
            observation=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(observation) is not TaxDeliveryInstanceObservation:raise ValueError()
            observation.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,_=await self._retain_read(session,query,command,observation)
        return retained.mutation_progress(TaxMutationKind.CREATE_INSTANCE)

    async def advance_upload(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        if self._upload_original(journal) is not None:return journal.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        if not journal.guarded_upload:raise CompanyTaxError.unavailable()
        created=self._created(journal)
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        latest=await self._guarded_history(session,query,command.filing_id);_approved(latest,command)
        if self._upload_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
        current=await self._current(journal)
        if self._review(journal,source,current,actor=session.actor_id,approval_id=journal.approval.approval_id,context=context)!=journal.approval:
            raise CompanyTaxError.draft_conflict()
        # A second provider read gets a new current owner/MFA guard. Historical
        # review-only rows can retain their matching admission before this GET.
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            if self._upload_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            await self._retain_admission(guard,latest)
        started=self._runtime.now()
        try:
            observed=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(observed) is not TaxDeliveryInstanceObservation:raise ValueError()
            observed.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_original=await self._retain_read(session,query,command,observed)
        if self._upload_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        # Only a positively known empty data task can prepare the exact intent.
        # Unknown/nonempty metadata is retained above but authorizes no POST.
        try:
            proof=bind_tax_delivery_upload_prerequisite(retained.approval,retained.draft,retained=first_original,fresh=observed,
                observed_from=started,observed_until=self._runtime.now())
        except (ValueError,TypeError):raise CompanyTaxError.draft_conflict() from None
        request=build_tax_delivery_mutation_request(retained.approval,retained.draft,TaxMutationKind.UPLOAD_ENVELOPE,
            target_instance=created.result['instanceId'],upload_prerequisite=proof)
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id);_approved(latest,command)
                # A committed concurrent winner is read before comparing newly
                # generated proof times or selecting an external mutation.
                if self._upload_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
                fresh=await read_company_tax_delivery_source(snapshot,query,correlation_id=command.correlation_id)
            if fresh!=source or latest.draft!=journal.draft:raise CompanyTaxError.draft_conflict()
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            try:proof.assert_current(self._runtime.now())
            except ValueError:raise CompanyTaxError.unavailable() from None
            if latest.plan(request) is not TaxMutationDisposition.EXECUTE:raise CompanyTaxError.draft_conflict()
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(request)
            retained=self._append(latest,result,request)
        if not result.inserted:return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        try:
            self._admit(retained,session.actor_id);proof.assert_current(self._runtime.now())
            completion=await self._authority.execute(request,retained.approval,retained.draft)
            if type(completion) is not TaxDeliveryMutationCompletion:raise ValueError()
            completion.assert_request(request,retained.approval)
        except (CompanyTaxReturnAuthorityError,CompanyTaxError,ValueError,TypeError,RecursionError,OverflowError):
            return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        return await self._record_read_completion(session,query,command,retained,request,completion)

    async def reconcile_upload(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        request=self._upload_original(journal)
        if request is None:raise CompanyTaxError.draft_conflict()
        if any(event.slot=='completion:upload_envelope' for event in journal.events):return journal.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        if not journal.guarded_upload:raise CompanyTaxError.unavailable()
        if self._admit(journal,session.actor_id)!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        created=self._created(journal)
        try:
            metadata=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(metadata) is not TaxDeliveryInstanceObservation:raise ValueError()
            metadata.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        # Store the known/unknown metadata and recheck current owner/MFA before
        # a second GET. A concurrent completion wins without another file read.
        retained,_=await self._retain_read(session,query,command,metadata)
        if any(event.slot=='completion:upload_envelope' for event in retained.events):return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        if not metadata.inspection.known or metadata.inspection.envelope is None:return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        try:
            envelope=await self._authority.observe_envelope(journal.approval,journal.draft,created,metadata)
            if type(envelope) is not TaxDeliveryEnvelopeObservation:raise ValueError()
            envelope.assert_instance(journal.approval,journal.draft,metadata)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        try:
            completion=reconcile_tax_delivery_upload(request,journal.approval,journal.draft,
                evidence=TaxDeliveryUploadReadEvidence(metadata,envelope),observed_at=self._runtime.now())
        except (ValueError,TypeError):
            # Retain a scoped drift original when still authorized. It never
            # clears the uncertain intent, replaces bytes or repeats the POST.
            retained,_=await self._retain_read(session,query,command,envelope)
            return retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        # These exact provided originals prove a result of the original actor's
        # committed request. Ownership/MFA changes during the final GET cannot
        # discard it; the narrow RPC permits no unrelated historical read.
        return await self._record_read_completion(session,query,command,retained,request,completion)

    async def advance_validation(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        if self._validation_original(journal) is not None:return journal.mutation_progress(TaxMutationKind.START_VALIDATION)
        if not journal.validation_evidence or self._response_schemas is None:raise CompanyTaxError.unavailable()
        created=self._created(journal)
        if not any(event.slot=='completion:upload_envelope' for event in journal.events):raise CompanyTaxError.draft_conflict()
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        latest=await self._guarded_history(session,query,command.filing_id);_approved(latest,command)
        if self._validation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.START_VALIDATION)
        if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
        current=await self._current(journal)
        if self._review(journal,source,current,actor=session.actor_id,approval_id=journal.approval.approval_id,context=context)!=journal.approval:
            raise CompanyTaxError.draft_conflict()
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            if self._validation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.START_VALIDATION)
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            await self._retain_admission(guard,latest)
        began=self._runtime.now()
        try:
            metadata=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(metadata) is not TaxDeliveryInstanceObservation:raise ValueError()
            metadata.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_metadata=await self._retain_read(session,query,command,metadata)
        if self._validation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.START_VALIDATION)
        if not metadata.inspection.known or metadata.inspection.envelope is None or metadata.inspection.envelope.scan_result!='Clean':
            raise CompanyTaxError.draft_conflict()
        try:
            envelope=await self._authority.observe_envelope(journal.approval,journal.draft,created,metadata)
            if type(envelope) is not TaxDeliveryEnvelopeObservation:raise ValueError()
            envelope.assert_instance(journal.approval,journal.draft,metadata)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_envelope=await self._retain_read(session,query,command,envelope)
        if self._validation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.START_VALIDATION)
        try:
            proof=bind_tax_delivery_validation_prerequisite(retained.approval,retained.draft,
                retained_instance=first_metadata,retained_envelope=first_envelope,fresh_instance=metadata,fresh_envelope=envelope,
                observed_from=began,observed_until=self._runtime.now())
        except (ValueError,TypeError):raise CompanyTaxError.draft_conflict() from None
        request=build_tax_delivery_mutation_request(retained.approval,retained.draft,TaxMutationKind.START_VALIDATION,
            target_instance=created.result['instanceId'],validation_prerequisite=proof)
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id);_approved(latest,command)
                if self._validation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.START_VALIDATION)
                fresh=await read_company_tax_delivery_source(snapshot,query,correlation_id=command.correlation_id)
            if fresh!=source or latest.draft!=journal.draft:raise CompanyTaxError.draft_conflict()
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            try:proof.assert_current(self._runtime.now())
            except ValueError:raise CompanyTaxError.unavailable() from None
            if latest.plan(request) is not TaxMutationDisposition.EXECUTE:raise CompanyTaxError.draft_conflict()
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(request);retained=self._append(latest,result,request)
        if not result.inserted:return retained.mutation_progress(TaxMutationKind.START_VALIDATION)
        try:
            self._admit(retained,session.actor_id);proof.assert_current(self._runtime.now())
            completion=await self._authority.execute(request,retained.approval,retained.draft)
            if type(completion) is not TaxDeliveryMutationCompletion:raise ValueError()
            completion.assert_request(request,retained.approval)
        except (CompanyTaxReturnAuthorityError,CompanyTaxError,ValueError,TypeError,RecursionError,OverflowError):
            return retained.mutation_progress(TaxMutationKind.START_VALIDATION)
        async with session.transaction() as transaction:
            result=await transaction.append_delivery_event(completion);completed=self._append(retained,result,completion)
        return completed.mutation_progress(TaxMutationKind.START_VALIDATION)

    async def reconcile_validation(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        request=self._validation_original(journal)
        if request is None:raise CompanyTaxError.draft_conflict()
        started=next((event.value for event in journal.events if event.slot=='completion:start_validation'),None)
        # No retained job ID means no documented GET target, lookup or retry.
        if started is None:return journal.mutation_progress(TaxMutationKind.START_VALIDATION)
        if not journal.validation_evidence or self._response_schemas is None:raise CompanyTaxError.unavailable()
        if self._admit(journal,session.actor_id)!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        try:
            job=await self._authority.observe_validation_job(journal.approval,journal.draft,request,started)
            if type(job) is not TaxDeliveryValidationJobObservation:raise ValueError()
            job.assert_started(journal.approval,journal.draft,request,started)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,_=await self._retain_read(session,query,command,job)
        if not job.inspection.known or job.inspection.status is not TaxValidationJobStatus.FINISHED:
            return retained.mutation_progress(TaxMutationKind.START_VALIDATION)
        try:
            value=await self._authority.observe_validation_result(journal.approval,journal.draft,request,started,job,
                schema_sha256=self._response_schemas.schema_sha256)
            if type(value) is not TaxDeliveryValidationResultObservation:raise ValueError()
            value.assert_status(journal.approval,journal.draft,request,started,job)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,_=await self._retain_read(session,query,command,value)
        try:value.inspect(self._response_schemas)
        except (ValueError,TypeError,CompanyTaxError):raise CompanyTaxError.unavailable() from None
        return retained.mutation_progress(TaxMutationKind.START_VALIDATION)

    @staticmethod
    def _confirmation_original(journal):
        return next((event.value for event in journal.events if event.slot=='intent:prepare_confirmation'),None)

    async def owner_review(self,session: CompanyTaxSession,query: TaxDeliveryOwnerReviewQuery):
        """Read exact prepared documents; current access/source is rechecked.

        No provider operation, mutation or readiness flag is returned. Expired
        dispatch admission cannot erase retained owner-review originals.
        """
        if type(query) is not TaxDeliveryOwnerReviewQuery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);scope=_query(session,query)
        journal=await self._guarded_history(session,scope,query.filing_id);_approved(journal,query)
        if not journal.confirmation_evidence or self._response_schemas is None or self._calculated_schemas is None:
            raise CompanyTaxError.unavailable()
        request=self._confirmation_original(journal)
        prepared=next((event.value for event in journal.events if event.slot=='completion:prepare_confirmation'),None)
        if request is None or request.confirmation_prerequisite is None or prepared is None:raise CompanyTaxError.draft_conflict()
        result=next((event.value for event in journal.events
            if event.value.sha256==request.confirmation_prerequisite.result_read.event_sha256),None)
        if type(result) is not TaxDeliveryValidationResultObservation:raise CompanyTaxError.unavailable()
        try:
            response=self._response_schemas.review(result.original)
            calculated=self._calculated_schemas.review_documents(result.original,draft=journal.draft)
            artifact=build_tax_delivery_owner_review(journal.approval,journal.draft,request,prepared,result,
                calculated=calculated,response=response)
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(scope)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,scope,query.filing_id);_approved(latest,query)
                current=await read_company_tax_delivery_source(snapshot,scope,correlation_id=query.correlation_id)
            if (latest.draft!=journal.draft or current!=journal.draft.envelope.source
                    or self._confirmation_original(latest)!=request
                    or not any(event.value==prepared for event in latest.events)):
                raise CompanyTaxError.draft_conflict()
            await guard.lock_delivery_draft_archive(scope)
        return artifact

    async def advance_confirmation(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        """Enter the owner-review stage once. This does not submit a filing."""
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        if self._confirmation_original(journal) is not None:return journal.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        if not journal.confirmation_evidence or self._response_schemas is None or self._calculated_schemas is None:
            raise CompanyTaxError.unavailable()
        created=self._created(journal);start_request=self._validation_original(journal)
        started=next((event.value for event in journal.events if event.slot=='completion:start_validation'),None)
        if start_request is None or started is None:raise CompanyTaxError.draft_conflict()
        context=self._admit(journal,session.actor_id)
        if context!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        source=await self._source(session,query,command)
        if source!=journal.draft.envelope.source:raise CompanyTaxError.draft_conflict()
        latest=await self._guarded_history(session,query,command.filing_id);_approved(latest,command)
        if self._confirmation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
        current=await self._current(journal)
        if self._review(journal,source,current,actor=session.actor_id,approval_id=journal.approval.approval_id,context=context)!=journal.approval:
            raise CompanyTaxError.draft_conflict()
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:latest=await self._history(snapshot,query,command.filing_id)
            _approved(latest,command)
            if self._confirmation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            await guard.lock_delivery_draft_archive(query)
            await self._retain_admission(guard,latest)
        began=self._runtime.now()
        try:
            job=await self._authority.observe_validation_job(journal.approval,journal.draft,start_request,started)
            if type(job) is not TaxDeliveryValidationJobObservation:raise ValueError()
            job.assert_started(journal.approval,journal.draft,start_request,started)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_job=await self._retain_read(session,query,command,job)
        if self._confirmation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        if not job.inspection.known or job.inspection.status is not TaxValidationJobStatus.FINISHED:raise CompanyTaxError.draft_conflict()
        try:
            response=await self._authority.observe_validation_result(journal.approval,journal.draft,start_request,started,job,
                schema_sha256=self._response_schemas.schema_sha256)
            if type(response) is not TaxDeliveryValidationResultObservation:raise ValueError()
            response.assert_status(journal.approval,journal.draft,start_request,started,job)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_result=await self._retain_read(session,query,command,response)
        if self._confirmation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        calculated=self._calculated_schemas.inspect(response.original,draft=journal.draft)
        file_began=self._runtime.now()
        try:
            instance=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(instance) is not TaxDeliveryInstanceObservation:raise ValueError()
            instance.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_instance=await self._retain_read(session,query,command,instance)
        if self._confirmation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        inspection=instance.inspection
        if (not inspection.known or inspection.process_task!='data' or inspection.envelope is None
                or inspection.envelope.scan_result!='Clean' or len(inspection.data)!=1):raise CompanyTaxError.draft_conflict()
        try:
            envelope=await self._authority.observe_envelope(journal.approval,journal.draft,created,instance)
            if type(envelope) is not TaxDeliveryEnvelopeObservation:raise ValueError()
            envelope.assert_instance(journal.approval,journal.draft,instance)
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,first_envelope=await self._retain_read(session,query,command,envelope)
        if self._confirmation_original(retained) is not None:return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        try:
            clean=bind_tax_delivery_validation_prerequisite(retained.approval,retained.draft,
                retained_instance=first_instance,retained_envelope=first_envelope,fresh_instance=instance,fresh_envelope=envelope,
                observed_from=file_began,observed_until=self._runtime.now())
            proof=bind_tax_delivery_confirmation_prerequisite(retained.approval,retained.draft,start_request,started,
                retained_job=first_job,retained_result=first_result,fresh_job=job,fresh_result=response,calculated=calculated,
                clean_file=clean,retained_instance=first_instance,retained_envelope=first_envelope,
                observed_from=began,observed_until=self._runtime.now())
        except (ValueError,TypeError):raise CompanyTaxError.draft_conflict() from None
        request=build_tax_delivery_mutation_request(retained.approval,retained.draft,TaxMutationKind.PREPARE_CONFIRMATION,
            target_instance=created.result['instanceId'],confirmation_prerequisite=proof)
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                latest=await self._history(snapshot,query,command.filing_id);_approved(latest,command)
                if self._confirmation_original(latest) is not None:return latest.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
                fresh=await read_company_tax_delivery_source(snapshot,query,correlation_id=command.correlation_id)
            if fresh!=source or latest.draft!=journal.draft:raise CompanyTaxError.draft_conflict()
            if self._admit(latest,session.actor_id)!=context:raise CompanyTaxError.forbidden()
            try:proof.assert_current(self._runtime.now())
            except ValueError:raise CompanyTaxError.unavailable() from None
            if latest.plan(request) is not TaxMutationDisposition.EXECUTE:raise CompanyTaxError.draft_conflict()
            await guard.lock_delivery_draft_archive(query)
            result=await guard.append_delivery_event(request);retained=self._append(latest,result,request)
        if not result.inserted:return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        try:
            self._admit(retained,session.actor_id);proof.assert_current(self._runtime.now())
            acknowledgment=await self._authority.prepare_confirmation(request,retained.approval,retained.draft)
            if type(acknowledgment) is not TaxDeliveryProcessAcknowledgment:raise ValueError()
            acknowledgment.assert_request(request,retained.approval,retained.draft)
        except (CompanyTaxReturnAuthorityError,CompanyTaxError,ValueError,TypeError,RecursionError,OverflowError):
            return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        async with session.transaction() as transaction:
            result=await transaction.append_delivery_event(acknowledgment)
            retained=self._append(retained,result,acknowledgment)
        # Even a successful process response is only an acknowledgment. A
        # separate read-only reconciliation proves the owner confirmation task.
        return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)

    async def reconcile_confirmation(self,session: CompanyTaxSession,command: AdvanceTaxDelivery):
        if type(command) is not AdvanceTaxDelivery:raise CompanyTaxError.invalid_input()
        self._runtime.assert_session(session);query=_query(session,command)
        journal=await self._guarded_history(session,query,command.filing_id);_approved(journal,command)
        request=self._confirmation_original(journal)
        if request is None:raise CompanyTaxError.draft_conflict()
        if any(event.slot=='completion:prepare_confirmation' for event in journal.events):
            return journal.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        if not journal.confirmation_evidence:raise CompanyTaxError.unavailable()
        if self._admit(journal,session.actor_id)!=journal.approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        created=self._created(journal)
        try:
            instance=await self._authority.observe_instance(journal.approval,journal.draft,created)
            if type(instance) is not TaxDeliveryInstanceObservation:raise ValueError()
            instance.assert_approval(journal.approval,journal.draft,created.result['instanceId'])
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
        retained,_=await self._retain_read(session,query,command,instance)
        if any(event.slot=='completion:prepare_confirmation' for event in retained.events):
            return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        if not is_tax_delivery_owner_confirmation_instance(instance):return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        try:
            envelope=await self._authority.observe_envelope(journal.approval,journal.draft,created,instance)
            if type(envelope) is not TaxDeliveryEnvelopeObservation:raise ValueError()
            envelope.assert_instance(journal.approval,journal.draft,instance)
            completion=reconcile_tax_delivery_confirmation(request,journal.approval,journal.draft,
                evidence=TaxDeliveryConfirmationReadEvidence(instance,envelope),observed_at=self._runtime.now())
        except CompanyTaxReturnAuthorityError:raise CompanyTaxError.unavailable() from None
        except (ValueError,TypeError,RecursionError,OverflowError):
            # A scoped changed file is retained as drift, never as permission to
            # repeat this PUT or to perform the later submission transition.
            if 'envelope' in locals() and type(envelope) is TaxDeliveryEnvelopeObservation:
                retained,_=await self._retain_read(session,query,command,envelope)
            return retained.mutation_progress(TaxMutationKind.PREPARE_CONFIRMATION)
        return await self._record_read_completion(session,query,command,retained,request,completion)
