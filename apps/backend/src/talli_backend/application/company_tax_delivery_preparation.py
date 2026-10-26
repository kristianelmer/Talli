"""Prepare from owning sources/current authority originals, never caller facts."""
from __future__ import annotations

from datetime import datetime,UTC
from talli_backend.shared.kernel import Timestamp

from talli_backend.application.company_tax_delivery_source import read_company_tax_delivery_source
from talli_backend.application.company_tax_filing_session import CompanyTaxSession
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCurrentDocumentReader, CompanyTaxError, CompanyTaxSourceQuery,
    PrepareTaxDeliveryDraft, StoredTaxDeliveryDraft, TaxDeliveryDraft,
    TaxDeliverySchemaValidator, prepare_tax_delivery,
    TaxCurrentDocument, CompanyTaxReturnAuthorityError,
    CompanyTaxCurrentDocumentIntake,TaxCurrentDocumentIntakeQuery,
    CompanyTaxTerminalParentReader,PrepareTaxDeliveryCorrection,TaxDeliveryCorrectionParent,
    TaxDeliverySubmissionReadEvidence,assert_tax_delivery_attempt_history,bind_tax_delivery_correction_parent,
)


class CompanyTaxDeliveryPreparation:
    def __init__(self, current: CompanyTaxCurrentDocumentReader | None, schemas: TaxDeliverySchemaValidator,
            *,intake: CompanyTaxCurrentDocumentIntake | None=None,parent_reader: CompanyTaxTerminalParentReader | None=None,now=None):
        if (current is None)==(intake is None):raise ValueError('Tax preparation needs exactly one current-document reader.')
        self._current, self._schemas = current, schemas
        self._intake=intake;self._parent_reader=parent_reader
        self._now=now or (lambda:Timestamp(datetime.now(UTC)))

    async def prepare(self, session: CompanyTaxSession, command: PrepareTaxDeliveryDraft) -> StoredTaxDeliveryDraft:
        if command.actor_id != session.actor_id:
            raise CompanyTaxError.forbidden()
        query = CompanyTaxSourceQuery(command.company_id,command.income_year,command.actor_id)
        # Read committed, authorized replay precedes any authority GET or source
        # regeneration. A lost response returns the exact original artifact.
        async with session.transaction() as transaction:
            stored = await transaction.delivery_draft_by_key(query,command.command_key)
            if stored is None:
                # The canonical original-read guard also protects current Tax
                # intake. It grants no Billing entitlement or filing permission.
                await transaction.lock_delivery_draft_archive(query)
        if stored is not None:
            return _replayed(stored,command)
        async with session.transaction(snapshot=True) as transaction:
            source = await read_company_tax_delivery_source(transaction,query,correlation_id=command.correlation_id)
        # Source enumeration can take time. Recheck current owner/MFA only
        # after it closes, immediately before the external read, with no SQL
        # transaction carried into provider I/O.
        async with session.transaction() as transaction:
            await transaction.lock_delivery_draft_archive(query)
            stored = await transaction.delivery_draft_by_key(query,command.command_key)
        if stored is not None:
            return _replayed(stored,command)
        correction=None
        if type(command) is PrepareTaxDeliveryCorrection:
            if self._parent_reader is None or self._intake is None:raise CompanyTaxError.unavailable()
            correction=await self._correction_parent(session,command,source)
        try:
            if self._intake is not None:
                response=await self._intake.read_current_document(TaxCurrentDocumentIntakeQuery(command.company_id,command.income_year,
                    command.actor_id,source.organization_number,getattr(session,'delivery_rehearsal_target',None),command.correlation_id))
            else:
                response = await self._current.fetch_current_document(income_year=int(command.income_year),
                    company_org_number=source.organization_number)
        except (CompanyTaxReturnAuthorityError, ValueError):
            raise CompanyTaxError.unavailable() from None
        schema_context={} if correction is None else {'correction_parent':correction}
        current = self._schemas.inspect_current(response,**schema_context)
        if (type(current) is not TaxCurrentDocument or current.response.organization_number != source.organization_number
                or current.response.income_year != command.income_year):
            raise CompanyTaxError.unavailable()
        try:
            envelope = prepare_tax_delivery(source,party_number=current.party_number,
                current_document_reference=current.document_reference,schema_sha256=self._schemas.schema_sha256)
            draft = TaxDeliveryDraft(str(command.filing_id),command.command_key,command.actor_id,envelope,
                self._schemas.validate(envelope,current_document=current,**schema_context),current,correction)
            _ = draft.canonical_json
        except (ValueError,TypeError,OverflowError):
            raise CompanyTaxError.invalid_input() from None
        async with session.transaction() as transaction:
            await transaction.lock_delivery_draft_archive(query)
            # A concurrent command may have won while both requests performed
            # GET. Its exact receipt wins over a new observation timestamp.
            stored = await transaction.delivery_draft_by_key(query,command.command_key)
            if stored is not None:
                return _replayed(stored,command)
            # Hold the RC company guard through a separate RR source snapshot
            # and the final store. Source writers use this same company lock.
            async with session.transaction(snapshot=True) as snapshot:
                latest = await read_company_tax_delivery_source(snapshot,query,
                    correlation_id=command.correlation_id)
            if latest != source:
                raise CompanyTaxError.draft_conflict()
            if correction is not None:
                async with session.transaction(snapshot=True) as snapshot:
                    parent=await self._parent_history(snapshot,query,command)
                try:correction.assert_parent(parent)
                except ValueError:raise CompanyTaxError.draft_conflict() from None
            if correction is not None:
                try:correction.assert_current(self._now())
                except ValueError:raise CompanyTaxError.unavailable() from None
            await transaction.lock_delivery_draft_archive(query)
            stored = await transaction.store_delivery_draft(draft)
            if stored.draft != draft:
                raise CompanyTaxError.unavailable()
            return stored

    async def _parent_history(self,transaction,query,command):
        snapshot=await transaction.journal_history_snapshot(query)
        if snapshot.contract_version!='company-tax-source-v9':raise CompanyTaxError.unavailable()
        parent=assert_tax_delivery_attempt_history(query,snapshot,str(command.parent_filing_id))
        if (parent.draft.sha256!=command.expected_parent_draft_sha256 or parent.approval is None
                or parent.approval.sha256!=command.expected_parent_approval_sha256
                or parent.approval.approved_by!=command.actor_id
                or not any(e.slot=='completion:confirm_submission' for e in parent.events)):
            raise CompanyTaxError.draft_conflict()
        return parent

    async def _guard_parent(self,session,query,command):
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as snapshot:
                parent=await self._parent_history(snapshot,query,command)
            await guard.lock_delivery_draft_archive(query)
        return parent

    async def _correction_parent(self,session,command,source):
        query=CompanyTaxSourceQuery(command.company_id,command.income_year,command.actor_id)
        parent=await self._guard_parent(session,query,command)
        read=TaxCurrentDocumentIntakeQuery(command.company_id,command.income_year,command.actor_id,
            source.organization_number,getattr(session,'delivery_rehearsal_target',None),command.correlation_id)
        try:
            instance=await self._parent_reader.read_parent_instance(read,parent)
            await self._guard_parent(session,query,command)
            feedback=await self._parent_reader.read_parent_feedback(read,parent,instance)
            await self._guard_parent(session,query,command)
            envelope=await self._parent_reader.read_parent_envelope(read,parent,instance)
            link=bind_tax_delivery_correction_parent(parent,TaxDeliverySubmissionReadEvidence(instance,envelope,feedback))
        except (CompanyTaxReturnAuthorityError,ValueError,TypeError,KeyError):
            raise CompanyTaxError.unavailable() from None
        await self._guard_parent(session,query,command)
        return link


def _replayed(stored: StoredTaxDeliveryDraft, command: PrepareTaxDeliveryDraft) -> StoredTaxDeliveryDraft:
    draft = stored.draft
    if (draft.prepared_by != command.actor_id or draft.command_key != command.command_key
            or draft.envelope.source.company_id != command.company_id
            or draft.envelope.source.income_year != command.income_year):
        raise CompanyTaxError.unavailable()
    if type(command) is PrepareTaxDeliveryCorrection:
        link=draft.correction_parent
        if (link is None or link.filing_id!=str(command.parent_filing_id)
                or link.draft_sha256!=command.expected_parent_draft_sha256
                or link.approval_sha256!=command.expected_parent_approval_sha256):raise CompanyTaxError.draft_conflict()
    elif draft.correction_parent is not None:raise CompanyTaxError.draft_conflict()
    if draft.filing_id != str(command.filing_id) or draft.current_document is None:
        raise CompanyTaxError.draft_conflict()
    return stored
