"""Company Tax capture composes public Ledger, Banking and Documents contracts."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from talli_backend.application.company_tax_filing_session import CompanyTaxSession, CompanyTaxSessionFactory
from talli_backend.modules.audit.public import AuditEventDraft
from talli_backend.modules.banking.public import BankTransactionId, ExternalActionReference, TaxSettlementBankCommand
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxRecordQuery, RecordCompanyTaxOverride, AddCompanyTaxReviewComment, ConfirmCompanyTaxPermission,
    RecordCompanyTaxTestEvidence, CompanyTaxRecordedResult, normalize_company_tax_override,
    normalize_company_tax_review, normalize_company_tax_test_evidence,
    AccountingEntryReference, CompanyTaxError, RecordTaxSettlementCommand,
    CompanyTaxWorkspaceQuery, CompanyTaxFilingRows,
    CompanyTaxSourceQuery, CompanyTaxSourceEvidence, CompanyTaxSourceFacts, project_company_tax_source, verify_company_tax_source,
    ImportCompanyTaxReturnEvidence, ImportedCompanyTaxEvidence, CompanyTaxEvidenceInput, project_company_tax_evidence,
    TaxSettlementKind, TaxSettlementArchiveQuery, validate_new_tax_settlement,
)
from talli_backend.modules.documents.public import DocumentBindingQuery, DocumentId
from talli_backend.modules.ledger.public import (
    LedgerCommands, LedgerEntryId, LedgerEntryKind, LedgerPersistence,
    LedgerSourceRecordId, PostedLedgerEntry, PostTaxSettlementCommand,
    TaxSettlementKind as LedgerTaxSettlementKind,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Money, Timestamp


@dataclass(frozen=True, slots=True)
class TaxSettlementResult:
    posted_entry: PostedLedgerEntry
    result: Mapping[str, object]
    replayed: bool


def _replayed(payload: Mapping[str, object], command: RecordTaxSettlementCommand) -> TaxSettlementResult:
    try:
        posted = PostedLedgerEntry(
            entry_id=LedgerEntryId(str(payload['entryId'])),
            company_id=CompanyId(str(payload['companyId'])),
            income_year=IncomeYear(int(payload['incomeYear'])),
            entry_kind=LedgerEntryKind(str(payload['entryKind'])),
            posted_at=Timestamp(datetime.fromisoformat(str(payload['postedAt']).replace('Z', '+00:00'))),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError):
        raise CompanyTaxError.unavailable() from None
    if (posted.company_id != command.company_id or posted.income_year != command.income_year
            or posted.entry_kind is not LedgerEntryKind.TAX_SETTLEMENT
            or str(payload.get('actionId')) != str(command.action_id)):
        raise CompanyTaxError.unavailable()
    return TaxSettlementResult(posted, dict(payload), True)


class CompanyTaxApplication:
    def __init__(self, sessions: CompanyTaxSessionFactory, ledger: Callable[[LedgerPersistence], LedgerCommands]):
        self._sessions, self._ledger = sessions, ledger

    async def session(self, access_token: str) -> AuthenticatedCompanyTax:
        return AuthenticatedCompanyTax(await self._sessions.session(access_token), self._ledger)


class AuthenticatedCompanyTax:
    def __init__(self, session: CompanyTaxSession, ledger: Callable[[LedgerPersistence], LedgerCommands]):
        self._session, self._ledger = session, ledger

    @property
    def actor_id(self):
        return self._session.actor_id

    async def record_tax_settlement(self, command: RecordTaxSettlementCommand) -> TaxSettlementResult:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            replay = await transaction.prepare_settlement(command)
            if replay is not None:
                return _replayed(replay, command)
            validate_new_tax_settlement(command)
            bank = None
            if command.bank_transaction_id is not None:
                bank = TaxSettlementBankCommand(
                    company_id=command.company_id, actor_id=command.actor_id,
                    correlation_id=command.correlation_id, idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    transaction_id=BankTransactionId(str(command.bank_transaction_id)),
                    expected_signed_amount=Money.nok(-command.amount.amount if command.settlement_kind is TaxSettlementKind.PAYMENT else command.amount.amount),
                    action_reference=ExternalActionReference(str(command.action_id)),
                )
                await transaction.prepare_tax_settlement_bank(bank)
            if command.document_id is not None:
                await transaction.lock_document_binding(DocumentBindingQuery(
                    actor_id=command.actor_id, company_id=command.company_id,
                    income_year=command.income_year, document_id=DocumentId(str(command.document_id)),
                ))
            posted = await self._ledger(transaction).post_tax_settlement(PostTaxSettlementCommand(
                company_id=command.company_id, actor_id=command.actor_id,
                correlation_id=command.correlation_id, idempotency_key=command.idempotency_key,
                income_year=command.income_year, settlement_id=LedgerSourceRecordId(str(command.action_id)),
                settlement_kind=LedgerTaxSettlementKind(command.settlement_kind), amount=command.amount,
            ))
            if bank is not None:
                await transaction.claim_tax_settlement_bank(bank)
            result = await transaction.complete_settlement(command, AccountingEntryReference(str(posted.entry_id)))
            return TaxSettlementResult(posted, result, False)

    async def archive_settlements(self, query: TaxSettlementArchiveQuery) -> tuple[Mapping[str, object], ...]:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            rows = await transaction.archive_settlements(query)
            if any(str(row.get('company_id')) != str(query.company_id) or row.get('income_year') != int(query.income_year) for row in rows):
                raise CompanyTaxError.unavailable()
            if len({row.get('id') for row in rows}) != len(rows):
                raise CompanyTaxError.unavailable()
            return rows

    async def filing_workspace(self, query: CompanyTaxWorkspaceQuery) -> CompanyTaxFilingRows:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            result = await transaction.filing_workspace(query)
            if result.company_id != query.company_id or result.income_year != query.income_year:
                raise CompanyTaxError.unavailable()
            return result

    async def filing_source_facts(self, query: CompanyTaxSourceQuery) -> CompanyTaxSourceFacts:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction(snapshot=True) as transaction:
            return project_company_tax_source(query, await transaction.filing_source_snapshot(query))

    async def verify_filing_source(self, query: CompanyTaxSourceQuery, evidence: CompanyTaxSourceEvidence) -> bool:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction(snapshot=True) as transaction:
            return verify_company_tax_source(query, evidence, await transaction.filing_source_snapshot(query))

    async def import_return_evidence(self, command: ImportCompanyTaxReturnEvidence) -> ImportedCompanyTaxEvidence:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            company = await transaction.filing_company_identity(command.company_id, command.actor_id)
            if company.company_id != command.company_id:
                raise CompanyTaxError.unavailable()
            try:
                projection = project_company_tax_evidence(CompanyTaxEvidenceInput(
                    company_id=str(command.company_id), expected_organization_number=company.organization_number,
                    expected_income_year=int(command.income_year), evidence=command.evidence,
                    evidence_url=command.evidence_url, recorded_by=str(command.actor_id.subject),
                ))
            except (ValueError, TypeError):
                raise CompanyTaxError.invalid_input() from None
            result = await transaction.import_return_evidence(projection, command.actor_id)
            if result.created:
                await transaction.include_audit_event(AuditEventDraft(
                    company_id=command.company_id, actor_id=command.actor_id, category='submission',
                    action='company_tax_tt02_evidence_imported',
                    message='Skattemelding TT02-evidens importert og venter på klassifisering med ref '
                    + str(projection.authority_run['test_reference']) + '.',
                ))
            return result

    async def filing_preview(self, query: CompanyTaxRecordQuery) -> Mapping[str, object] | None:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            return await transaction.filing_preview(query)

    async def record_override(self, command: RecordCompanyTaxOverride) -> CompanyTaxRecordedResult:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        normalized = normalize_company_tax_override(command)
        async with self._session.transaction() as transaction:
            return await transaction.record_override(normalized)

    async def add_review_comment(self, command: AddCompanyTaxReviewComment) -> CompanyTaxRecordedResult:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        normalized = normalize_company_tax_review(command)
        async with self._session.transaction() as transaction:
            return await transaction.add_review_comment(normalized)

    async def acknowledge_review_comment(self, query: CompanyTaxRecordQuery) -> CompanyTaxRecordedResult:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        async with self._session.transaction() as transaction:
            result = await transaction.acknowledge_review_comment(query)
            if result.record_id != query.record_id:
                raise CompanyTaxError.unavailable()
            return result

    async def confirm_filing_permission(self, command: ConfirmCompanyTaxPermission) -> CompanyTaxRecordedResult:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        if type(command.production_enabled) is not bool:
            raise CompanyTaxError.invalid_input()
        async with self._session.transaction() as transaction:
            result = await transaction.confirm_filing_permission(command)
            if result.company_id != command.company_id or result.income_year is not None:
                raise CompanyTaxError.unavailable()
            return result

    async def record_test_evidence(self, command: RecordCompanyTaxTestEvidence) -> CompanyTaxRecordedResult:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        normalized = normalize_company_tax_test_evidence(command)
        async with self._session.transaction() as transaction:
            result = await transaction.record_test_evidence(normalized)
            if result.company_id != command.company_id or result.income_year is not None:
                raise CompanyTaxError.unavailable()
            return result
