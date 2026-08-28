"""Neonomics Account Data API edge adapter with no direct persistence or posting."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

from talli_backend.adapters.bank_provider_http import (
    BankProviderHttpTransport,
    masked_account,
    money,
    optional_date,
    provider_error,
    required_text,
    response_parts,
    successful_body,
    transaction_state,
)
from talli_backend.modules.banking.public import (
    BankConsentRedirect,
    BankConnectorId,
    BankDataProvider,
    BankProviderAccount,
    BankProviderConnection,
    BankProviderTransaction,
    BankProviderTransactionPage,
    BankingErrorCode,
    BeginBankConsentRequest,
    CompleteBankConsentRequest,
    FetchBankTransactionsRequest,
    RevokeBankConsentRequest,
    bank_data_provider_adapter,
)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    return value


def _sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    return tuple(value)


@bank_data_provider_adapter(BankDataProvider)
class NeonomicsBankingAdapter:
    connector_id = BankConnectorId("neonomics")

    def __init__(self, *, transport: BankProviderHttpTransport, authorization: str) -> None:
        self._transport = transport
        self._authorization = required_text(authorization, maximum=8192)

    def _headers(self, connection_id: object, *, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": self._authorization,
            "x-device-id": str(connection_id),
            "x-psu-ip-address": "",
        }
        if session_id is not None:
            headers["x-session-id"] = session_id
        return headers

    async def begin_consent(self, request: BeginBankConsentRequest) -> BankConsentRedirect:
        created = successful_body(
            await self._transport.request(
                method="POST",
                path="/ics/v3/session",
                headers=self._headers(request.connection_id),
                json={"bankId": request.bank_key},
            )
        )
        session_id = required_text(created.get("sessionId"))
        account_response = await self._transport.request(
            method="GET",
            path="/ics/v3/accounts",
            headers=self._headers(request.connection_id, session_id=session_id),
            query={"scope": "business-accounts"},
        )
        status, body = response_parts(account_response)
        if 200 <= status < 300:
            return BankConsentRedirect(redirect_url=request.return_url, state=session_id)
        if str(body.get("errorCode")) != "1426":
            raise provider_error()
        consent_path = None
        for raw_link in _sequence(body.get("links")):
            link = _mapping(raw_link)
            if str(link.get("rel", "")).lower() == "consent":
                consent_path = required_text(link.get("href"))
                break
        if consent_path is None:
            raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        consent = successful_body(
            await self._transport.request(
                method="GET",
                path=consent_path,
                headers={
                    **self._headers(request.connection_id, session_id=session_id),
                    "x-redirect-url": request.return_url,
                },
                query={"scope": "business-accounts"},
            )
        )
        return BankConsentRedirect(
            redirect_url=required_text(consent.get("url") or consent.get("redirectUrl")),
            state=session_id,
        )

    async def complete_consent(self, request: CompleteBankConsentRequest) -> BankProviderConnection:
        session_id = request.callback_parameters.get("resource_id")
        if session_id is None:
            raise provider_error(BankingErrorCode.CONSENT_CALLBACK_INVALID)
        if request.callback_parameters.get("result", "OK").upper() != "OK":
            raise provider_error(BankingErrorCode.CONSENT_CALLBACK_INVALID)
        body = successful_body(
            await self._transport.request(
                method="GET",
                path="/ics/v3/accounts",
                headers=self._headers(request.connection_id, session_id=session_id),
                query={"scope": "business-accounts"},
            )
        )
        raw_accounts = body.get("accounts", body) if isinstance(body, Mapping) else body
        accounts = self._accounts(raw_accounts)
        return BankProviderConnection(
            connection_id=request.connection_id,
            connector_id=self.connector_id,
            adapter_connection_reference=session_id,
            consent_expires_on=optional_date(body.get("consentExpiresOn")),
            accounts=accounts,
        )

    def _accounts(self, value: object) -> tuple[BankProviderAccount, ...]:
        return tuple(
            BankProviderAccount(
                adapter_account_reference=required_text(account.get("id")),
                masked_account=masked_account(account.get("iban") or account.get("bban") or account.get("id")),
                currency=required_text(account.get("currency", "NOK"), maximum=3),
                account_kind=required_text(account.get("accountType") or account.get("type") or "CACC", maximum=40),
                display_name=required_text(account.get("displayName") or account.get("name") or "Bankkonto", maximum=120),
            )
            for account in (_mapping(raw) for raw in _sequence(value))
        )

    async def fetch_transactions(
        self, request: FetchBankTransactionsRequest
    ) -> BankProviderTransactionPage:
        session_id = request.adapter_connection_reference
        query = (
            {"scope": "business-accounts", "cursor": request.cursor}
            if request.cursor is not None
            else {
                "scope": "business-accounts",
                "fromDate": request.date_from.value.isoformat(),
                "toDate": request.date_to.value.isoformat(),
                "pageSize": 50,
            }
        )
        body = successful_body(
            await self._transport.request(
                method="GET",
                path=f"/ics/v3/accounts/{request.adapter_account_reference}/transactions",
                headers=self._headers(request.connection_id, session_id=session_id),
                query=query,
            )
        )
        transactions = tuple(self._transaction(_mapping(raw)) for raw in _sequence(body.get("transactions")))
        next_cursor = None
        for raw_link in _sequence(body.get("links", [])):
            link = _mapping(raw_link)
            if str(link.get("rel", "")).lower() == "next":
                values = parse_qs(urlparse(required_text(link.get("href"))).query).get("cursor")
                if values:
                    next_cursor = required_text(values[0])
                break
        return BankProviderTransactionPage(transactions=transactions, next_cursor=next_cursor)

    def _transaction(self, raw: Mapping[str, object]) -> BankProviderTransaction:
        amount = _mapping(raw.get("transactionAmount"))
        raw_balance = raw.get("balanceAfterTransaction")
        balance = _mapping(raw_balance) if raw_balance is not None else None
        text_value = raw.get("remittanceInformationUnstructured") or raw.get("transactionReference") or raw.get("id")
        if isinstance(text_value, list):
            text_value = " ".join(str(part) for part in text_value)
        return BankProviderTransaction(
            adapter_transaction_reference=required_text(raw.get("id") or raw.get("transactionId")),
            booking_date=optional_date(raw.get("bookingDate")) or (_ for _ in ()).throw(provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)),
            value_date=optional_date(raw.get("valueDate")),
            text=required_text(text_value, maximum=500),
            amount=money(amount.get("amount"), currency=amount.get("currency")),
            balance=(money(balance.get("amount"), currency=balance.get("currency")) if balance is not None else None),
            state=transaction_state(raw.get("bookingStatus") or raw.get("status") or "booked"),
            bank_reference=(
                required_text(raw.get("transactionReference"), maximum=1024)
                if raw.get("transactionReference")
                else None
            ),
        )

    async def revoke_consent(self, request: RevokeBankConsentRequest) -> None:
        successful_body(
            await self._transport.request(
                method="DELETE",
                path=f"/ics/v3/session/{request.adapter_connection_reference}",
                headers=self._headers(
                    request.connection_id,
                    session_id=request.adapter_connection_reference,
                ),
            )
        )


__all__ = ["NeonomicsBankingAdapter"]
