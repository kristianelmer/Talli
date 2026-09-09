"""Fixed production registry transport using local fakes only; no provider calls."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from talli_backend.adapters.altinn_authority_operations import AltinnAuthorityOperationsAdapter
from talli_backend.adapters.maskinporten import (
    MaskinportenAccessToken, MaskinportenConfiguration, MaskinportenTokenError, SYSTEM_REGISTER_WRITE_SCOPE,
)
from talli_backend.modules.authority_connections.public import (
    AuthorityOperationCode as Code, AuthorityOperationError, AuthorityOperationIntent,
    AuthorityOperationKind as Kind, AuthorityOperationStatus as Status,
)


CLIENT_ID = "10000000-0000-4000-8000-000000000001"
KEY_ID = "20000000-0000-4000-8000-000000000001"
PEM = "-----BEGIN PRIVATE KEY-----\nlocal-placeholder\n-----END PRIVATE KEY-----"
CONFIG = MaskinportenConfiguration("production", CLIENT_ID, KEY_ID, PEM)
BASE = "https://platform.altinn.no/authentication/api/v1/systemregister/vendor"
SYSTEM = BASE + "/930835978_talli"


class Tokens:
    environment = "production"
    def __init__(self):
        self.calls = []
        self.tokens = []
        self.error = None
    async def request_token(self, scope, **kwargs):
        self.calls.append((scope, kwargs))
        if self.error:
            raise self.error
        token = MaskinportenAccessToken("memory-only-secret", "Bearer", 599, scope, "production")
        self.tokens.append(token)
        return token


def definition(kind=Kind.REGISTER_RF1086_SYSTEM, *, empty=False):
    result = json.loads(AuthorityOperationIntent(kind, CLIENT_ID).request_body)
    if empty:
        result["allowedRedirectUrls"] = []
    return result


def setup(responses, *, enabled=True, configuration=CONFIG):
    calls = []
    tokens = Tokens()
    async def handler(request):
        calls.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    adapter = AltinnAuthorityOperationsAdapter(configuration, enabled=enabled,
        maskinporten=tokens, transport=httpx.MockTransport(handler))
    return adapter, calls, tokens


def run(adapter, kind=Kind.REGISTER_RF1086_SYSTEM):
    return asyncio.run(adapter.execute(adapter.prepare(kind)))


@pytest.mark.parametrize("kind,code", [
    (Kind.REGISTER_RF1086_SYSTEM, Code.ALREADY_VERIFIED),
    (Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK, Code.CALLBACK_ALREADY_VERIFIED),
])
def test_existing_exact_definition_is_read_only_and_token_never_escapes(kind, code):
    adapter, calls, tokens = setup([httpx.Response(200, json=definition(kind))])
    result = run(adapter, kind)
    assert result.status is Status.SUCCEEDED and result.result_code is code
    assert [(r.method, str(r.url)) for r in calls] == [("GET", SYSTEM)]
    assert tokens.calls == [(SYSTEM_REGISTER_WRITE_SCOPE, {})]
    assert all(token.access_token == "" for token in tokens.tokens)
    assert "memory-only-secret" not in repr(result) and "memory-only-secret" not in repr(adapter)


def test_registration_missing_creates_exact_body_once_and_verifies():
    adapter, calls, tokens = setup([
        httpx.Response(404), httpx.Response(201, json=KEY_ID),
        httpx.Response(200, json=definition()),
    ])
    result = run(adapter)
    assert result.result_code is Code.CREATED_AND_VERIFIED and result.authority_http_status == 200
    assert [(r.method, str(r.url)) for r in calls] == [("GET", SYSTEM), ("POST", BASE), ("GET", SYSTEM)]
    assert calls[1].content == AuthorityOperationIntent(Kind.REGISTER_RF1086_SYSTEM, CLIENT_ID).request_body
    assert tokens.tokens[0].access_token == ""


def test_callback_empty_updates_exact_body_once_and_verifies_after_uncertain_put():
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    adapter, calls, tokens = setup([
        httpx.Response(200, json=definition(kind, empty=True)),
        httpx.ReadTimeout("private lost response"), httpx.Response(200, json=definition(kind)),
    ])
    result = run(adapter, kind)
    assert result.result_code is Code.CALLBACK_UPDATED_AND_VERIFIED
    assert [(r.method, str(r.url)) for r in calls] == [("GET", SYSTEM), ("PUT", SYSTEM), ("GET", SYSTEM)]
    assert calls[1].content == AuthorityOperationIntent(kind, CLIENT_ID).request_body
    assert tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("enabled", [False, None, "true", 1])
def test_operations_are_disabled_by_default_even_with_injected_credentials(kind, enabled):
    adapter, calls, tokens = setup([], enabled=enabled)
    with pytest.raises(AuthorityOperationError) as error:
        adapter.prepare(kind)
    assert error.value.code == Code.AUTHORITY_OPS_DISABLED and not calls and not tokens.calls


@pytest.mark.parametrize("enabled", [None, "false", "1", "TRUE", " true"])
def test_lazy_disabled_environment_never_requires_provider_credentials(enabled):
    adapter = AltinnAuthorityOperationsAdapter.from_environment({"TALLI_AUTHORITY_OPS_ENABLED": enabled})
    with pytest.raises(AuthorityOperationError) as error:
        adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    assert error.value.code == Code.AUTHORITY_OPS_DISABLED


@pytest.mark.parametrize("field,value,expected", [
    ("CLIENT_ID", "test-client", Code.AUTHORITY_CLIENT_ID_INVALID),
    ("CLIENT_ID", " " + CLIENT_ID, Code.AUTHORITY_CLIENT_ID_INVALID),
    ("KEY_ID", "tt02-key", Code.AUTHORITY_KEY_ID_INVALID),
    ("PRIVATE_KEY_PEM", "/private/key.pem", Code.AUTHORITY_PRIVATE_KEY_INVALID),
    ("PRIVATE_KEY_PEM", PEM.replace("local", "test"), Code.AUTHORITY_PRIVATE_KEY_INVALID),
    ("PRIVATE_KEY_PEM", PEM + "x" * 16384, Code.AUTHORITY_PRIVATE_KEY_INVALID),
])
def test_production_configuration_errors_are_safe_before_signing(field, value, expected):
    environment = {"TALLI_AUTHORITY_OPS_ENABLED": "true", "TALLI_PROD_MASKINPORTEN_CLIENT_ID": CLIENT_ID,
                   "TALLI_PROD_MASKINPORTEN_KEY_ID": KEY_ID, "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": PEM}
    environment["TALLI_PROD_MASKINPORTEN_" + field] = value
    adapter = AltinnAuthorityOperationsAdapter.from_environment(environment)
    with pytest.raises(AuthorityOperationError) as error:
        adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    assert error.value.code == expected and value not in str(error.value)


def test_test_configuration_is_never_usable_for_these_production_operations():
    adapter, calls, tokens = setup([], configuration=replace(CONFIG, environment="test"))
    with pytest.raises(AuthorityOperationError) as error:
        adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    assert error.value.code == Code.AUTHORITY_ENVIRONMENT_INVALID and not calls and not tokens.calls


@pytest.mark.parametrize("prepared", [False, True])
def test_unprepared_or_substituted_intent_has_no_token_or_http_activity(prepared):
    adapter, calls, tokens = setup([])
    if prepared:
        adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(adapter.execute(AuthorityOperationIntent(Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK, CLIENT_ID)))
    assert error.value.code == Code.AUTHORITY_OPERATION_INVALID and not calls and not tokens.calls


@pytest.mark.parametrize("kind", list(Kind))
def test_token_error_never_reaches_system_register_and_diagnostics_are_redacted(kind):
    adapter, calls, tokens = setup([])
    tokens.error = MaskinportenTokenError("maskinporten_http_error", status=403)
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == Code.AUTHORITY_TOKEN_ERROR and error.value.authority_http_status is None
    assert not calls


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_failed_initial_read_cannot_create_or_update(kind, status):
    adapter, calls, tokens = setup([httpx.Response(status, content=b"private provider body")])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == Code.AUTHORITY_HTTP_ERROR and error.value.authority_http_status == status
    assert len(calls) == 1 and tokens.tokens[0].access_token == ""
    assert "private" not in str(error.value)


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://untrusted.invalid/"}),
    httpx.Response(307, headers={"location": SYSTEM}),
])
def test_redirect_is_never_followed_or_treated_as_a_normal_provider_response(kind, response):
    adapter, calls, tokens = setup([response])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == Code.AUTHORITY_NETWORK_ERROR and len(calls) == 1
    assert tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("response", [
    httpx.Response(200, content=b"{}", headers={"content-type": "text/plain"}),
    httpx.Response(200, json=[]),
    httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"}),
    httpx.Response(200, content=b'{"id":1,"id":2}', headers={"content-type": "application/json"}),
    httpx.Response(200, content=b"{}", headers={"content-type": "application/json", "content-length": "65537"}),
    httpx.Response(200, content=b" " * 65537, headers={"content-type": "application/json"}),
])
def test_invalid_initial_read_is_bounded_and_cannot_write(kind, response):
    adapter, calls, tokens = setup([response])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == Code.AUTHORITY_RESPONSE_INVALID and error.value.authority_http_status == 200
    assert len(calls) == 1 and tokens.tokens[0].access_token == ""


def test_registration_projection_preserves_legacy_documented_response_aliases():
    actual = definition()
    actual["allowedRedirectUrls"] = actual.pop("allowedredirecturls")
    actual["vendor"] = {"ID": "0192:930835978"}
    actual["isDeleted"] = False
    adapter, calls, _ = setup([httpx.Response(200, json=actual)])
    assert run(adapter).result_code is Code.ALREADY_VERIFIED and len(calls) == 1


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("key,value", [
    ("clientId", [KEY_ID]), ("rights", []), ("accessPackages", ["additional"]),
    ("isVisible", 1), ("id", "other-system"),
])
def test_drift_is_conflict_and_never_overwritten(kind, key, value):
    actual = definition(kind)
    actual[key] = value
    adapter, calls, _ = setup([httpx.Response(200, json=actual)])
    assert run(adapter, kind).result_code is Code.DEFINITION_CONFLICT and len(calls) == 1


@pytest.mark.parametrize("create_response,code,status", [
    (httpx.Response(409), Code.AUTHORITY_HTTP_ERROR, 409),
    (httpx.Response(204), Code.AUTHORITY_HTTP_ERROR, 204),
    (httpx.Response(201, json={"id": KEY_ID}), Code.AUTHORITY_RESPONSE_INVALID, 201),
    (httpx.Response(201, json="invalid"), Code.AUTHORITY_RESPONSE_INVALID, 201),
    (httpx.ReadTimeout("private uncertain create"), Code.AUTHORITY_NETWORK_ERROR, None),
])
def test_registration_create_failure_is_not_reposted_and_later_explicit_attempt_reads_first(create_response, code, status):
    adapter, calls, tokens = setup([httpx.Response(404), create_response])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter)
    assert error.value.code == code and error.value.authority_http_status == status
    assert [r.method for r in calls] == ["GET", "POST"] and tokens.tokens[0].access_token == ""
    recovered_adapter, recovered_calls, _ = setup([httpx.Response(200, json=definition())])
    assert run(recovered_adapter).result_code is Code.ALREADY_VERIFIED
    assert [r.method for r in recovered_calls] == ["GET"]


def test_callback_missing_system_is_conflict_without_registration():
    adapter, calls, _ = setup([httpx.Response(404)])
    result = run(adapter, Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK)
    assert result.status is Status.CONFLICT and result.authority_http_status == 404 and len(calls) == 1


@pytest.mark.parametrize("drift", ["top", "vendor", "localized", "right", "resource", "dual_alias", "deleted", "vendor_null"])
def test_callback_requires_exact_current_shape_before_whole_definition_update(drift):
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    actual = definition(kind, empty=True)
    if drift == "top": actual["unknown"] = "additional authority"
    elif drift == "vendor": actual["vendor"]["unknown"] = "additional"
    elif drift == "localized": actual["name"]["se"] = "additional"
    elif drift == "right": actual["rights"][0]["unknown"] = "additional"
    elif drift == "resource": actual["rights"][0]["resource"][0]["unknown"] = "additional"
    elif drift == "dual_alias": actual["allowedredirecturls"] = []
    elif drift == "deleted": actual["isDeleted"] = True
    else: actual["vendor"]["authority"] = None
    adapter, calls, _ = setup([httpx.Response(200, json=actual)])
    assert run(adapter, kind).status is Status.CONFLICT and len(calls) == 1


def test_callback_accepts_exact_legacy_casing_and_omitted_vendor_authority():
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    actual = definition(kind)
    actual["allowedredirecturls"] = actual.pop("allowedRedirectUrls")
    actual["vendor"] = {"ID": "0192:930835978"}
    adapter, calls, _ = setup([httpx.Response(200, json=actual)])
    assert run(adapter, kind).result_code is Code.CALLBACK_ALREADY_VERIFIED and len(calls) == 1


@pytest.mark.parametrize("update", [httpx.Response(204), httpx.Response(200, json={}), httpx.Response(500),
    httpx.Response(200, json=[]), httpx.Response(204, content=b"x" * 65537),
    httpx.ReadTimeout("private lost update")])
def test_callback_reads_back_after_any_update_outcome_and_only_observed_target_confirms(update):
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    adapter, calls, tokens = setup([httpx.Response(200, json=definition(kind, empty=True)), update,
                                   httpx.Response(200, json=definition(kind))])
    assert run(adapter, kind).result_code is Code.CALLBACK_UPDATED_AND_VERIFIED
    assert [r.method for r in calls] == ["GET", "PUT", "GET"] and tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("update,code,status", [
    (httpx.Response(503), Code.AUTHORITY_HTTP_ERROR, 503),
    (httpx.Response(200, json=[]), Code.AUTHORITY_RESPONSE_INVALID, 200),
    (httpx.ReadTimeout("private lost update"), Code.AUTHORITY_NETWORK_ERROR, None),
])
def test_callback_preserves_safe_update_failure_when_readback_proves_no_change(update, code, status):
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    adapter, calls, _ = setup([httpx.Response(200, json=definition(kind, empty=True)), update,
                              httpx.Response(200, json=definition(kind, empty=True))])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == code and error.value.authority_http_status == status
    assert [r.method for r in calls] == ["GET", "PUT", "GET"]


@pytest.mark.parametrize("verification,status", [
    (httpx.Response(404), 404), (httpx.Response(200, json=[]), 200),
    (httpx.Response(200, content=b"x" * 65537), 200), (httpx.ReadTimeout("private verification"), None),
])
def test_callback_readback_failure_remains_unverified_even_if_put_succeeded(verification, status):
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    adapter, calls, _ = setup([httpx.Response(200, json=definition(kind, empty=True)), httpx.Response(204), verification])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, kind)
    assert error.value.code == Code.AUTHORITY_VERIFICATION_ERROR and error.value.authority_http_status == status
    assert [r.method for r in calls] == ["GET", "PUT", "GET"]


@pytest.mark.parametrize("status", [404, 503])
def test_callback_even_error_responses_are_stream_capped_before_status_branch(status):
    adapter, calls, _ = setup([httpx.Response(status, content=b"x" * 65537)])
    with pytest.raises(AuthorityOperationError) as error:
        run(adapter, Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK)
    assert error.value.code == Code.AUTHORITY_RESPONSE_INVALID and error.value.authority_http_status == status
    assert len(calls) == 1


@pytest.mark.parametrize("verification", ["empty", "drift"])
def test_callback_successful_put_without_exact_observed_target_is_conflict(verification):
    kind = Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK
    actual = definition(kind, empty=verification == "empty")
    if verification == "drift":
        actual["rights"] = []
    adapter, calls, _ = setup([httpx.Response(200, json=definition(kind, empty=True)), httpx.Response(204),
                              httpx.Response(200, json=actual)])
    result = run(adapter, kind)
    assert result.status is Status.CONFLICT and result.result_code is Code.DEFINITION_CONFLICT
    assert [r.method for r in calls] == ["GET", "PUT", "GET"]


@pytest.mark.parametrize("verification", ["drift", "absent"])
def test_registration_created_uuid_alone_does_not_prove_verified_definition(verification):
    actual = definition()
    actual["rights"] = []
    adapter, calls, _ = setup([httpx.Response(404), httpx.Response(201, json=KEY_ID),
                              httpx.Response(404) if verification == "absent" else httpx.Response(200, json=actual)])
    if verification == "absent":
        with pytest.raises(AuthorityOperationError) as error:
            run(adapter)
        assert error.value.code == Code.AUTHORITY_HTTP_ERROR and error.value.authority_http_status == 404
    else:
        assert run(adapter).status is Status.CONFLICT
    assert [r.method for r in calls] == ["GET", "POST", "GET"]


def test_configuration_change_before_explicit_next_prepare_rebinds_tokens_to_audited_client(monkeypatch):
    import talli_backend.adapters.altinn_authority_operations as module
    prepared_clients = []
    class BoundTokens(Tokens):
        def __init__(self, configuration, *, transport):
            super().__init__()
            prepared_clients.append(configuration.client_id)
            self.client_id = configuration.client_id
        async def request_token(self, scope, **kwargs):
            token = await super().request_token(scope, **kwargs)
            token.access_token = self.client_id
            return token
    monkeypatch.setattr(module, "MaskinportenClient", BoundTokens)
    environment = {"TALLI_AUTHORITY_OPS_ENABLED": "true", "TALLI_PROD_MASKINPORTEN_CLIENT_ID": CLIENT_ID,
                   "TALLI_PROD_MASKINPORTEN_KEY_ID": KEY_ID, "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": PEM}
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=json.loads(AuthorityOperationIntent(Kind.REGISTER_RF1086_SYSTEM, KEY_ID).request_body))
    adapter = AltinnAuthorityOperationsAdapter(configuration_environment=environment, transport=httpx.MockTransport(handler))
    adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    environment["TALLI_PROD_MASKINPORTEN_CLIENT_ID"] = KEY_ID
    intent = adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    # Later environment changes cannot replace the configuration already bound
    # to this intent between the durable audit and external execution.
    environment["TALLI_PROD_MASKINPORTEN_CLIENT_ID"] = CLIENT_ID
    assert asyncio.run(adapter.execute(intent)).result_code is Code.ALREADY_VERIFIED
    assert prepared_clients == [CLIENT_ID, KEY_ID]
    assert calls[0].headers["authorization"] == "Bearer " + KEY_ID


def test_shared_adapter_keeps_both_fixed_preparations_independent():
    adapter, calls, tokens = setup([httpx.Response(200, json=definition()),
        httpx.Response(200, json=definition(Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK))])
    registration = adapter.prepare(Kind.REGISTER_RF1086_SYSTEM)
    callback = adapter.prepare(Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK)
    assert asyncio.run(adapter.execute(registration)).result_code is Code.ALREADY_VERIFIED
    assert asyncio.run(adapter.execute(callback)).result_code is Code.CALLBACK_ALREADY_VERIFIED
    assert len(calls) == 2 and all(token.access_token == "" for token in tokens.tokens)
