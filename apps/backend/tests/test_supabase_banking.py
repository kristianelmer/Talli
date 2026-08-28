from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from talli_backend.adapters.supabase_banking import (
    SupabaseBankingAdapter,
    SupabaseBankingSession,
    _banking_error,
)
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.banking.public import (
    BankAccountId,
    BankConnectionId,
    BankConnectorId,
    BankProviderAccount,
    BankProviderConnection,
    BankSyncAttemptId,
    BankSyncCommand,
    BankSyncContext,
    BankSyncMode,
    BankTransactionState,
    BankingError,
    CompleteBankConnectionCommand,
    ImportBankStatementCommand,
    ImportedBankTransaction,
    SupportedBankDataFormat,
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


ACTOR_ID = ActorId(
    ActorKind.USER,
    UserId("20000000-0000-0000-0000-000000000002"),
)
COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")


def bound_session() -> SupabaseBankingSession:
    return SupabaseBankingSession(
        "postgresql://unused",
        _VerifiedActor(actor_id=ACTOR_ID, claims_json='{"aal":"aal2"}'),
        "test-only-encryption-key",
    )


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("banking_invalid_cursor", "BANKING_INVALID_CURSOR"),
        ("banking_company_year_not_admitted", "BANKING_COMPANY_YEAR_NOT_ADMITTED"),
        ("banking_idempotency_key_reused", "BANKING_IDEMPOTENCY_KEY_REUSED"),
        ("banking_idempotency_in_progress", "BANKING_IDEMPOTENCY_IN_PROGRESS"),
        (
            "banking_suggestion_acceptance_conflict",
            "BANKING_SUGGESTION_ACCEPTANCE_CONFLICT",
        ),
    ],
)
def test_declared_database_outcomes_keep_their_closed_contract(
    marker: str,
    code: str,
) -> None:
    assert _banking_error(marker).code == code


def test_unknown_database_outcome_is_redacted_to_dependency_unavailable() -> None:
    error = _banking_error("sensitive raw database detail")

    assert error.code == "BANKING_DEPENDENCY_UNAVAILABLE"
    assert "sensitive" not in str(error)


def test_import_rpc_is_account_free_and_binds_the_verified_actor() -> None:
    session = bound_session()
    captured: dict[str, object] = {}

    async def rows(query: str, parameters: tuple[object, ...]):
        captured.update(query=query, parameters=parameters)
        return [
            {
                "result": {
                    "importedCount": 1,
                    "duplicateCount": 0,
                    "replayed": False,
                }
            }
        ]

    session._banking_rows = rows  # type: ignore[method-assign]
    command = ImportBankStatementCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("adapter-test"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000003"
        ),
        income_year=IncomeYear(2026),
        data_format=SupportedBankDataFormat.CSV,
        statement_text="date,text,amount\n2026-01-02,Annual fee,-89\n",
    )
    transaction = ImportedBankTransaction(
        transaction_date=LocalDate(date(2026, 1, 2)),
        text="Annual fee",
        amount=Money.nok("-89"),
        balance=None,
        source_hash="a" * 64,
    )

    result = asyncio.run(
        session.import_transactions(command, transactions=(transaction,))
    )

    request = json.loads(captured["parameters"][0])
    assert result.imported_count == 1
    assert captured["query"] == (
        "select banking.import_statement_v1(%s::jsonb, %s::text) as result"
    )
    assert captured["parameters"][1] == str(ACTOR_ID.subject)
    assert request["transactions"] == [
        {
            "transactionDate": "2026-01-02",
            "text": "Annual fee",
            "amount": "-89.00",
            "balance": None,
            "sourceHash": "a" * 64,
        }
    ]
    assert not ({"account", "lines", "debit", "credit"} & set(request))


def test_import_rejects_a_forged_actor_before_database_io() -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object):
        raise AssertionError("database must not be called")

    session._banking_rows = forbidden_database  # type: ignore[method-assign]
    command = ImportBankStatementCommand(
        company_id=COMPANY_ID,
        actor_id=ActorId(
            ActorKind.USER,
            UserId("90000000-0000-0000-0000-000000000009"),
        ),
        correlation_id=CorrelationId("adapter-test"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000003"
        ),
        income_year=IncomeYear(2026),
        data_format=SupportedBankDataFormat.CSV,
        statement_text="date,text,amount\n2026-01-02,Annual fee,-89\n",
    )

    with pytest.raises(BankingError) as failure:
        asyncio.run(session.import_transactions(command, transactions=()))

    assert failure.value.code == "BANKING_FORBIDDEN"


def test_environment_prefers_the_banking_database_binding(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("TALLI_LEDGER_DATABASE_URL", "postgresql://ledger")
    monkeypatch.setenv("TALLI_BANKING_DATABASE_URL", "postgresql://banking")
    monkeypatch.setenv("TALLI_BANKING_ENCRYPTION_KEY", "secret-from-environment")

    adapter = SupabaseBankingAdapter.from_environment()

    assert adapter._configuration.database_url == "postgresql://banking"
    assert adapter._configuration.encryption_key == "secret-from-environment"


def test_complete_connection_uses_provider_role_and_maps_canonical_accounts() -> None:
    session = bound_session()
    captured: dict[str, object] = {}

    async def rows(query: str, parameters: tuple[object, ...]):
        captured.update(query=query, parameters=parameters)
        return [
            {
                "result": {
                    "connectionId": "30000000-0000-0000-0000-000000000003",
                    "companyId": str(COMPANY_ID),
                    "connectorId": "fixture-connector",
                    "status": "ACTIVE",
                    "consentExpiresOn": "2027-02-24",
                    "accounts": [
                        {
                            "accountId": "40000000-0000-0000-0000-000000000004",
                            "connectionId": "30000000-0000-0000-0000-000000000003",
                            "maskedAccount": "•••• 1234",
                            "currency": "NOK",
                            "accountKind": "CACC",
                            "displayName": "Driftskonto",
                            "status": "ACTIVE",
                            "earliestCoveredDate": None,
                            "latestCoveredDate": None,
                            "lastSuccessAt": None,
                        }
                    ],
                    "lastSuccessAt": None,
                    "lastFailureCode": None,
                }
            }
        ]

    session._provider_rows = rows  # type: ignore[method-assign]
    command = CompleteBankConnectionCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("adapter-consent"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        connection_id=BankConnectionId(
            "30000000-0000-0000-0000-000000000003"
        ),
        callback_parameters={"resource_id": "opaque-state"},
    )
    provider_connection = BankProviderConnection(
        connection_id=command.connection_id,
        connector_id=BankConnectorId("fixture-connector"),
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

    connection = asyncio.run(
        session.complete_connection(command, provider_connection)
    )

    request = json.loads(captured["parameters"][0])
    provider = json.loads(captured["parameters"][1])
    assert request["callbackState"] == "opaque-state"
    assert provider["accounts"][0]["adapterReference"] == "provider-account"
    assert captured["parameters"][3] == "test-only-encryption-key"
    assert connection.accounts[0].masked_account == "•••• 1234"


def test_sync_page_binds_checkpoint_and_encrypted_provider_material() -> None:
    session = bound_session()
    captured: dict[str, object] = {}

    async def rows(query: str, parameters: tuple[object, ...]):
        captured.update(query=query, parameters=parameters)
        return [
            {
                "result": {
                    "importedCount": 1,
                    "updatedCount": 0,
                    "duplicateCount": 0,
                }
            }
        ]

    session._provider_rows = rows  # type: ignore[method-assign]
    command = BankSyncCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("adapter-sync"),
        idempotency_key=IdempotencyKey("60000000-0000-4000-8000-000000000006"),
        income_year=IncomeYear(2026),
        connection_id=BankConnectionId(
            "30000000-0000-0000-0000-000000000003"
        ),
        account_id=BankAccountId("40000000-0000-0000-0000-000000000004"),
        date_from=LocalDate(date(2026, 1, 1)),
        date_to=LocalDate(date(2026, 12, 31)),
        mode=BankSyncMode.ON_DEMAND,
    )
    context = BankSyncContext(
        attempt_id=BankSyncAttemptId(
            "50000000-0000-0000-0000-000000000005"
        ),
        connector_id=BankConnectorId("fixture-connector"),
        adapter_connection_reference="provider-session",
        adapter_account_reference="provider-account",
        resume_cursor=None,
    )
    transaction = ImportedBankTransaction(
        transaction_date=LocalDate(date(2026, 1, 2)),
        value_date=LocalDate(date(2026, 1, 2)),
        text="Annual fee",
        amount=Money.nok("-89"),
        balance=Money.nok("1000"),
        source_hash="a" * 64,
        state=BankTransactionState.BOOKED,
        adapter_transaction_reference="provider-transaction",
    )

    result = asyncio.run(
        session.apply_sync_page(
            command,
            context=context,
            transactions=(transaction,),
            next_cursor="next-page",
        )
    )

    page = json.loads(captured["parameters"][2])
    assert result.imported_count == 1
    assert page[0]["adapterReference"] == "provider-transaction"
    assert captured["parameters"][3] == "next-page"
    assert captured["parameters"][5] == "test-only-encryption-key"


def test_completed_sync_replay_is_returned_without_provider_io() -> None:
    session = bound_session()

    async def rows(_query: str, _parameters: tuple[object, ...]):
        return [
            {
                "result": {
                    "attemptId": "50000000-0000-0000-0000-000000000005",
                    "connectorId": "fixture-connector",
                    "adapterConnectionReference": "provider-session",
                    "adapterAccountReference": "provider-account",
                    "resumeCursor": None,
                    "pageCount": 2,
                    "importedCount": 3,
                    "updatedCount": 1,
                    "duplicateCount": 4,
                    "replayed": True,
                }
            }
        ]

    session._provider_rows = rows  # type: ignore[method-assign]
    command = BankSyncCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("adapter-replay"),
        idempotency_key=IdempotencyKey("60000000-0000-4000-8000-000000000006"),
        income_year=IncomeYear(2026),
        connection_id=BankConnectionId(
            "30000000-0000-0000-0000-000000000003"
        ),
        account_id=BankAccountId("40000000-0000-0000-0000-000000000004"),
        date_from=LocalDate(date(2026, 1, 1)),
        date_to=LocalDate(date(2026, 12, 31)),
        mode=BankSyncMode.RECOVERY,
    )

    context = asyncio.run(session.prepare_sync(command))

    assert context.replayed_result is not None
    assert context.replayed_result.replayed is True
    assert context.replayed_result.imported_count == 3
