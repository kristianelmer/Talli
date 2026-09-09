"""Authenticated original-agreement recovery; fixtures are not Merchant Test evidence."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_annual_cleanup_service import ACTOR, COMPANY, PURCHASE, Provider, Store, candidate, observation
from talli_backend.application.annual_billing import AnnualAgreementCleanupWorkflow
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, BillingError, annual_agreement_cleanup_operations,
)
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

PATH = "/api/v1/billing/annual/agreement-cleanups"


class Session(Store):
    def __init__(self):
        super().__init__()
        self.cleanup = self
        self.fresh = True
        self.tokens = []
        self.claims = 0

    async def session(self, token):
        if token != "verified-owner":
            raise BillingAuthenticationError()
        self.tokens.append(token)
        return self

    async def claim_agreement_cleanup(self, company, purchase):
        self.claims += 1
        if not self.fresh:
            raise BillingError.step_up_required()
        return await super().claim_agreement_cleanup(company, purchase)


def api(session, provider=None):
    return TestClient(create_app(annual_billing_session_factory=session, annual_billing_provider=provider))


def fixture():
    session = Session()
    provider = Provider(session)
    return api(session, provider), session, provider


def body(**changes):
    return {"companyId": str(COMPANY), "purchaseId": str(PURCHASE), **changes}


def headers():
    return {"Authorization": "Bearer verified-owner", "X-Request-ID": "annual-cleanup-fixture"}


def cleanup(client, **changes):
    return client.post(PATH, headers=headers(), json=body(**changes))


def test_cleanup_commits_original_intent_and_projects_only_public_outcome():
    client, session, provider = fixture()
    first, second = cleanup(client), cleanup(client)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {**body(), "status": "confirmed"}
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-request-id"] == "annual-cleanup-fixture"
    assert provider.executions == [session.saved.intent] and provider.reads == []
    assert session.claims == 2
    assert client.get(PATH, headers=headers()).status_code == 405


@pytest.mark.parametrize("mode", ["claim", "provider", "settlement"])
def test_lost_response_recovers_same_purchase_operation_and_receipt(mode):
    client, session, provider = fixture()
    session.lose_claim = mode == "claim"
    provider.lose_response = mode == "provider"
    session.lose_settlement = mode == "settlement"
    first = cleanup(client)
    assert first.status_code == (200 if mode == "provider" else 503)
    if mode == "provider":
        assert first.json()["status"] == "unknown"
    original = session.saved
    session.lose_claim = session.lose_settlement = provider.lose_response = False
    second = cleanup(client)
    assert second.status_code == 200 and second.json()["status"] == "confirmed"
    assert session.saved.intent == original.intent
    assert session.saved.cancellation_id == original.cancellation_id
    assert provider.executions == [original.intent]
    assert provider.reads == ([] if mode == "settlement" else [original.intent])


def test_absent_provider_never_executes_and_confirmed_history_still_replays():
    client, session, provider = fixture()
    disabled = api(session)
    response = cleanup(disabled)
    assert response.status_code == 503 and response.json()["code"] == "BILLING_PROVIDER_DISABLED"
    assert session.saved.observation is None
    original = session.saved.intent
    assert provider.executions == provider.reads == []
    confirmed = cleanup(client)
    assert confirmed.json()["status"] == "confirmed"
    assert provider.reads == provider.executions == [original]
    assert cleanup(disabled).json() == confirmed.json()
    assert provider.executions == [original]


def test_unsafe_cleanup_is_deferred_without_provider_or_recorded_intent():
    client, session, provider = fixture()
    session.ready = False
    response = cleanup(client)
    assert response.status_code == 200 and response.json() == {**body(), "status": "deferred"}
    assert cleanup(api(session)).json() == response.json()
    assert session.saved is None and provider.executions == provider.reads == []


def test_unknown_observation_cannot_repeat_provider_mutation_or_claim_success():
    client, session, provider = fixture()
    session.saved = candidate()
    provider.unknown_read = True
    response = cleanup(client)
    assert response.status_code == 200 and response.json()["status"] == "unknown"
    assert provider.executions == [] and provider.reads == [session.saved.intent]


@pytest.mark.parametrize("token", [None, "unverified"])
def test_authentication_failure_precedes_claim_or_provider_io(token):
    client, session, provider = fixture()
    request_headers = headers()
    if token is None:
        request_headers.pop("Authorization")
    else:
        request_headers["Authorization"] = "Bearer " + token
    response = client.post(PATH, headers=request_headers, json=body())
    assert response.status_code == 401
    assert session.claims == 0 and session.tokens == []
    assert session.saved is None and provider.executions == provider.reads == []


@pytest.mark.parametrize("mode", ["owner", "mfa", "company", "purchase"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_current_scope_and_fresh_mfa_gate_even_confirmed_replay(mode, confirmed):
    client, session, provider = fixture()
    if confirmed:
        session.saved = candidate()
        session.saved = replace(session.saved, observation=observation(session.saved))
    session.authorized = mode != "owner"
    session.fresh = mode != "mfa"
    changes = {"companyId": str(uuid4())} if mode == "company" else {"purchaseId": str(uuid4())} if mode == "purchase" else {}
    response = cleanup(client, **changes)
    assert response.status_code == 403
    assert response.json()["code"] == ("BILLING_STEP_UP_REQUIRED" if mode == "mfa" else "BILLING_FORBIDDEN")
    assert provider.executions == provider.reads == []


@pytest.mark.parametrize("field,value", [
    ("production_enabled", True), ("provider", "other"), ("account_reference", "other"),
])
def test_runtime_provider_must_match_original_nonproduction_binding(field, value):
    client, session, provider = fixture()
    setattr(provider, field, value)
    response = cleanup(client)
    assert response.status_code == 503 and response.json()["code"] == "BILLING_PROVIDER_DISABLED"
    assert provider.executions == provider.reads == [] and session.saved.observation is None


@pytest.mark.parametrize("changes", [
    {"actorId": str(ACTOR.subject)}, {"supportCaseId": str(uuid4())}, {"cancellationId": str(uuid4())},
    {"refundRequestId": str(uuid4())}, {"operationId": str(uuid4())}, {"idempotencyKey": "replacement-key"},
    {"providerAccount": "123456"}, {"agreementReference": "override"}, {"ready": True},
    {"companyId": "broken"}, {"purchaseId": "broken"},
])
def test_browser_cannot_supply_authority_receipt_or_provider_identity(changes):
    client, session, provider = fixture()
    response = cleanup(client, **changes)
    assert response.status_code == 422
    assert session.claims == 0 and session.tokens == []
    assert provider.executions == provider.reads == []


def test_workflow_rejects_actor_mismatch_before_persistence():
    session = Session()
    outsider = ActorId(ActorKind.USER, UserId(str(uuid4())))
    with pytest.raises(BillingError):
        AnnualAgreementCleanupWorkflow(SimpleNamespace(actor_id=outsider, cleanup=session), None)
    assert session.claims == 0


def test_public_factory_recovers_confirmed_history_with_no_provider():
    import asyncio
    from test_annual_cleanup_service import QUERY
    session = Session()
    session.saved = candidate()
    session.saved = replace(session.saved, observation=observation(session.saved))
    result = asyncio.run(annual_agreement_cleanup_operations(session, None).cleanup(QUERY))
    assert result == session.saved
