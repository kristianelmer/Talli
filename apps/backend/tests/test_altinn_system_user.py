"""Local standard System User transport proof; never actual Altinn evidence."""

import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from talli_backend.adapters.altinn_system_user import (
    AltinnSystemUserAdapter, validate_queried_system_user, validate_system_user_response,
)
from talli_backend.adapters.maskinporten import (
    MaskinportenAccessToken, MaskinportenTokenError, SYSTEM_USER_CONTROL_READ_SCOPE,
    SYSTEM_USER_CONTROL_WRITE_SCOPE, SYSTEM_USER_TAX_SCOPE,
)
from talli_backend.modules.authority_connections.public import (
    AuthorityFailureCode as Failure, AuthorityProviderError, SYSTEM_USER_CALLBACK_URL,
    SYSTEM_USER_RIGHT, SYSTEM_USER_SYSTEM_ID, SystemUserIdentity, SystemUserRequestStatus,
)
from talli_backend.shared.kernel import CompanyId, UserId


REQUEST_ID = "10000000-0000-4000-8000-000000000001"
USER_ID = "20000000-0000-4000-8000-000000000002"
IDENTITY = SystemUserIdentity(CompanyId("30000000-0000-4000-8000-000000000003"),
    UserId("40000000-0000-4000-8000-000000000004"), "123456789", "A" * 43)
RIGHTS = [{"resource": [{"id": "urn:altinn:resource", "value": SYSTEM_USER_RIGHT}]}]


def request_body(**changes):
    return {"id": REQUEST_ID, "externalRef": IDENTITY.external_reference,
        "systemId": SYSTEM_USER_SYSTEM_ID, "partyOrgNo": IDENTITY.organization_number,
        "rights": RIGHTS, "status": "New", "redirectUrl": SYSTEM_USER_CALLBACK_URL,
        "confirmUrl": f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}"} | changes


def query_body(**changes):
    return {"id": USER_ID, "systemId": SYSTEM_USER_SYSTEM_ID,
        "reporteeOrgNo": IDENTITY.organization_number, "externalRef": IDENTITY.external_reference,
        "userType": "standard", "isDeleted": False} | changes


class Tokens:
    environment = "production"

    def __init__(self, *, failure=None, token_value="memory-only-secret", scope=None):
        self.requests = []
        self.tokens = []
        self.failure = failure
        self.token_value = token_value
        self.scope = scope

    async def request_token(self, scope, **kwargs):
        self.requests.append((scope, kwargs))
        if self.failure:
            raise self.failure
        token = MaskinportenAccessToken(self.token_value, "Bearer", 599, self.scope or scope, self.environment)
        self.tokens.append(token)
        return token


def provider(body=None, *, status=200, handler=None, tokens=None, environment="production"):
    seen = []
    def respond(request):
        seen.append(request)
        return handler(request) if handler else httpx.Response(status, json=body)
    tokens = tokens or Tokens()
    return AltinnSystemUserAdapter(tokens, environment=environment,
        transport=httpx.MockTransport(respond)), seen, tokens


def test_one_exact_standard_create_uses_fixed_scope_and_discards_token():
    client, seen, tokens = provider(request_body(), status=201)
    result = asyncio.run(client.create_request(IDENTITY))
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor"
    assert request.headers["authorization"] == "Bearer memory-only-secret"
    assert request.headers["accept"] == "application/json" and request.headers["cache-control"] == "no-store"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"externalRef": IDENTITY.external_reference,
        "systemId": SYSTEM_USER_SYSTEM_ID, "partyOrgNo": IDENTITY.organization_number,
        "rights": RIGHTS, "redirectUrl": SYSTEM_USER_CALLBACK_URL}
    assert tokens.requests == [(SYSTEM_USER_CONTROL_WRITE_SCOPE, {})]
    assert tokens.tokens[0].access_token == ""
    assert result.status is SystemUserRequestStatus.NEW and result.provider_request_id == REQUEST_ID
    assert "memory-only-secret" not in repr(result) and "access_token" not in asdict(result)


def test_get_find_query_use_exact_original_relationship_and_documented_external_ref_selector():
    bodies = iter([request_body(status="Accepted", confirmUrl=None), request_body(status="Accepted", confirmUrl=None), query_body()])
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, json=next(bodies)))
    assert asyncio.run(client.get_request(IDENTITY, REQUEST_ID)).status is SystemUserRequestStatus.ACCEPTED
    assert asyncio.run(client.find_request(IDENTITY)).provider_request_id == REQUEST_ID
    assert asyncio.run(client.query_system_user(IDENTITY)).system_user_id == USER_ID
    root = "https://platform.altinn.no/authentication/api/v1"
    assert [(r.method, str(r.url)) for r in seen] == [
        ("GET", f"{root}/systemuser/request/vendor/{REQUEST_ID}"),
        ("GET", f"{root}/systemuser/request/vendor/byexternalref/930835978_talli/123456789/{IDENTITY.external_reference}"),
        ("GET", f"{root}/systemuser/vendor/byquery?system-id=930835978_talli&orgno=123456789&external-ref={IDENTITY.external_reference}"),
    ]
    assert all(not r.content for r in seen)
    assert tokens.requests == [(SYSTEM_USER_CONTROL_READ_SCOPE, {}), (SYSTEM_USER_CONTROL_READ_SCOPE, {}),
                               (SYSTEM_USER_CONTROL_WRITE_SCOPE, {})]
    assert all(t.access_token == "" for t in tokens.tokens)


def test_delegation_acquires_exact_rf_relationship_discards_token_and_returns_no_credential():
    client, seen, tokens = provider()
    assert asyncio.run(client.verify_delegation(IDENTITY)) is None
    assert tokens.requests == [(SYSTEM_USER_TAX_SCOPE, {"system_user_org_number": "123456789",
        "system_user_external_ref": IDENTITY.external_reference})]
    assert seen == [] and tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("code", ["maskinporten_grant_signing_failed", "maskinporten_network_error",
    "maskinporten_http_error", "maskinporten_response_invalid", "maskinporten_token_error"])
def test_token_failure_is_distinct_from_ambiguous_create_and_sends_no_altinn_request(code):
    tokens = Tokens(failure=MaskinportenTokenError(code, status=400 if code == "maskinporten_http_error" else None))
    client, seen, _ = provider(tokens=tokens)
    with pytest.raises(AuthorityProviderError) as caught:
        asyncio.run(client.create_request(IDENTITY))
    assert caught.value.code.value == code and not caught.value.retryable
    assert caught.value.__cause__ is None and len(tokens.requests) == 1 and seen == []


@pytest.mark.parametrize("value", ["", "x" * 8193, "secret\nvalue", "secret value", "secret\x7fvalue", "non-ascii-æ"])
def test_bad_bearer_token_is_discarded_before_network(value):
    client, seen, tokens = provider(tokens=Tokens(token_value=value))
    with pytest.raises(AuthorityProviderError, match="invalid_bearer_token"):
        asyncio.run(client.create_request(IDENTITY))
    assert not seen and tokens.tokens[0].access_token == ""


def test_mismatched_token_scope_is_discarded_before_network():
    client, seen, tokens = provider(tokens=Tokens(scope="extra:scope"))
    with pytest.raises(AuthorityProviderError, match="maskinporten_response_invalid"):
        asyncio.run(client.create_request(IDENTITY))
    assert not seen and tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("status,expected", [("New", "new"), ("Accepted", "accepted"), ("Rejected", "rejected"),
    ("Denied", "denied"), ("TimedOut", "timedout"), ("new", "new"), ("accepted", "accepted"),
    ("rejected", "rejected"), ("denied", "denied"), ("timedout", "timedout")])
def test_original_status_mapping(status, expected):
    result = validate_system_user_response(request_body(status=status), IDENTITY, environment="production")
    assert result.status.value == expected


@pytest.mark.parametrize("change", [
    {"id": "not-uuid"}, {"externalRef": "B" * 43}, {"systemId": "930835978_other"},
    {"partyOrgNo": "987654321"}, {"status": "Pending"}, {"status": ["New"]},
    {"redirectUrl": "https://evil.example"}, {"rights": []}, {"rights": RIGHTS * 2},
    {"rights": [{"resource": RIGHTS[0]["resource"] * 2}]},
    {"rights": [{"resource": RIGHTS[0]["resource"], "accessPackages": []}]},
    {"rights": [{"resource": [{"id": "urn:altinn:resource", "value": "other-right"}]}]},
    {"accessPackages": []}, {"unknown": "secret"}, {"confirmUrl": None},
    {"created": None}, {"created": "not-a-date"}, {"created": "2026-09-09T12:00:00"},
])
def test_request_relationship_shape_right_and_unknown_fields_fail_closed(change):
    with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
        validate_system_user_response(request_body(**change), IDENTITY, environment="production")


def test_missing_required_fields_and_wrong_top_level_shape_are_rejected():
    for field in request_body():
        body = request_body()
        del body[field]
        with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
            validate_system_user_response(body, IDENTITY, environment="production")
    for body in [[], None, True]:
        with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
            validate_system_user_response(body, IDENTITY, environment="production")


def test_get_request_must_match_bound_provider_identity_and_discards_token_on_mismatch():
    client, _, tokens = provider(request_body(id=USER_ID, confirmUrl=None, status="Accepted"))
    with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
        asyncio.run(client.get_request(IDENTITY, REQUEST_ID))
    assert tokens.tokens[0].access_token == ""


def test_only_documented_additive_metadata_is_accepted_and_discarded():
    base = validate_system_user_response(request_body(), IDENTITY, environment="production")
    assert validate_system_user_response(request_body(created="2026-09-09T10:00:00Z"), IDENTITY,
                                        environment="production") == base
    metadata = {"integrationTitle": "Talli", "productName": "", "created": "2026-05-21T13:35:24.161Z",
                "supplierName": "Talli", "supplierOrgno": "930835978"}
    assert validate_queried_system_user(query_body(**metadata), IDENTITY) == validate_queried_system_user(query_body(), IDENTITY)


@pytest.mark.parametrize("change", [
    {"id": "bad"}, {"systemId": "other"}, {"reporteeOrgNo": "987654321"}, {"externalRef": "B" * 43},
    {"externalRef": ""}, {"userType": "agent"}, {"isDeleted": True}, {"isDeleted": 0},
    {"accessPackages": []}, {"rights": RIGHTS}, {"unknown": "secret"},
    {"integrationTitle": {}}, {"productName": "x" * 2049}, {"supplierName": "unsafe\nvalue"},
    {"supplierOrgno": "987654321"}, {"created": False},
])
def test_query_keeps_exact_live_standard_relationship_despite_metadata_compatibility(change):
    with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
        validate_queried_system_user(query_body(**change), IDENTITY)


@pytest.mark.parametrize("host", ["am.ui.at22.altinn.cloud", "authn.ui.tt02.altinn.no", "am.ui.tt02.altinn.no"])
def test_exact_documented_tt02_confirmation_hosts_are_allowed_only_in_tt02(host):
    url = f"https://{host}/accessmanagement/ui/systemuser/request?id={REQUEST_ID}"
    assert validate_system_user_response(request_body(confirmUrl=url), IDENTITY, environment="tt02").confirmation_url == url
    with pytest.raises(AuthorityProviderError, match="invalid_confirmation_url"):
        validate_system_user_response(request_body(confirmUrl=url), IDENTITY, environment="production")


@pytest.mark.parametrize("url", [
    f"http://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}",
    f"https://am.ui.altinn.no.evil.example/accessmanagement/ui/systemuser/request?id={REQUEST_ID}",
    f"https://evil.example@am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}",
    f"https://am.ui.altinn.no:443/accessmanagement/ui/systemuser/request?id={REQUEST_ID}",
    f"https://am.ui.altinn.no/other?id={REQUEST_ID}",
    f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={USER_ID}",
    f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}&id={REQUEST_ID}",
    f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}&redirectUrl=https://evil.example",
    f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}#fragment",
    f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}\n",
    f"https://am.ui.altinn.no\\evil/accessmanagement/ui/systemuser/request?id={REQUEST_ID}",
    "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?bad", "x" * 2049,
])
def test_confirmation_urls_cannot_escape_exact_https_host_path_and_request(url):
    with pytest.raises(AuthorityProviderError, match="invalid_confirmation_url"):
        validate_system_user_response(request_body(confirmUrl=url), IDENTITY, environment="production")


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 408, 425, 429, 500, 503])
def test_http_failures_have_bounded_codes_and_no_redirect_or_retry(status):
    client, seen, tokens = provider(handler=lambda _: httpx.Response(status,
        headers={"location": "https://evil.example"}, json={"code": "unsafe-secret", "detail": "memory-only-secret"}))
    with pytest.raises(AuthorityProviderError) as caught:
        asyncio.run(client.create_request(IDENTITY))
    assert caught.value.code is Failure.AUTHORITY_HTTP_ERROR and caught.value.status == status
    assert caught.value.retryable == (status in (408, 425, 429) or status >= 500)
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("field", ["code", "errorCode", "error"])
def test_only_known_duplicate_authority_code_is_preserved(field):
    client, seen, _ = provider({field: "AUTH-00007", "detail": "unsafe-secret"}, status=409)
    with pytest.raises(AuthorityProviderError) as caught:
        asyncio.run(client.create_request(IDENTITY))
    assert caught.value.code is Failure.DUPLICATE_SYSTEM_USER_REQUEST and caught.value.status == 409
    assert len(seen) == 1 and "unsafe-secret" not in str(caught.value)


@pytest.mark.parametrize("raw,code", [
    (b"x" * 65537, "response_too_large"), (b"\xff", "response_contract_mismatch"),
    (b"{", "response_contract_mismatch"), (b"", "response_contract_mismatch"),
    (b'{"id":"secret","id":"replaced"}', "response_contract_mismatch"),
])
def test_bounded_strict_json_parser_discards_token_on_failure(raw, code):
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, content=raw))
    with pytest.raises(AuthorityProviderError, match=code):
        asyncio.run(client.create_request(IDENTITY))
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""


def test_stream_failure_has_no_provider_cause_or_blind_replay_and_discards_token():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            raise httpx.ReadError("unsafe-secret")
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, stream=BrokenStream()))
    with pytest.raises(AuthorityProviderError) as caught:
        asyncio.run(client.create_request(IDENTITY))
    assert caught.value.code is Failure.NETWORK_ERROR and caught.value.__cause__ is None
    assert "unsafe-secret" not in str(caught.value) and len(seen) == 1 and tokens.tokens[0].access_token == ""


def test_invalid_configuration_and_request_identity_fail_before_token_or_network():
    for environment in ["test", "invalid", "https://evil.example", "tt02"]:
        with pytest.raises(AuthorityProviderError, match="invalid_environment"):
            AltinnSystemUserAdapter(Tokens(), environment=environment)
    for duration in [0, 999, 120001, True, 1000.5]:
        with pytest.raises(AuthorityProviderError, match="invalid_timeout"):
            AltinnSystemUserAdapter(Tokens(), timeout_ms=duration)
    client, seen, tokens = provider()
    for request_id in ["bad", "../secret", REQUEST_ID + "?extra=true"]:
        with pytest.raises(AuthorityProviderError, match="invalid_request_id"):
            asyncio.run(client.get_request(IDENTITY, request_id))
    with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
        asyncio.run(client.create_request(None))
    assert seen == [] and tokens.requests == []


def test_tt02_client_uses_only_fixed_test_platform():
    tokens = Tokens()
    tokens.environment = "test"
    url = f"https://am.ui.tt02.altinn.no/accessmanagement/ui/systemuser/request?id={REQUEST_ID}"
    client, seen, _ = provider(request_body(confirmUrl=url), tokens=tokens, environment="tt02")
    assert asyncio.run(client.create_request(IDENTITY)).confirmation_url == url
    assert seen[0].url.host == "platform.tt02.altinn.no"


def test_from_environment_never_loads_credentials_at_construction_or_falls_back_from_explicit_empty_mapping():
    client = AltinnSystemUserAdapter.from_environment({})
    with pytest.raises(AuthorityProviderError, match="maskinporten_token_error"):
        asyncio.run(client.create_request(IDENTITY))


def test_combined_real_maskinporten_signer_and_altinn_transport_keep_scope_and_tokens_inside_adapter():
    import base64
    from urllib.parse import parse_qs
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()).decode()
    config = MaskinportenConfiguration("production", "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
                                       "2d275f93-10a2-4839-993e-b14da2b84ad8", private_pem)
    seen = []
    claims_seen = []
    def decode(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    def respond(request):
        seen.append((request.method, request.url.host, request.url.path))
        if request.url.host == "maskinporten.no":
            assertion = parse_qs(request.content.decode())["assertion"][0]
            h, c, s = assertion.split(".")
            key.public_key().verify(decode(s), (h + "." + c).encode(), padding.PKCS1v15(), hashes.SHA256())
            claims_seen.append(json.loads(decode(c)))
            return httpx.Response(200, json={"access_token": "memory-only-secret", "expires_in": 599,
                                            "scope": claims_seen[-1]["scope"]})
        assert request.url.host == "platform.altinn.no"
        assert request.headers["authorization"] == "Bearer memory-only-secret"
        return httpx.Response(201, json=request_body())
    transport = httpx.MockTransport(respond)
    client = AltinnSystemUserAdapter(MaskinportenClient(config, transport=transport), transport=transport)
    result = asyncio.run(client.create_request(IDENTITY))
    assert asyncio.run(client.verify_delegation(IDENTITY)) is None
    assert seen == [("POST", "maskinporten.no", "/token"),
                    ("POST", "platform.altinn.no", "/authentication/api/v1/systemuser/request/vendor"),
                    ("POST", "maskinporten.no", "/token")]
    assert claims_seen[0]["scope"] == SYSTEM_USER_CONTROL_WRITE_SCOPE
    assert "authorization_details" not in claims_seen[0]
    assert claims_seen[1]["scope"] == SYSTEM_USER_TAX_SCOPE
    assert claims_seen[1]["authorization_details"] == [{"type": "urn:altinn:systemuser",
        "systemuser_org": {"authority": "iso6523-actorid-upis", "ID": "0192:123456789"},
        "externalRef": IDENTITY.external_reference}]
    assert claims_seen[0]["jti"] != claims_seen[1]["jti"]
    assert "secret" not in repr(result)


def test_oversized_stream_stops_reading_and_closes_before_full_body_arrives():
    class OversizedStream(httpx.AsyncByteStream):
        def __init__(self):
            self.closed = False
            self.reads = 0
        async def __aiter__(self):
            for _ in range(20):
                self.reads += 1
                yield b"x" * 8192
        async def aclose(self):
            self.closed = True
    stream = OversizedStream()
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(AuthorityProviderError, match="response_too_large"):
        asyncio.run(client.create_request(IDENTITY))
    assert stream.closed and stream.reads == 9 and len(seen) == 1 and tokens.tokens[0].access_token == ""


def test_system_user_fatal_textdecoder_accepts_single_leading_bom_and_preserves_error_code():
    raw = b'\xef\xbb\xbf' + json.dumps(request_body()).encode()
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, content=raw))
    assert asyncio.run(client.get_request(IDENTITY, REQUEST_ID)).provider_request_id == REQUEST_ID
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""
    client, seen, tokens = provider(handler=lambda _: httpx.Response(409, content=b'\xef\xbb\xbf{"code":"AUTH-00007"}'))
    with pytest.raises(AuthorityProviderError) as error:
        asyncio.run(client.create_request(IDENTITY))
    assert error.value.code is Failure.DUPLICATE_SYSTEM_USER_REQUEST
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("status", [200, 409])
def test_system_user_utf8_is_fatal_even_in_ignored_fields_and_non_success_responses(status):
    raw = json.dumps(query_body(productName="invalid-byte-here")).encode().replace(b"invalid-byte-here", b"\xff")
    client, seen, tokens = provider(handler=lambda _: httpx.Response(status, content=raw))
    with pytest.raises(AuthorityProviderError) as error:
        asyncio.run(client.query_system_user(IDENTITY))
    assert error.value.code is Failure.RESPONSE_CONTRACT_MISMATCH
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""


@pytest.mark.parametrize("prefix", [b'\xef\xbb\xbf\xef\xbb\xbf', b' \xef\xbb\xbf'], ids=["two-boms", "bom-after-space"])
def test_system_user_only_strips_one_bom_at_the_start(prefix):
    client, _, _ = provider(handler=lambda _: httpx.Response(200, content=prefix + json.dumps(request_body()).encode()))
    with pytest.raises(AuthorityProviderError, match="response_contract_mismatch"):
        asyncio.run(client.get_request(IDENTITY, REQUEST_ID))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_system_user_json_constants_cannot_complete_a_query_or_select_duplicate_recovery(constant):
    raw = json.dumps(query_body(productName="replace-constant")).replace('"replace-constant"', constant).encode()
    client, seen, tokens = provider(handler=lambda _: httpx.Response(200, content=raw))
    with pytest.raises(AuthorityProviderError) as error:
        asyncio.run(client.query_system_user(IDENTITY))
    assert error.value.code is Failure.RESPONSE_CONTRACT_MISMATCH
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""
    # On non-success, the predecessor discarded invalid JSON before selecting
    # safe provider codes. A non-JSON constant must not enable duplicate lookup.
    error_raw = ('{"code":"AUTH-00007","ignored":[' + constant + ']}').encode()
    client, seen, tokens = provider(handler=lambda _: httpx.Response(409, content=error_raw))
    with pytest.raises(AuthorityProviderError) as error:
        asyncio.run(client.create_request(IDENTITY))
    assert error.value.code is Failure.AUTHORITY_HTTP_ERROR
    assert len(seen) == 1 and tokens.tokens[0].access_token == ""
    client, _, _ = provider(query_body(productName=constant))
    assert asyncio.run(client.query_system_user(IDENTITY)).system_user_id == USER_ID
