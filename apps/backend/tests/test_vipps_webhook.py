import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from talli_backend.adapters.vipps_webhook import VippsWebhookAuthentication, VippsWebhookRejected


NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
SECRET = "local-fixture-only-key-ending-in=="
AUTH = VippsWebhookAuthentication("123456", "https://talli.example/api/v1/billing/vipps/webhook?test=1", SECRET)
PAYLOAD = {
    "msn": "123456", "agreementId": "agr_local-123", "chargeId": "talli-2026-charge",
    "eventType": "recurring.charge-captured.v1", "occurred": "2026-09-05T11:59:00Z",
    "amount": 149000, "currency": "NOK", "amountCaptured": 149000,
    "transactionId": None,
}


def signed(body: bytes, *, at=NOW, path="/api/v1/billing/vipps/webhook?test=1", host="talli.example", key=SECRET):
    date = format_datetime(at, usegmt=True)
    content_hash = base64.b64encode(hashlib.sha256(body).digest()).decode()
    canonical = f"POST\n{path}\n{date};{host};{content_hash}"
    signature = base64.b64encode(hmac.new(key.encode(), canonical.encode(), hashlib.sha256).digest()).decode()
    return {
        "x-ms-date": date, "x-ms-content-sha256": content_hash,
        "Authorization": "HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature=" + signature,
    }


def encoded(**changes):
    return json.dumps(PAYLOAD | changes, separators=(",", ":")).encode()


def test_valid_raw_signed_notification_provides_only_reconciliation_references():
    body = encoded()
    notification = AUTH.verify(body, signed(body), at=NOW)
    assert notification.agreement_reference == "agr_local-123"
    assert notification.charge_reference == "talli-2026-charge"
    assert notification.receipt_digest == hashlib.sha256(body).hexdigest()
    assert AUTH.verify(body, signed(body, at=NOW - timedelta(days=7)), at=NOW) == notification
    assert "local-fixture" not in repr(AUTH)


@pytest.mark.parametrize("change", [
    {"msn": "999999"}, {"agreementId": "../../other"}, {"chargeId": ""},
    {"eventType": "epayments.payment.captured.v1"}, {"currency": "EUR"},
    {"amountCaptured": -1}, {"amount": True}, {"amount": 149000.5},
    {"occurred": "2026-09-05T11:59:00"}, {"occurred": "2027-01-01T00:00:00Z"},
    {"occurred": None}, {"occurred": 1}, {"occurred": {}},
])
def test_signed_but_invalid_or_wrong_scope_data_fails_closed(change):
    body = encoded(**change)
    with pytest.raises(VippsWebhookRejected, match="^VIPPS_WEBHOOK_REJECTED$"):
        AUTH.verify(body, signed(body), at=NOW)


@pytest.mark.parametrize("headers", [
    {}, {"path": "/wrong"}, {"host": "other.example"}, {"key": "other-fixture-key"},
    {"at": NOW - timedelta(days=9)}, {"at": NOW + timedelta(minutes=6)},
])
def test_tampering_wrong_target_key_and_expired_signatures_reject(headers):
    body = encoded()
    supplied = signed(body, **headers)
    if not headers:
        supplied["x-ms-content-sha256"] = "wrong"
    with pytest.raises(VippsWebhookRejected):
        AUTH.verify(body, supplied, at=NOW)


def test_reserialization_duplicate_headers_and_duplicate_json_keys_reject():
    body = encoded()
    with pytest.raises(VippsWebhookRejected):
        AUTH.verify(body + b" ", signed(body), at=NOW)
    headers = signed(body)
    headers["authorization"] = headers["Authorization"]
    with pytest.raises(VippsWebhookRejected):
        AUTH.verify(body, headers, at=NOW)
    duplicate = body[:-1] + b',"msn":"123456"}'
    with pytest.raises(VippsWebhookRejected):
        AUTH.verify(duplicate, signed(duplicate), at=NOW)


def test_body_limit_and_missing_secret_fail_closed():
    body = b" " * 65537
    with pytest.raises(VippsWebhookRejected):
        AUTH.verify(body, signed(body), at=NOW)
    with pytest.raises(VippsWebhookRejected):
        VippsWebhookAuthentication("123456", AUTH.callback_url, "")


def test_untrusted_proxy_headers_cannot_change_registered_signed_target():
    body = encoded()
    headers = signed(body) | {"Host": "internal.local", "X-Forwarded-Host": "attacker.example"}
    assert AUTH.verify(body, headers, at=NOW).merchant_serial_number == "123456"
