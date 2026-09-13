"""Company Tax capture composes public Ledger, Banking and Documents contracts."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from talli_backend.application.company_tax_filing_session import CompanyTaxSession, CompanyTaxSessionFactory
from talli_backend.modules.banking.public import BankTransactionId, ExternalActionReference, TaxSettlementBankCommand
from talli_backend.modules.company_tax_filing.public import (
    AccountingEntryReference, CompanyTaxError, RecordTaxSettlementCommand,
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
