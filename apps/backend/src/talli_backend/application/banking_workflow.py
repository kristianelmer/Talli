"""Authenticated banking workflows and atomic ledger composition."""

from __future__ import annotations

from collections.abc import Callable

from talli_backend.application.banking_session import (
    AuthenticatedBankingSession,
    BankingSessionFactory,
)
from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankStatementImportResult,
    BankSuggestionAcceptancePage,
    BankSuggestionKind,
    BankTransactionPage,
    BankingCursor,
    BankingError,
    ImportBankStatementCommand,
)
from talli_backend.modules.banking.service import BankingService
from talli_backend.modules.ledger.public import (
    BankSuggestionRule,
    LedgerCommands,
    LedgerPersistence,
    LedgerSourceRecordId,
    PostBankSuggestionOutcomeCommand,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, Money


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerCommands]

_LEDGER_RULE = {
    BankSuggestionKind.BANK_FEE: BankSuggestionRule.BANK_FEE,
    BankSuggestionKind.SYSTEM_SUBSCRIPTION: BankSuggestionRule.SYSTEM_SUBSCRIPTION,
    BankSuggestionKind.DEPOSIT_INTEREST: BankSuggestionRule.DEPOSIT_INTEREST,
}


class BankingSession:
    def __init__(
        self,
        persistence: AuthenticatedBankingSession,
        ledger_facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._persistence = persistence
        self._ledger_facade_factory = ledger_facade_factory

    @property
    def actor_id(self) -> ActorId:
        return self._persistence.actor_id

    async def import_statement(
        self, command: ImportBankStatementCommand
    ) -> BankStatementImportResult:
        if command.actor_id != self.actor_id:
            raise BankingError.forbidden()
        return await BankingService(self._persistence).import_statement(command)

    async def accept_suggestion(
        self, command: AcceptBankSuggestionCommand
    ) -> AcceptedBankSuggestion:
        if command.actor_id != self.actor_id:
            raise BankingError.forbidden()
        async with self._persistence.transaction() as transaction:
            banking = BankingService(transaction)
            replay = await banking.get_suggestion_acceptance_replay(command)
            if replay is not None:
                return replay
            prepared = await banking.prepare_suggestion_acceptance(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).post_bank_suggestion_outcome(
                PostBankSuggestionOutcomeCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    acceptance_id=LedgerSourceRecordId(str(command.acceptance_id)),
                    rule=_LEDGER_RULE[prepared.suggestion.kind],
                    amount=Money.nok(abs(prepared.transaction.amount.amount)),
                    transaction_text=prepared.transaction.text,
                )
            )
            return await banking.complete_suggestion_acceptance(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def list_transactions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankTransactionPage:
        if actor_id != self.actor_id:
            raise BankingError.forbidden()
        return await BankingService(self._persistence).list_transactions(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_suggestion_acceptances(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankSuggestionAcceptancePage:
        if actor_id != self.actor_id:
            raise BankingError.forbidden()
        return await BankingService(self._persistence).list_suggestion_acceptances(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


class BankingApplication:
    def __init__(
        self,
        sessions: BankingSessionFactory,
        ledger_facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._sessions = sessions
        self._ledger_facade_factory = ledger_facade_factory

    async def session(self, access_token: str) -> BankingSession:
        return BankingSession(
            await self._sessions.session(access_token),
            self._ledger_facade_factory,
        )


__all__ = ["BankingApplication", "BankingSession", "LedgerFacadeFactory"]
