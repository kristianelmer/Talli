"""Complete retained Tax journal originals under a current archive guard."""
from __future__ import annotations

from dataclasses import dataclass,replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .public import CompanyTaxSourceFacts

from .delivery_draft import StoredTaxDeliveryDraft
from .delivery_events import StoredTaxDeliveryEvent,_guarded_upload_value,_validation_value,_confirmation_value
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


@dataclass(frozen=True, slots=True)
class TaxDeliveryJournalArchive:
    company_id: CompanyId
    income_year: IncomeYear
    drafts: tuple[StoredTaxDeliveryDraft, ...]
    events: tuple[StoredTaxDeliveryEvent, ...]
    source_facts: CompanyTaxSourceFacts
    observed_at: Timestamp


def archive_tax_delivery_journal(query, snapshot, *, read_evidence: bool=True,guarded_upload: bool=True,
        validation_evidence: bool=True,confirmation_evidence: bool=True) -> TaxDeliveryJournalArchive:
    from .public import CompanyTaxError, project_company_tax_source
    facts=project_company_tax_source(query,snapshot)
    # An unresolved predecessor effect does not erase retained originals. Every
    # extent, enumeration, linkage, tracking and scope failure still blocks.
    if (snapshot.contract_version not in ('company-tax-source-v3','company-tax-source-v4','company-tax-source-v5','company-tax-source-v6','company-tax-source-v7')
            or facts.history_coverage.status=='unavailable'
            or set(facts.history_coverage.reasons)-{'production_journal_unavailable'}):
        raise CompanyTaxError.unavailable()
    if any(type(value) is not bool for value in (read_evidence,guarded_upload,validation_evidence,confirmation_evidence)):raise CompanyTaxError.invalid_input()
    if snapshot.contract_version=='company-tax-source-v7' and not (read_evidence and guarded_upload and validation_evidence and confirmation_evidence):
        if any(_confirmation_value(event.value) for event in snapshot.delivery_events):raise CompanyTaxError.unavailable()
        proof=dict(snapshot.coverage)|{'contractVersion':'company-tax-source-v6'}
        proof.pop('declaredConfirmationExtentValid',None);proof.pop('confirmationCodecVersion',None)
        snapshot=replace(snapshot,contract_version='company-tax-source-v6',coverage=proof)
        facts=project_company_tax_source(query,snapshot)
    if snapshot.contract_version=='company-tax-source-v6' and not (read_evidence and guarded_upload and validation_evidence):
        if any(_validation_value(event.value) for event in snapshot.delivery_events):raise CompanyTaxError.unavailable()
        proof=dict(snapshot.coverage)|{'contractVersion':'company-tax-source-v5'}
        proof.pop('declaredValidationExtentValid',None);proof.pop('validationCodecVersion',None)
        snapshot=replace(snapshot,contract_version='company-tax-source-v5',coverage=proof)
        facts=project_company_tax_source(query,snapshot)
    if snapshot.contract_version=='company-tax-source-v5' and not (read_evidence and guarded_upload):
        if any(_guarded_upload_value(event.value) for event in snapshot.delivery_events):raise CompanyTaxError.unavailable()
        proof=dict(snapshot.coverage)|{'contractVersion':'company-tax-source-v4'}
        proof.pop('declaredGuardedUploadExtentValid',None);proof.pop('guardedUploadCodecVersion',None)
        snapshot=replace(snapshot,contract_version='company-tax-source-v4',coverage=proof)
        facts=project_company_tax_source(query,snapshot)
    if not read_evidence and snapshot.contract_version=='company-tax-source-v4':
        # Negotiate only a genuinely compatible history. Never omit new records
        # to manufacture a predecessor response, even when a client is older.
        if any(event.slot=='admission' or event.slot.startswith('observation:') for event in snapshot.delivery_events):
            raise CompanyTaxError.unavailable()
        proof=dict(snapshot.coverage)|{'contractVersion':'company-tax-source-v3'}
        proof.pop('declaredObservationExtentValid',None);proof.pop('observationCodecVersion',None)
        compatible=replace(snapshot,contract_version='company-tax-source-v3',coverage=proof)
        facts=project_company_tax_source(query,compatible)
    return TaxDeliveryJournalArchive(query.company_id,query.income_year,
        snapshot.delivery_drafts,snapshot.delivery_events,facts,snapshot.as_of)
