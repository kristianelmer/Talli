"""Support recovery preserves the stored requester; all fixtures remain synthetic."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_annual_refund_recovery_service import ACTOR, COMPANY, PURCHASE, REQUEST, RecoveryStore, Reconciler
from test_annual_refund_service import NOW, observation
from talli_backend.modules.billing.annual_refund import AnnualSupportRefundRecoveryService
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId, AnnualSupportCaseId,
    AnnualSupportRefundRecoveryQuery, BillingError, settle_annual_refund,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

OPERATOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
CASE = AnnualSupportCaseId(str(uuid4()))
QUERY = AnnualSupportRefundRecoveryQuery(COMPANY, PURCHASE, REQUEST, CASE, OPERATOR)


class SupportStore(RecoveryStore):
    actor_id = OPERATOR

    def __init__(self):
        super().__init__()
        self.support_case_id = CASE
        self.queries = []
        self.settlement_queries = []

    def authorize_query(self, query):
        self.authorize()
        if query.support_case_id != self.support_case_id:
            raise BillingError.forbidden()

    async def load_refund_recovery(self, query):
        self.queries.append(query)
        self.authorize_query(query)
        return await super().load_refund_recovery(query)

    async def settle_refund_recovery(self, query, recovery, result):
        self.settlement_queries.append(query)
        self.authorize_query(query)
        return await super().settle_refund_recovery(recovery, result)


def fixture(provider_enabled=True):
    store = SupportStore()
    provider = Reconciler(store)
    service = AnnualSupportRefundRecoveryService(store, provider if provider_enabled else None, now=lambda: NOW.value)
    return service, store, provider


def test_operator_recovers_owner_created_request_with_original_intent_and_current_case_at_settlement():
    service, store, provider = fixture()
    original = store.saved
    assert original.resolution.request.actor_id == ACTOR != OPERATOR
    result = asyncio.run(service.recover_refund(QUERY))
    assert provider.reads == [original.resolution.operation.intent]
    assert result.resolution.request == original.resolution.request
    assert result.resolution.operation.intent == original.resolution.operation.intent
    assert result.resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED
    assert store.queries == store.settlement_queries == [QUERY]
    assert store.settlement_queries[0].actor_id != result.resolution.request.actor_id


@pytest.mark.parametrize('status', [AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED])
def test_authorized_terminal_support_replay_needs_no_provider(status):
    service, store, provider = fixture(False)
    store.saved = replace(store.saved, resolution=settle_annual_refund(
        store.saved.resolution, observation(store.saved.resolution, status), NOW,
    ))
    assert asyncio.run(service.recover_refund(QUERY)) == store.saved
    assert store.settlement_queries == [] and provider.reads == []
    store.authorized = False
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))


@pytest.mark.parametrize('mode', ['actor', 'case', 'admin', 'mfa', 'company', 'purchase', 'request', 'unbound', 'digest'])
def test_bad_support_authority_or_original_binding_never_reaches_provider(mode):
    service, store, provider = fixture()
    query = QUERY
    if mode == 'actor': query = replace(query, actor_id=ACTOR)
    elif mode == 'case': query = replace(query, support_case_id=AnnualSupportCaseId(str(uuid4())))
    elif mode == 'admin': store.authorized = False
    elif mode == 'mfa': store.fresh = False
    elif mode == 'company': query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode == 'purchase': query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    elif mode == 'request': query = replace(query, refund_request_id=AnnualRefundRequestId(str(uuid4())))
    elif mode == 'unbound': store.saved = replace(store.saved, resolution=replace(store.saved.resolution, operation=None))
    else: store.saved = replace(store.saved, resolution=replace(store.saved.resolution, source_digest='invalid'))
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    assert provider.reads == [] and store.settlement_queries == []
    if mode == 'actor': assert store.queries == []


@pytest.mark.parametrize('mode', ['admin', 'mfa', 'case'])
def test_lost_case_authority_during_provider_read_cannot_settle_as_original_owner(mode):
    service, store, provider = fixture()
    original = store.saved
    read = provider.reconcile
    async def revoked(intent):
        result = await read(intent)
        if mode == 'admin': store.authorized = False
        elif mode == 'mfa': store.fresh = False
        else: store.support_case_id = AnnualSupportCaseId(str(uuid4()))
        return result
    provider.reconcile = revoked
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))
    assert store.saved == original
    assert store.settlement_queries == [QUERY]


@pytest.mark.parametrize('mode', ['requester', 'key', 'case', 'operation', 'request'])
def test_settlement_cannot_replace_any_original_envelope(mode):
    service, store, _ = fixture()
    settle = store.settle_refund_recovery
    async def replaced(query, recovery, result):
        value = await settle(query, recovery, result)
        resolution = value.resolution
        if mode == 'requester': resolution = replace(resolution, request=replace(resolution.request, actor_id=OPERATOR))
        elif mode == 'key':
            from talli_backend.shared.kernel import IdempotencyKey
            resolution = replace(resolution, request=replace(resolution.request, idempotency_key=IdempotencyKey('different-original-key')))
        elif mode == 'case':
            from talli_backend.modules.billing.public import AnnualRefundCaseId
            resolution = replace(resolution, case_id=AnnualRefundCaseId(str(uuid4())))
        elif mode == 'operation': resolution = replace(resolution, operation=None)
        else: value = replace(value, refund_request_id=AnnualRefundRequestId(str(uuid4())))
        return replace(value, resolution=resolution)
    store.settle_refund_recovery = replaced
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))


def test_lost_committed_support_response_replays_original_terminal_evidence():
    service, store, provider = fixture()
    original = store.saved
    store.lose_response = True
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))
    store.lose_response = False
    result = asyncio.run(service.recover_refund(QUERY))
    assert result.resolution.request == original.resolution.request
    assert provider.reads == [original.resolution.operation.intent]
    assert result.resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED


@pytest.mark.parametrize('mode', ['missing', 'account', 'production', 'provider'])
def test_support_recovery_never_activates_a_provider(mode):
    service, store, provider = fixture(mode != 'missing')
    if mode == 'account': provider.account_reference = 'another-account'
    elif mode == 'production': provider.production_enabled = True
    elif mode == 'provider': provider.provider = 'another-provider'
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(QUERY))
    assert provider.reads == [] and store.settlement_queries == []
