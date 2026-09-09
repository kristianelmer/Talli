"""Support observes an original STOP without claiming or executing anything."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_annual_cleanup_service import ACTOR, COMPANY, PURCHASE, candidate, observation
from talli_backend.modules.billing.public import (
    AnnualProviderOperation, AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId,
    AnnualSupportCaseId, AnnualSupportCleanupRecoveryQuery, BillingError,
    annual_support_cleanup_recovery_operations, settle_annual_agreement_cleanup,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

OPERATOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
CASE = AnnualSupportCaseId(str(uuid4()))
QUERY = AnnualSupportCleanupRecoveryQuery(COMPANY, PURCHASE, CASE, OPERATOR)


class SupportStore:
    actor_id = OPERATOR

    def __init__(self):
        self.saved = candidate()
        self.authorized = self.fresh = True
        self.support_case_id = CASE
        self.loads = []
        self.settlements = []
        self.lose_response = False

    def authorize(self, query):
        if not self.authorized or query.support_case_id != self.support_case_id:
            raise BillingError.forbidden()
        if not self.fresh:
            raise BillingError.step_up_required()
        if query.company_id != COMPANY or query.purchase_id != PURCHASE or self.saved is None:
            raise BillingError.not_found()

    async def load_cleanup_recovery(self, query):
        self.loads.append(query)
        self.authorize(query)
        return self.saved

    async def settle_cleanup_recovery(self, query, cleanup, value):
        self.settlements.append(query)
        self.authorize(query)
        assert replace(cleanup, observation=None) == replace(self.saved, observation=None)
        self.saved = settle_annual_agreement_cleanup(self.saved, value)
        if self.lose_response:
            raise BillingError.unavailable()
        return self.saved


class Reconciler:
    provider = 'vipps-mt'
    account_reference = '123456'
    production_enabled = False

    def __init__(self, store):
        self.store = store
        self.reads = []
        self.status = AnnualProviderStatus.CONFIRMED

    async def execute(self, intent):
        raise AssertionError('Support recovery must never execute')

    async def reconcile(self, intent):
        self.reads.append(intent)
        return observation(self.store.saved, self.status)


def fixture(provider_enabled=True):
    store = SupportStore()
    provider = Reconciler(store)
    return annual_support_cleanup_recovery_operations(store, provider if provider_enabled else None), store, provider


@pytest.mark.parametrize('receipt', ['cancellation', 'refund'])
def test_recovery_preserves_the_original_stop_and_receipt(receipt):
    service, store, provider = fixture()
    if receipt == 'refund':
        store.saved = replace(store.saved, cancellation_id=None, refund_request_id=AnnualRefundRequestId(str(uuid4())))
    original = store.saved
    result = asyncio.run(service.recover_cleanup(QUERY))
    assert replace(result, observation=None) == original
    assert provider.reads == [original.intent]
    assert store.loads == store.settlements == [QUERY]
    assert result.observation.status is AnnualProviderStatus.CONFIRMED


@pytest.mark.parametrize('status', [AnnualProviderStatus.PENDING, AnnualProviderStatus.UNKNOWN])
def test_active_or_unknown_agreement_is_not_stopped_by_recovery(status):
    service, store, provider = fixture()
    provider.status = status
    result = asyncio.run(service.recover_cleanup(QUERY))
    assert result.observation.status is status
    assert provider.reads == [store.saved.intent]


def test_confirmed_replay_needs_current_case_but_no_provider():
    service, store, provider = fixture(False)
    store.saved = settle_annual_agreement_cleanup(store.saved, observation(store.saved))
    assert asyncio.run(service.recover_cleanup(QUERY)) == store.saved
    assert not provider.reads and not store.settlements
    store.authorized = False
    with pytest.raises(BillingError):
        asyncio.run(service.recover_cleanup(QUERY))


@pytest.mark.parametrize('mode', ['actor', 'case', 'admin', 'mfa', 'company', 'purchase', 'missing'])
def test_denial_and_missing_stop_never_reach_provider(mode):
    service, store, provider = fixture()
    query = QUERY
    if mode == 'actor': query = replace(query, actor_id=ACTOR)
    elif mode == 'case': query = replace(query, support_case_id=AnnualSupportCaseId(str(uuid4())))
    elif mode == 'admin': store.authorized = False
    elif mode == 'mfa': store.fresh = False
    elif mode == 'company': query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode == 'purchase': query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    else: store.saved = None
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert not provider.reads and not store.settlements


@pytest.mark.parametrize('mode', ['company', 'purchase', 'operation', 'observation'])
def test_misbound_stored_operation_cannot_reach_provider(mode):
    service, store, provider = fixture()
    if mode == 'company': store.saved = replace(store.saved, intent=replace(store.saved.intent, company_id=CompanyId(str(uuid4()))))
    elif mode == 'purchase': store.saved = replace(store.saved, purchase_id=AnnualPurchaseId(str(uuid4())))
    elif mode == 'operation': store.saved = replace(store.saved, intent=replace(store.saved.intent, operation=AnnualProviderOperation.CANCEL_CHARGE))
    else: store.saved = replace(store.saved, observation=observation(store.saved, amount_minor=1))
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(QUERY))
    assert not provider.reads


@pytest.mark.parametrize('mode', ['admin', 'mfa', 'case'])
def test_authority_loss_during_get_cannot_settle_under_owner_authority(mode):
    service, store, provider = fixture()
    original = store.saved
    async def revoked(intent):
        if mode == 'admin': store.authorized = False
        elif mode == 'mfa': store.fresh = False
        else: store.support_case_id = AnnualSupportCaseId(str(uuid4()))
        return observation(original)
    provider.reconcile = revoked
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(QUERY))
    assert store.saved == original


@pytest.mark.parametrize('mode', ['missing', 'production', 'account', 'provider'])
def test_provider_enablement_and_identity_fail_closed(mode):
    service, store, provider = fixture(mode != 'missing')
    if mode == 'production': provider.production_enabled = True
    elif mode == 'account': provider.account_reference = 'other'
    elif mode == 'provider': provider.provider = 'other'
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(QUERY))
    assert not provider.reads and not store.settlements


@pytest.mark.parametrize('mode', ['timeout', 'wrong-reference', 'money'])
def test_failed_or_malformed_get_remains_unknown(mode):
    service, store, provider = fixture()
    async def bad(intent):
        if mode == 'timeout': raise TimeoutError('private provider diagnostic')
        return observation(store.saved, **({'agreement_reference': 'foreign'} if mode == 'wrong-reference' else {'captured_minor': 1}))
    provider.reconcile = bad
    assert asyncio.run(service.recover_cleanup(QUERY)).observation.status is AnnualProviderStatus.UNKNOWN


def test_lost_settlement_response_replays_terminal_original():
    service, store, provider = fixture()
    original = store.saved
    store.lose_response = True
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(QUERY))
    store.lose_response = False
    assert asyncio.run(service.recover_cleanup(QUERY)).observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == [original.intent]


def test_settlement_response_cannot_replace_original_receipt():
    service, store, provider = fixture()
    settle = store.settle_cleanup_recovery
    async def changed(query, cleanup, value):
        return replace(await settle(query, cleanup, value), cancellation_id=candidate().cancellation_id)
    store.settle_cleanup_recovery = changed
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(QUERY))
