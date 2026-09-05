"""Bounded, test-origin-only Vipps Recurring adapter; no automatic blind retries."""

import hashlib
import json
import re
from asyncio import timeout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

import httpx

from talli_backend.adapters.vipps_webhook import _unique_object
from talli_backend.modules.billing.public import (
    AnnualBillingProvider,
    AnnualProviderIntent,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    BillingError,
    billing_provider_adapter,
)


_ORIGIN = "https://apitest.vipps.no"
_AGREEMENTS = "/recurring/v3/agreements"


class _UnknownOutcome(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VippsTestConfiguration:
    merchant_serial_number: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    subscription_key: str = field(repr=False)
    # Populate only after the designated MT response's origin is verified.
    confirmation_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9]{3,12}", self.merchant_serial_number):
            raise BillingError.invalid()
        for secret in (self.client_id, self.client_secret, self.subscription_key):
            if not secret or len(secret) > 8192 or "\n" in secret or "\r" in secret:
                raise BillingError.invalid()
        for origin in self.confirmation_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or parsed.hostname == "api.vipps.no"
            ):
                raise BillingError.invalid()


def vipps_operation_key(configuration: VippsTestConfiguration, intent: AnnualProviderIntent) -> str:
    scope = "|".join((
        "vipps-mt", configuration.merchant_serial_number, str(intent.company_id),
        str(intent.income_year.value), intent.operation.value, str(intent.operation_id),
    ))
    return hashlib.sha256(scope.encode()).hexdigest()[:40]


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise _UnknownOutcome()
    return value


def _id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise _UnknownOutcome()
    return value


def _minor(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _UnknownOutcome()
    return value


@billing_provider_adapter(AnnualBillingProvider)
class VippsTestBillingProvider:
    provider = "vipps-mt"
    production_enabled = False

    def __init__(self, configuration: VippsTestConfiguration, *, transport=None, now=None):
        self._configuration = configuration
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))

    def _observation(self, intent, status, *, agreement=None, captured=0, refunded=0, checkout_url=None):
        return AnnualProviderObservation(
            provider=self.provider, operation=intent.operation, status=status,
            agreement_reference=agreement or intent.agreement_reference,
            charge_reference=intent.charge_reference, amount_minor=intent.amount_minor,
            captured_minor=captured, refunded_minor=refunded, checkout_url=checkout_url,
        )

    async def _request(self, client, method, path, *, headers, body=None, params=None, expected=(200,)):
        async with client.stream(method, _ORIGIN + path, headers=headers, json=body, params=params) as response:
            if response.status_code not in expected:
                raise _UnknownOutcome()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise _UnknownOutcome()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)

    async def _headers(self, client):
        config = self._configuration
        common = {
            "Merchant-Serial-Number": config.merchant_serial_number,
            "Ocp-Apim-Subscription-Key": config.subscription_key,
            "Vipps-System-Name": "talli", "Vipps-System-Version": "annual-2026-09-05",
        }
        token = _object(await self._request(
            client, "POST", "/accesstoken/get",
            headers=common | {"client_id": config.client_id, "client_secret": config.client_secret},
        ))
        value = token.get("access_token")
        if not isinstance(value, str) or not value or len(value) > 8192 or any(c in value for c in "\r\n"):
            raise _UnknownOutcome()
        return common | {"Authorization": "Bearer " + value, "Content-Type": "application/json"}

    async def execute(self, intent: AnnualProviderIntent) -> AnnualProviderObservation:
        return await self._run(intent, execute=True)

    async def reconcile(self, intent: AnnualProviderIntent) -> AnnualProviderObservation:
        return await self._run(intent, execute=False)

    async def _run(self, intent, *, execute):
        try:
            async with timeout(10), httpx.AsyncClient(
                transport=self._transport, timeout=5, follow_redirects=False,
            ) as client:
                headers = await self._headers(client)
                if execute:
                    return await self._execute(client, headers, intent)
                return await self._reconcile(client, headers, intent)
        except (httpx.HTTPError, TimeoutError, _UnknownOutcome, ValueError, TypeError, KeyError, UnicodeError):
            # No provider diagnostic, token, response body or secret escapes.
            return self._observation(intent, AnnualProviderStatus.UNKNOWN)

    def _checkout_url(self, value):
        if not isinstance(value, str) or len(value) > 4096:
            return None
        parsed = urlsplit(value)
        origin = parsed.scheme + "://" + parsed.netloc
        if (
            parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
            or origin not in self._configuration.confirmation_origins
        ):
            return None
        return value

    async def _execute(self, client, headers, intent):
        key = vipps_operation_key(self._configuration, intent)
        modifying = headers | {"Idempotency-Key": key}
        if intent.operation is AnnualProviderOperation.CHECKOUT:
            for value in (intent.return_url, intent.management_url):
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise _UnknownOutcome()
            created = _object(await self._request(
                client, "POST", _AGREEMENTS, headers=modifying, expected=(201,),
                body={
                    "pricing": {"type": "LEGACY", "amount": intent.amount_minor, "currency": "NOK"},
                    "interval": {"unit": "YEAR", "count": 1},
                    "externalId": intent.agreement_external_reference,
                    "productName": "Talli årsabonnement",
                    "productDescription": "Årlig fornyelse" if intent.recurring_consent else "Uten automatisk fornyelse",
                    "merchantRedirectUrl": intent.return_url,
                    "merchantAgreementUrl": intent.management_url,
                    "initialCharge": {
                        "amount": intent.amount_minor, "description": f"Talli {intent.income_year.value}",
                        "transactionType": "DIRECT_CAPTURE", "orderId": intent.charge_reference,
                        "externalId": intent.charge_reference,
                    },
                },
            ))
            agreement = _id(created["agreementId"])
            if created.get("chargeId", intent.charge_reference) != intent.charge_reference:
                raise _UnknownOutcome()
            return self._observation(
                intent, AnnualProviderStatus.PENDING, agreement=agreement,
                checkout_url=self._checkout_url(created.get("vippsConfirmationUrl")),
            )
        agreement_path = _AGREEMENTS + "/" + quote(_id(intent.agreement_reference), safe="")
        charge_path = agreement_path + "/charges/" + quote(intent.charge_reference, safe="")
        # Bind every consequential request to the original merchant agreement.
        # Renewals create a new charge, so only the agreement exists beforehand.
        await self._read_agreement(client, headers, intent, intent.agreement_reference)
        if intent.operation in {AnnualProviderOperation.CANCEL_CHARGE, AnnualProviderOperation.REFUND}:
            await self._read_charge(client, headers, intent, intent.agreement_reference)
        if intent.operation is AnnualProviderOperation.RENEWAL:
            if intent.due_date < self._now().date() + timedelta(days=1):
                raise _UnknownOutcome()
            result = _object(await self._request(
                client, "POST", agreement_path + "/charges", headers=modifying, expected=(201,),
                body={"amount": intent.amount_minor, "description": f"Talli {intent.income_year.value}",
                      "transactionType": "DIRECT_CAPTURE", "type": "RECURRING",
                      "due": intent.due_date.isoformat(), "retryDays": 5,
                      "orderId": intent.charge_reference, "externalId": intent.charge_reference},
            ))
            if result.get("chargeId") != intent.charge_reference:
                raise _UnknownOutcome()
        elif intent.operation is AnnualProviderOperation.STOP_AGREEMENT:
            await self._request(client, "PATCH", agreement_path, headers=modifying,
                                body={"status": "STOPPED"}, expected=(204,))
        elif intent.operation is AnnualProviderOperation.CANCEL_CHARGE:
            await self._request(client, "DELETE", charge_path, headers=modifying, expected=(202, 204))
        elif intent.operation is AnnualProviderOperation.REFUND:
            await self._request(client, "POST", charge_path + "/refund", headers=modifying,
                                body={"amount": intent.amount_minor, "description": "Talli refusjon"}, expected=(204,))
        return await self._reconcile(client, headers, intent)

    async def _find_agreement(self, client, headers, intent):
        matches = set()
        for status in ("PENDING", "ACTIVE", "STOPPED", "EXPIRED"):
            for page in range(1, 21):
                rows = await self._request(client, "GET", _AGREEMENTS, headers=headers,
                    params={"status": status, "pageNumber": page, "pageSize": 100,
                            "createdAfter": int((intent.created_at.value - timedelta(days=1)).timestamp() * 1000)})
                if not isinstance(rows, list):
                    raise _UnknownOutcome()
                for row in rows:
                    row = _object(row)
                    if row.get("externalId") == intent.agreement_external_reference:
                        matches.add(_id(row.get("id")))
                if len(rows) < 100:
                    break
            else:
                raise _UnknownOutcome()
        if len(matches) != 1:
            raise _UnknownOutcome()
        return matches.pop()

    async def _read_agreement(self, client, headers, intent, agreement):
        agreement_path = _AGREEMENTS + "/" + quote(_id(agreement), safe="")
        value = _object(await self._request(client, "GET", agreement_path, headers=headers))
        pricing = _object(value.get("pricing"))
        interval = _object(value.get("interval"))
        if (
            value.get("id") != agreement
            or value.get("externalId") != intent.agreement_external_reference
            or pricing.get("type") != "LEGACY" or pricing.get("currency") != "NOK"
            or _minor(pricing.get("amount")) != intent.original_charge_minor
            or interval.get("unit") != "YEAR" or type(interval.get("count")) is not int or interval.get("count") != 1
            or value.get("merchantRedirectUrl") != intent.return_url
            or value.get("merchantAgreementUrl") != intent.management_url
            or value.get("countryCode") != "NO"
            or value.get("productName") != "Talli årsabonnement"
            or value.get("status") not in {"PENDING", "ACTIVE", "STOPPED", "EXPIRED"}
        ):
            raise _UnknownOutcome()
        return value

    async def _read_charge(self, client, headers, intent, agreement):
        agreement_path = _AGREEMENTS + "/" + quote(_id(agreement), safe="")
        charge = _object(await self._request(client, "GET", agreement_path + "/charges/" + quote(intent.charge_reference, safe=""), headers=headers))
        if (
            charge.get("id") != intent.charge_reference or charge.get("agreementId") != agreement
            or charge.get("externalId") != intent.charge_reference
            or charge.get("currency") != "NOK" or _minor(charge.get("amount")) != intent.original_charge_minor
            or charge.get("transactionType") != "DIRECT_CAPTURE"
            or charge.get("type") != ("RECURRING" if intent.original_charge_is_renewal else "INITIAL")
            or charge.get("status") not in {"PENDING", "DUE", "RESERVED", "CHARGED", "PARTIALLY_CAPTURED", "FAILED", "CANCELLED", "PARTIALLY_REFUNDED", "REFUNDED", "PROCESSING"}
        ):
            raise _UnknownOutcome()
        summary = _object(charge.get("summary"))
        captured, refunded = _minor(summary.get("captured")), _minor(summary.get("refunded"))
        if not refunded <= captured <= intent.original_charge_minor:
            raise _UnknownOutcome()
        return charge, captured, refunded

    async def _reconcile(self, client, headers, intent):
        agreement = intent.agreement_reference or await self._find_agreement(client, headers, intent)
        value = await self._read_agreement(client, headers, intent, agreement)
        if intent.operation is AnnualProviderOperation.STOP_AGREEMENT:
            status = AnnualProviderStatus.CONFIRMED if value.get("status") == "STOPPED" else AnnualProviderStatus.PENDING
            return self._observation(intent, status, agreement=agreement)
        if intent.operation is AnnualProviderOperation.CHECKOUT and value.get("status") == "PENDING":
            return self._observation(intent, AnnualProviderStatus.PENDING, agreement=agreement,
                checkout_url=self._checkout_url(value.get("vippsConfirmationUrl")))
        charge, captured, refunded = await self._read_charge(client, headers, intent, agreement)
        status = AnnualProviderStatus.PENDING
        if intent.operation is AnnualProviderOperation.REFUND:
            history = charge.get("history")
            if not isinstance(history, list):
                raise _UnknownOutcome()
            matches = [row for row in history if isinstance(row, dict)
                       and row.get("event") == "REFUND"
                       and row.get("idempotencyKey") == vipps_operation_key(self._configuration, intent)]
            if len(matches) == 1 and matches[0].get("success") is True and _minor(matches[0].get("amount")) == intent.amount_minor and refunded >= intent.amount_minor:
                status = AnnualProviderStatus.CONFIRMED
            else:
                status = AnnualProviderStatus.UNKNOWN
        elif intent.operation is AnnualProviderOperation.CANCEL_CHARGE:
            status = AnnualProviderStatus.CONFIRMED if charge.get("status") == "CANCELLED" else AnnualProviderStatus.PENDING
        elif captured == intent.amount_minor and charge.get("status") in {"CHARGED", "PARTIALLY_REFUNDED", "REFUNDED"}:
            status = AnnualProviderStatus.CONFIRMED
        elif charge.get("status") in {"FAILED", "CANCELLED"}:
            status = AnnualProviderStatus.FAILED
        return self._observation(intent, status, agreement=agreement, captured=captured, refunded=refunded)
