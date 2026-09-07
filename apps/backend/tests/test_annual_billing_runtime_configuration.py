"""Opt-in runtime composition, with synthetic credentials and local HTTP only."""

import asyncio
from datetime import UTC, datetime
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from test_annual_checkout_api import Session, prerequisites, start
from test_vipps_webhook import encoded, signed
from talli_backend.adapters import annual_billing_runtime as runtime
from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.adapters.vipps_billing import VippsTestBillingProvider
from talli_backend.main import create_app
from talli_backend.modules.billing.public import AnnualNotificationReceipt, AnnualNotificationReceiptId
from talli_backend.shared.kernel import Timestamp


SETTINGS = {
    "TALLI_ANNUAL_BILLING_MODE": "vipps-mt",
    "TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER": "535717",
    "TALLI_VIPPS_MT_CLIENT_ID": "local-client-only",
    "TALLI_VIPPS_MT_CLIENT_SECRET": "local-client-secret-only",
    "TALLI_VIPPS_MT_SUBSCRIPTION_KEY": "local-subscription-secret-only",
    "TALLI_VIPPS_MT_CONFIRMATION_ORIGINS": "https://mt-confirmation.example",
    "TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL": "https://talli.example" + runtime.ANNUAL_NOTIFICATION_PATH,
    "TALLI_VIPPS_MT_WEBHOOK_SECRET": "local-webhook-secret-only",
    "TALLI_ANNUAL_NOTIFICATION_DATABASE_URL": "postgresql://notification:local-db-secret@127.0.0.1:5432/disposable",
}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


def enabled_environment(monkeypatch, **changes):
    for name, value in (SETTINGS | changes).items():
        monkeypatch.setenv(name, value)


def test_default_and_explicit_off_construct_no_provider_or_inbox(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled configuration must not construct transports")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    monkeypatch.setattr(runtime, "PostgresAnnualNotificationInbox", forbidden)
    assert runtime.compose_annual_billing_runtime({}) == runtime.AnnualBillingRuntime()
    assert runtime.compose_annual_billing_runtime(
        SETTINGS | {"TALLI_ANNUAL_BILLING_MODE": "off", "TALLI_VIPPS_MT_CLIENT_SECRET": "invalid\nsecret"}
    ) == runtime.AnnualBillingRuntime()
    api = TestClient(create_app(annual_billing_session_factory=Session()))
    assert start(api).json()["code"] == "BILLING_PROVIDER_DISABLED"
    assert api.post(runtime.ANNUAL_NOTIFICATION_PATH, content=b"{}").status_code == 503


@pytest.mark.parametrize("missing", [name for name in SETTINGS if name != "TALLI_ANNUAL_BILLING_MODE"])
def test_enabled_runtime_requires_complete_settings_before_constructing_adapters(missing, monkeypatch):
    values = SETTINGS.copy()
    values.pop(missing)

    def forbidden(*args, **kwargs):
        pytest.fail("Incomplete configuration must not construct transports")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    monkeypatch.setattr(runtime, "PostgresAnnualNotificationInbox", forbidden)
    with pytest.raises(runtime.AnnualBillingRuntimeConfigurationError, match=missing):
        runtime.compose_annual_billing_runtime(values)


@pytest.mark.parametrize("setting,value", [
    ("TALLI_ANNUAL_BILLING_MODE", "production"),
    ("TALLI_ANNUAL_BILLING_MODE", "true"),
    ("TALLI_ANNUAL_BILLING_MODE", ""),
    ("TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER", "123456"),
    ("TALLI_VIPPS_MT_CLIENT_SECRET", "local-client-secret\nonly"),
    ("TALLI_VIPPS_MT_CLIENT_ID", " local-client-only"),
    ("TALLI_VIPPS_MT_SUBSCRIPTION_KEY", "x" * 8193),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://api.vipps.no"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example/"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example/path"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example,"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example,https://mt-confirmation.example"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://user:secret@mt-confirmation.example"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example:99999"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example?query"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://mt-confirmation.example#fragment"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://%invalid.example"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://invalid..example"),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", "http://talli.example" + runtime.ANNUAL_NOTIFICATION_PATH),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", "https://talli.example/wrong"),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", SETTINGS["TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL"] + "/"),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", SETTINGS["TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL"] + "?fixture=1"),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", SETTINGS["TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL"] + "?"),
    ("TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL", SETTINGS["TALLI_VIPPS_MT_WEBHOOK_CALLBACK_URL"] + "#"),
    ("TALLI_VIPPS_MT_WEBHOOK_SECRET", "x" * 1025),
    ("TALLI_ANNUAL_NOTIFICATION_DATABASE_URL", "https://notification:local-db-secret@example.test/db"),
    ("TALLI_ANNUAL_NOTIFICATION_DATABASE_URL", "postgresql://notification:local-db-secret@127.0.0.1:wrong/db"),
    ("TALLI_ANNUAL_NOTIFICATION_DATABASE_URL", "postgresql://notification:local-db-secret@127.0.0.1/db?unknown=secret"),
    ("TALLI_ANNUAL_NOTIFICATION_DATABASE_URL", "postgresql://127.0.0.1/db"),
])
def test_invalid_enabled_settings_fail_startup_without_exposing_values(setting, value, monkeypatch):
    enabled_environment(monkeypatch, **{setting: value})
    with pytest.raises(runtime.AnnualBillingRuntimeConfigurationError) as error:
        create_app()
    assert str(error.value) == f"Invalid annual billing runtime setting: {setting}"
    assert error.value.__cause__ is None


def test_typed_configuration_redacts_credentials_and_binds_one_designated_account():
    configuration = runtime.AnnualBillingRuntimeConfiguration.from_environment(SETTINGS)
    assert configuration.vipps.merchant_serial_number == configuration.webhook.account.reference == "535717"
    assert configuration.webhook.account.provider == "vipps-mt"
    assert configuration.notification_database_url == SETTINGS["TALLI_ANNUAL_NOTIFICATION_DATABASE_URL"]
    for secret in ("local-client-only", "local-client-secret-only", "local-subscription-secret-only",
                   "local-webhook-secret-only", "local-db-secret"):
        assert secret not in repr(configuration)
    # The offline MT runner can parse provider configuration independently of
    # webhook credentials, database access, runtime activation and readiness.
    provider_settings = {key: value for key, value in SETTINGS.items()
                         if key.startswith("TALLI_VIPPS_MT_") and "WEBHOOK" not in key}
    assert runtime.load_vipps_mt_configuration(provider_settings) == configuration.vipps


class LocalInbox:
    def __init__(self, database_url, account):
        self.database_url = database_url
        self.account = account
        self.saved = {}

    async def record_notification(self, notification):
        assert notification.account == self.account
        return self.saved.setdefault(notification.receipt_digest, AnnualNotificationReceipt(
            AnnualNotificationReceiptId(str(uuid4())), Timestamp(datetime.now(UTC)), notification,
        ))


@pytest.fixture
def transports(monkeypatch):
    requests, providers, inboxes = [], [], []

    def http(request):
        requests.append(request)
        assert request.url.host == "apitest.vipps.no"
        assert request.headers["Merchant-Serial-Number"] == "535717"
        if request.url.path == "/accesstoken/get":
            return httpx.Response(200, json={"access_token": "local-access-token"})
        assert request.method == "POST" and request.url.path == "/recurring/v3/agreements"
        intent = json.loads(request.content)
        return httpx.Response(201, json={
            "agreementId": "local-agreement", "chargeId": intent["initialCharge"]["orderId"],
            "vippsConfirmationUrl": "https://mt-confirmation.example/approve",
        })

    def provider(configuration):
        value = VippsTestBillingProvider(configuration, transport=httpx.MockTransport(http))
        providers.append(value)
        return value

    def inbox(database_url, account):
        value = LocalInbox(database_url, account)
        inboxes.append(value)
        return value

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", provider)
    monkeypatch.setattr(runtime, "PostgresAnnualNotificationInbox", inbox)
    return requests, providers, inboxes


def test_environment_composes_actual_mt_provider_and_signed_intake_through_http(monkeypatch, transports):
    enabled_environment(monkeypatch)
    requests, providers, inboxes = transports
    api = TestClient(create_app(annual_billing_session_factory=Session(), annual_checkout_prerequisites=prerequisites))
    assert requests == [] and len(providers) == len(inboxes) == 1
    assert not providers[0].production_enabled
    assert providers[0].account_reference == inboxes[0].account.reference == "535717"
    result = start(api)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "pending"
    assert result.json()["checkoutUrl"] == "https://mt-confirmation.example/approve"
    assert len(requests) == 2
    payload = json.loads(requests[-1].content)
    assert payload["initialCharge"]["amount"] == 149000

    body = encoded(msn="535717", occurred=datetime.now(UTC).isoformat())
    headers = signed(body, path=runtime.ANNUAL_NOTIFICATION_PATH, at=datetime.now(UTC),
                     key=SETTINGS["TALLI_VIPPS_MT_WEBHOOK_SECRET"])
    for _ in range(2):
        response = api.post(runtime.ANNUAL_NOTIFICATION_PATH, content=body, headers=headers)
        assert response.status_code == 200 and response.json() == {"status": "received"}
    assert len(inboxes[0].saved) == 1 and len(requests) == 2
    wrong = encoded(msn="999999", occurred=datetime.now(UTC).isoformat())
    response = api.post(runtime.ANNUAL_NOTIFICATION_PATH, content=wrong,
                        headers=signed(wrong, path=runtime.ANNUAL_NOTIFICATION_PATH, at=datetime.now(UTC),
                                       key=SETTINGS["TALLI_VIPPS_MT_WEBHOOK_SECRET"]))
    assert response.status_code == 401 and len(inboxes[0].saved) == 1


def test_enabling_transport_does_not_supply_checkout_readiness_or_current_source_verification(monkeypatch, transports):
    enabled_environment(monkeypatch)
    requests, _, _ = transports
    api = TestClient(create_app(annual_billing_session_factory=Session()))
    result = start(api)
    assert result.status_code == 409 and result.json()["code"] == "BILLING_FILING_NOT_READY"
    assert requests == []

    # The real environment session still constructs the default closed verifier.
    adapter = SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration("", "", ""))
    class VerifiedSession:
        _verified = object()

    async def authenticated(token):
        return VerifiedSession()

    monkeypatch.setattr(adapter._authentication, "session", authenticated)
    session = asyncio.run(adapter.session("local-token"))
    assert asyncio.run(session.checkout._readiness_is_current(object())) is False


@pytest.mark.parametrize("dependency", ["provider", "intake"])
def test_explicit_dependency_injection_never_composes_an_ambient_merchant(dependency, monkeypatch):
    monkeypatch.setenv("TALLI_ANNUAL_BILLING_MODE", "vipps-mt")
    # Missing credentials intentionally demonstrate that injection is independent
    # of environment composition, without accidentally enabling the other side.
    if dependency == "provider":
        from test_annual_checkout_api import LocalProvider
        api = TestClient(create_app(annual_billing_provider=LocalProvider()))
        assert api.post(runtime.ANNUAL_NOTIFICATION_PATH, content=b"{}").status_code == 503
    else:
        from test_annual_notification_intake import AUTH, Receipts
        from talli_backend.application.annual_notifications import AnnualNotificationIntake
        api = TestClient(create_app(annual_billing_session_factory=Session(),
                                   annual_notification_intake=AnnualNotificationIntake(AUTH, Receipts())))
        assert start(api).json()["code"] == "BILLING_PROVIDER_DISABLED"
