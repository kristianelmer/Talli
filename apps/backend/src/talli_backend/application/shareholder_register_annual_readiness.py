"""Thin composition of owner evidence inside an existing RF admission."""
from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.application.shareholder_register_annual_documents import Rf1086AnnualDocumentInputs
from talli_backend.application.shareholder_register_annual_ledger import Rf1086AnnualLedgerInputs
from talli_backend.application.shareholder_register_annual_opening import Rf1086AnnualOpeningInputs
from talli_backend.modules.banking.public import BankYearReconciliationEvidence
from talli_backend.modules.shareholder_register_filing import public as rf


def _scope(value, expected_type, source):
    if (not isinstance(value, expected_type) or value.company_id != source.company_id
            or value.income_year != source.income_year):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')


async def read_annual_readiness(admitted, correlation_id):
    """All owner reads remain sequential on the same held connection."""
    transaction, source = admitted.transaction, admitted.source
    opening = await transaction.annual_opening_inputs()
    _scope(opening, Rf1086AnnualOpeningInputs, source)
    ledger = await transaction.annual_ledger_inputs(correlation_id)
    _scope(ledger, Rf1086AnnualLedgerInputs, source)
    banking = await transaction.bank_year_evidence(correlation_id)
    if not isinstance(banking, BankYearReconciliationEvidence):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')
    reconciliation = banking.reconciliation
    if reconciliation.company_id != source.company_id or reconciliation.income_year != source.income_year:
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')
    interview = await transaction.annual_interview()
    if interview is not None:
        _scope(interview, LegacyAnnualDataView, source)
    documents = await transaction.annual_document_inputs()
    _scope(documents, Rf1086AnnualDocumentInputs, source)
    # Missing keys retain the frozen interview consumer's false default. Typed
    # decoder validation forbids string/number truthiness for present answers.
    answers = interview.answers if interview is not None else {}
    inputs = rf.Rf1086AnnualReadinessInputs(
        company_id=source.company_id, income_year=source.income_year,
        opening_snapshot_ids=tuple(sorted(str(item.opening_snapshot_id) for item in opening.opening_sources)),
        opening_bank_snapshot_ids=tuple(sorted(item.snapshot_id for item in ledger.opening_bank_inputs)),
        period_lock_ids=tuple(sorted(str(item.period_lock_id) for item in ledger.period_locks)),
        bank_transaction_count=reconciliation.transaction_count,
        unmatched_bank_count=reconciliation.unmatched_count,
        accepted_bank_warning_count=reconciliation.accepted_warning_count,
        interview_source_id=interview.source_id if interview is not None else None,
        bank_balance_confirmed=answers.get('bank_balance_confirmed', False) if interview is not None else None,
        has_unpaid_items=answers.get('has_unpaid_items', False) if interview is not None else None,
        authority_to_submit_confirmed=answers.get('authority_to_submit_confirmed', False) if interview is not None else None,
        documents=tuple(sorted((rf.Rf1086AnnualDocumentStatus(str(item.document_id), item.linked_to, item.status.value)
                               for item in documents.documents), key=lambda item: item.document_id)),
        evidence_sha256={
            'opening': rf.rf1086_year_source_digest(opening),
            'ledger': rf.rf1086_year_source_digest(ledger),
            'banking': banking.source_sha256,
            'interview': rf.rf1086_year_source_digest(interview),
            'documents': rf.rf1086_year_source_digest(documents),
        },
    )
    return rf.build_rf1086_annual_readiness(source, admitted.preview, inputs)
