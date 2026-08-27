"""Thin authenticated application wrapper around the ledger capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from talli_backend.application.ledger_session import (
    AuthenticatedLedgerSession,
    LedgerAuthenticationError,
    LedgerSessionFactory,
    LedgerWorkflowTransaction,
)
from talli_backend.application.shareholder_register_compatibility import (
    LegacyShareholderRegisterFilingFacade,
)
from talli_backend.modules.ledger.public import (
    LedgerCommands,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerError,
    LedgerPersistence,
    LedgerQueries,
    LedgerSourceRecordId,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostOpeningBalanceCommand,
    LockPeriodCommand,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
    ShareholderRegisterFilingCommands,
    ShareholderRegisterFilingError,
)
from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    Money,
    Timestamp,
)


@dataclass(frozen=True, slots=True)
class NewYearStartCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    bank_balance: Money
    share_capital: Money
    share_count: int
    nominal_value: Money
    shareholders: tuple[OpeningShareholder, ...]

    def __post_init__(self) -> None:
        try:
            _opening_snapshot_command(self)
        except ShareholderRegisterFilingError:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")


@dataclass(frozen=True, slots=True)
class NewYearStartResult:
    setup_id: OpeningSnapshotId
    posted_entry: PostedLedgerEntry


def _opening_snapshot_command(
    command: NewYearStartCommand,
) -> RecordOpeningSnapshotCommand:
    return RecordOpeningSnapshotCommand(
        company_id=command.company_id,
        actor_id=command.actor_id,
        correlation_id=command.correlation_id,
        idempotency_key=command.idempotency_key,
        income_year=command.income_year,
        share_capital=command.share_capital,
        share_count=command.share_count,
        nominal_value=command.nominal_value,
        shareholders=command.shareholders,
    )


def _new_year_request(command: NewYearStartCommand) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "bankBalance": format(command.bank_balance.amount, "f"),
        "shareCapital": format(command.share_capital.amount, "f"),
        "shareCount": command.share_count,
        "nominalValue": format(command.nominal_value.amount, "f"),
        "shareholders": [
            {
                "name": shareholder.name,
                "shareholderKind": shareholder.shareholder_kind,
                "nationalId": shareholder.national_id,
                "orgNumber": shareholder.org_number,
                "shareCount": shareholder.share_count,
            }
            for shareholder in command.shareholders
        ],
    }


def _new_year_result_payload(result: NewYearStartResult) -> dict[str, object]:
    posted = result.posted_entry
    return {
        "setupId": str(result.setup_id),
        "entryId": str(posted.entry_id),
        "companyId": str(posted.company_id),
        "incomeYear": int(posted.income_year),
        "entryKind": posted.entry_kind.value,
        "postedAt": posted.posted_at.value.isoformat(),
    }


def _replayed_new_year(
    payload: dict[str, object], command: NewYearStartCommand
) -> NewYearStartResult:
    try:
        setup_id = OpeningSnapshotId(str(UUID(str(payload["setupId"]))))
        posted = PostedLedgerEntry(
            entry_id=LedgerEntryId(str(payload["entryId"])),
            company_id=CompanyId(str(payload["companyId"])),
            income_year=IncomeYear(int(payload["incomeYear"])),
            entry_kind=LedgerEntryKind(str(payload["entryKind"])),
            posted_at=Timestamp(
                datetime.fromisoformat(str(payload["postedAt"]).replace("Z", "+00:00"))
            ),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError):
        raise LedgerError.unavailable() from None
    if (
        posted.company_id != command.company_id
        or posted.income_year != command.income_year
        or posted.entry_kind is not LedgerEntryKind.OPENING_BALANCE
    ):
        raise LedgerError.unavailable()
    return NewYearStartResult(setup_id=setup_id, posted_entry=posted)


class LedgerFacade(LedgerCommands, LedgerQueries, Protocol):
    pass


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerFacade]
OpeningSnapshotFacadeFactory = Callable[
    [LedgerWorkflowTransaction, Money], ShareholderRegisterFilingCommands
]


class LedgerApplicationSession:
    def __init__(
        self,
        persistence: AuthenticatedLedgerSession,
        ledger: LedgerFacade,
        facade_factory: LedgerFacadeFactory,
        opening_snapshot_factory: OpeningSnapshotFacadeFactory,
    ) -> None:
        self._persistence = persistence
        self._ledger = ledger
        self._facade_factory = facade_factory
        self._opening_snapshot_factory = opening_snapshot_factory

    @property
    def actor_id(self) -> ActorId:
        return self._persistence.actor_id

    async def post_opening_balance(
        self, command: PostOpeningBalanceCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_opening_balance(command)

    async def start_new_year(
        self, command: NewYearStartCommand
    ) -> NewYearStartResult:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()

        for attempt in range(2):
            try:
                return await self._start_new_year_once(command)
            except (LedgerError, ShareholderRegisterFilingError) as error:
                if (
                    error.category is not ErrorCategory.DEPENDENCY_UNAVAILABLE
                    or attempt == 1
                ):
                    raise
        raise LedgerError.unavailable()

    async def _start_new_year_once(
        self, command: NewYearStartCommand
    ) -> NewYearStartResult:
        operation_name = "new_year_start"
        async with self._persistence.transaction() as transaction:
            replay = await transaction.claim_workflow(
                operation_name=operation_name,
                command=command,
                request=_new_year_request(command),
            )
            if replay is not None:
                return _replayed_new_year(replay, command)

            setup_id = await self._opening_snapshot_factory(
                transaction,
                command.bank_balance,
            ).record_opening_snapshot(_opening_snapshot_command(command))
            ledger = self._facade_factory(transaction)
            posted_entry = await ledger.post_opening_balance(
                PostOpeningBalanceCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    bank_balance=command.bank_balance,
                    share_capital_snapshot=command.share_capital,
                    opening_snapshot_id=LedgerSourceRecordId(
                        f"opening-setup:{setup_id}"
                    ),
                )
            )
            result = NewYearStartResult(
                setup_id=setup_id,
                posted_entry=posted_entry,
            )
            await transaction.complete_workflow(
                operation_name=operation_name,
                command=command,
                result=_new_year_result_payload(result),
            )
            return result

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
        opening_snapshot_factory: OpeningSnapshotFacadeFactory = (
            LegacyShareholderRegisterFilingFacade
        ),
    ) -> None:
        self._sessions = sessions
        self._facade_factory = facade_factory
        self._opening_snapshot_factory = opening_snapshot_factory

    async def session(self, access_token: str) -> LedgerApplicationSession:
        persistence = await self._sessions.session(access_token)
        return LedgerApplicationSession(
            persistence,
            self._facade_factory(persistence),
            self._facade_factory,
            self._opening_snapshot_factory,
        )


__all__ = [
    "LedgerApplication",
    "LedgerAuthenticationError",
    "LedgerFacadeFactory",
    "LedgerSessionFactory",
    "NewYearStartCommand",
    "NewYearStartResult",
]
