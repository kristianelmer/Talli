"""Exact-year active Documents metadata for RF annual-readiness composition."""
from dataclasses import dataclass

from talli_backend.modules.documents.public import DocumentRecord, DocumentStatus
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear


@dataclass(frozen=True, slots=True)
class Rf1086AnnualDocumentInputs:
    company_id: CompanyId
    income_year: IncomeYear
    documents: tuple[DocumentRecord, ...]


def annual_document_inputs(records: tuple[DocumentRecord, ...],
                           query: rf.Rf1086SourceQuery) -> Rf1086AnnualDocumentInputs:
    """Select after complete enumeration; metadata never proves original bytes."""
    if (type(records) is not tuple
            or any(not isinstance(item, DocumentRecord) or item.company_id != query.company_id
                   or item.status == DocumentStatus.REMOVED or item.removed_at is not None
                   for item in records)
            or len({item.document_id for item in records}) != len(records)):
        raise rf.ShareholderRegisterFilingError.unavailable()
    selected = tuple(sorted((item for item in records if item.income_year == query.income_year),
                            key=lambda item: str(item.document_id)))
    return Rf1086AnnualDocumentInputs(query.company_id, query.income_year, selected)
