"""Complete retained Tax journal originals under a current archive guard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .public import CompanyTaxSourceFacts

from .delivery_draft import StoredTaxDeliveryDraft
from .delivery_events import StoredTaxDeliveryEvent
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


@dataclass(frozen=True, slots=True)
class TaxDeliveryJournalArchive:
    company_id: CompanyId
    income_year: IncomeYear
    drafts: tuple[StoredTaxDeliveryDraft, ...]
    events: tuple[StoredTaxDeliveryEvent, ...]
    source_facts: CompanyTaxSourceFacts
    observed_at: Timestamp


def archive_tax_delivery_journal(query, snapshot) -> TaxDeliveryJournalArchive:
    from .public import CompanyTaxError, project_company_tax_source
    facts=project_company_tax_source(query,snapshot)
    # An unresolved predecessor effect does not erase retained originals. Every
    # extent, enumeration, linkage, tracking and scope failure still blocks.
    if (snapshot.contract_version!='company-tax-source-v3'
            or facts.history_coverage.status=='unavailable'
            or set(facts.history_coverage.reasons)-{'production_journal_unavailable'}):
        raise CompanyTaxError.unavailable()
    return TaxDeliveryJournalArchive(query.company_id,query.income_year,
        snapshot.delivery_drafts,snapshot.delivery_events,facts,snapshot.as_of)
