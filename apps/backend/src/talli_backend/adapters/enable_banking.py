"""Enable Banking API edge adapter and fallback conformance implementation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from talli_backend.adapters.bank_provider_http import (
    BankProviderHttpTransport,
    masked_account,
    money,
    optional_date,
    provider_error,
    required_text,
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
class EnableBankingAdapter:
    connector_id = BankConnectorId("enable-banking")

    def __init__(self, *, transport: BankProviderHttpTransport, authorization: str) -> None:
        self._transport = transport
        self._authorization = required_text(authorization, maximum=8192)

    @staticmethod
    def _state(connection_id: object, company_id: object) -> str:
        return hashlib.sha256(f"{connection_id}|{company_id}".encode()).hexdigest()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._authorization, "Accept": "application/json"}

    async def begin_consent(self, request: BeginBankConsentRequest) -> BankConsentRedirect:
        state = self._state(request.connection_id, request.company_id)
        body = successful_body(
            await self._transport.request(
                method="POST",
                path="/api/v1/auth",
                headers=self._headers,
                json={
                    "aspsp": {"name": request.bank_key, "country": "NO"},
                    "psu_type": "BUSINESS",
                    "redirect_url": request.return_url,
                    "state": state,
                    "access": {"balances": True, "transactions": True},
                },
            )
        )
        return BankConsentRedirect(
            redirect_url=required_text(body.get("url") or body.get("authorizationUri")),
            state=state,
        )

    async def complete_consent(self, request: CompleteBankConsentRequest) -> BankProviderConnection:
        state = self._state(request.connection_id, request.company_id)
        if request.callback_parameters.get("state") != state:
            raise provider_error(BankingErrorCode.CONSENT_CALLBACK_INVALID)
        body = successful_body(
            await self._transport.request(
                method="POST",
                path="/api/v1/sessions",
                headers=self._headers,
                json={"code": required_text(request.callback_parameters.get("code"))},
            )
        )
        session_id = required_text(body.get("session_id") or body.get("sessionId"))
        access = _mapping(body.get("access", {}))
        accounts = tuple(self._account(_mapping(raw)) for raw in _sequence(body.get("accounts")))
        return BankProviderConnection(
            connection_id=request.connection_id,
            connector_id=self.connector_id,
            adapter_connection_reference=session_id,
            consent_expires_on=optional_date(access.get("valid_until") or access.get("validUntil")),
            accounts=accounts,
        )

    def _account(self, raw: Mapping[str, object]) -> BankProviderAccount:
        reference = required_text(raw.get("account_id") or raw.get("accountId"))
        return BankProviderAccount(
            adapter_account_reference=reference,
            masked_account=masked_account(
                raw.get("identification_hash")
                or raw.get("identificationHash")
                or reference
            ),
            currency=required_text(raw.get("currency", "NOK"), maximum=3),
            account_kind=required_text(raw.get("cash_account_type") or raw.get("cashAccountType") or "CACC", maximum=40),
            display_name=required_text(raw.get("details") or raw.get("product") or "Bankkonto", maximum=120),
        )

    async def fetch_transactions(
        self, request: FetchBankTransactionsRequest
    ) -> BankProviderTransactionPage:
        query = {
            "date_from": request.date_from.value.isoformat(),
            "date_to": request.date_to.value.isoformat(),
        }
        if request.cursor is not None:
            query["continuation_key"] = request.cursor
        body = successful_body(
            await self._transport.request(
                method="GET",
                path=f"/api/v1/accounts/{request.adapter_account_reference}/transactions",
                headers=self._headers,
                query=query,
            )
        )
        return BankProviderTransactionPage(
            transactions=tuple(self._transaction(_mapping(raw)) for raw in _sequence(body.get("transactions"))),
            next_cursor=(body.get("continuation_key") or body.get("continuationKey")),
        )

    def _transaction(self, raw: Mapping[str, object]) -> BankProviderTransaction:
        amount = _mapping(raw.get("transaction_amount") or raw.get("transactionAmount"))
        raw_balance = raw.get("balance_after_transaction") or raw.get("balanceAfterTransaction")
        balance = _mapping(raw_balance) if raw_balance is not None else None
        reference = required_text(
            raw.get("transaction_id")
            or raw.get("transactionId")
            or raw.get("entry_reference")
            or raw.get("entryReference")
        )
        raw_text = raw.get("remittance_information") or raw.get("remittanceInformation") or raw.get("reference_number") or reference
        if isinstance(raw_text, list):
            raw_text = " ".join(str(part) for part in raw_text)
        amount_value = money(amount.get("amount"), currency=amount.get("currency"))
        indicator = str(raw.get("credit_debit_indicator") or raw.get("creditDebitIndicator") or "").upper()
        if indicator == "DBIT" and amount_value.amount > 0:
            amount_value = money(str(-amount_value.amount))
        return BankProviderTransaction(
            adapter_transaction_reference=reference,
            booking_date=optional_date(raw.get("booking_date") or raw.get("bookingDate")) or (_ for _ in ()).throw(provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)),
            value_date=optional_date(raw.get("value_date") or raw.get("valueDate")),
            text=required_text(raw_text, maximum=500),
            amount=amount_value,
            balance=(money(balance.get("amount"), currency=balance.get("currency")) if balance is not None else None),
            state=transaction_state(raw.get("status") or "booked"),
            bank_reference=(
                required_text(
                    raw.get("reference_number")
                    or raw.get("referenceNumber")
                    or raw.get("entry_reference")
                    or raw.get("entryReference"),
                    maximum=1024,
                )
                if (
                    raw.get("reference_number")
                    or raw.get("referenceNumber")
                    or raw.get("entry_reference")
                    or raw.get("entryReference")
                )
                else None
            ),
        )

    async def revoke_consent(self, request: RevokeBankConsentRequest) -> None:
        successful_body(
            await self._transport.request(
                method="DELETE",
                path=f"/api/v1/sessions/{request.adapter_connection_reference}",
                headers=self._headers,
            )
        )


__all__ = ["EnableBankingAdapter"]
