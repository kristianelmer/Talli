from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import date
from pathlib import Path

from talli_backend.modules.banking.public import (
    BankConnectionId,
    BankConnectorId,
    BankDataProvider,
    BankProviderAccount,
    BankProviderConnection,
    BankProviderTransaction,
    BankProviderTransactionPage,
    BankSyncMode,
    BankTransactionState,
    BeginBankConsentRequest,
    CompleteBankConsentRequest,
    FetchBankTransactionsRequest,
)
from talli_backend.shared.kernel import CompanyId, LocalDate, Money


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
CONNECTION_ID = BankConnectionId("20000000-0000-0000-0000-000000000002")


def test_provider_port_is_read_only_provider_neutral_and_secret_free() -> None:
    source = Path(inspect.getsourcefile(BankDataProvider) or "").read_text(encoding="utf-8")

    assert set(BankDataProvider.__dict__) >= {
        "begin_consent",
        "complete_consent",
        "fetch_transactions",
        "revoke_consent",
    }
    assert not {
        "ledger_entry_id",
        "accounting_account",
        "debit",
        "credit",
        "access_token",
        "refresh_token",
        "client_secret",
    } & set(source.split())
    assert set(field.name for field in fields(BeginBankConsentRequest)) == {
        "connection_id",
        "company_id",
        "connector_id",
        "bank_key",
        "return_url",
    }


def test_provider_contract_normalizes_accounts_and_transaction_pages() -> None:
    connection = BankProviderConnection(
        connection_id=CONNECTION_ID,
        connector_id=BankConnectorId("fixture-connector"),
        adapter_connection_reference="opaque-connection-ref",
        consent_expires_on=LocalDate(date(2027, 2, 24)),
        accounts=(
            BankProviderAccount(
                adapter_account_reference="opaque-account-ref",
                masked_account="•••• 1234",
                currency="NOK",
                account_kind="CACC",
                display_name="Driftskonto",
            ),
        ),
    )
    page = BankProviderTransactionPage(
        transactions=(
            BankProviderTransaction(
                adapter_transaction_reference="opaque-transaction-ref",
                booking_date=LocalDate(date(2026, 1, 2)),
                value_date=LocalDate(date(2026, 1, 2)),
                text="Årsgebyr",
                amount=Money.nok("-89"),
                balance=Money.nok("1000"),
                state=BankTransactionState.BOOKED,
            ),
        ),
        next_cursor="opaque-next",
    )

    assert connection.accounts[0].masked_account == "•••• 1234"
    assert page.transactions[0].state is BankTransactionState.BOOKED
    assert not hasattr(page.transactions[0], "ledger_entry_id")


def test_sync_request_keeps_schedule_and_pagination_explicit() -> None:
    request = FetchBankTransactionsRequest(
        connection_id=CONNECTION_ID,
        company_id=COMPANY_ID,
        adapter_connection_reference="opaque-connection-ref",
        adapter_account_reference="opaque-account-ref",
        date_from=LocalDate(date(2026, 1, 1)),
        date_to=LocalDate(date(2026, 12, 31)),
        cursor=None,
        mode=BankSyncMode.INITIAL_BACKFILL,
        owner_present=True,
    )
    callback = CompleteBankConsentRequest(
        connection_id=CONNECTION_ID,
        company_id=COMPANY_ID,
        callback_parameters={"code": "opaque-code", "state": "opaque-state"},
    )

    assert request.cursor is None
    assert request.mode is BankSyncMode.INITIAL_BACKFILL
    assert callback.callback_parameters == {"code": "opaque-code", "state": "opaque-state"}
