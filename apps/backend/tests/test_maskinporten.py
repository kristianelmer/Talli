"""Local cryptographic and HTTP conformance; no Maskinporten calls."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from talli_backend.adapters.maskinporten import (
    MASKINPORTEN_JWT_BEARER_GRANT_TYPE, MaskinportenClient, MaskinportenConfiguration,
    MaskinportenTokenError, SYSTEM_REGISTER_WRITE_SCOPE, SYSTEM_USER_CONTROL_READ_SCOPE,
    SYSTEM_USER_CONTROL_WRITE_SCOPE, SYSTEM_USER_TAX_SCOPE, build_maskinporten_grant,
    sign_maskinporten_grant,
)


NOW = datetime(2026, 7, 14, 10, tzinfo=UTC)
CLIENT_ID = "7166e743-978e-4a60-8a2d-0a5c00fe6ad0"
KEY_ID = "2d275f93-10a2-4839-993e-b14da2b84ad8"
JTI = "3e51ac33-9675-4328-9604-01c34c9f0170"
EXTERNAL_REF = "A" * 43
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(key=KEY, format=serialization.PrivateFormat.PKCS8, password=None):
    encryption = serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    return key.private_bytes(serialization.Encoding.PEM, format, encryption).decode("ascii")


def configuration(**changes):
    return replace(MaskinportenConfiguration("test", CLIENT_ID, KEY_ID, pem()), **changes)


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def grant(config=None, scope=SYSTEM_USER_TAX_SCOPE, **changes):
    arguments = dict(now=NOW, jti=JTI)
    if scope == SYSTEM_USER_TAX_SCOPE:
        arguments.update(system_user_org_number="310279617", system_user_external_ref=EXTERNAL_REF)
    arguments.update(changes)
    return build_maskinporten_grant(config or configuration(), scope, **arguments)


def test_fixed_grant_vector_and_rs256_signature_preserve_legacy_claims_and_both_pem_formats():
    header, claims = grant()
    assert header == {"alg": "RS256", "kid": KEY_ID, "typ": "JWT"}
    assert claims == {
        "aud": "https://test.maskinporten.no/", "iss": CLIENT_ID, "iat": 1784023200,
        "exp": 1784023319, "jti": JTI, "scope": SYSTEM_USER_TAX_SCOPE, "sub": CLIENT_ID,
        "authorization_details": [{"type": "urn:altinn:systemuser", "systemuser_org": {
            "authority": "iso6523-actorid-upis", "ID": "0192:310279617"}, "externalRef": EXTERNAL_REF}],
    }
    token = sign_maskinporten_grant(header, claims, pem())
    assert token == sign_maskinporten_grant(header, claims, pem(format=serialization.PrivateFormat.TraditionalOpenSSL))
    h, c, s = token.split(".")
    assert "=" not in token
    assert json.loads(decode(h)) == header and json.loads(decode(c)) == claims
    KEY.public_key().verify(decode(s), (h + "." + c).encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(InvalidSignature):
        KEY.public_key().verify(decode(s), (h + "." + c + "x").encode("ascii"), padding.PKCS1v15(), hashes.SHA256())


@pytest.mark.parametrize("scope", [SYSTEM_USER_CONTROL_READ_SCOPE, SYSTEM_USER_CONTROL_WRITE_SCOPE, SYSTEM_REGISTER_WRITE_SCOPE])
def test_control_scopes_have_no_delegation_and_production_audience_is_exact(scope):
    _, claims = grant(configuration(environment="production"), scope)
    assert claims["aud"] == "https://maskinporten.no/"
    assert claims["scope"] == scope
    assert "sub" not in claims and "authorization_details" not in claims


def test_fresh_grants_have_unique_jti_and_token_repr_and_discard_hide_secret():
    _, a = build_maskinporten_grant(configuration(), SYSTEM_USER_CONTROL_READ_SCOPE)
    _, b = build_maskinporten_grant(configuration(), SYSTEM_USER_CONTROL_READ_SCOPE)
    assert a["jti"] != b["jti"]
    assert "PRIVATE KEY" not in repr(configuration()) and CLIENT_ID not in repr(configuration())


@pytest.mark.parametrize("scope,changes", [
    ("", {}), ([], {}), (None, {}), ("other:scope", {}), (SYSTEM_USER_TAX_SCOPE + " extra:scope", {}),
    (SYSTEM_USER_TAX_SCOPE + "\n", {}), (SYSTEM_USER_TAX_SCOPE, {"system_user_org_number": " 310279617"}),
    (SYSTEM_USER_TAX_SCOPE, {"system_user_org_number": "٣١٠٢٧٩٦١٧"}),
    (SYSTEM_USER_TAX_SCOPE, {"system_user_external_ref": None}),
    (SYSTEM_USER_TAX_SCOPE, {"system_user_external_ref": "A" * 42}),
    (SYSTEM_USER_CONTROL_READ_SCOPE, {"system_user_org_number": "310279617"}),
    (SYSTEM_USER_CONTROL_READ_SCOPE, {"system_user_external_ref": EXTERNAL_REF}),
    (SYSTEM_USER_CONTROL_READ_SCOPE, {"now": datetime(2026, 7, 14)}),
    (SYSTEM_USER_CONTROL_READ_SCOPE, {"jti": "secret\nidentifier"}),
])
def test_bad_scope_and_relationship_and_time_fail_before_network(scope, changes):
    with pytest.raises(MaskinportenTokenError):
        grant(scope=scope, **changes)


@pytest.mark.parametrize("key_pem", [
    "not-a-private-key", None, b"bytes-key",
    pem(rsa.generate_private_key(public_exponent=65537, key_size=1024)),
    pem(ec.generate_private_key(ec.SECP256R1())), pem(password=b"test-only-password"),
    "-----BEGIN " "PRIVATE KEY-----\nmalformed-secret\n-----END PRIVATE KEY-----",
], ids=["invalid-text", "missing", "bytes-input", "weak-rsa", "non-rsa", "encrypted", "malformed-pem"])
def test_invalid_keys_fail_closed_without_key_in_error(key_pem):
    with pytest.raises(MaskinportenTokenError) as caught:
        sign_maskinporten_grant(*grant(), key_pem)
    assert caught.value.code == "maskinporten_grant_signing_failed"
    assert str(key_pem) not in str(caught.value) and "malformed-secret" not in repr(caught.value)
    assert caught.value.__cause__ is None


def token_client(response=None, handler=None, config=None):
    seen = []
    def respond(request):
        seen.append(request)
        return handler(request) if handler else response
    return MaskinportenClient(config or configuration(), transport=httpx.MockTransport(respond),
                             now=lambda: NOW, jti=lambda: JTI), seen


def test_exact_http_form_and_opaque_token_lifetime_and_production_configuration():
    config = MaskinportenConfiguration.production({
        "TALLI_PROD_MASKINPORTEN_CLIENT_ID": CLIENT_ID, "TALLI_PROD_MASKINPORTEN_KEY_ID": KEY_ID,
        "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": pem(), "TALLI_AUTHORITY_OPS_ENABLED": "false",
    })
    client, seen = token_client(httpx.Response(200, json={"access_token": "memory-only-secret",
        "expires_in": "599", "scope": SYSTEM_USER_CONTROL_READ_SCOPE}), config=config)
    token = asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert len(seen) == 1 and str(seen[0].url) == "https://maskinporten.no/token"
    assert seen[0].method == "POST"
    assert seen[0].headers["content-type"] == "application/x-www-form-urlencoded"
    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == [MASKINPORTEN_JWT_BEARER_GRANT_TYPE]
    h, c, s = form["assertion"][0].split(".")
    KEY.public_key().verify(decode(s), (h + "." + c).encode(), padding.PKCS1v15(), hashes.SHA256())
    assert token.access_token == "memory-only-secret" and token.expires_in == 599
    assert token.token_type == "Bearer" and token.environment == "production"
    assert "memory-only-secret" not in repr(token)
    token.discard()
    assert token.access_token == ""


@pytest.mark.parametrize("body", [
    {}, [], {"access_token": ""}, {"access_token": "secret token", "expires_in": 500},
    {"access_token": "secret\x00token", "expires_in": 500},
    {"access_token": "non-ascii-æ", "expires_in": 500},
    {"access_token": "x" * 8193, "expires_in": 500},
    *[{"access_token": "response-secret", "expires_in": value} for value in [None, True, 0, -1, "NaN", "Infinity", [], {}]],
    {"access_token": "response-secret", "expires_in": 599, "scope": "other:scope"},
    {"access_token": "response-secret", "expires_in": 599, "token_type": "Basic"},
])
def test_invalid_token_responses_fail_without_secrets(body):
    client, seen = token_client(httpx.Response(200, json=body))
    with pytest.raises(MaskinportenTokenError) as caught:
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert caught.value.code == "maskinporten_response_invalid"
    assert "response-secret" not in str(caught.value) and len(seen) == 1


@pytest.mark.parametrize("raw", [b"x" * 65537, b"\xff", b"{", b'{"access_token":"secret","access_token":"replacement","expires_in":599}'])
def test_bounded_strict_response_parser(raw):
    client, _ = token_client(httpx.Response(200, content=raw))
    with pytest.raises(MaskinportenTokenError, match="maskinporten_response_invalid"):
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 429, 500])
def test_redirects_and_http_errors_do_not_replay_or_expose_provider_diagnostics(status):
    client, seen = token_client(httpx.Response(status, headers={"location": "https://evil.example/token"},
        json={"error": "unsafe-secret", "error_description": "unsafe-secret"}))
    with pytest.raises(MaskinportenTokenError) as caught:
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert caught.value.code == "maskinporten_http_error" and caught.value.status == status
    assert "unsafe-secret" not in str(caught.value) and len(seen) == 1


def test_network_failure_has_no_request_or_provider_cause_and_does_not_retry():
    def failure(request):
        raise httpx.ReadTimeout("unsafe-secret", request=request)
    client, seen = token_client(handler=failure)
    with pytest.raises(MaskinportenTokenError) as caught:
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert caught.value.code == "maskinporten_network_error" and len(seen) == 1
    assert caught.value.__cause__ is None and "unsafe-secret" not in repr(caught.value)


def test_invalid_configuration_or_signing_never_calls_transport():
    for changes in [{"environment": "staging"}, {"client_id": ""}, {"key_id": "bad\nidentifier"},
                    {"private_key_pem": "file:///private/key"}]:
        with pytest.raises(MaskinportenTokenError):
            configuration(**changes)
    client, seen = token_client(config=configuration(private_key_pem=
        "-----BEGIN " "PRIVATE KEY-----\nmalformed\n-----END PRIVATE KEY-----"))
    with pytest.raises(MaskinportenTokenError, match="maskinporten_grant_signing_failed"):
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert seen == []


def test_environment_loading_is_lazy_and_empty_mapping_cannot_use_ambient_credentials(monkeypatch):
    valid = {"TALLI_PROD_MASKINPORTEN_CLIENT_ID": CLIENT_ID, "TALLI_PROD_MASKINPORTEN_KEY_ID": KEY_ID,
             "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": pem()}
    for name, value in valid.items():
        monkeypatch.setenv(name, value)
    client = MaskinportenClient.from_environment({})
    assert client.environment == "production"
    with pytest.raises(MaskinportenTokenError, match="maskinporten_token_error"):
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    env = {}
    client = MaskinportenClient(configuration_environment=env,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"access_token": "secret", "expires_in": 599})))
    env.update(valid)
    token = asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert token.environment == "production"
    token.discard()


def test_response_stream_is_bounded_and_closed_without_retry():
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
    client, seen = token_client(httpx.Response(200, stream=stream))
    with pytest.raises(MaskinportenTokenError, match="maskinporten_response_invalid"):
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert stream.closed and stream.reads == 9 and len(seen) == 1


@pytest.mark.parametrize("prefix", [b'', b'\xef\xbb\xbf'], ids=["without-bom", "with-bom"])
def test_fetch_json_replaces_invalid_utf8_in_ignored_fields_and_strips_leading_bom(prefix):
    client, seen = token_client(httpx.Response(200, content=prefix +
        b'{"access_token":"memory-only-secret","expires_in":599,"ignored":"\xff"}'))
    token = asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert token.access_token == "memory-only-secret" and len(seen) == 1
    assert "memory-only-secret" not in repr(token)
    token.discard()


@pytest.mark.parametrize("raw", [
    b'\xef\xbb\xbf{"access_token":"\xff","expires_in":599}',
    b'\xef\xbb\xbf\xef\xbb\xbf{"access_token":"valid","expires_in":599}',
    b' \xef\xbb\xbf{"access_token":"valid","expires_in":599}',
], ids=["invalid-token-byte", "two-boms", "bom-after-space"])
def test_replacement_decoding_does_not_relax_token_or_json_contract(raw):
    client, seen = token_client(httpx.Response(200, content=raw))
    with pytest.raises(MaskinportenTokenError, match="maskinporten_response_invalid"):
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert len(seen) == 1


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_token_response_rejects_non_json_constants_even_in_ignored_nested_values(constant):
    raw = ('{"access_token":"synthetic-local-only","expires_in":60,"ignored":{"nested":[' + constant + ']}}').encode()
    client, seen = token_client(httpx.Response(200, content=raw))
    with pytest.raises(MaskinportenTokenError) as error:
        asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert error.value.code == "maskinporten_response_invalid" and len(seen) == 1
    assert "synthetic-local-only" not in str(error.value)
    valid = raw.replace(constant.encode(), json.dumps(constant).encode())
    client, _ = token_client(httpx.Response(200, content=valid))
    token = asyncio.run(client.request_token(SYSTEM_USER_CONTROL_READ_SCOPE))
    assert token.access_token == "synthetic-local-only"
    token.discard()
