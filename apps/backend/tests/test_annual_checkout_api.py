"""Local HTTP orchestration only; no real merchant or filing-readiness evidence."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_annual_checkout_service import ACTOR, COMPANY, YEAR, Provider, Store, command, eligible
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, BillingError, settle_annual_checkout,
)
from talli_backend.shared.kernel import Timestamp


class Session(Store):
    def __init__(self):
        super().__init__()
        self.reads = self.cancellation = self
        self.fresh = True
        self.tokens = []

    async def session(self, token):
        if token != 'verified-owner':
            raise BillingAuthenticationError()
        self.tokens.append(token)
        # Keep the persistence's stored checkout distinct from the composition port.
        class Bound:
            actor_id = ACTOR
            checkout = self
        return Bound()

    async def authorize_owner_command(self, company):
        await super().authorize_owner_command(company)
        if not self.fresh:
            raise BillingError.step_up_required()

    async def settle_checkout(self, checkout, observation):
        if self.lose_settlement:
            raise BillingError.unavailable()
        self.checkout = settle_annual_checkout(self.checkout, observation, Timestamp(datetime.now(UTC)))
        return self.checkout


class LocalProvider(Provider):
    def observation(self, intent):
        return replace(super().observation(intent), captured_at=intent.created_at)


async def prerequisites(company, year, actor):
    assert (company, year, actor) == (COMPANY, YEAR, ACTOR)
    return replace(await eligible(), evaluated_at=Timestamp(datetime.now(UTC)))


def fixture(*, source=prerequisites, provider_enabled=True):
    session, provider = Session(), LocalProvider()
    provider.store = session
    api = TestClient(create_app(
        annual_billing_session_factory=session,
        annual_billing_provider=provider if provider_enabled else None,
        annual_checkout_prerequisites=source,
    ))
    return api, session, provider


def headers():
    return {'Authorization': 'Bearer verified-owner', 'Idempotency-Key': 'annual-checkout-api-00001',
            'X-Request-ID': 'annual-checkout-api'}


def body(**changes):
    value = command()
    return {'companyId': str(COMPANY), 'incomeYear': 2026, 'offerVersion': value.offer_version,
            'termsDigest': value.terms_digest, 'purchaseAccepted': True, 'recurringConsent': False,
            'consentVersion': value.consent_version, **changes}


def start(api, **changes):
    return api.post('/api/v1/billing/annual/checkouts', headers=headers(), json=body(**changes))


def observe(api, purchase, **changes):
    return api.post('/api/v1/billing/annual/checkout-observations', headers=headers(),
                    json={'companyId': str(COMPANY), 'purchaseId': str(purchase), **changes})


def test_start_stores_exact_terms_and_separate_consent_and_projects_only_customer_facts():
    api, session, provider = fixture()
    response = start(api)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['status'] == 'paid'
    assert value['offer']['grossMinor'] == 149000 and value['offer']['vatMinor'] == 29800
    assert value['capturedMinor'] == 149000 and value['refundedMinor'] == 0
    assert value['checkoutUrl'] is None
    assert response.headers['cache-control'] == 'no-store'
    assert session.checkout.accepted_by == ACTOR.subject
    assert session.checkout.intent.recurring_consent is False
    assert provider.executions[0].return_url == f'https://talli.no/billing?companyId={COMPANY}'
    assert provider.executions[0].management_url == provider.executions[0].return_url
    assert set(value) == {'purchaseId', 'companyId', 'incomeYear', 'status', 'offer',
                          'capturedMinor', 'refundedMinor', 'checkoutUrl'}
    assert 'providerAccount' not in response.text and 'requestFingerprint' not in response.text


@pytest.mark.parametrize('mode', ['lost_claim', 'lost_provider', 'lost_settlement'])
def test_retry_recovers_original_intent_without_repeating_acquisition(mode):
    api, session, provider = fixture()
    if mode == 'lost_claim':
        session.lose_claim_response = True
    if mode == 'lost_provider':
        provider.lose_response = True
    if mode == 'lost_settlement':
        session.lose_settlement = True
    first = start(api)
    assert first.status_code == (200 if mode == 'lost_provider' else 503)
    purchase = session.checkout.purchase_id
    session.lose_claim_response = session.lose_settlement = provider.lose_response = False
    second = start(api)
    assert second.status_code == 200, second.text
    assert second.json()['purchaseId'] == str(purchase)
    assert len(provider.executions) == (0 if mode == 'lost_claim' else 1)
    assert len(provider.reconciliations) == 1
    assert second.json()['status'] == ('pending' if mode == 'lost_claim' else 'paid')


def test_observation_recovers_pending_original_with_read_only_provider_reconciliation():
    api, session, provider = fixture()
    provider.lose_response = True
    assert start(api).json()['status'] == 'pending'
    provider.lose_response = False
    result = observe(api, session.checkout.purchase_id)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'paid'
    assert len(provider.executions) == len(provider.reconciliations) == 1
    repeated = observe(api, session.checkout.purchase_id)
    assert repeated.json() == result.json()
    assert len(provider.reconciliations) == 1
    assert api.get('/api/v1/billing/annual/checkout-observations', headers=headers()).status_code == 405


@pytest.mark.parametrize('token', [None, 'unverified'])
@pytest.mark.parametrize('path', ['checkouts', 'checkout-observations'])
def test_unauthenticated_calls_do_not_reach_store_or_provider(token, path):
    api, session, provider = fixture()
    request_headers = headers()
    if token is None:
        request_headers.pop('Authorization')
    else:
        request_headers['Authorization'] = 'Bearer ' + token
    data = body() if path == 'checkouts' else {'companyId': str(COMPANY), 'purchaseId': str(uuid4())}
    response = api.post('/api/v1/billing/annual/' + path, headers=request_headers, json=data)
    assert response.status_code == 401
    assert not provider.executions and not provider.reconciliations and not session.tokens


@pytest.mark.parametrize('mode', ['outsider', 'stale_mfa'])
@pytest.mark.parametrize('path', ['start', 'observe'])
def test_current_company_authority_and_fresh_mfa_precede_every_effect(mode, path):
    api, session, provider = fixture()
    session.authorized = mode != 'outsider'
    session.fresh = mode != 'stale_mfa'
    response = start(api) if path == 'start' else observe(api, uuid4())
    assert response.status_code == 403
    assert response.json()['code'] == ('BILLING_FORBIDDEN' if mode == 'outsider' else 'BILLING_STEP_UP_REQUIRED')
    assert not provider.executions and not provider.reconciliations


@pytest.mark.parametrize('changes', [
    {'grossMinor': 1}, {'ready': True}, {'providerAccount': '123456'},
    {'actorId': str(ACTOR.subject)}, {'returnUrl': 'https://evil.example'},
    {'recurringConsent': 'false'}, {'recurringConsent': 1}, {'purchaseAccepted': 'true'},
    {'incomeYear': 1999}, {'termsDigest': 'invalid'},
])
def test_caller_cannot_supply_authority_price_or_redirect_or_coerce_consent(changes):
    api, session, provider = fixture()
    response = start(api, **changes)
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert session.checkout is None and not provider.executions


@pytest.mark.parametrize('changes', [
    {'offerVersion': 'stale'}, {'termsDigest': 'd' * 64}, {'consentVersion': 'stale'},
    {'purchaseAccepted': False},
])
def test_exact_acceptance_is_required_before_provider_or_claim(changes):
    api, session, provider = fixture()
    response = start(api, **changes)
    assert response.status_code in (400, 409, 422)
    assert session.checkout is None and not provider.executions


def test_missing_idempotency_key_fails_before_claim():
    api, session, provider = fixture()
    response = api.post('/api/v1/billing/annual/checkouts', headers={'Authorization': 'Bearer verified-owner'}, json=body())
    assert response.status_code == 422
    assert session.checkout is None and not provider.executions


def test_reusing_key_with_changed_consent_conflicts():
    api, session, provider = fixture()
    assert start(api).status_code == 200
    response = start(api, recurringConsent=True)
    assert response.status_code == 409 and response.json()['code'] == 'BILLING_IDEMPOTENCY_KEY_REUSED'
    assert len(provider.executions) == 1


def test_default_readiness_binding_prevents_new_intent_even_with_test_provider():
    api, session, provider = fixture(source=None)
    response = start(api)
    assert response.status_code == 409 and response.json()['code'] == 'BILLING_FILING_NOT_READY'
    assert session.checkout is None and not provider.executions


def test_absent_or_production_provider_prevents_new_intent():
    for production in (False, True):
        api, session, provider = fixture(provider_enabled=production)
        provider.production_enabled = production
        response = start(api)
        assert response.status_code == 503 and response.json()['code'] == 'BILLING_PROVIDER_DISABLED'
        assert session.checkout is None and not provider.executions


def test_terminal_history_replays_without_provider_or_current_readiness():
    api, session, provider = fixture()
    first = start(api)
    closed = TestClient(create_app(annual_billing_session_factory=session))
    assert start(closed).json() == first.json()
    assert observe(closed, session.checkout.purchase_id).json() == first.json()
    assert len(provider.executions) == 1


def test_pending_recovery_does_not_require_new_source_readiness():
    api, session, provider = fixture()
    provider.lose_response = True
    assert start(api).json()['status'] == 'pending'
    provider.lose_response = False
    recovery = TestClient(create_app(annual_billing_session_factory=session, annual_billing_provider=provider))
    assert start(recovery).json()['status'] == 'paid'
    assert len(provider.executions) == len(provider.reconciliations) == 1


def test_unknown_purchase_is_concealed_without_provider_call():
    api, session, provider = fixture()
    response = observe(api, uuid4())
    assert response.status_code == 404
    assert not provider.executions and not provider.reconciliations
