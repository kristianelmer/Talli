"""The bounded worker observes exactly one existing intent and never executes."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from test_annual_checkout_service import fixture, command, eligible, NOW
from talli_backend.modules.billing.public import (
    AnnualCheckoutObservationBinding, AnnualCheckoutObservationLease,
    AnnualProviderObservation, AnnualProviderOperation, AnnualProviderStatus,
    AnnualPurchaseStatus, AnnualPurchaseId, BillingPaymentEventId, BillingError,
    annual_checkout_observation_operations, settle_annual_checkout,
    validate_annual_checkout_observation,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp, UserId


@pytest.fixture
def checkout():
    service, _, _ = fixture()
    result = asyncio.run(service.start_checkout(command(), eligible))
    return replace(result, status=AnnualPurchaseStatus.PENDING, observation=None)


class Store:
    provider = 'vipps-mt'
    provider_account = '123456'
    def __init__(self, checkout):
        self.checkout = checkout
        self.lease = AnnualCheckoutObservationLease(checkout, str(uuid4()), 1)
        self.calls = []
        self.authorized = True
    async def claim_checkout_observation(self):
        self.calls.append('claim')
        return self.lease
    async def authorize_checkout_observation(self, lease):
        self.calls.append('authorize')
        assert lease == self.lease
        if not self.authorized:
            raise BillingError.unavailable()
    async def settle_checkout_observation(self, lease, observation):
        self.calls.append(('settle', observation))
        if not self.authorized:
            raise BillingError.unavailable()
        if observation is not None:
            self.checkout = settle_annual_checkout(self.checkout, observation, Timestamp(NOW))
        return self.checkout


class Provider:
    provider = 'vipps-mt'
    account_reference = '123456'
    production_enabled = False
    def __init__(self, checkout):
        self.calls = []
        self.observation = AnnualProviderObservation('vipps-mt', AnnualProviderOperation.CHECKOUT,
            AnnualProviderStatus.CONFIRMED, 'agreement', checkout.intent.charge_reference,
            149000, captured_minor=149000, captured_at=Timestamp(NOW))
    async def execute(self, intent):
        raise AssertionError('No checkout or refund execution is allowed')
    async def reconcile(self, intent):
        self.calls.append(intent)
        return self.observation


def test_one_pass_only_observes_original_unbound_checkout(checkout):
    store, provider = Store(checkout), Provider(checkout)
    assert checkout.intent.agreement_reference is None
    assert asyncio.run(annual_checkout_observation_operations(store, provider).run_once()).value == 'reconciled'
    assert provider.calls == [checkout.intent]
    assert store.calls == ['claim', 'authorize', ('settle', provider.observation)]


def test_bound_agreement_is_reused_without_replacing_original_intent(checkout):
    store, provider = Store(checkout), Provider(checkout)
    old = replace(provider.observation, status=AnnualProviderStatus.PENDING, captured_minor=0, captured_at=None)
    store.checkout = replace(checkout, observation=old)
    store.lease = replace(store.lease, checkout=store.checkout)
    asyncio.run(annual_checkout_observation_operations(store, provider).run_once())
    assert provider.calls == [replace(checkout.intent, agreement_reference='agreement')]
    assert store.lease.checkout.intent == checkout.intent


@pytest.mark.parametrize('disabled', ['none','production','account','provider'])
def test_disabled_or_mismatched_runtime_never_claims(checkout, disabled):
    store, provider = Store(checkout), Provider(checkout)
    if disabled == 'none': provider = None
    elif disabled == 'production': provider.production_enabled = True
    elif disabled == 'account': provider.account_reference = 'other'
    else: provider.provider = 'other'
    with pytest.raises(BillingError):
        asyncio.run(annual_checkout_observation_operations(store, provider).run_once())
    assert store.calls == []


def test_idle_pass_has_no_provider_or_settlement_calls(checkout):
    store, provider = Store(checkout), Provider(checkout)
    store.lease = None
    assert asyncio.run(annual_checkout_observation_operations(store, provider).run_once()).value == 'idle'
    assert provider.calls == [] and store.calls == ['claim']


def test_revoked_lease_never_calls_provider(checkout):
    store, provider = Store(checkout), Provider(checkout)
    store.authorized = False
    with pytest.raises(BillingError):
        asyncio.run(annual_checkout_observation_operations(store, provider).run_once())
    assert provider.calls == [] and store.calls == ['claim', 'authorize']


@pytest.mark.parametrize('failure', ['exception','amount','reference','operation','capture'])
def test_bad_provider_result_only_schedules_technical_retry(checkout, failure):
    store, provider = Store(checkout), Provider(checkout)
    if failure == 'exception':
        async def failed(intent): raise TimeoutError('read failed')
        provider.reconcile = failed
    else:
        changes = {'amount': {'amount_minor': 1}, 'reference': {'charge_reference': 'other'},
                   'operation': {'operation': AnnualProviderOperation.REFUND},
                   'capture': {'captured_minor': 1}}[failure]
        provider.observation = replace(provider.observation, **changes)
    assert asyncio.run(annual_checkout_observation_operations(store, provider).run_once()).value == 'retry'
    assert store.checkout == checkout and store.calls[-1] == ('settle', None)


def binding(checkout):
    return AnnualCheckoutObservationBinding(checkout.purchase_id, checkout.intent.operation_id,
        checkout.offer.company_id, checkout.offer.income_year, checkout.accepted_by,
        checkout.intent.created_at, checkout.intent.created_at, checkout.offer.gross_minor,
        checkout.intent.agreement_external_reference, checkout.intent.charge_reference,
        checkout.intent.recurring_consent, checkout.offer.offer_version)


def test_exact_original_billing_binding_is_accepted(checkout):
    validate_annual_checkout_observation(checkout, binding(checkout))


@pytest.mark.parametrize('field,value', [
    ('purchase_id',AnnualPurchaseId(str(uuid4()))), ('operation_id',BillingPaymentEventId(str(uuid4()))),
    ('company_id',CompanyId(str(uuid4()))), ('income_year',IncomeYear(2025)),
    ('created_by',UserId(str(uuid4()))), ('accepted_at',Timestamp(NOW-timedelta(seconds=1))),
    ('created_at',Timestamp(NOW-timedelta(seconds=1))), ('amount_minor',1),
    ('agreement_external_reference','other'), ('charge_reference','other'),
    ('recurring_consent',True), ('consent_version','other'),
])
def test_changed_original_binding_is_rejected(checkout, field, value):
    with pytest.raises(BillingError):
        validate_annual_checkout_observation(checkout, replace(binding(checkout), **{field:value}))
