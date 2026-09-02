from __future__ import annotations

import asyncio
from datetime import date

import pytest

from talli_backend.application.banking_sync import BankingSyncWorkflow
from talli_backend.modules.banking.public import (
    BankAccountId,
    BankConnectionId,
    BankConnectorId,
    BankProviderTransaction,
    BankProviderTransactionPage,
    BankSyncAttemptId,
    BankSyncCommand,
    BankSyncContext,
    BankSyncMode,
    BankSyncPageResult,
    BankSyncResult,
    BankTransactionState,
    BankingError,
    BankingErrorCode,
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
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
CONNECTION_ID = BankConnectionId("30000000-0000-0000-0000-000000000003")
ACCOUNT_ID = BankAccountId("40000000-0000-0000-0000-000000000004")
ATTEMPT_ID = BankSyncAttemptId("50000000-0000-0000-0000-000000000005")


def command(mode: BankSyncMode = BankSyncMode.ON_DEMAND) -> BankSyncCommand:
    return BankSyncCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("bank-sync"),
        idempotency_key=IdempotencyKey("60000000-0000-4000-8000-000000000006"),
        income_year=IncomeYear(2026),
        connection_id=CONNECTION_ID,
        account_id=ACCOUNT_ID,
        date_from=LocalDate(date(2026, 1, 1)),
        date_to=LocalDate(date(2026, 12, 31)),
        mode=mode,
    )


def transaction(state: BankTransactionState) -> BankProviderTransaction:
    return BankProviderTransaction(
        adapter_transaction_reference="provider-transaction-id",
        bank_reference="bank-reference-1",
        booking_date=LocalDate(date(2026, 1, 2)),
        value_date=LocalDate(date(2026, 1, 2)),
        text="Årsgebyr",
        amount=Money.nok("-89"),
        balance=Money.nok("1000"),
        state=state,
    )


class ProviderStub:
    connector_id = BankConnectorId("fixture-connector")

    def __init__(self, pages: list[BankProviderTransactionPage] | None = None, error: BankingError | None = None) -> None:
        self.pages = list(pages or [])
        self.error = error
        self.requests = []

    async def fetch_transactions(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)


class PersistenceStub:
    def __init__(self) -> None:
        self.events = []
        self.pages = []

    async def prepare_sync(self, sync_command):
        self.events.append("prepare")
        return BankSyncContext(
            attempt_id=ATTEMPT_ID,
            connector_id=BankConnectorId("fixture-connector"),
            adapter_connection_reference="provider-session",
            adapter_account_reference="provider-account-id",
            resume_cursor=None,
        )

    async def apply_sync_page(self, sync_command, *, context, transactions, next_cursor):
        self.events.append(f"page:{next_cursor}")
        self.pages.append(transactions)
        return BankSyncPageResult(
            imported_count=len(transactions),
            updated_count=0,
            duplicate_count=0,
        )

    async def complete_sync(self, sync_command, *, context, pages, imported_count, updated_count, duplicate_count):
        self.events.append("complete")
        return BankSyncResult(
            attempt_id=context.attempt_id,
            page_count=pages,
            imported_count=imported_count,
            updated_count=updated_count,
            duplicate_count=duplicate_count,
            replayed=False,
        )

    async def fail_sync(self, sync_command, *, context, error_code):
        self.events.append(f"failed:{error_code}")


def test_sync_persists_attempt_before_io_and_follows_empty_continuation_pages() -> None:
    provider = ProviderStub(
        [
            BankProviderTransactionPage(transactions=(), next_cursor="next-page"),
            BankProviderTransactionPage(transactions=(transaction(BankTransactionState.BOOKED),), next_cursor=None),
        ]
    )
    persistence = PersistenceStub()

    result = asyncio.run(BankingSyncWorkflow(persistence, provider).sync(command()))

    assert result.page_count == 2
    assert persistence.events == ["prepare", "page:next-page", "page:None", "complete"]
    assert provider.requests[0].cursor is None
    assert provider.requests[1].cursor == "next-page"
    assert provider.requests[0].owner_present is True


def test_pending_to_booked_uses_one_stable_fact_identity_and_never_posts() -> None:
    provider = ProviderStub(
        [
            BankProviderTransactionPage(
                transactions=(transaction(BankTransactionState.PENDING),),
                next_cursor="booked-page",
            ),
            BankProviderTransactionPage(
                transactions=(transaction(BankTransactionState.BOOKED),),
                next_cursor=None,
            ),
        ]
    )
    persistence = PersistenceStub()

    asyncio.run(BankingSyncWorkflow(persistence, provider).sync(command()))

    first, second = persistence.pages
    assert first[0].source_hash == second[0].source_hash
    assert first[0].state is BankTransactionState.PENDING
    assert second[0].state is BankTransactionState.BOOKED
    assert not hasattr(first[0], "ledger_entry_id")


def test_background_sync_marks_owner_absent_and_records_provider_failure() -> None:
    provider = ProviderStub(error=BankingError.unavailable())
    persistence = PersistenceStub()

    with pytest.raises(BankingError):
        asyncio.run(BankingSyncWorkflow(persistence, provider).sync(command(BankSyncMode.NIGHTLY)))

    assert provider.requests[0].owner_present is False
    assert persistence.events == ["prepare", f"failed:{BankingErrorCode.DEPENDENCY_UNAVAILABLE.value}"]


def test_completed_idempotent_retry_returns_without_provider_io() -> None:
    provider = ProviderStub(error=AssertionError("provider must not be called"))
    persistence = PersistenceStub()
    replay = BankSyncResult(
        attempt_id=ATTEMPT_ID,
        page_count=2,
        imported_count=3,
        updated_count=1,
        duplicate_count=4,
        replayed=True,
    )

    async def replayed_prepare(_command):
        persistence.events.append("prepare")
        return BankSyncContext(
            attempt_id=ATTEMPT_ID,
            connector_id=BankConnectorId("fixture-connector"),
            adapter_connection_reference="provider-session",
            adapter_account_reference="provider-account-id",
            resume_cursor=None,
            replayed_result=replay,
        )

    persistence.prepare_sync = replayed_prepare

    result = asyncio.run(BankingSyncWorkflow(persistence, provider).sync(command()))

    assert result == replay
    assert provider.requests == []
    assert persistence.events == ["prepare"]
