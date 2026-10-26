"""Prepare from owning sources/current authority originals, never caller facts."""
from __future__ import annotations

from talli_backend.application.company_tax_delivery_source import read_company_tax_delivery_source
from talli_backend.application.company_tax_filing_session import CompanyTaxSession
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCurrentDocumentReader, CompanyTaxError, CompanyTaxSourceQuery,
    PrepareTaxDeliveryDraft, StoredTaxDeliveryDraft, TaxDeliveryDraft,
    TaxDeliverySchemaValidator, prepare_tax_delivery,
    TaxCurrentDocument, CompanyTaxReturnAuthorityError,
)


class CompanyTaxDeliveryPreparation:
    def __init__(self, current: CompanyTaxCurrentDocumentReader, schemas: TaxDeliverySchemaValidator):
        self._current, self._schemas = current, schemas

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
        try:
            response = await self._current.fetch_current_document(income_year=int(command.income_year),
                company_org_number=source.organization_number)
        except (CompanyTaxReturnAuthorityError, ValueError):
            raise CompanyTaxError.unavailable() from None
        current = self._schemas.inspect_current(response)
        if (type(current) is not TaxCurrentDocument or current.response.organization_number != source.organization_number
                or current.response.income_year != command.income_year):
            raise CompanyTaxError.unavailable()
        try:
            envelope = prepare_tax_delivery(source,party_number=current.party_number,
                current_document_reference=current.document_reference,schema_sha256=self._schemas.schema_sha256)
            draft = TaxDeliveryDraft(str(command.filing_id),command.command_key,command.actor_id,envelope,
                self._schemas.validate(envelope,current_document=current),current)
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
            await transaction.lock_delivery_draft_archive(query)
            stored = await transaction.store_delivery_draft(draft)
            if stored.draft != draft:
                raise CompanyTaxError.unavailable()
            return stored


def _replayed(stored: StoredTaxDeliveryDraft, command: PrepareTaxDeliveryDraft) -> StoredTaxDeliveryDraft:
    draft = stored.draft
    if (draft.prepared_by != command.actor_id or draft.command_key != command.command_key
            or draft.envelope.source.company_id != command.company_id
            or draft.envelope.source.income_year != command.income_year):
        raise CompanyTaxError.unavailable()
    if draft.filing_id != str(command.filing_id) or draft.current_document is None:
        raise CompanyTaxError.draft_conflict()
    return stored
