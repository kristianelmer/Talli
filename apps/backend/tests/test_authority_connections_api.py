from __future__ import annotations

import hashlib
import hmac
import time

from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.authority_connections_session import AuthorityConnectionsAuthenticationError
from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError, AuthorityConnectionsErrorCode as Code,
    AuthorityFailureCode, AuthorityProviderError, SystemUserRequestStatus as Status,
)
from talli_backend.shared.kernel import ErrorCategory
from test_authority_connections_service import (
    ACTOR, COMPANY, EXTERNAL_REF, REQUEST_ID, FakeProvider, MemoryPersistence, row,
)


KEY = "local-test-callback-transport-key-32-bytes-minimum"
TOKEN = "verified-owner-session"
BASE = "/api/v1/authority-connections"
BODY = {"companyId": str(COMPANY), "requestId": REQUEST_ID}
HEADERS = {"Authorization": f"Bearer {TOKEN}", "X-Request-ID": "authority-api-test"}


class Session(MemoryPersistence):
    def __init__(self, request=None):
        super().__init__(request)
        self.tokens = []

    @property
    def actor_id(self):
        return ACTOR

    async def session(self, access_token):
        self.tokens.append(access_token)
        if access_token != TOKEN:
            raise AuthorityConnectionsAuthenticationError()
        return self

    async def authorize_owner(self, company_id, actor_id, *, require_fresh_mfa):
        if not self.authorized or company_id != COMPANY or actor_id != ACTOR:
            raise AuthorityConnectionsError(Code.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
        return await super().authorize_owner(company_id, actor_id, require_fresh_mfa=require_fresh_mfa)


def client(store, *, key=KEY):
    provider = FakeProvider(store)
    return TestClient(create_app(
        authority_connections_session_factory=store,
        system_user_authority_provider=provider,
        authority_callback_internal_key=key,
    )), provider


def callback_proof(*, request_id=REQUEST_ID, token=TOKEN, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    payload = f"v1\nPOST\n{BASE}/system-user-callbacks\n{request_id}\n{hashlib.sha256(token.encode()).hexdigest()}\n{timestamp}"
    return f"v1:{timestamp}:{hmac.new(KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()}"


def test_owner_start_and_read_use_verified_actor_and_generated_safe_contract(monkeypatch):
    monkeypatch.setattr("talli_backend.modules.authority_connections.service.secrets.token_urlsafe", lambda _: EXTERNAL_REF)
    store = Session()
    api, provider = client(store)
    response = api.post(f"{BASE}/system-user-requests", headers=HEADERS, json=BODY)
    assert response.status_code == 200, response.text
    assert response.json()["requestId"] == REQUEST_ID
    assert response.json()["status"] == "new"
    assert "externalReference" not in response.json()
    assert store.effects == ["callback_audit", "persist_creating", "persist_new"]
    assert [call[0] for call in provider.calls] == ["create"]
    result = api.get(f"{BASE}/system-user-requests", headers=HEADERS, params={"companyIds": str(COMPANY)})
    assert result.status_code == 200
    assert result.json()["requests"][0]["externalReference"] == EXTERNAL_REF
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"] == "authority-api-test"
    assert TOKEN not in result.text and KEY not in result.text


@pytest.mark.parametrize("extra", [
    {"actorId": str(ACTOR.subject)}, {"requireFreshMfa": False},
    {"organizationNumber": "310279617"}, {"status": "accepted"},
    {"externalReference": EXTERNAL_REF}, {"bearerToken": "authority-secret"},
])
def test_owner_commands_reject_caller_authority_facts(extra):
    store = Session()
    api, provider = client(store)
    response = api.post(f"{BASE}/system-user-requests", headers=HEADERS, json=BODY | extra)
    assert response.status_code == 422
    assert store.request is None and not provider.calls
    assert response.headers["Cache-Control"] == "no-store"


def test_missing_authentication_and_missing_callback_configuration_fail_before_effect():
    store = Session()
    api, provider = client(store, key="")
    assert api.post(f"{BASE}/system-user-requests", json=BODY).status_code == 401
    response = api.post(f"{BASE}/system-user-requests", headers=HEADERS, json=BODY)
    assert response.status_code == 409
    assert response.json()["code"] == "callback_not_verified"
    assert store.request is None and not provider.calls


def test_missing_callback_configuration_blocks_possible_create_retry_but_preserves_status_recovery():
    store = Session(row())
    api, provider = client(store, key="")
    response = api.post(f"{BASE}/system-user-requests/retries", headers=HEADERS, json=BODY)
    assert response.status_code == 409
    assert response.json()["code"] == "callback_not_verified"
    assert not provider.calls
    store.request = row(Status.NEW)
    response = api.post(f"{BASE}/system-user-requests/retries", headers=HEADERS, json=BODY)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"


@pytest.mark.parametrize("proof", ["", "attacker-proof", callback_proof(token="another-session"), callback_proof(timestamp=1)], ids=["missing", "invalid", "wrong-bearer", "expired"])
def test_callback_requires_cookie_forwarding_proof_in_addition_to_known_request_and_bearer(proof):
    store = Session(row(Status.NEW))
    api, provider = client(store)
    response = api.post(f"{BASE}/system-user-callbacks", headers=HEADERS | {"X-Talli-Authority-Callback-Proof": proof}, json={"requestId": REQUEST_ID})
    assert response.status_code == 401
    assert not provider.calls and not store.tokens
    assert response.headers["Cache-Control"] == "no-store"


def test_valid_callback_preserves_no_fresh_mfa_recovery_but_ordinary_retry_cannot_select_it():
    store = Session(row(Status.NEW))
    store.fresh_mfa = False
    api, provider = client(store)
    response = api.post(f"{BASE}/system-user-requests/reconciliations", headers=HEADERS, json=BODY)
    assert response.status_code == 409
    assert response.json()["code"] == "step_up_required"
    assert not provider.calls
    callback = api.post(f"{BASE}/system-user-callbacks", headers=HEADERS | {"X-Talli-Authority-Callback-Proof": callback_proof()}, json={"requestId": REQUEST_ID})
    assert callback.status_code == 200, callback.text
    assert callback.json()["companyId"] == str(COMPANY)
    assert callback.json()["preflightVerifiedAt"] is not None
    assert [call[0] for call in provider.calls] == ["get", "query", "delegate"]


def test_callback_still_rechecks_current_owner_after_valid_transport_proof():
    store = Session(row(Status.NEW))
    store.authorized = False
    api, provider = client(store)
    response = api.post(f"{BASE}/system-user-callbacks", headers=HEADERS | {"X-Talli-Authority-Callback-Proof": callback_proof()}, json={"requestId": REQUEST_ID})
    assert response.status_code == 403
    assert not provider.calls


def test_provider_failure_uses_safe_problem_response_and_leaves_request_unchanged():
    store = Session(row(Status.NEW))
    original = store.request
    api, provider = client(store)
    async def unavailable(*_):
        raise AuthorityProviderError(AuthorityFailureCode.MASKINPORTEN_NETWORK_ERROR)
    provider.get_request = unavailable
    response = api.post(f"{BASE}/system-user-requests/reconciliations", headers=HEADERS, json=BODY)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "maskinporten_network_error"
    assert store.request == original
    assert TOKEN not in response.text and EXTERNAL_REF not in response.text


def test_callback_openapi_does_not_accept_owner_mfa_or_company_authority():
    api, _ = client(Session())
    schema = api.app.openapi()
    assert set(schema["components"]["schemas"]["SystemUserCallbackWire"]["properties"]) == {"requestId"}
    assert schema["components"]["schemas"]["SystemUserCallbackWire"]["additionalProperties"] is False
