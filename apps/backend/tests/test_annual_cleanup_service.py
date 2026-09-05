"""Recovery of a committed agreement stop, separate from purchase settlement."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from talli_backend.modules.billing.annual_cleanup import AnnualAgreementCleanupService
from talli_backend.modules.billing.public import (
    AnnualAgreementCleanup, AnnualAgreementCleanupClaim, AnnualCancellationId,
    AnnualCheckoutQuery, AnnualProviderIntent, AnnualProviderObservation,
    AnnualProviderOperation, AnnualProviderStatus, AnnualPurchaseId,
    BillingError, BillingPaymentEventId, settle_annual_agreement_cleanup,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId

ACTOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
COMPANY = CompanyId(str(uuid4()))
PURCHASE = AnnualPurchaseId(str(uuid4()))
NOW = Timestamp(datetime(2026, 9, 5, 12, tzinfo=UTC))
QUERY = AnnualCheckoutQuery(COMPANY, ACTOR, PURCHASE)


def candidate():
    return AnnualAgreementCleanup(
        purchase_id=PURCHASE, cancellation_id=AnnualCancellationId(str(uuid4())),
        provider="vipps-mt", provider_account="123456",
        intent=AnnualProviderIntent(
            operation_id=BillingPaymentEventId(str(uuid4())), company_id=COMPANY,
            income_year=IncomeYear(2026), operation=AnnualProviderOperation.STOP_AGREEMENT,
            amount_minor=0, created_at=NOW, agreement_external_reference="agreement-fixture",
            charge_reference="charge-fixture", return_url="https://talli.example/return",
            management_url="https://talli.example/billing", recurring_consent=True,
            agreement_reference="agr_fixture",
        ),
    )


def observation(cleanup, status=AnnualProviderStatus.CONFIRMED, **changes):
    return replace(AnnualProviderObservation(
        provider=cleanup.provider, operation=AnnualProviderOperation.STOP_AGREEMENT,
        status=status, agreement_reference=cleanup.intent.agreement_reference,
        charge_reference=cleanup.intent.charge_reference, amount_minor=0,
    ), **changes)


class Store:
    actor_id = ACTOR

    def __init__(self):
        self.saved = None
        self.authorized = True
        self.ready = True
        self.lose_claim = False
        self.lose_settlement = False
        self.lock = asyncio.Lock()
        self.settlements = 0

    async def claim_agreement_cleanup(self, company, purchase):
        if not self.authorized or company != COMPANY or purchase != PURCHASE:
            raise BillingError.forbidden()
        async with self.lock:
            if self.saved:
                return AnnualAgreementCleanupClaim(self.saved, False)
            if not self.ready:
                return None
            self.saved = candidate()
            if self.lose_claim:
                raise BillingError.unavailable()
            return AnnualAgreementCleanupClaim(self.saved, True)

    async def settle_agreement_cleanup(self, cleanup, result):
        async with self.lock:
            assert self.saved.intent == cleanup.intent
            self.saved = settle_annual_agreement_cleanup(self.saved, result)
            self.settlements += 1
            if self.lose_settlement:
                raise BillingError.unavailable()
            return self.saved


class Provider:
    provider = "vipps-mt"
    account_reference = "123456"
    production_enabled = False

    def __init__(self, store):
        self.store = store
        self.executions = []
        self.reads = []
        self.stopped = False
        self.lose_response = False
        self.unknown_read = False
        self.malformed = {}

    async def execute(self, intent):
        assert self.store.saved is not None, "Provider effect preceded committed intent"
        assert self.store.saved.intent == intent
        self.executions.append(intent)
        self.stopped = True
        if self.lose_response:
            raise TimeoutError("fixture-only diagnostic")
        return observation(self.store.saved, **self.malformed)

    async def reconcile(self, intent):
        self.reads.append(intent)
        status = (AnnualProviderStatus.UNKNOWN if self.unknown_read else
                  AnnualProviderStatus.CONFIRMED if self.stopped else AnnualProviderStatus.PENDING)
        return observation(self.store.saved, status, **self.malformed)


def fixture():
    store = Store()
    provider = Provider(store)
    return AnnualAgreementCleanupService(store, provider), store, provider


def test_claim_precedes_io_and_confirmed_replay_needs_no_provider():
    service, store, provider = fixture()
    first = asyncio.run(service.cleanup(QUERY))
    second = asyncio.run(service.cleanup(QUERY))
    assert first == second == store.saved
    assert first.observation.status is AnnualProviderStatus.CONFIRMED
    assert len(provider.executions) == 1 and provider.reads == []


def test_concurrent_requests_recover_the_same_immutable_stop_intent():
    async def run():
        service, store, provider = fixture()
        results = await asyncio.gather(service.cleanup(QUERY), service.cleanup(QUERY))
        assert results[0] == results[1] == store.saved
        assert len({item.operation_id for item in provider.executions}) == 1
    asyncio.run(run())


def test_lost_claim_response_recovers_unexecuted_original_operation():
    service, store, provider = fixture()
    store.lose_claim = True
    with pytest.raises(BillingError):
        asyncio.run(service.cleanup(QUERY))
    original = store.saved.intent
    assert provider.executions == []
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == provider.executions == [original]


def test_lost_provider_response_reconciles_without_another_execution():
    service, store, provider = fixture()
    provider.lose_response = True
    first = asyncio.run(service.cleanup(QUERY))
    assert first.observation.status is AnnualProviderStatus.UNKNOWN
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == provider.executions == [first.intent]


def test_lost_settlement_response_replays_the_committed_confirmation():
    service, store, provider = fixture()
    store.lose_settlement = True
    with pytest.raises(BillingError):
        asyncio.run(service.cleanup(QUERY))
    store.lose_settlement = False
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation.status is AnnualProviderStatus.CONFIRMED
    assert len(provider.executions) == 1 and provider.reads == []


def test_unresolved_original_purchase_defers_without_intent_or_provider_io():
    service, store, provider = fixture()
    store.ready = False
    assert asyncio.run(service.cleanup(QUERY)) is None
    assert store.saved is None and not provider.executions and not provider.reads


@pytest.mark.parametrize("mode", ["owner", "actor", "company", "purchase"])
def test_unauthorized_query_never_calls_provider(mode):
    service, store, provider = fixture()
    query = QUERY
    if mode == "owner":
        store.authorized = False
    elif mode == "actor":
        query = replace(query, actor_id=ActorId(ActorKind.USER, UserId(str(uuid4()))))
    elif mode == "company":
        query = replace(query, company_id=CompanyId(str(uuid4())))
    else:
        query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    with pytest.raises(BillingError):
        asyncio.run(service.cleanup(query))
    assert store.saved is None and not provider.executions


@pytest.mark.parametrize("field,value", [("production_enabled", True), ("account_reference", "other"), ("provider", "other")])
def test_wrong_provider_never_executes_stored_intent(field, value):
    service, store, provider = fixture()
    setattr(provider, field, value)
    with pytest.raises(BillingError):
        asyncio.run(service.cleanup(QUERY))
    assert provider.executions == provider.reads == []


@pytest.mark.parametrize("changes", [
    {"agreement_reference": "other"}, {"charge_reference": "other"}, {"provider": "other"},
    {"operation": AnnualProviderOperation.CHECKOUT}, {"amount_minor": 1},
    {"captured_minor": 149000}, {"refunded_minor": 1}, {"captured_minor": False},
    {"captured_at": NOW}, {"checkout_url": "https://talli.example/other"},
    {"status": AnnualProviderStatus.FAILED}, {"status": "confirmed"},
])
def test_malformed_evidence_never_confirms_cleanup(changes):
    service, store, provider = fixture()
    provider.malformed = changes
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation == observation(result, AnnualProviderStatus.UNKNOWN)


def test_unknown_reconciliation_does_not_repeat_modification():
    service, store, provider = fixture()
    store.saved = candidate()
    provider.unknown_read = True
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation.status is AnnualProviderStatus.UNKNOWN
    assert provider.executions == [] and provider.reads == [store.saved.intent]


def test_malformed_pending_read_cannot_trigger_modification():
    service, store, provider = fixture()
    store.saved = candidate()
    provider.malformed = {"agreement_reference": "wrong"}
    result = asyncio.run(service.cleanup(QUERY))
    assert result.observation.status is AnnualProviderStatus.UNKNOWN
    assert provider.executions == []


def test_late_unknown_observation_cannot_overwrite_confirmed_cleanup():
    cleanup = candidate()
    confirmed = settle_annual_agreement_cleanup(cleanup, observation(cleanup))
    assert settle_annual_agreement_cleanup(confirmed, observation(cleanup, AnnualProviderStatus.UNKNOWN)) == confirmed


@pytest.mark.parametrize("mode", ["company", "purchase", "operation"])
def test_misbound_stored_cleanup_never_reaches_provider(mode):
    service, store, provider = fixture()
    store.saved = candidate()
    if mode == "company":
        store.saved = replace(store.saved, intent=replace(store.saved.intent, company_id=CompanyId(str(uuid4()))))
    elif mode == "purchase":
        store.saved = replace(store.saved, purchase_id=AnnualPurchaseId(str(uuid4())))
    else:
        store.saved = replace(store.saved, intent=replace(store.saved.intent, operation=AnnualProviderOperation.CANCEL_CHARGE))
    with pytest.raises(BillingError):
        asyncio.run(service.cleanup(QUERY))
    assert provider.executions == provider.reads == []
