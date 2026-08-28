from __future__ import annotations

import asyncio
from datetime import date

import pytest

from talli_backend.application.banking_consent import BankingConsentWorkflow
from talli_backend.modules.banking.public import (
    BankAccount,
    BankAccountId,
    BankAccountStatus,
    BankConnection,
    BankConnectionId,
    BankConnectionStatus,
    BankConnectorId,
    BankConsentRedirect,
    BankProviderAccount,
    BankProviderConnection,
    BankingError,
    BankingErrorCode,
    CompleteBankConnectionCommand,
    RevokeBankConnectionCommand,
    StartBankConnectionCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
CONNECTION_ID = BankConnectionId("30000000-0000-0000-0000-000000000003")
ACCOUNT_ID = BankAccountId("40000000-0000-0000-0000-000000000004")


def metadata() -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "actor_id": ACTOR_ID,
        "correlation_id": CorrelationId("bank-consent"),
        "idempotency_key": IdempotencyKey("50000000-0000-4000-8000-000000000005"),
        "income_year": IncomeYear(2026),
    }


class ProviderStub:
    connector_id = BankConnectorId("fixture-connector")

    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def begin_consent(self, request):
        self.events.append("provider:begin")
        if self.fail:
            raise BankingError.unavailable()
        return BankConsentRedirect("https://bank.example/consent", "opaque-state")

    async def complete_consent(self, request):
        self.events.append("provider:complete")
        if self.fail:
            raise BankingError.invalid_input(BankingErrorCode.CONSENT_CALLBACK_INVALID)
        return BankProviderConnection(
            connection_id=CONNECTION_ID,
            connector_id=self.connector_id,
            adapter_connection_reference="provider-session",
            consent_expires_on=LocalDate(date(2027, 2, 24)),
            accounts=(
                BankProviderAccount(
                    adapter_account_reference="provider-account",
                    masked_account="•••• 1234",
                    currency="NOK",
                    account_kind="CACC",
                    display_name="Driftskonto",
                ),
            ),
        )

    async def revoke_consent(self, request):
        self.events.append("provider:revoke")


class PersistenceStub:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def begin_connection(self, command):
        self.events.append("db:begin")

    async def get_connection_completion_replay(self, command):
        return None

    async def record_consent_redirect(self, command, redirect):
        self.events.append("db:redirect")
        return redirect

    async def complete_connection(self, command, provider_connection):
        self.events.append("db:complete")
        return BankConnection(
            connection_id=CONNECTION_ID,
            company_id=COMPANY_ID,
            connector_id=provider_connection.connector_id,
            status=BankConnectionStatus.ACTIVE,
            consent_expires_on=provider_connection.consent_expires_on,
            accounts=(
                BankAccount(
                    account_id=ACCOUNT_ID,
                    connection_id=CONNECTION_ID,
                    masked_account="•••• 1234",
                    currency="NOK",
                    account_kind="CACC",
                    display_name="Driftskonto",
                    status=BankAccountStatus.ACTIVE,
                    earliest_covered_date=None,
                    latest_covered_date=None,
                    last_success_at=None,
                ),
            ),
            last_success_at=None,
            last_failure_code=None,
        )

    async def fail_connection(self, command, *, error_code):
        self.events.append(f"db:failed:{error_code}")

    async def begin_revocation(self, command):
        self.events.append("db:revoking")
        return "provider-session"

    async def complete_revocation(self, command):
        self.events.append("db:revoked")


def test_connection_is_durable_before_redirect_and_callback_accounts_are_canonical() -> None:
    events: list[str] = []
    workflow = BankingConsentWorkflow(PersistenceStub(events), ProviderStub(events))
    start = StartBankConnectionCommand(
        **metadata(),
        connection_id=CONNECTION_ID,
        connector_id=BankConnectorId("fixture-connector"),
        bank_key="DNB",
        return_url="https://app.talli.no/bank/callback",
    )
    complete = CompleteBankConnectionCommand(
        **metadata(),
        connection_id=CONNECTION_ID,
        callback_parameters={"code": "opaque-code", "state": "opaque-state"},
    )

    redirect = asyncio.run(workflow.start(start))
    connection = asyncio.run(workflow.complete(complete))

    assert redirect.redirect_url == "https://bank.example/consent"
    assert connection.accounts[0].account_id == ACCOUNT_ID
    assert events == [
        "db:begin",
        "provider:begin",
        "db:redirect",
        "provider:complete",
        "db:complete",
    ]


def test_provider_failure_is_recorded_without_an_empty_account_result() -> None:
    events: list[str] = []
    workflow = BankingConsentWorkflow(PersistenceStub(events), ProviderStub(events, fail=True))
    start = StartBankConnectionCommand(
        **metadata(),
        connection_id=CONNECTION_ID,
        connector_id=BankConnectorId("fixture-connector"),
        bank_key="DNB",
        return_url="https://app.talli.no/bank/callback",
    )

    with pytest.raises(BankingError):
        asyncio.run(workflow.start(start))

    assert events == [
        "db:begin",
        "provider:begin",
        f"db:failed:{BankingErrorCode.DEPENDENCY_UNAVAILABLE.value}",
    ]


def test_revocation_blocks_collection_before_provider_disconnect() -> None:
    events: list[str] = []
    workflow = BankingConsentWorkflow(PersistenceStub(events), ProviderStub(events))
    command = RevokeBankConnectionCommand(
        **metadata(),
        connection_id=CONNECTION_ID,
    )

    asyncio.run(workflow.revoke(command))

    assert events == ["db:revoking", "provider:revoke", "db:revoked"]


def test_completed_callback_retry_returns_durable_connection_without_provider_io() -> None:
    events: list[str] = []
    persistence = PersistenceStub(events)
    replay = asyncio.run(
        persistence.complete_connection(
            CompleteBankConnectionCommand(
                **metadata(),
                connection_id=CONNECTION_ID,
                callback_parameters={"state": "opaque-state"},
            ),
            BankProviderConnection(
                connection_id=CONNECTION_ID,
                connector_id=BankConnectorId("fixture-connector"),
                adapter_connection_reference="provider-session",
                consent_expires_on=None,
                accounts=(
                    BankProviderAccount(
                        adapter_account_reference="provider-account",
                        masked_account="•••• 1234",
                        currency="NOK",
                        account_kind="CACC",
                        display_name="Driftskonto",
                    ),
                ),
            ),
        )
    )

    async def completed(_command):
        return replay

    persistence.get_connection_completion_replay = completed
    provider = ProviderStub(events, fail=True)
    result = asyncio.run(
        BankingConsentWorkflow(persistence, provider).complete(
            CompleteBankConnectionCommand(
                **metadata(),
                connection_id=CONNECTION_ID,
                callback_parameters={"state": "opaque-state"},
            )
        )
    )

    assert result == replay
    assert events == ["db:complete"]
