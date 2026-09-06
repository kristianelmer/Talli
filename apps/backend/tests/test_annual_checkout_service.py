import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from talli_backend.modules.billing.annual_policy import annual_offer
from talli_backend.modules.billing.annual_service import AnnualCheckoutService
from talli_backend.modules.billing.public import (
    AnnualAcceptanceBasisReference, AnnualCheckoutClaim, AnnualCheckoutPrerequisites,
    AnnualCheckoutQuery, AnnualCheckoutPreparationQuery, AnnualCheckoutPurchaseReference,
    AnnualProviderObservation, AnnualProviderOperation,
    AnnualProviderStatus, AnnualPurchaseStatus, BillingError, BillingErrorCode,
    StartAnnualCheckoutCommand, annual_billing_consent_version,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, Timestamp, UserId

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
ACTOR = ActorId(ActorKind.USER, UserId('10000000-0000-4000-8000-000000000001'))
COMPANY = CompanyId('10000000-0000-4000-8000-000000000002')
YEAR = IncomeYear(2026)


def command(**changes):
    offer = annual_offer(COMPANY, YEAR)
    return replace(StartAnnualCheckoutCommand(
        company_id=COMPANY, actor_id=ACTOR, correlation_id=CorrelationId('checkout-fixture'),
        idempotency_key=IdempotencyKey('checkout-fixture-00000001'), income_year=YEAR,
        offer_version=offer.offer_version, terms_digest=offer.terms_digest,
        purchase_accepted=True, recurring_consent=False, consent_version=offer.offer_version,
    ), **changes)


async def eligible():
    return AnnualCheckoutPrerequisites(
        basis=AnnualAcceptanceBasisReference(COMPANY, YEAR, str(uuid4()), str(uuid4()), str(uuid4()), 'a'*64, 'b'*64),
        readiness_reference=str(uuid4()), readiness_digest='c'*64, evaluated_at=Timestamp(NOW), ready=True,
    )


class Store:
    actor_id = ACTOR
    def __init__(self):
        self.checkout = None
        self.lock = asyncio.Lock()
        self.lose_claim_response = False
        self.lose_settlement = False
        self.authorized = True

    async def authorize_owner_command(self, company):
        if not self.authorized or company != COMPANY:
            raise BillingError.forbidden()

    async def find_checkout(self, company, key):
        await asyncio.sleep(0)
        return self.checkout if self.checkout and self.checkout.idempotency_key == key else None

    async def find_active_checkout(self, company, year):
        await self.authorize_owner_command(company)
        checkout = self.checkout
        if (checkout and checkout.offer.company_id == company and checkout.offer.income_year == year
                and checkout.status in {AnnualPurchaseStatus.PENDING, AnnualPurchaseStatus.PAID}):
            return AnnualCheckoutPurchaseReference(company, year, checkout.purchase_id, checkout.status)
        return None

    async def verify_checkout_preparation(self, company, year, prerequisites):
        async with self.lock:
            return await self.find_active_checkout(company, year)

    async def claim_checkout(self, checkout, prerequisites):
        async with self.lock:
            if self.checkout:
                return AnnualCheckoutClaim(self.checkout, False)
            self.checkout = checkout
            if self.lose_claim_response:
                raise BillingError.unavailable()
            return AnnualCheckoutClaim(checkout, True)

    async def load_checkout(self, company, purchase):
        if not self.checkout or self.checkout.offer.company_id != company or self.checkout.purchase_id != purchase:
            raise BillingError.not_found()
        return self.checkout

    async def settle_checkout(self, checkout, observation):
        if self.lose_settlement:
            raise BillingError.unavailable()
        async with self.lock:
            if self.checkout.status in {AnnualPurchaseStatus.PAID, AnnualPurchaseStatus.FAILED, AnnualPurchaseStatus.REFUNDED}:
                return self.checkout
            current = self.checkout.observation
            if current and (observation.captured_minor < current.captured_minor
                    or observation.refunded_minor < current.refunded_minor
                    or (current.captured_at and observation.captured_at != current.captured_at)
                    or (current.agreement_reference and observation.agreement_reference != current.agreement_reference)):
                return self.checkout
            status = AnnualPurchaseStatus.PENDING
            if (observation.status is AnnualProviderStatus.CONFIRMED
                    and observation.captured_minor == observation.refunded_minor == checkout.offer.gross_minor):
                status = AnnualPurchaseStatus.REFUNDED
            elif observation.status is AnnualProviderStatus.CONFIRMED:
                status = AnnualPurchaseStatus.PAID
            elif observation.status is AnnualProviderStatus.FAILED:
                status = AnnualPurchaseStatus.FAILED
            self.checkout = replace(self.checkout, observation=observation, status=status)
            return self.checkout


class Provider:
    provider = 'vipps-mt'
    account_reference = '123456'
    production_enabled = False
    def __init__(self):
        self.executions = []
        self.reconciliations = []
        self.lose_response = False
        self.malformed = None
        self.store = None

    def observation(self, intent):
        result = AnnualProviderObservation(self.provider, AnnualProviderOperation.CHECKOUT,
            AnnualProviderStatus.CONFIRMED, 'agr_fixture', intent.charge_reference, intent.amount_minor,
            captured_minor=149000, captured_at=Timestamp(NOW))
        return replace(result, **self.malformed) if self.malformed else result

    async def execute(self, intent):
        assert self.store.checkout is not None, 'Provider effect preceded durable claim'
        self.executions.append(intent)
        await asyncio.sleep(0)
        if self.lose_response:
            raise TimeoutError('fixture lost provider response')
        return self.observation(intent)

    async def reconcile(self, intent):
        self.reconciliations.append(intent)
        if not self.executions:
            return AnnualProviderObservation(self.provider, AnnualProviderOperation.CHECKOUT,
                AnnualProviderStatus.UNKNOWN, None, intent.charge_reference, intent.amount_minor)
        return self.observation(intent)


def fixture():
    store, provider = Store(), Provider()
    provider.store = store
    service = AnnualCheckoutService(store, provider, return_url='https://talli.example/return',
        management_url='https://talli.example/billing', now=lambda: NOW)
    return service, store, provider


def test_concurrent_identical_checkout_executes_provider_once_after_commit():
    async def scenario():
        service, store, provider = fixture()
        first, second = await asyncio.gather(service.start_checkout(command(), eligible), service.start_checkout(command(), eligible))
        assert first.purchase_id == second.purchase_id
        assert len(provider.executions) == 1
        assert store.checkout.status is AnnualPurchaseStatus.PAID
    asyncio.run(scenario())


def test_lost_provider_response_recovers_original_intent_after_eligibility_expires():
    async def scenario():
        service, store, provider = fixture()
        provider.lose_response = True
        first = await service.start_checkout(command(), eligible)
        assert first.status is AnnualPurchaseStatus.PENDING
        assert first.observation.status is AnnualProviderStatus.UNKNOWN
        async def blocked():
            pytest.fail('A retry must not require new readiness or acceptance')
        second = await service.start_checkout(command(), blocked)
        assert second.status is AnnualPurchaseStatus.PAID
        assert second.intent == first.intent
        assert len(provider.executions) == len(provider.reconciliations) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['claim', 'settlement'])
def test_crash_after_claim_or_during_settlement_never_reissues_checkout(failure):
    async def scenario():
        service, store, provider = fixture()
        store.lose_claim_response = failure == 'claim'
        store.lose_settlement = failure == 'settlement'
        with pytest.raises(BillingError):
            await service.start_checkout(command(), eligible)
        original = store.checkout.intent
        store.lose_claim_response = store.lose_settlement = False
        recovered = await service.start_checkout(command(), eligible)
        assert recovered.intent == original
        assert len(provider.executions) == int(failure == 'settlement')
        assert len(provider.reconciliations) == 1
        assert recovered.status is (AnnualPurchaseStatus.PENDING if failure == 'claim' else AnnualPurchaseStatus.PAID)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'recurring_consent': True}, {'terms_digest': '0'*64},
    {'idempotency_key': IdempotencyKey('checkout-fixture-00000002')},
])
def test_changed_request_cannot_create_another_purchase(change):
    async def scenario():
        service, _, provider = fixture()
        await service.start_checkout(command(), eligible)
        with pytest.raises(BillingError):
            await service.start_checkout(command(**change), eligible)
        assert len(provider.executions) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'captured_minor': 50000}, {'amount_minor': 1}, {'charge_reference': 'wrong-charge'},
    {'provider': 'another-provider'}, {'captured_minor': True}, {'refunded_minor': 149001},
    {'captured_at': None}, {'status': AnnualProviderStatus.FAILED},
])
def test_malformed_capture_evidence_never_grants_paid_access(change):
    async def scenario():
        service, _, provider = fixture()
        provider.malformed = change
        result = await service.start_checkout(command(), eligible)
        assert result.status is AnnualPurchaseStatus.PENDING
        assert result.observation.status is AnnualProviderStatus.UNKNOWN
    asyncio.run(scenario())


def test_unready_or_unauthorized_request_makes_no_claim_or_provider_call():
    async def scenario():
        service, store, provider = fixture()
        async def blocked():
            return replace(await eligible(), ready=False)
        with pytest.raises(BillingError):
            await service.start_checkout(command(), blocked)
        assert store.checkout is None and provider.executions == []
        store.authorized = False
        with pytest.raises(BillingError):
            await service.start_checkout(command(), eligible)
        assert store.checkout is None and provider.executions == []
    asyncio.run(scenario())


def test_poll_is_read_only_and_account_changes_cannot_reconcile_another_merchant():
    async def scenario():
        service, store, provider = fixture()
        provider.lose_response = True
        first = await service.start_checkout(command(), eligible)
        query = AnnualCheckoutQuery(COMPANY, ACTOR, first.purchase_id)
        provider.account_reference = '999999'
        with pytest.raises(BillingError):
            await service.poll_checkout(query)
        assert provider.reconciliations == []
        provider.account_reference = '123456'
        assert (await service.poll_checkout(query)).status is AnnualPurchaseStatus.PAID
        assert len(provider.executions) == len(provider.reconciliations) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['stale', 'future', 'wrong_company', 'wrong_year'])
def test_stale_or_wrong_scope_readiness_cannot_claim_checkout(mode):
    from datetime import timedelta
    async def scenario():
        service, store, provider = fixture()
        async def invalid():
            facts = await eligible()
            if mode in ('stale', 'future'):
                return replace(facts, evaluated_at=Timestamp(NOW + timedelta(seconds=-301 if mode == 'stale' else 1)))
            return replace(facts, basis=replace(facts.basis, **(
                {'company_id': CompanyId(str(uuid4()))} if mode == 'wrong_company' else {'income_year': IncomeYear(2027)})))
        with pytest.raises(BillingError):
            await service.start_checkout(command(), invalid)
        assert store.checkout is None and provider.executions == []
    asyncio.run(scenario())


def test_production_prerequisite_binding_is_explicitly_unavailable():
    from talli_backend.application.annual_checkout_prerequisites import unavailable_annual_checkout_prerequisites
    async def scenario():
        service, store, provider = fixture()
        with pytest.raises(BillingError) as failure:
            await service.start_checkout(command(), unavailable_annual_checkout_prerequisites)
        assert failure.value.code is BillingErrorCode.FILING_NOT_READY
        assert store.checkout is None and provider.executions == []
    asyncio.run(scenario())


def test_capture_before_checkout_creation_cannot_grant_access():
    from datetime import timedelta
    async def scenario():
        service, _, provider = fixture()
        provider.malformed = {'captured_at': Timestamp(NOW - timedelta(days=365))}
        result = await service.start_checkout(command(), eligible)
        assert result.status is AnnualPurchaseStatus.PENDING
        assert result.observation.status is AnnualProviderStatus.UNKNOWN
    asyncio.run(scenario())


def test_refund_observed_before_first_settlement_cannot_grant_paid_access():
    async def scenario():
        service, _, provider = fixture()
        provider.malformed = {'refunded_minor': 149000}
        result = await service.start_checkout(command(), eligible)
        assert result.status is AnnualPurchaseStatus.REFUNDED
    asyncio.run(scenario())


@pytest.mark.parametrize('latest', ['failed', 'larger_capture', 'bound_reference'])
def test_stale_poll_cannot_overwrite_newer_locked_settlement(latest):
    async def scenario():
        service, store, provider = fixture()
        provider.lose_response = True
        initial = await service.start_checkout(command(), eligible)
        query = AnnualCheckoutQuery(COMPANY, ACTOR, initial.purchase_id)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def reconcile(intent):
            nonlocal calls
            calls += 1
            observation = provider.observation(intent)
            if calls == 1:
                entered.set()
                await release.wait()
                return replace(observation, status=AnnualProviderStatus.PENDING,
                    captured_minor=0, captured_at=None, agreement_reference=None)
            return replace(observation,
                status=AnnualProviderStatus.FAILED if latest == 'failed' else AnnualProviderStatus.PENDING,
                captured_minor=100000 if latest == 'larger_capture' else 0,
                captured_at=Timestamp(NOW) if latest == 'larger_capture' else None)
        provider.reconcile = reconcile
        slow = asyncio.create_task(service.poll_checkout(query))
        await entered.wait()
        newest = await service.poll_checkout(query)
        release.set()
        delayed = await slow
        assert delayed == newest == store.checkout
    asyncio.run(scenario())



def test_refunded_partial_capture_stays_unresolved_until_remaining_charge_is_final():
    async def scenario():
        service, _, provider = fixture()
        provider.malformed = {'captured_minor': 50000, 'refunded_minor': 50000,
            'status': AnnualProviderStatus.PENDING}
        result = await service.start_checkout(command(), eligible)
        assert result.status is AnnualPurchaseStatus.PENDING
    asyncio.run(scenario())


def preparation_query(**changes):
    return replace(AnnualCheckoutPreparationQuery(COMPANY, YEAR, ACTOR), **changes)


def test_preparation_returns_exact_offer_and_consent_without_ids_claims_or_provider_calls(monkeypatch):
    async def scenario():
        service, store, provider = fixture()
        def unexpected_id():
            pytest.fail('Preparation generated a purchase or operation identity')
        monkeypatch.setattr('talli_backend.modules.billing.annual_service.uuid4', unexpected_id)
        result = await service.prepare_checkout(preparation_query(), eligible)
        assert result.offer == annual_offer(COMPANY, YEAR)
        assert result.consent_version == annual_billing_consent_version()
        assert result.existing_purchase is None
        assert store.checkout is None
        assert provider.executions == provider.reconciliations == []
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [AnnualPurchaseStatus.PENDING, AnnualPurchaseStatus.PAID])
def test_preparation_returns_existing_purchase_before_unavailable_provider_or_source(status):
    async def scenario():
        service, store, provider = fixture()
        await service.start_checkout(command(), eligible)
        store.checkout = replace(store.checkout, status=status)
        stored = store.checkout
        service._provider = None
        async def unavailable():
            pytest.fail('Existing purchase preparation resolved new-sale sources')
        result = await service.prepare_checkout(preparation_query(), unavailable)
        assert result.offer is None and result.consent_version is None
        assert result.existing_purchase == AnnualCheckoutPurchaseReference(COMPANY, YEAR, stored.purchase_id, status)
        assert store.checkout == stored
        assert len(provider.executions) == 1 and provider.reconciliations == []
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [AnnualPurchaseStatus.FAILED, AnnualPurchaseStatus.REFUNDED])
def test_failed_or_refunded_purchase_does_not_enable_new_checkout_without_provider(status):
    async def scenario():
        service, store, provider = fixture()
        await service.start_checkout(command(), eligible)
        store.checkout = replace(store.checkout, status=status)
        service._provider = None
        with pytest.raises(BillingError) as error:
            await service.prepare_checkout(preparation_query(), eligible)
        assert error.value.code is BillingErrorCode.PROVIDER_DISABLED
        assert len(provider.executions) == 1 and provider.reconciliations == []
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['actor', 'owner', 'provider', 'source', 'not_ready', 'stale', 'future', 'company', 'year', 'verifier'])
def test_unavailable_preparation_never_creates_purchase_or_calls_provider(mode):
    from datetime import timedelta
    async def scenario():
        service, store, provider = fixture()
        query = preparation_query(actor_id=ActorId(ActorKind.USER, UserId(str(uuid4())))) if mode == 'actor' else preparation_query()
        if mode == 'owner':
            store.authorized = False
        if mode == 'provider':
            service._provider = None
        if mode == 'verifier':
            async def denied(*args):
                raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
            store.verify_checkout_preparation = denied
        async def source():
            if mode == 'source':
                raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
            facts = await eligible()
            if mode == 'not_ready':
                return replace(facts, ready=False)
            if mode in ('stale', 'future'):
                return replace(facts, evaluated_at=Timestamp(NOW + timedelta(seconds=-301 if mode == 'stale' else 1)))
            if mode in ('company', 'year'):
                return replace(facts, basis=replace(facts.basis, **(
                    {'company_id': CompanyId(str(uuid4()))} if mode == 'company' else {'income_year': IncomeYear(2027)})))
            return facts
        with pytest.raises(BillingError):
            await service.prepare_checkout(query, source)
        assert store.checkout is None
        assert provider.executions == provider.reconciliations == []
    asyncio.run(scenario())


def test_preparation_rechecks_racing_purchase_and_authority_after_source_resolution():
    async def scenario():
        service, store, provider = fixture()
        async def source_with_racing_purchase():
            await service.start_checkout(command(), eligible)
            return await eligible()
        result = await service.prepare_checkout(preparation_query(), source_with_racing_purchase)
        assert result.existing_purchase.purchase_id == store.checkout.purchase_id
        assert result.offer is None and result.consent_version is None
        assert len(provider.executions) == 1 and provider.reconciliations == []
        store.checkout = None
        async def source_with_revocation():
            store.authorized = False
            return await eligible()
        with pytest.raises(BillingError):
            await service.prepare_checkout(preparation_query(), source_with_revocation)
        assert store.checkout is None
    asyncio.run(scenario())


def test_preparation_does_not_reserve_or_waive_changed_terms_and_readiness_on_post():
    async def scenario():
        service, store, provider = fixture()
        await service.prepare_checkout(preparation_query(), eligible)
        with pytest.raises(BillingError):
            await service.start_checkout(command(terms_digest='0'*64), eligible)
        async def unavailable():
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        with pytest.raises(BillingError):
            await service.start_checkout(command(), unavailable)
        assert store.checkout is None and provider.executions == provider.reconciliations == []
    asyncio.run(scenario())
