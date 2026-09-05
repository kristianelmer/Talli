"""Synthetic orchestration evidence only; no database/source-authority proof."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from talli_backend.modules.billing.annual_refund import AnnualRefundService
from talli_backend.modules.billing.public import (
    AnnualProviderIntent, AnnualProviderObservation, AnnualProviderOperation,
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundCaseId, AnnualRefundClaim,
    AnnualRefundFacts, AnnualRefundOperation, AnnualRefundReason, AnnualRefundResolution,
    BillingError, BillingPaymentEventId, RequestAnnualRefundCommand,
    annual_refund_decision, settle_annual_refund,
)
from talli_backend.shared.kernel import (
    ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, Timestamp, UserId,
)

ACTOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
COMPANY = CompanyId(str(uuid4()))
PURCHASE = AnnualPurchaseId(str(uuid4()))
NOW = Timestamp(datetime(2026, 9, 5, 12, tzinfo=UTC))
BOUGHT = Timestamp(NOW.value - timedelta(days=60))
COMMAND = RequestAnnualRefundCommand(
    company_id=COMPANY, actor_id=ACTOR, correlation_id=CorrelationId('refund-fixture'),
    idempotency_key=IdempotencyKey('refund-fixture-000001'), purchase_id=PURCHASE,
    source_reference='incident-fixture',
)


def candidate(*, refunded=0, captured=149000, reason=AnnualRefundReason.TALLI_DELIVERY_FAILURE):
    facts = AnnualRefundFacts(
        reason=reason, purchased_at=BOUGHT, first_purchased_at=BOUGHT,
        accepted_at=BOUGHT, discovered_at=NOW, condition_effective_at=NOW,
        blocked_at=NOW, income_year=IncomeYear(2026), gross_minor=149000,
        refunded_minor=refunded, production_submission_at=BOUGHT,
        evidence_reference=COMMAND.source_reference,
    )
    decision = annual_refund_decision(facts)
    operation = None if not decision.amount_due_minor else AnnualRefundOperation(
        purchase_id=PURCHASE, captured_minor=captured,
        provider='vipps-mt', provider_account='fixture',
        previous_refunded_minor=refunded, captured_at=BOUGHT,
        intent=AnnualProviderIntent(
            operation_id=BillingPaymentEventId(str(uuid4())), company_id=COMPANY,
            income_year=facts.income_year, operation=AnnualProviderOperation.REFUND,
            amount_minor=min(captured, decision.total_entitlement_minor) - refunded, created_at=NOW,
            agreement_external_reference='fixture', charge_reference='charge-fixture',
            return_url='https://talli.example/return', management_url='https://talli.example/billing',
            agreement_reference='agreement-fixture',
        ),
    )
    return AnnualRefundResolution(AnnualRefundCaseId(str(uuid4())), COMMAND, 'a' * 64,
                                  facts, decision, operation)


def observation(resolution, status=AnnualProviderStatus.CONFIRMED, **changes):
    operation = resolution.operation
    intent = operation.intent
    return replace(AnnualProviderObservation(
        provider=operation.provider, operation=AnnualProviderOperation.REFUND, status=status,
        agreement_reference=intent.agreement_reference, charge_reference=intent.charge_reference,
        amount_minor=intent.amount_minor, captured_minor=operation.captured_minor,
        refunded_minor=(operation.previous_refunded_minor + intent.amount_minor
                        if status is AnnualProviderStatus.CONFIRMED else operation.previous_refunded_minor),
        captured_at=operation.captured_at,
    ), **changes)


class Store:
    actor_id = ACTOR

    def __init__(self):
        self.saved = None
        self.authorized = True
        self.source_available = True
        self.lose_claim = self.lose_settlement = False
        self.lock = asyncio.Lock()
        self.renewal_stopped = False
        self.claim_new_override = None

    async def claim_refund(self, command):
        if not self.authorized or command.company_id != COMPANY or command.purchase_id != PURCHASE:
            raise BillingError.forbidden()
        async with self.lock:
            new = self.saved is None
            if new:
                if not self.source_available:
                    raise BillingError.unavailable()
                self.saved = candidate()
                self.renewal_stopped = True
                if self.lose_claim:
                    raise BillingError.unavailable()
            return AnnualRefundClaim(self.saved, new if self.claim_new_override is None else self.claim_new_override)

    async def settle_refund(self, resolution, result):
        if not self.authorized:
            raise BillingError.forbidden()
        async with self.lock:
            assert resolution.operation.intent == self.saved.operation.intent
            self.saved = settle_annual_refund(self.saved, result, NOW)
            if self.lose_settlement:
                raise BillingError.unavailable()
            return self.saved


class Provider:
    provider = 'vipps-mt'
    account_reference = 'fixture'
    production_enabled = False

    def __init__(self, store):
        self.store = store
        self.executions = []
        self.reads = []
        self.refunded = False
        self.lose_response = False
        self.malformed = {}
        self.revoke_after_execution = False

    async def execute(self, intent):
        assert self.store.saved.operation.intent == intent and self.store.renewal_stopped
        self.executions.append(intent)
        self.refunded = True
        if self.revoke_after_execution:
            self.store.authorized = False
        if self.lose_response:
            raise TimeoutError('synthetic provider timeout')
        return observation(self.store.saved, **self.malformed)

    async def reconcile(self, intent):
        self.reads.append(intent)
        return observation(self.store.saved, AnnualProviderStatus.CONFIRMED if self.refunded
                           else AnnualProviderStatus.UNKNOWN, **self.malformed)


def fixture():
    store = Store()
    provider = Provider(store)
    return AnnualRefundService(store, provider, now=lambda: NOW.value), store, provider


def test_records_liability_and_renewal_stop_before_execution_and_replays_without_provider():
    service, store, provider = fixture()
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.decision.amount_due_minor == 149000
    assert result.decision.initiate_by.isoformat() == '2026-09-11'
    assert result.decision.export_available and store.renewal_stopped
    replay = AnnualRefundService(store, None, now=lambda: NOW.value)
    assert asyncio.run(replay.request_refund(replace(COMMAND, correlation_id=CorrelationId('retry')))) == result
    assert len(provider.executions) == 1 and not provider.reads


@pytest.mark.parametrize('mode', ['missing', 'account', 'provider', 'production'])
def test_disabled_provider_retains_liability_and_stop(mode):
    service, store, provider = fixture()
    if mode == 'missing':
        service = AnnualRefundService(store, None, now=lambda: NOW.value)
    elif mode == 'account':
        provider.account_reference = 'other'
    elif mode == 'provider':
        provider.provider = 'other'
    else:
        provider.production_enabled = True
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(COMMAND))
    assert store.saved.decision.amount_due_minor == 149000 and store.renewal_stopped
    assert provider.executions == provider.reads == []


@pytest.mark.parametrize('mode', ['actor', 'owner', 'company', 'purchase', 'source'])
def test_no_authority_fails_before_claim_or_provider(mode):
    service, store, provider = fixture()
    command = COMMAND
    if mode == 'actor':
        command = replace(command, actor_id=ActorId(ActorKind.USER, UserId(str(uuid4()))))
    elif mode == 'owner':
        store.authorized = False
    elif mode == 'company':
        command = replace(command, company_id=CompanyId(str(uuid4())))
    elif mode == 'purchase':
        command = replace(command, purchase_id=AnnualPurchaseId(str(uuid4())))
    else:
        store.source_available = False
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(command))
    assert store.saved is None and not provider.executions and not provider.reads


def test_revoked_owner_cannot_replay_even_terminal_result():
    service, store, provider = fixture()
    asyncio.run(service.request_refund(COMMAND))
    store.authorized = False
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(COMMAND))
    assert len(provider.executions) == 1 and not provider.reads


@pytest.mark.parametrize('loss', ['claim', 'provider', 'settlement', 'authorization'])
def test_ambiguous_effect_recovers_original_identity_without_another_execution(loss):
    service, store, provider = fixture()
    store.lose_claim = loss == 'claim'
    store.lose_settlement = loss == 'settlement'
    provider.lose_response = loss == 'provider'
    provider.revoke_after_execution = loss == 'authorization'
    if loss == 'provider':
        first = asyncio.run(service.request_refund(COMMAND))
        assert first.operation.observation.status is AnnualProviderStatus.UNKNOWN
    else:
        with pytest.raises(BillingError):
            asyncio.run(service.request_refund(COMMAND))
    original = store.saved.operation.intent
    store.lose_claim = store.lose_settlement = False
    store.authorized = True
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.operation.intent == original
    assert result.operation.observation.status is (AnnualProviderStatus.UNKNOWN if loss == 'claim' else AnnualProviderStatus.CONFIRMED)
    assert len(provider.executions) == (0 if loss == 'claim' else 1)
    assert all(intent == original for intent in provider.executions + provider.reads)


def test_concurrent_requests_execute_only_once():
    async def run():
        service, store, provider = fixture()
        results = await asyncio.gather(*(service.request_refund(COMMAND) for _ in range(8)))
        assert all(result == store.saved for result in results)
        assert len(provider.executions) == 1
    asyncio.run(run())


@pytest.mark.parametrize('reason', [AnnualRefundReason.TALLI_DELIVERY_FAILURE, AnnualRefundReason.CUSTOMER_UNRESOLVED])
def test_no_operation_preserves_case_without_claiming_provider_settlement(reason):
    service, store, provider = fixture()
    store.saved = replace(candidate(reason=reason), operation=None)
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.operation is None and result.decision.cancel_renewal and result.decision.export_available
    assert not provider.executions and not provider.reads


@pytest.mark.parametrize('changes', [
    {'provider': 'other'}, {'operation': AnnualProviderOperation.CHECKOUT}, {'status': 'confirmed'},
    {'agreement_reference': 'other'}, {'charge_reference': 'other'}, {'amount_minor': 1},
    {'amount_minor': True}, {'captured_minor': 149000.5}, {'refunded_minor': True},
    {'captured_minor': 148999}, {'refunded_minor': 148999}, {'refunded_minor': 149001},
    {'captured_at': NOW}, {'checkout_url': 'https://talli.example/checkout'},
    {'status': AnnualProviderStatus.FAILED, 'refunded_minor': 149000},
])
def test_malformed_provider_result_never_confirms_or_discards_liability(changes):
    service, store, provider = fixture()
    provider.malformed = changes
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.operation.observation.status is AnnualProviderStatus.UNKNOWN
    assert result.operation.observation.refunded_minor == 0
    assert result.decision.amount_due_minor == 149000


def test_partial_prior_refund_requires_the_original_remainder():
    service, store, provider = fixture()
    store.saved = candidate(refunded=30000)
    provider.refunded = True
    result = asyncio.run(service.request_refund(COMMAND))
    assert provider.reads[0].amount_minor == 119000 and not provider.executions
    assert result.operation.observation.refunded_minor == 149000


def test_late_or_regressing_observations_preserve_confirmed_or_larger_totals():
    resolution = candidate()
    pending = settle_annual_refund(resolution, observation(resolution, AnnualProviderStatus.UNKNOWN, refunded_minor=10000), NOW)
    assert settle_annual_refund(pending, observation(resolution, AnnualProviderStatus.UNKNOWN), NOW) == pending
    confirmed = settle_annual_refund(pending, observation(resolution), NOW)
    assert settle_annual_refund(confirmed, observation(resolution, AnnualProviderStatus.UNKNOWN), NOW) == confirmed


@pytest.mark.parametrize('mode', ['digest', 'evidence', 'decision', 'future', 'company', 'year', 'capture', 'prior', 'amount', 'new_observation'])
def test_misbound_claim_never_reaches_provider(mode):
    service, store, provider = fixture()
    resolution = candidate()
    if mode == 'digest':
        resolution = replace(resolution, source_digest='x' * 64)
    elif mode == 'evidence':
        resolution = replace(resolution, facts=replace(resolution.facts, evidence_reference='other'))
    elif mode == 'decision':
        resolution = replace(resolution, decision=replace(resolution.decision, amount_due_minor=1))
    elif mode == 'future':
        future = Timestamp(NOW.value + timedelta(days=1))
        facts = replace(resolution.facts, discovered_at=future)
        resolution = replace(resolution, facts=facts, decision=annual_refund_decision(facts), operation=None)
    else:
        operation = resolution.operation
        if mode == 'company':
            operation = replace(operation, intent=replace(operation.intent, company_id=CompanyId(str(uuid4()))))
        elif mode == 'year':
            operation = replace(operation, intent=replace(operation.intent, income_year=IncomeYear(2025)))
        elif mode == 'capture':
            operation = replace(operation, captured_at=NOW)
        elif mode == 'prior':
            operation = replace(operation, previous_refunded_minor=True)
        elif mode == 'amount':
            operation = replace(operation, intent=replace(operation.intent, amount_minor=1))
        else:
            operation = replace(operation, observation=observation(resolution, AnnualProviderStatus.UNKNOWN))
            store.claim_new_override = True
        resolution = replace(resolution, operation=operation)
    store.saved = resolution
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(COMMAND))
    assert not provider.executions and not provider.reads


def test_changed_source_on_same_key_is_rejected():
    service, store, provider = fixture()
    store.saved = candidate()
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(replace(COMMAND, source_reference='other')))
    assert not provider.executions and not provider.reads


def test_failed_original_is_terminal_but_liability_remains():
    service, store, provider = fixture()
    provider.malformed = {'status': AnnualProviderStatus.FAILED}
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.operation.observation.status is AnnualProviderStatus.FAILED
    assert result.decision.amount_due_minor == 149000
    service = AnnualRefundService(store, None, now=lambda: NOW.value)
    assert asyncio.run(service.request_refund(COMMAND)) == result
    assert settle_annual_refund(result, observation(result), NOW) == result
    assert len(provider.executions) == 1 and not provider.reads


def test_partial_capture_refunds_only_the_debit_preserving_original_charge():
    service, store, provider = fixture()
    store.saved = candidate(captured=50000, refunded=10000)
    provider.refunded = True
    result = asyncio.run(service.request_refund(COMMAND))
    assert result.operation.intent.original_charge_minor == 149000
    assert result.operation.intent.amount_minor == 40000
    assert result.operation.observation.captured_minor == 50000
    assert result.operation.observation.refunded_minor == 50000
    assert result.facts.gross_minor == 149000


def test_operation_for_another_purchase_never_reaches_provider():
    service, store, provider = fixture()
    resolution = candidate()
    store.saved = replace(resolution, operation=replace(resolution.operation, purchase_id=AnnualPurchaseId(str(uuid4()))))
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(COMMAND))
    assert not provider.executions and not provider.reads


@pytest.mark.parametrize('changes', [{'status': 'confirmed'}, {'refunded_minor': 1}, {'captured_at': NOW}])
def test_malformed_stored_terminal_result_is_not_success(changes):
    service, store, provider = fixture()
    resolution = candidate()
    store.saved = replace(resolution, operation=replace(resolution.operation, observation=observation(resolution, **changes)))
    with pytest.raises(BillingError):
        asyncio.run(service.request_refund(COMMAND))
    with pytest.raises(BillingError):
        settle_annual_refund(store.saved, observation(resolution), NOW)
    assert not provider.executions and not provider.reads
