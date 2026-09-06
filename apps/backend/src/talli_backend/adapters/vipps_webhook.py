"""Authenticate MT Recurring notifications before durable resource reconciliation.

No financial amount is applied from a delivery. The returned resource references
must resolve to a previously persisted local intent under the configured MSN.
Source: https://developer.vippsmobilepay.com/docs/APIs/webhooks-api/request-authentication/
"""

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from talli_backend.modules.billing.public import (
    AnnualNotificationAccount, AnnualNotificationAuthentication,
    AnnualNotificationRejected, AnnualProviderNotification, billing_provider_adapter,
)
from talli_backend.shared.kernel import Timestamp


class VippsWebhookRejected(ValueError):
    def __init__(self) -> None:
        super().__init__("VIPPS_WEBHOOK_REJECTED")


@dataclass(frozen=True, slots=True)
class VippsNotification:
    receipt_digest: str
    merchant_serial_number: str
    agreement_reference: str
    charge_reference: str | None
    event_type: str
    occurred_at: datetime


_EVENTS = frozenset(
    "recurring." + event + ".v1" for event in (
        "agreement-activated", "agreement-rejected", "agreement-stopped",
        "agreement-expired", "charge-reserved", "charge-captured", "charge-canceled",
        "charge-refunded", "charge-failed", "charge-creation-failed",
    )
)
_REFERENCE = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_AUTH_PREFIX = "HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature="


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VippsWebhookRejected()
        result[key] = value
    return result


def _reference(value: object) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise VippsWebhookRejected()
    return value


@billing_provider_adapter(AnnualNotificationAuthentication)
@dataclass(frozen=True, slots=True)
class VippsWebhookAuthentication:
    merchant_serial_number: str
    callback_url: str
    secret: str = field(repr=False)

    @property
    def account(self) -> AnnualNotificationAccount:
        return AnnualNotificationAccount("vipps-mt", self.merchant_serial_number)

    def authenticate(
        self, body: bytes, headers: Mapping[str, str], *, at: datetime,
    ) -> AnnualProviderNotification:
        try:
            value = self.verify(body, headers, at=at)
            return AnnualProviderNotification(
                account=self.account, receipt_digest=value.receipt_digest,
                agreement_reference=value.agreement_reference, charge_reference=value.charge_reference,
                event_type=value.event_type, occurred_at=Timestamp(value.occurred_at),
            )
        except ValueError:
            raise AnnualNotificationRejected() from None

    def __post_init__(self) -> None:
        target = urlsplit(self.callback_url)
        if (
            not re.fullmatch(r"[0-9]{3,12}", self.merchant_serial_number)
            or target.scheme != "https"
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.fragment
            or not self.secret
            or len(self.secret) > 1024
        ):
            raise VippsWebhookRejected()

    def verify(
        self, body: bytes, headers: Mapping[str, str], *, at: datetime
    ) -> VippsNotification:
        """Verify raw bytes and exact registered target, allowing seven-day retries.

        The eight-day past bound is a local defensive policy, not a Vipps promise.
        Durable receipt deduplication and GET reconciliation remain mandatory.
        Proxy-supplied Host/Forwarded values are not trusted for the signed target.
        """
        try:
            return self._verify(body, headers, at=at)
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
            raise VippsWebhookRejected() from None

    def _verify(
        self, body: bytes, headers: Mapping[str, str], *, at: datetime
    ) -> VippsNotification:
        if not 0 < len(body) <= 65536 or at.tzinfo is None:
            raise VippsWebhookRejected()
        normalized: dict[str, str] = {}
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise VippsWebhookRejected()
            name = key.lower()
            if name in normalized:
                raise VippsWebhookRejected()
            if name in {"authorization", "x-ms-date", "x-ms-content-sha256"}:
                if len(value) > 1024 or "\n" in value or "\r" in value:
                    raise VippsWebhookRejected()
            normalized[name] = value
        request_date = normalized["x-ms-date"]
        timestamp = parsedate_to_datetime(request_date)
        if timestamp.tzinfo is None:
            raise VippsWebhookRejected()
        if not at - timedelta(days=8) <= timestamp <= at + timedelta(minutes=5):
            raise VippsWebhookRejected()
        content_hash = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
        if not hmac.compare_digest(content_hash, normalized["x-ms-content-sha256"]):
            raise VippsWebhookRejected()
        target = urlsplit(self.callback_url)
        path = target.path or "/"
        if target.query:
            path += "?" + target.query
        canonical = f"POST\n{path}\n{request_date};{target.netloc};{content_hash}"
        signature = base64.b64encode(hmac.new(
            self.secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
        ).digest()).decode("ascii")
        if not hmac.compare_digest(_AUTH_PREFIX + signature, normalized["authorization"]):
            raise VippsWebhookRejected()
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or payload.get("msn") != self.merchant_serial_number:
            raise VippsWebhookRejected()
        event = payload["eventType"]
        if not isinstance(event, str) or event not in _EVENTS:
            raise VippsWebhookRejected()
        agreement = _reference(payload["agreementId"])
        charge = None
        if event.startswith("recurring.charge-"):
            charge = _reference(payload["chargeId"])
            if payload.get("currency") != "NOK":
                raise VippsWebhookRejected()
            for key in ("amount", "amountCaptured", "amountRefunded", "amountCanceled"):
                if key in payload and (type(payload[key]) is not int or payload[key] < 0):
                    raise VippsWebhookRejected()
        if not isinstance(payload.get("occurred"), str):
            raise VippsWebhookRejected()
        occurred = datetime.fromisoformat(payload["occurred"].replace("Z", "+00:00"))
        if occurred.tzinfo is None or occurred > at + timedelta(minutes=5):
            raise VippsWebhookRejected()
        return VippsNotification(
            receipt_digest=hashlib.sha256(body).hexdigest(),
            merchant_serial_number=self.merchant_serial_number,
            agreement_reference=agreement,
            charge_reference=charge,
            event_type=event,
            occurred_at=occurred.astimezone(UTC),
        )
