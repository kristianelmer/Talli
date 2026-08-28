from __future__ import annotations

import asyncio
from datetime import date

import pytest

from talli_backend.adapters.enable_banking import EnableBankingAdapter
from talli_backend.adapters.neonomics_banking import NeonomicsBankingAdapter
from talli_backend.modules.banking.public import (
    BankConnectionId,
    BankConnectorId,
    BankSyncMode,
    BankTransactionState,
    BankingError,
    BeginBankConsentRequest,
    CompleteBankConsentRequest,
    FetchBankTransactionsRequest,
)
from talli_backend.shared.kernel import CompanyId, LocalDate


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
CONNECTION_ID = BankConnectionId("20000000-0000-0000-0000-000000000002")


class FixtureTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def request(self, **request: object) -> dict[str, object]:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected provider request")
        return self.responses.pop(0)


def consent_request(connector: str) -> BeginBankConsentRequest:
    return BeginBankConsentRequest(
        connection_id=CONNECTION_ID,
        company_id=COMPANY_ID,
        connector_id=BankConnectorId(connector),
        bank_key="DNB",
        return_url="https://app.talli.no/api/v1/banking/consent-return",
    )


def sync_request(*, cursor: str | None = None) -> FetchBankTransactionsRequest:
    return FetchBankTransactionsRequest(
        connection_id=CONNECTION_ID,
        company_id=COMPANY_ID,
        adapter_account_reference="opaque-account-ref",
        date_from=LocalDate(date(2026, 1, 1)),
        date_to=LocalDate(date(2026, 12, 31)),
        cursor=cursor,
        mode=BankSyncMode.ON_DEMAND,
        owner_present=True,
    )


def test_neonomics_models_business_consent_and_opaque_cursor_pagination() -> None:
    transport = FixtureTransport(
        [
            {"status": 201, "body": {"sessionId": "provider-session"}},
            {
                "status": 510,
                "body": {
                    "errorCode": "1426",
                    "links": [{"rel": "consent", "href": "/ics/v3/consent/provider-session"}],
                },
            },
            {"status": 200, "body": {"url": "https://bank.example/consent"}},
            {
                "status": 200,
                "body": {
                    "transactions": [
                        {
                            "id": "provider-transaction",
                            "bookingDate": "2026-01-02",
                            "valueDate": "2026-01-02",
                            "transactionAmount": {"amount": "-89.00", "currency": "NOK"},
                            "remittanceInformationUnstructured": "Årsgebyr",
                            "bookingStatus": "booked",
                            "balanceAfterTransaction": {"amount": "1000.00", "currency": "NOK"},
                        }
                    ],
                    "links": [{"rel": "next", "href": "/transactions?cursor=opaque-next"}],
                },
            },
        ]
    )
    adapter = NeonomicsBankingAdapter(transport=transport, authorization="fixture")

    redirect = asyncio.run(adapter.begin_consent(consent_request("neonomics")))
    page = asyncio.run(adapter.fetch_transactions(sync_request()))

    assert redirect.redirect_url == "https://bank.example/consent"
    assert transport.requests[1]["query"] == {"scope": "business-accounts"}
    assert page.next_cursor == "opaque-next"
    assert page.transactions[0].state is BankTransactionState.BOOKED
    assert page.transactions[0].amount.amount < 0


def test_enable_banking_exchanges_code_and_follows_continuation_after_empty_page() -> None:
    transport = FixtureTransport(
        [
            {"status": 200, "body": {"url": "https://bank.example/consent", "authorization_id": "auth-id"}},
            {
                "status": 200,
                "body": {
                    "session_id": "provider-session",
                    "access": {"valid_until": "2027-02-24"},
                    "accounts": [
                        {
                            "account_id": "provider-account",
                            "currency": "NOK",
                            "cash_account_type": "CACC",
                            "details": "Driftskonto",
                            "identification_hash": "hash-ending-1234",
                        }
                    ],
                },
            },
            {"status": 200, "body": {"transactions": [], "continuation_key": "opaque-next"}},
        ]
    )
    adapter = EnableBankingAdapter(transport=transport, authorization="fixture")

    redirect = asyncio.run(adapter.begin_consent(consent_request("enable-banking")))
    connection = asyncio.run(
        adapter.complete_consent(
            CompleteBankConsentRequest(
                connection_id=CONNECTION_ID,
                company_id=COMPANY_ID,
                callback_parameters={"code": "opaque-code", "state": redirect.state},
            )
        )
    )
    page = asyncio.run(adapter.fetch_transactions(sync_request()))

    assert redirect.redirect_url == "https://bank.example/consent"
    assert connection.accounts[0].masked_account == "•••• 1234"
    assert page.transactions == ()
    assert page.next_cursor == "opaque-next"


@pytest.mark.parametrize("adapter_type", [NeonomicsBankingAdapter, EnableBankingAdapter])
def test_provider_failures_are_coded_and_redacted(adapter_type: type[object]) -> None:
    transport = FixtureTransport(
        [{"status": 503, "body": {"message": "Bearer secret-token account NO12345678901"}}]
    )
    adapter = adapter_type(transport=transport, authorization="fixture")

    with pytest.raises(BankingError) as failure:
        asyncio.run(adapter.begin_consent(consent_request("fixture")))

    assert failure.value.code == "BANKING_PROVIDER_UNAVAILABLE"
    assert "secret-token" not in str(failure.value)

