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


def withdraw(api, **changes):
    return api.post('/api/v1/billing/annual/checkout-withdrawals', headers=headers(), json=body(**changes))


def test_withdrawal_is_explicit_scoped_private_and_works_without_new_sale_sources():
    api, session, provider = fixture(source=None, provider_enabled=False)
    first = withdraw(api, offerVersion='obsolete', consentVersion='obsolete')
    assert first.status_code == 200, first.text
    value = first.json()
    assert set(value) == {'companyId','incomeYear','state','purchaseId','withdrawalId','withdrawnAt'}
    assert value['companyId'] == str(COMPANY) and value['incomeYear'] == 2026
    assert value['state'] == 'withdrawn' and value['purchaseId'] is None
    assert value['withdrawalId'] and value['withdrawnAt']
    assert first.headers['cache-control'] == 'no-store'
    assert withdraw(api, offerVersion='obsolete', consentVersion='obsolete').json() == value
    assert start(api, offerVersion='obsolete', consentVersion='obsolete').json()['code'] == 'BILLING_CHECKOUT_REQUEST_WITHDRAWN'
    assert session.checkout is None and provider.executions == provider.reconciliations == []


def test_withdrawal_of_claimed_request_returns_purchase_without_cancellation_or_provider_observation():
    api, session, provider = fixture()
    original = start(api).json()
    before = session.checkout
    result = withdraw(api)
    assert result.status_code == 200 and result.json()['purchaseId'] == original['purchaseId']
    assert result.json()['state'] == 'existing' and result.json()['withdrawalId'] is None
    assert session.checkout == before
    assert len(provider.executions) == 1 and provider.reconciliations == []


@pytest.mark.parametrize('mode,expected', [('missing_session',401),('revoked',403),('stale',403),('actor_field',422),('false_acceptance',422)])
def test_withdrawal_requires_verified_owner_fresh_mfa_and_exact_original_input(mode,expected):
    api, session, provider = fixture()
    auth = headers()
    payload = body()
    if mode == 'missing_session': auth.pop('Authorization')
    if mode == 'revoked': session.authorized = False
    if mode == 'stale': session.fresh = False
    if mode == 'actor_field': payload['actorId'] = str(ACTOR.subject)
    if mode == 'false_acceptance': payload['purchaseAccepted'] = False
    response = api.post('/api/v1/billing/annual/checkout-withdrawals', headers=auth, json=payload)
    assert response.status_code == expected, response.text
    assert session.checkout is None and session.withdrawals == {}
    assert provider.executions == provider.reconciliations == []


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


def prepare(api, **changes):
    return api.get('/api/v1/billing/annual/checkout-preparation', headers=headers(),
                   params={'company_id': str(COMPANY), 'income_year': 2026, **changes})


def test_preparation_get_publishes_exact_offer_and_independent_consent_without_effects():
    from talli_backend.modules.billing.public import annual_billing_consent_version
    api, session, provider = fixture()
    response = prepare(api)
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {'companyId', 'incomeYear', 'state', 'offer', 'consentVersion', 'purchaseId'}
    assert value['companyId'] == str(COMPANY) and value['incomeYear'] == 2026
    assert value['state'] == 'available' and value['purchaseId'] is None
    assert value['consentVersion'] == annual_billing_consent_version()
    assert value['offer']['termsDigest'] == command().terms_digest
    assert value['offer']['grossMinor'] == 149000 and value['offer']['vatMinor'] == 29800
    assert response.headers['cache-control'] == 'no-store'
    assert session.checkout is None and not provider.executions and not provider.reconciliations


@pytest.mark.parametrize('pending', [False, True])
def test_preparation_existing_reference_hides_current_terms_and_private_evidence(pending):
    api, session, provider = fixture()
    provider.lose_response = pending
    started = start(api)
    assert started.status_code == 200
    stored = session.checkout
    async def unavailable(*args):
        pytest.fail('Existing purchase must bypass new-sale prerequisites')
    disabled = TestClient(create_app(annual_billing_session_factory=session, annual_checkout_prerequisites=unavailable))
    response = prepare(disabled)
    assert response.status_code == 200, response.text
    assert response.json() == {'companyId': str(COMPANY), 'incomeYear': 2026, 'state': 'existing',
                               'purchaseId': str(stored.purchase_id), 'offer': None, 'consentVersion': None}
    assert session.checkout == stored
    assert len(provider.executions) == 1 and not provider.reconciliations


@pytest.mark.parametrize('mode', ['authentication', 'owner', 'mfa', 'provider', 'source', 'verifier'])
def test_preparation_unavailable_denies_without_exposing_offer_or_creating_intent(mode):
    api, session, provider = fixture(source=None if mode == 'source' else prerequisites,
                                     provider_enabled=mode != 'provider')
    request_headers = headers()
    if mode == 'authentication':
        request_headers['Authorization'] = 'Bearer invalid'
    if mode == 'owner':
        session.authorized = False
    if mode == 'mfa':
        session.fresh = False
    if mode == 'verifier':
        async def denied(*args):
            from talli_backend.modules.billing.public import BillingErrorCode
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        session.verify_checkout_preparation = denied
    response = api.get('/api/v1/billing/annual/checkout-preparation', headers=request_headers,
                       params={'company_id': str(COMPANY), 'income_year': 2026})
    assert response.status_code == {'authentication': 401, 'owner': 403, 'mfa': 403,
                                   'provider': 503, 'source': 409, 'verifier': 409}[mode]
    assert 'offer' not in response.json() and 'consentVersion' not in response.json()
    assert session.checkout is None and not provider.executions and not provider.reconciliations


def test_preparation_uses_current_consent_accessor_without_changing_offer_version(monkeypatch):
    monkeypatch.setattr('talli_backend.modules.billing.annual_policy.ANNUAL_CONSENT_VERSION', 'separate-consent-v2')
    api, session, provider = fixture()
    response = prepare(api)
    assert response.json()['consentVersion'] == 'separate-consent-v2'
    assert response.json()['offer']['offerVersion'] == command().offer_version
    assert start(api).status_code == 409
    accepted = start(api, consentVersion='separate-consent-v2')
    assert accepted.status_code == 200, accepted.text
    assert len(provider.executions) == 1
    # The original accepted request still replays after the current consent changes.
    monkeypatch.setattr('talli_backend.modules.billing.annual_policy.ANNUAL_CONSENT_VERSION', 'separate-consent-v3')
    assert start(api, consentVersion='separate-consent-v2').json() == accepted.json()
    assert len(provider.executions) == 1 and not provider.reconciliations
