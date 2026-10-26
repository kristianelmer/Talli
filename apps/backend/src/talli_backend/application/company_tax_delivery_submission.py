"""Guarded finite Tax review, create and upload with durable submit-once intents.

All authority I/O follows closed SQL contexts. A committed uncertain create has
no documented lookup proof and remains reconciliation-only. Unknown uploads
resolve only through exact known-instance reads. Validation and confirmation
stay closed until their retained prerequisites are implemented.
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
        return TaxDeliveryJournal(journal.draft,journal.events+(result.event,),journal.read_evidence,journal.guarded_upload)

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
        if type(value) not in (TaxDeliveryInstanceObservation,TaxDeliveryEnvelopeObservation):raise CompanyTaxError.invalid_input()
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
            retained=TaxDeliveryJournal(latest.draft,latest.events+(result.event,),latest.read_evidence,latest.guarded_upload)
        return retained,result.event.value

    @staticmethod
    def _upload_original(journal):
        return next((event.value for event in journal.events if event.slot=='intent:upload_envelope'),None)

    @staticmethod
    def _created(journal):
        value=next((event.value for event in journal.events if event.slot=='completion:create_instance'),None)
        if type(value) is not TaxDeliveryMutationCompletion:raise CompanyTaxError.draft_conflict()
        return value

    async def _record_upload_completion(self,session,query,command,retained,request,completion):
        try:
            async with session.transaction() as transaction:
                result=await transaction.append_delivery_event(completion)
                completed=self._append(retained,result,completion)
            return completed.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)
        except CompanyTaxError as error:
            if error.code not in ('COMPANY_TAX_INVALID_INPUT','COMPANY_TAX_DRAFT_CONFLICT'):raise
            # Another caller can have committed different exact read originals
            # for this same intent. The narrow late-result writer cannot reveal
            # them: only a separate current owner/MFA history read may do so.
            latest=await self._guarded_history(session,query,command.filing_id)
            _approved(latest,command)
            if (self._upload_original(latest)!=request
                    or not any(event.slot=='completion:upload_envelope' for event in latest.events)):raise
            return latest.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE)

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
        return await self._record_upload_completion(session,query,command,retained,request,completion)

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
        return await self._record_upload_completion(session,query,command,retained,request,completion)
