"""Independent worker configuration and a single pass with local HTTP only."""

import asyncio
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4

import httpx
import pytest

from talli_backend.adapters import annual_billing_runtime as runtime
from talli_backend.adapters.vipps_billing import VippsTestBillingProvider
from talli_backend.modules.billing.public import (
    AnnualCheckout, AnnualCheckoutObservationLease,
    AnnualPurchaseId, AnnualPurchaseStatus, BillingError, annual_billing_offer,
    settle_annual_checkout,
)
from talli_backend.shared.kernel import IdempotencyKey, Timestamp, UserId
from test_vipps_billing import NOW, intent


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_annual_checkout_reconciliation.py"
spec = importlib.util.spec_from_file_location("annual_checkout_reconciliation_cli", SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

SETTINGS = {
    "TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE": "vipps-mt",
    "TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL": "postgresql://worker:local-worker-secret@127.0.0.1:5432/disposable",
    "TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER": "535717",
    "TALLI_VIPPS_MT_CLIENT_ID": "local-client-only",
    "TALLI_VIPPS_MT_CLIENT_SECRET": "local-client-secret-only",
    "TALLI_VIPPS_MT_SUBSCRIPTION_KEY": "local-subscription-secret-only",
    "TALLI_VIPPS_MT_CONFIRMATION_ORIGINS": "https://mt-confirmation.example",
}


def test_default_off_preflight_ignores_other_runtime_settings_and_constructs_nothing(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline preflight must not compose a worker")

    monkeypatch.setattr(runtime, "compose_annual_checkout_reconciliation", forbidden)
    environment = SETTINGS | {"TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE": "off", "TALLI_ANNUAL_BILLING_MODE": "vipps-mt"}
    assert cli.main([], environment=environment) == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "offline-preflight", "configuration_valid": True, "enabled": False,
        "database_calls": 0, "provider_calls": 0, "missing_names": [],
    }
    assert runtime.AnnualCheckoutReconciliationConfiguration.from_environment(environment) is None


def test_enabled_preflight_validates_without_db_provider_or_webhook_configuration(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must not construct transports or use a database")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    monkeypatch.setattr(runtime.psycopg.AsyncConnection, "connect", forbidden)
    assert cli.main([], environment=SETTINGS) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["enabled"] and report["configuration_valid"]
    assert report["database_calls"] == report["provider_calls"] == 0
    assert "535717" not in json.dumps(report) and "local-" not in json.dumps(report)
    configuration = runtime.AnnualCheckoutReconciliationConfiguration.from_environment(SETTINGS)
    assert configuration.database_url == SETTINGS["TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL"]
    assert configuration.vipps.merchant_serial_number == "535717"
    assert "secret" not in repr(configuration)
    assert runtime.compose_annual_billing_runtime(SETTINGS) == runtime.AnnualBillingRuntime()


@pytest.mark.parametrize("missing", cli.REQUIRED_SETTINGS)
def test_each_enabled_setting_is_required_before_worker_construction(missing, monkeypatch, capsys):
    settings = SETTINGS.copy()
    settings.pop(missing)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid configuration must not construct a provider")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    assert cli.main([], environment=settings) == 0
    preflight = json.loads(capsys.readouterr().out)
    assert not preflight["configuration_valid"] and missing in preflight["missing_names"]
    assert cli.main(["--run-once"], environment=settings) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err) == {"error": "checkout_reconciliation_configuration_invalid"}


@pytest.mark.parametrize("setting,value", [
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE", "production"),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE", ""),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE", "vipps-mt\nlocal-secret"),
    ("TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER", "123456"),
    ("TALLI_VIPPS_MT_CONFIRMATION_ORIGINS", "https://api.vipps.no"),
    ("TALLI_VIPPS_MT_CLIENT_SECRET", "local-secret\ninvalid"),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL", "https://worker:local-secret@example.test/db"),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL", "postgresql://127.0.0.1/db"),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL", "postgresql://worker:local-secret@127.0.0.1:wrong/db"),
    ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL", "postgresql://worker:local-secret@127.0.0.1/db?unknown=local-secret"),
])
def test_invalid_worker_configuration_is_rejected_without_values(setting, value, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid configuration must precede construction")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    assert cli.main(["--run-once"], environment=SETTINGS | {setting: value}) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err) == {"error": "checkout_reconciliation_configuration_invalid"}


def test_explicit_pass_with_mode_off_cannot_activate_from_http_runtime(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Off worker mode must not construct the provider")

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", forbidden)
    assert cli.main(["--run-once"], environment={"TALLI_ANNUAL_BILLING_MODE": "vipps-mt"}) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "checkout_reconciliation_disabled"}


def test_invalid_arguments_never_echo_argument_values(capsys):
    assert cli.main(["--database-url", "local-private-database-url"], environment={}) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err) == {"error": "invalid_arguments"}


class Store:
    def __init__(self, database_url, provider, provider_account):
        self.database_url, self.provider, self.provider_account = database_url, provider, provider_account
        original = intent(agreement_reference="agr_local")
        self.checkout = AnnualCheckout(
            AnnualPurchaseId(str(uuid4())), annual_billing_offer(original.company_id, original.income_year),
            UserId(str(uuid4())), "a" * 64, IdempotencyKey("local-checkout-key"),
            provider, provider_account, original, AnnualPurchaseStatus.PENDING,
        )
        self.events = []
        self.idle = False
        self.authorized = True

    async def claim_checkout_observation(self):
        self.events.append("claim")
        return None if self.idle else AnnualCheckoutObservationLease(self.checkout, "local-lease", 1)

    async def authorize_checkout_observation(self, lease):
        self.events.append("authorize")
        if not self.authorized:
            raise BillingError.forbidden()

    async def settle_checkout_observation(self, lease, observation):
        self.events.append("settle")
        if observation is not None:
            self.checkout = settle_annual_checkout(self.checkout, observation, Timestamp(datetime.now(UTC)))
        return self.checkout


@pytest.fixture
def local_worker(monkeypatch):
    stores, calls = [], []
    flags = {"idle": False, "authorized": True, "unknown": False}

    def store(database_url, provider, provider_account):
        value = Store(database_url, provider, provider_account)
        value.idle, value.authorized = flags["idle"], flags["authorized"]
        stores.append(value)
        return value

    # A constructor-only substitute keeps this composition/CLI test independent
    # of database access; the real adapter has a separate mandatory DB suite.
    module = ModuleType("talli_backend.adapters.postgres_annual_observation")
    module.PostgresAnnualCheckoutObservationStore = store
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def http(request):
        calls.append(request)
        assert request.url.host == "apitest.vipps.no"
        assert request.headers["Merchant-Serial-Number"] == "535717"
        if request.url.path == "/accesstoken/get":
            return httpx.Response(200, json={"access_token": "local-private-token"})
        assert request.method == "GET", "The worker must never execute a provider mutation"
        if flags["unknown"]:
            raise httpx.ReadTimeout("tenant-local-private-token")
        original = stores[-1].checkout.intent
        if "/charges/" in request.url.path:
            return httpx.Response(200, json={
                "id": original.charge_reference, "agreementId": "agr_local",
                "externalId": original.charge_reference, "currency": "NOK", "amount": 149000,
                "transactionType": "DIRECT_CAPTURE", "type": "INITIAL", "status": "CHARGED",
                "summary": {"captured": 149000, "refunded": 0},
                "history": [{"event": "CAPTURE", "amount": 149000, "success": True, "occurred": NOW.isoformat()}],
            })
        return httpx.Response(200, json={
            "id": "agr_local", "externalId": original.agreement_external_reference,
            "pricing": {"type": "LEGACY", "currency": "NOK", "amount": 149000},
            "interval": {"unit": "YEAR", "count": 1}, "countryCode": "NO", "status": "ACTIVE",
            "merchantRedirectUrl": original.return_url, "merchantAgreementUrl": original.management_url,
            "productName": "Talli årsabonnement",
        })

    def provider(configuration):
        return VippsTestBillingProvider(configuration, transport=httpx.MockTransport(http))

    monkeypatch.setattr(runtime, "VippsTestBillingProvider", provider)
    return stores, calls, flags


def test_one_explicit_pass_uses_real_public_factory_and_reconcile_only_provider(local_worker, capsys):
    stores, calls, _ = local_worker
    operations = runtime.compose_annual_checkout_reconciliation(SETTINGS)
    assert len(stores) == 1 and not calls and stores[0].events == []
    assert stores[0].provider == "vipps-mt" and stores[0].provider_account == "535717"
    assert asyncio.run(cli.run_once(operations)) == {"action": "run-once", "outcome": "reconciled"}
    assert stores[0].events == ["claim", "authorize", "settle"]
    assert len(calls) == 3
    assert cli.main(["--run-once"], environment=SETTINGS) == 0
    assert json.loads(capsys.readouterr().out) == {"action": "run-once", "outcome": "reconciled"}
    assert stores[1].events == ["claim", "authorize", "settle"]


@pytest.mark.parametrize("idle,unknown,outcome", [(True, False, "idle"), (False, True, "retry")])
def test_idle_or_unknown_result_still_runs_only_one_bounded_pass(local_worker, capsys, idle, unknown, outcome):
    stores, calls, flags = local_worker
    flags.update(idle=idle, unknown=unknown)
    assert cli.main(["--run-once"], environment=SETTINGS) == 0
    assert json.loads(capsys.readouterr().out) == {"action": "run-once", "outcome": outcome}
    assert len(stores) == 1 and stores[0].events.count("claim") == 1
    assert len(calls) == (0 if idle else 2)


def test_revoked_worker_authority_prevents_provider_read_and_has_no_data_output(local_worker, capsys):
    stores, calls, flags = local_worker
    flags["authorized"] = False
    assert cli.main(["--run-once"], environment=SETTINGS) == 2
    assert not calls and stores[0].events == ["claim", "authorize"]
    assert json.loads(capsys.readouterr().err) == {"error": "checkout_reconciliation_unavailable"}


def test_overall_timeout_cancels_one_pass_without_printing_exception(monkeypatch, capsys):
    events = []

    class Hung:
        async def run_once(self):
            events.append("start")
            try:
                await asyncio.Future()
            finally:
                events.append("cancel")

    monkeypatch.setattr(cli, "PASS_TIMEOUT_SECONDS", .01)
    monkeypatch.setattr(runtime, "compose_annual_checkout_reconciliation", lambda _: Hung())
    assert cli.main(["--run-once"], environment=SETTINGS) == 2
    assert events == ["start", "cancel"]
    assert json.loads(capsys.readouterr().err) == {"error": "checkout_reconciliation_unavailable"}


@pytest.mark.parametrize("value", ["tenant-private-outcome", {"tenant": "local-private"}])
def test_untyped_worker_result_never_leaks_to_command_output(monkeypatch, capsys, value):
    class Invalid:
        async def run_once(self):
            return value

    monkeypatch.setattr(runtime, "compose_annual_checkout_reconciliation", lambda _: Invalid())
    assert cli.main(["--run-once"], environment=SETTINGS) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "invalid_worker_outcome"}
