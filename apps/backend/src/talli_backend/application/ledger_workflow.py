"""Thin authenticated application wrapper around the ledger capability."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from talli_backend.application.ledger_session import (
    AuthenticatedLedgerSession,
    LedgerAuthenticationError,
    LedgerSessionFactory,
)
from talli_backend.modules.ledger.public import (
    LedgerCommands,
    LedgerCursor,
    LedgerEntryPage,
    LedgerQueries,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostOpeningBalanceCommand,
    LockPeriodCommand,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId


class LedgerFacade(LedgerCommands, LedgerQueries, Protocol):
    pass


LedgerFacadeFactory = Callable[[AuthenticatedLedgerSession], LedgerFacade]


class LedgerApplicationSession:
    def __init__(
        self,
        persistence: AuthenticatedLedgerSession,
        ledger: LedgerFacade,
    ) -> None:
        self._persistence = persistence
        self._ledger = ledger

    @property
    def actor_id(self) -> ActorId:
        return self._persistence.actor_id

    async def post_opening_balance(
        self, command: PostOpeningBalanceCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_opening_balance(command)

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_administrative_cost(command)

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_manual_journal(command)

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        return await self._ledger.lock_period(command)

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        return await self._ledger.list_entries(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        return await self._ledger.list_period_locks(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


class LedgerApplication:
    def __init__(
        self,
        sessions: LedgerSessionFactory,
        facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._sessions = sessions
        self._facade_factory = facade_factory

    async def session(self, access_token: str) -> LedgerApplicationSession:
        persistence = await self._sessions.session(access_token)
        return LedgerApplicationSession(
            persistence,
            self._facade_factory(persistence),
        )


__all__ = [
    "LedgerApplication",
    "LedgerAuthenticationError",
    "LedgerFacadeFactory",
    "LedgerSessionFactory",
]
