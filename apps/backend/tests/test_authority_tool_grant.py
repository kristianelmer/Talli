"""Standalone CLI grant characterization using local RSA keys and fake HTTP only."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration, MaskinportenTokenError
from talli_backend.authority_tools import token_smoke
from talli_backend.authority_tools._grant import CliGrantConfiguration, build_cli_grant, request_token


@pytest.fixture
def grant_environment(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "private.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    path.chmod(0o600)
    return {"TALLI_MASKINPORTEN_ENVIRONMENT": "test", "TALLI_MASKINPORTEN_CLIENT_ID": "cli-client",
            "TALLI_MASKINPORTEN_KEY_ID": "cli-key", "TALLI_MASKINPORTEN_PRIVATE_KEY_PATH": str(path),
            "TALLI_MASKINPORTEN_SCOPE": "configured:first configured:second",
            "TALLI_MASKINPORTEN_SYSTEM_USER_ORG": "310279617"}


@pytest.mark.parametrize("selected", ["test", "production"])
@pytest.mark.parametrize("reference", [None, "original-external-reference"])
def test_configurable_cli_scope_and_rar_preserve_exact_original_claims(grant_environment, selected, reference):
    configuration = replace(CliGrantConfiguration.from_environment(grant_environment),
                            environment=selected, system_user_external_ref=reference)
    header, claims = build_cli_grant(configuration, now=datetime(2026, 7, 14, 10, tzinfo=UTC), jti="original-jti")
    detail = {"type": "urn:altinn:systemuser", "systemuser_org": {
        "authority": "iso6523-actorid-upis", "ID": "0192:310279617"}}
    if reference is not None:
        detail["externalRef"] = reference
    assert header == {"alg": "RS256", "kid": "cli-key", "typ": "JWT"}
    assert claims == {"aud": "https://test.maskinporten.no/" if selected == "test" else "https://maskinporten.no/",
        "iss": "cli-client", "iat": 1784023200, "exp": 1784023319, "jti": "original-jti",
        "scope": "configured:first configured:second", "sub": "cli-client", "authorization_details": [detail]}


def test_exact_form_endpoint_summary_and_discard_never_return_grant_or_bearer(grant_environment, monkeypatch):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"access_token": "private-bearer-test-only", "expires_in": "119", "token_type": "Bearer"})
    discarded = []
    from talli_backend.adapters.maskinporten import MaskinportenAccessToken
    original = MaskinportenAccessToken.discard
    def discard(self):
        original(self)
        discarded.append(self.access_token)
    monkeypatch.setattr(MaskinportenAccessToken, "discard", discard)
    result = asyncio.run(token_smoke.run(grant_environment, transport=httpx.MockTransport(respond)))
    assert result == {"ok": True, "environment": "test", "scope": "configured:first configured:second",
                      "tokenType": "Bearer", "expiresIn": 119, "accessTokenPresent": True}
    assert discarded == [""]
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://test.maskinporten.no/token"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    form = parse_qs(request.content.decode())
    assert form.keys() == {"grant_type", "assertion"}
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    claim_segment = form["assertion"][0].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claim_segment + "=" * (-len(claim_segment) % 4)))
    assert claims["exp"] - claims["iat"] == 119
    assert "private-bearer" not in json.dumps(result) and "assertion" not in result


@pytest.mark.parametrize("mode", [0o644, 0o620, 0o601])
def test_private_key_permissions_fail_before_transport(grant_environment, mode):
    from pathlib import Path
    Path(grant_environment["TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"]).chmod(mode)
    with pytest.raises(ValueError, match="mode-0600"):
        CliGrantConfiguration.from_environment(grant_environment)


def test_nonregular_private_key_path_is_rejected_without_blocking(grant_environment, tmp_path):
    import os
    fifo = tmp_path / "not-a-regular-key"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="regular file"):
        CliGrantConfiguration.from_environment(grant_environment | {"TALLI_MASKINPORTEN_PRIVATE_KEY_PATH": str(fifo)})


@pytest.mark.parametrize("field,value", [
    ("client_id", ""), ("key_id", "bad key"), ("scope", "bad scope\nsecond"),
    ("scope", "bad  scope"), ("system_user_org_number", "123"),
    ("system_user_external_ref", "invalid reference"),
])
def test_cli_grant_input_validation_matches_original_before_signing(grant_environment, field, value):
    with pytest.raises(ValueError):
        build_cli_grant(replace(CliGrantConfiguration.from_environment(grant_environment), **{field: value}))


def test_cli_signing_failure_and_missing_access_token_remain_closed(grant_environment):
    configuration = CliGrantConfiguration.from_environment(grant_environment)
    with pytest.raises(MaskinportenTokenError, match="maskinporten_grant_signing_failed"):
        asyncio.run(request_token(replace(configuration, private_key_pem="private-invalid-key")))
    with pytest.raises(MaskinportenTokenError, match="maskinporten_response_invalid"):
        asyncio.run(request_token(configuration, transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"token_type": "Bearer", "expires_in": 599}))))


def test_fifteen_second_total_timeout_covers_response_body_stream(grant_environment, monkeypatch):
    from talli_backend.authority_tools import _grant
    configured = []
    actual_timeout = asyncio.timeout
    def short_timeout(seconds):
        configured.append(seconds)
        return actual_timeout(0.01)
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.1)
            yield b"private-body"
    monkeypatch.setattr(_grant, "timeout", short_timeout)
    with pytest.raises(MaskinportenTokenError, match="maskinporten_network_error"):
        asyncio.run(request_token(CliGrantConfiguration.from_environment(grant_environment),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowBody()))))
    assert configured == [15]


def test_token_response_bom_matches_original_fetch_json_utf8_decoding(grant_environment):
    raw = b"\xef\xbb\xbf" + json.dumps({"access_token": "private-bearer", "expires_in": 119}).encode()
    result = asyncio.run(token_smoke.run(grant_environment,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))))
    assert result["accessTokenPresent"] is True and "private-bearer" not in json.dumps(result)


def test_token_response_does_not_auto_detect_non_utf8_json(grant_environment):
    raw = json.dumps({"access_token": "private-bearer", "expires_in": 119}).encode("utf-16")
    with pytest.raises(MaskinportenTokenError, match="maskinporten_response_invalid"):
        asyncio.run(token_smoke.run(grant_environment,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))))


@pytest.mark.parametrize("name,value", [
    ("TALLI_MASKINPORTEN_ENVIRONMENT", "staging"), ("TALLI_MASKINPORTEN_SYSTEM_USER_ORG", ""),
    ("TALLI_MASKINPORTEN_SCOPE", ""), ("TALLI_MASKINPORTEN_CLIENT_ID", ""),
])
def test_original_required_configuration_rejects_before_transport(grant_environment, name, value):
    with pytest.raises(ValueError):
        CliGrantConfiguration.from_environment(grant_environment | {name: value})


@pytest.mark.parametrize("response", [
    httpx.Response(400, json={"error": "private-bearer", "error_description": "-----BEGIN PRIVATE KEY-----private"}),
    httpx.Response(302, headers={"location": "https://untrusted.invalid/private"}),
    httpx.Response(200, json={"access_token": "private-bearer", "expires_in": 119, "token_type": "private-bearer"}),
    httpx.Response(200, json={"access_token": "private-bearer", "expires_in": 119, "scope": "reflected-private"}),
    httpx.Response(200, content=b"x" * 65_537), httpx.Response(200, content=b"not-json-private"),
])
def test_closed_errors_caps_redirects_and_reflections_do_not_leak(grant_environment, response):
    seen = []
    def respond(request):
        seen.append(request)
        return response
    with pytest.raises(MaskinportenTokenError) as caught:
        asyncio.run(request_token(CliGrantConfiguration.from_environment(grant_environment), transport=httpx.MockTransport(respond)))
    assert len(seen) == 1
    assert "private" not in str(caught.value) and caught.value.__cause__ is None


def test_network_error_and_main_diagnostics_are_redacted(grant_environment, monkeypatch, capsys):
    def fail(request):
        raise httpx.ConnectError("private-bearer-and-key", request=request)
    with pytest.raises(MaskinportenTokenError, match="maskinporten_network_error"):
        asyncio.run(request_token(CliGrantConfiguration.from_environment(grant_environment), transport=httpx.MockTransport(fail)))
    async def bad_run():
        raise ValueError("private-key-and-bearer")
    monkeypatch.setattr(token_smoke, "run", bad_run)
    assert token_smoke.main() == 1
    output = capsys.readouterr()
    assert not output.out and "private" not in output.err
    assert json.loads(output.err)["code"] == "local_configuration_error"


def test_cli_scope_does_not_widen_web_provider_port(grant_environment):
    cli = CliGrantConfiguration.from_environment(grant_environment)
    web = MaskinportenClient(MaskinportenConfiguration("test", cli.client_id, cli.key_id, cli.private_key_pem))
    with pytest.raises(MaskinportenTokenError):
        asyncio.run(web.request_token(cli.scope, system_user_org_number=cli.system_user_org_number))
    with pytest.raises(MaskinportenTokenError):
        asyncio.run(web.request_token("skatteetaten:innrapporteringaksjonaerregisteroppgave",
                                     system_user_org_number=cli.system_user_org_number))
