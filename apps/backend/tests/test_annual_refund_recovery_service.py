"""Recovery-only orchestration; synthetic stores are not source/provider authority."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_annual_refund_service import ACTOR, COMPANY, PURCHASE, NOW, candidate, observation
from talli_backend.modules.billing.annual_refund import AnnualRefundRecoveryService
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId, AnnualRefundRecovery,
    AnnualRefundRecoveryQuery, BillingError, settle_annual_refund,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

REQUEST = AnnualRefundRequestId(str(uuid4()))
QUERY = AnnualRefundRecoveryQuery(COMPANY, PURCHASE, REQUEST, ACTOR)


class RecoveryStore:
    actor_id = ACTOR

    def __init__(self):
        self.saved = AnnualRefundRecovery(REQUEST, candidate())
        self.authorized = self.fresh = True
        self.loads = self.settlements = 0
        self.lock = asyncio.Lock()
        self.lose_response = False

    def authorize(self):
        if not self.authorized:
            raise BillingError.forbidden()
        if not self.fresh:
            raise BillingError.step_up_required()

    async def load_refund_recovery(self, query):
        self.loads += 1
        self.authorize()
        return self.saved

    async def settle_refund_recovery(self, recovery, result):
        self.authorize()
        async with self.lock:
            self.settlements += 1
            self.saved = replace(self.saved, resolution=settle_annual_refund(self.saved.resolution, result, NOW))
            if self.lose_response:
                raise BillingError.unavailable()
            return self.saved


class Reconciler:
    provider = 'vipps-mt'
    account_reference = 'fixture'
    production_enabled = False

    def __init__(self, store):
        self.store = store
        self.reads = []
        self.status = AnnualProviderStatus.CONFIRMED
        self.changes = {}
        self.error = False
        self.revoke = self.expire_mfa = False

    async def execute(self, intent):
        pytest.fail('Recovery must never execute a refund')

    async def reconcile(self, intent):
        self.reads.append(intent)
        if self.revoke:
            self.store.authorized = False
        if self.expire_mfa:
            self.store.fresh = False
        if self.error:
            raise TimeoutError('synthetic missing observation')
        return observation(self.store.saved.resolution, self.status, **self.changes)


def fixture():
    store = RecoveryStore()
    provider = Reconciler(store)
    service = AnnualRefundRecoveryService(store, provider, now=lambda: NOW.value)
    return service, store, provider


def test_created_operation_reconciles_original_identity_without_claim_or_execution():
    service, store, provider = fixture()
    original = store.saved
    result = asyncio.run(service.recover_refund(QUERY))
    assert result.refund_request_id == REQUEST
    assert result.resolution.request == original.resolution.request
    assert result.resolution.operation.intent == original.resolution.operation.intent
    assert result.resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == [original.resolution.operation.intent]


@pytest.mark.parametrize('status', [AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED])
def test_terminal_recovery_needs_no_provider_and_never_creates_attempt(status):
    _, store, _ = fixture()
    store.saved = replace(store.saved, resolution=settle_annual_refund(
        store.saved.resolution, observation(store.saved.resolution, status), NOW,
    ))
    service = AnnualRefundRecoveryService(store, None, now=lambda: NOW.value)
    assert asyncio.run(service.recover_refund(QUERY)) == store.saved
    assert store.settlements == 0
    assert store.saved.resolution.decision.total_entitlement_minor == 149000


@pytest.mark.parametrize('mode', ['actor', 'owner', 'mfa', 'request', 'company', 'purchase', 'stored_actor', 'unbound', 'digest', 'stored_terminal'])
def test_invalid_authority_or_binding_never_reaches_provider(mode):
    service, store, provider = fixture()
    query = QUERY
    other = ActorId(ActorKind.USER, UserId(str(uuid4())))
    if mode == 'actor':
        query = replace(query, actor_id=other)
    elif mode == 'owner':
        store.authorized = False
    elif mode == 'mfa':
        store.fresh = False
    elif mode == 'request':
        query = replace(query, refund_request_id=AnnualRefundRequestId(str(uuid4())))
    elif mode == 'company':
        query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode == 'purchase':
        query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    else:
        resolution = store.saved.resolution
        if mode == 'stored_actor':
            resolution = replace(resolution, request=replace(resolution.request, actor_id=other))
        elif mode == 'unbound':
            resolution = replace(resolution, operation=None)
        elif mode == 'digest':
            resolution = replace(resolution, source_digest='invalid')
        else:
            resolution = replace(resolution, operation=replace(resolution.operation,
                observation=observation(resolution, refunded_minor=1)))
        store.saved = replace(store.saved, resolution=resolution)
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    assert provider.reads == [] and store.settlements == 0


@pytest.mark.parametrize('mode', ['missing', 'account', 'production', 'provider'])
def test_unresolved_recovery_requires_matching_nonproduction_provider(mode):
    service, store, provider = fixture()
    if mode == 'missing':
        service = AnnualRefundRecoveryService(store, None, now=lambda: NOW.value)
    elif mode == 'account':
        provider.account_reference = 'other'
    elif mode == 'production':
        provider.production_enabled = True
    else:
        provider.provider = 'other'
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))
    assert provider.reads == [] and store.settlements == 0


@pytest.mark.parametrize('mode', ['timeout', 'malformed', 'absent'])
def test_missing_or_malformed_observation_preserves_original_unknown_operation(mode):
    service, store, provider = fixture()
    original = store.saved
    if mode == 'timeout':
        provider.error = True
    elif mode == 'malformed':
        provider.changes = {'amount_minor': True}
    else:
        provider.status = AnnualProviderStatus.UNKNOWN
    result = asyncio.run(service.recover_refund(QUERY))
    assert result.resolution.operation.observation.status is AnnualProviderStatus.UNKNOWN
    assert result.resolution.operation.intent == original.resolution.operation.intent
    assert result.resolution.decision == original.resolution.decision


@pytest.mark.parametrize('mode', ['owner', 'mfa', 'lost_response'])
def test_recovery_after_authority_loss_or_committed_response_loss_preserves_identity(mode):
    service, store, provider = fixture()
    original = store.saved
    provider.revoke = mode == 'owner'
    provider.expire_mfa = mode == 'mfa'
    store.lose_response = mode == 'lost_response'
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))
    if mode != 'lost_response':
        assert store.saved == original
    store.authorized = store.fresh = True
    provider.revoke = provider.expire_mfa = store.lose_response = False
    result = asyncio.run(service.recover_refund(QUERY))
    assert result.resolution.operation.intent == original.resolution.operation.intent
    assert all(value == original.resolution.operation.intent for value in provider.reads)
    assert len(provider.reads) == (1 if mode == 'lost_response' else 2)


def test_concurrent_recovery_preserves_one_terminal_operation():
    async def run():
        service, store, provider = fixture()
        original = store.saved
        results = await asyncio.gather(*(service.recover_refund(QUERY) for _ in range(6)))
        assert all(result == store.saved for result in results)
        assert all(value == original.resolution.operation.intent for value in provider.reads)
    asyncio.run(run())


def test_confirmed_original_partial_refund_does_not_mean_all_liability_is_refunded():
    service, store, provider = fixture()
    store.saved = replace(store.saved, resolution=candidate(captured=50000))
    provider.changes = {'captured_minor': 149000}
    result = asyncio.run(service.recover_refund(QUERY))
    assert result.resolution.operation.intent.amount_minor == 50000
    assert result.resolution.operation.observation.refunded_minor == 50000
    assert result.resolution.decision.total_entitlement_minor == 149000
