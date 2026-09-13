from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

from talli_backend.application.ledger_workflow import (
    LedgerApplication,
    NewYearStartCommand,
    RecordAdministrativeCostCommand,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerError,
    LedgerFactReference,
    LedgerLine,
    LedgerPage,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    OpeningBalanceCategory,
    OpeningBankInput,
    RecordOpeningBankInputCommand,
    OpeningBalanceComponent,
    OpeningPositionMode,
    PeriodLockPage,
    PostedLedgerEntry,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)

COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)
SETUP_ID = OpeningSnapshotId("30000000-0000-0000-0000-000000000003")
ENTRY_ID = LedgerEntryId("40000000-0000-0000-0000-000000000004")
NOW = Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC))


def new_year_command() -> NewYearStartCommand:
    return NewYearStartCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("new-year-start-test"),
        idempotency_key=IdempotencyKey(
            "50000000-0000-4000-8000-000000000005"
        ),
        income_year=IncomeYear(2026),
        bank_balance=Money.nok("30000"),
        share_capital=Money.nok("30000"),
        share_count=30000,
        nominal_value=Money.nok("1"),
        shareholders=(
            OpeningShareholder(
                name="Owner",
                shareholder_kind="norwegian_person",
                national_id="01010112345",
                org_number=None,
                share_count=30000,
            ),
        ),
    )


class WorkflowTransactionStub:
    def __init__(self, replay: dict[str, object] | None = None) -> None:
        self.replay = replay
        self.events: list[str] = []
        self.posting: dict[str, object] | None = None
        self.claim_request: dict[str, object] | None = None

    @property
    def actor_id(self) -> ActorId:
        return ACTOR_ID

    async def claim_workflow(
        self, *, operation_name: str, command: object, request: dict[str, object]
    ) -> dict[str, object] | None:
        self.events.append(f"claim:{operation_name}")
        assert command == new_year_command()
        assert request["shareholders"] == [
            {
                "name": "Owner",
                "shareholderKind": "norwegian_person",
                "nationalId": "01010112345",
                "orgNumber": None,
                "shareCount": 30000,
            }
        ]
        assert request["bankBalance"] == "30000.00"
        assert request["shareCapital"] == "30000.00"
        assert "openingMode" not in request
        assert "openingComponents" not in request
        self.claim_request = request
        return self.replay

    async def record_opening_snapshot(
        self,
        command: RecordOpeningSnapshotCommand,
    ) -> OpeningSnapshotId:
        self.events.append("shareholder-register")
        assert command.share_capital == Money.nok("30000")
        return SETUP_ID

    async def record_opening_bank_input(
        self, command: RecordOpeningBankInputCommand
    ) -> OpeningBankInput:
        self.events.append("ledger-bank-input")
        assert command.snapshot_id == str(SETUP_ID)
        assert command.bank_balance == Money.nok("30000")
        return OpeningBankInput(
            snapshot_id=command.snapshot_id,
            company_id=command.company_id,
            income_year=command.income_year,
            bank_balance=command.bank_balance,
            recorded_by=command.actor_id,
            recorded_at=NOW,
        )

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
        result: dict[str, object],
    ) -> None:
        self.events.append(f"complete:{operation_name}")
        assert request is self.claim_request
        assert result["entryId"] == str(ENTRY_ID)
        assert result["setupId"] == str(SETUP_ID)

    async def post_entry(self, command: object, **posting: object) -> PostedLedgerEntry:
        self.events.append("ledger")
        self.posting = posting
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=posting["entry_kind"],
            posted_at=NOW,
            replayed=False,
        )

    async def rebuild_company_year_opening(
        self, command: object, **posting: object
    ) -> PostedLedgerEntry:
        self.events.append("ledger")
        self.posting = posting
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.OPENING_BALANCE,
            posted_at=NOW,
            replayed=False,
        )

    async def lock_period(self, command: object) -> object:
        raise AssertionError("unused")

    async def list_entries(self, **query: object) -> LedgerEntryPage:
        return LedgerEntryPage(
            items=(), page=LedgerPage(next_cursor=None, has_more=False)
        )

    async def list_period_locks(self, **query: object) -> PeriodLockPage:
        return PeriodLockPage(
            items=(), page=LedgerPage(next_cursor=None, has_more=False)
        )


class WorkflowSessionStub:
    def __init__(self, transaction: WorkflowTransactionStub) -> None:
        self._transaction = transaction

    @property
    def actor_id(self) -> ActorId:
        return ACTOR_ID

    @asynccontextmanager
    async def transaction(self):
        self._transaction.events.append("begin")
        try:
            yield self._transaction
        except Exception:
            self._transaction.events.append("rollback")
            raise
        else:
            self._transaction.events.append("commit")

    async def post_entry(self, command: object, **posting: object) -> object:
        raise AssertionError("new-year start must use a transaction")

    async def lock_period(self, command: object) -> object:
        raise AssertionError("unused")

    async def list_entries(self, **query: object) -> LedgerEntryPage:
        raise AssertionError("unused")

    async def list_period_locks(self, **query: object) -> PeriodLockPage:
        raise AssertionError("unused")


class WorkflowSessionFactoryStub:
    def __init__(self, transaction: WorkflowTransactionStub) -> None:
        self.session_value = WorkflowSessionStub(transaction)

    async def session(self, _access_token: str) -> WorkflowSessionStub:
        return self.session_value


def application(transaction: WorkflowTransactionStub) -> LedgerApplication:
    return LedgerApplication(WorkflowSessionFactoryStub(transaction), LedgerService)


def test_new_year_start_uses_one_transaction_and_ledger_owned_posting_policy() -> None:
    transaction = WorkflowTransactionStub()
    session = asyncio.run(application(transaction).session("token"))

    result = asyncio.run(session.start_new_year(new_year_command()))

    assert result.setup_id == SETUP_ID
    assert result.posted_entry.entry_id == ENTRY_ID
    assert transaction.events == [
        "begin",
        "claim:new_year_start",
        "shareholder-register",
        "ledger-bank-input",
        "ledger",
        "complete:new_year_start",
        "commit",
    ]
    assert transaction.posting is not None
    assert transaction.posting["lines"] == (
        LedgerLine(
            "1920",
            f"Bank balance: opening-setup:{SETUP_ID}:bank",
            Money.nok("30000"),
            Money.nok("0"),
        ),
        LedgerLine(
            "2000",
            f"Registered share capital: opening-setup:{SETUP_ID}:share-capital",
            Money.nok("0"),
            Money.nok("30000"),
        ),
    )


def test_new_year_start_replays_the_complete_workflow_before_any_new_write() -> None:
    transaction = WorkflowTransactionStub(
        replay={
            "setupId": str(SETUP_ID),
            "entryId": str(ENTRY_ID),
            "companyId": str(COMPANY_ID),
            "incomeYear": 2026,
            "entryKind": "OPENING_BALANCE",
            "postedAt": "2026-08-27T10:00:00Z",
        }
    )
    session = asyncio.run(application(transaction).session("token"))

    result = asyncio.run(session.start_new_year(new_year_command()))

    assert result.posted_entry.replayed is True
    assert transaction.events == ["begin", "claim:new_year_start", "commit"]


def test_new_year_start_fails_closed_on_semantically_inconsistent_replay() -> None:
    transaction = WorkflowTransactionStub(
        replay={
            "setupId": str(SETUP_ID),
            "entryId": str(ENTRY_ID),
            "companyId": "90000000-0000-0000-0000-000000000009",
            "incomeYear": 2026,
            "entryKind": "MANUAL_JOURNAL",
            "postedAt": "2026-08-27T10:00:00Z",
        }
    )
    session = asyncio.run(application(transaction).session("token"))

    try:
        asyncio.run(session.start_new_year(new_year_command()))
    except LedgerError as error:
        assert error.code == "LEDGER_DEPENDENCY_UNAVAILABLE"
    else:
        raise AssertionError("inconsistent receipt unexpectedly replayed")

    assert transaction.events == [
        "begin",
        "claim:new_year_start",
        "rollback",
        "begin",
        "claim:new_year_start",
        "rollback",
    ]


def test_new_year_start_rolls_back_every_effect_when_a_later_step_fails() -> None:
    class FailingTransaction(WorkflowTransactionStub):
        async def complete_workflow(
            self,
            *,
            operation_name: str,
            command: object,
            request: dict[str, object],
            result: dict[str, object],
        ) -> None:
            await super().complete_workflow(
                operation_name=operation_name,
                command=command,
                request=request,
                result=result,
            )
            raise RuntimeError("receipt unavailable")

    transaction = FailingTransaction()
    session = asyncio.run(application(transaction).session("token"))

    try:
        asyncio.run(session.start_new_year(new_year_command()))
    except RuntimeError as error:
        assert str(error) == "receipt unavailable"
    else:
        raise AssertionError("workflow unexpectedly committed")

    assert transaction.events[-1] == "rollback"
    assert "complete:new_year_start" in transaction.events


def test_new_year_start_retries_one_unknown_commit_with_the_same_command() -> None:
    transaction = WorkflowTransactionStub()

    class UnknownCommitSession(WorkflowSessionStub):
        def __init__(self) -> None:
            super().__init__(transaction)
            self.attempts = 0

        @asynccontextmanager
        async def transaction(self):
            self.attempts += 1
            transaction.events.append(f"begin:{self.attempts}")
            yield transaction
            if self.attempts == 1:
                transaction.replay = {
                    "setupId": str(SETUP_ID),
                    "entryId": str(ENTRY_ID),
                    "companyId": str(COMPANY_ID),
                    "incomeYear": 2026,
                    "entryKind": "OPENING_BALANCE",
                    "postedAt": "2026-08-27T10:00:00Z",
                }
                transaction.events.append("commit:unknown")
                raise LedgerError.unavailable()
            transaction.events.append("commit:replayed")

    unknown_session = UnknownCommitSession()

    class Factory:
        async def session(self, _access_token: str) -> UnknownCommitSession:
            return unknown_session

    session = asyncio.run(LedgerApplication(Factory(), LedgerService).session("token"))
    result = asyncio.run(session.start_new_year(new_year_command()))

    assert result.posted_entry.replayed is True
    assert unknown_session.attempts == 2
    assert transaction.events.count("shareholder-register") == 1
    assert transaction.events.count("ledger-bank-input") == 1
    assert transaction.events.count("claim:new_year_start") == 2


def test_administrative_cost_uses_one_transaction_and_python_posting_policy() -> None:
    class AdministrativeCostTransaction(WorkflowTransactionStub):
        async def prepare_administrative_cost(
            self, command: RecordAdministrativeCostCommand
        ) -> dict[str, object]:
            self.events.append("prepare:record_administrative_cost")
            return {"replay": None}

        async def complete_administrative_cost(
            self,
            command: RecordAdministrativeCostCommand,
            posted_entry: PostedLedgerEntry,
            prepared: dict[str, object],
        ) -> dict[str, object]:
            self.events.append("complete:record_administrative_cost")
            assert prepared == {"replay": None}
            return {"entryId": str(posted_entry.entry_id), "auditRequired": True}

    transaction = AdministrativeCostTransaction()
    session = asyncio.run(application(transaction).session("token"))
    result = asyncio.run(
        session.record_administrative_cost(
            RecordAdministrativeCostCommand(
                company_id=COMPANY_ID,
                actor_id=ACTOR_ID,
                correlation_id=CorrelationId("admin-cost-workflow"),
                idempotency_key=IdempotencyKey(
                    "51000000-0000-4000-8000-000000000005"
                ),
                income_year=IncomeYear(2026),
                bank_transaction_id=LedgerSourceRecordId(
                    "61000000-0000-0000-0000-000000000006"
                ),
                category=AdministrativeCostCategory.SOFTWARE,
                payee="Talli AS",
                amount=Money.nok("1490"),
                paid_date=LocalDate(date(2026, 8, 27)),
            )
        )
    )

    assert result.posted_entry is not None
    assert result.result == {"entryId": str(ENTRY_ID), "auditRequired": True}
    assert result.replayed is False
    assert transaction.events == [
        "begin",
        "prepare:record_administrative_cost",
        "ledger",
        "complete:record_administrative_cost",
        "commit",
    ]
    assert transaction.posting is not None
    assert transaction.posting["entry_kind"] is LedgerEntryKind.ADMINISTRATIVE_COST


def test_new_year_rolls_back_rf_snapshot_before_posting_if_bank_provenance_disagrees() -> None:
    from dataclasses import replace

    class MisboundBankTransaction(WorkflowTransactionStub):
        async def record_opening_bank_input(self, command):
            original = await super().record_opening_bank_input(command)
            return replace(original, bank_balance=Money.nok("1"))

    transaction = MisboundBankTransaction()
    session = asyncio.run(application(transaction).session("token"))
    try:
        asyncio.run(session.start_new_year(new_year_command()))
    except LedgerError as error:
        assert error.code == "LEDGER_DEPENDENCY_UNAVAILABLE"
    else:
        raise AssertionError("misbound original bank input unexpectedly committed")
    assert transaction.events.count("shareholder-register") == 2
    assert transaction.events.count("rollback") == 2
    assert "ledger" not in transaction.events
    assert "complete:new_year_start" not in transaction.events
    assert "commit" not in transaction.events
