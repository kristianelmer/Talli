"""Authenticated generated boundary uses the real operator service and local ports."""
from fastapi.testclient import TestClient
import pytest
from talli_backend.main import create_app
from talli_backend.application.authority_connections_session import AuthorityConnectionsAuthenticationError
from talli_backend.modules.authority_connections.public import AuthorityOperationError, AuthorityOperationCode as Code
from talli_backend.shared.kernel import ErrorCategory
from test_authority_operations import ACTOR, OPERATION_ID, Persistence, Provider

BASE = '/api/v1/authority-connections/operations'
TOKEN = 'operator-session-local'
HEADERS = {'Authorization': 'Bearer '+TOKEN, 'X-Request-ID': 'authority-operator-test'}
BODY = dict(operationId=OPERATION_ID, operation='register_rf1086_system', confirmation='REGISTER TALLI RF1086 SYSTEM')

class Sessions(Persistence):
    allowed = True
    @property
    def actor_id(self): return ACTOR
    async def session(self, token):
        if token != TOKEN: raise AuthorityConnectionsAuthenticationError()
        return self
    async def authorize_operator(self, actor_id, *, require_fresh_mfa):
        if not self.allowed:
            raise AuthorityOperationError(Code.ADMIN_OPERATOR_REQUIRED, category=ErrorCategory.FORBIDDEN)
        assert actor_id == ACTOR
        await super().authorize_operator(actor_id, require_fresh_mfa=require_fresh_mfa)


def setup():
    sessions = Sessions()
    provider = Provider(sessions)
    api = TestClient(create_app(authority_connections_session_factory=sessions, authority_operations_provider=provider))
    return api, sessions, provider


def test_verified_operator_audit_and_duplicate_request_never_reexecutes():
    api, store, provider = setup()
    result = api.post(BASE, headers=HEADERS, json=BODY)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['operationId'] == OPERATION_ID and value['actorId'] == str(ACTOR.subject)
    assert value['status'] == 'succeeded' and value['resultCode'] == 'created_and_verified'
    assert value['requestHash'] == store.rows[OPERATION_ID].request_hash
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-request-id'] == 'authority-operator-test'
    assert TOKEN not in result.text
    duplicate = api.post(BASE, headers=HEADERS, json=BODY)
    assert duplicate.status_code == 409 and len(provider.calls) == 1
    history = api.get(BASE, headers=HEADERS)
    assert history.status_code == 200 and history.json()['operations'] == [value]
    assert store.authorizations == [True, True, False]


@pytest.mark.parametrize('extra', [dict(actorId=str(ACTOR.subject)), dict(clientId='caller-client'),
    dict(requestHash='a'*64), dict(status='succeeded'), dict(metadata={}), dict(requireFreshMfa=False),
    dict(url='https://not-authorized.test'), dict(environment='test')])
def test_operator_contract_rejects_caller_authority_facts(extra):
    api, store, provider = setup()
    response = api.post(BASE, headers=HEADERS, json=BODY | extra)
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert not store.rows and not provider.calls


def test_exact_confirmation_and_authentication_before_audit():
    api, store, provider = setup()
    assert api.post(BASE, json=BODY).status_code == 401
    assert api.post(BASE, headers=HEADERS, json=BODY | dict(confirmation='approved')).status_code == 409
    assert api.post(BASE, headers=HEADERS, json=BODY | dict(operation='arbitrary')).status_code == 422
    store.allowed = False
    assert api.post(BASE, headers=HEADERS, json=BODY).status_code == 403
    assert api.get(BASE, headers=HEADERS).status_code == 403
    assert not store.rows and not provider.calls


def test_provider_exception_has_safe_problem_after_terminal_audit():
    api, store, provider = setup()
    provider.error = RuntimeError('private-token-or-key-must-not-leak')
    response = api.post(BASE, headers=HEADERS, json=BODY)
    assert response.status_code == 409
    assert response.json()['code'] == 'authority_operation_failed'
    assert response.headers['content-type'] == 'application/problem+json'
    assert response.headers['cache-control'] == 'no-store'
    assert 'private-token' not in response.text
    assert store.rows[OPERATION_ID].status == 'failed'


def test_operator_list_limit_is_bounded():
    api, store, provider = setup()
    assert api.get(BASE, headers=HEADERS, params={'limit':11}).status_code == 422
    assert api.get(BASE, headers=HEADERS, params={'limit':0}).status_code == 422
    assert not store.authorizations
