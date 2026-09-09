from __future__ import annotations

import hashlib
import hmac

import pytest

from talli_backend.adapters.authority_callback_transport import AuthorityCallbackTransport


KEY = "local-test-callback-key-with-32-bytes-minimum"
NOW = 1788960000
REQUEST = "20000000-0000-4000-8000-000000000001"
BEARER = "synthetic-verified-session"


def proof(*, request=REQUEST, bearer=BEARER, timestamp=NOW, method="POST", path="/api/v1/authority-connections/system-user-callbacks"):
    message = f"v1\n{method}\n{path}\n{request}\n{hashlib.sha256(bearer.encode()).hexdigest()}\n{timestamp}"
    return f"v1:{timestamp}:{hmac.new(KEY.encode(), message.encode(), hashlib.sha256).hexdigest()}"


def test_callback_requires_bound_server_proof_without_exposing_the_key():
    verifier = AuthorityCallbackTransport(KEY, clock=lambda: NOW)
    assert verifier.configured
    assert verifier.verify(request_id=REQUEST, bearer=BEARER, proof=proof())
    assert KEY not in repr(verifier)
    assert not AuthorityCallbackTransport("").verify(request_id=REQUEST, bearer=BEARER, proof=proof())
    assert not AuthorityCallbackTransport("short").configured


@pytest.mark.parametrize("change", [
    {"request": "20000000-0000-4000-8000-000000000002"},
    {"bearer": "another-session"},
    {"timestamp": NOW - 61},
    {"timestamp": NOW + 6},
    {"method": "GET"},
    {"path": "/api/v1/authority-connections/system-user-requests"},
])
def test_rejects_rebound_expired_and_wrong_purpose_callbacks(change):
    verifier = AuthorityCallbackTransport(KEY, clock=lambda: NOW)
    assert not verifier.verify(request_id=REQUEST, bearer=BEARER, proof=proof(**change))


@pytest.mark.parametrize("value", ["", "v1:0:bad", "v2:1788960000:" + "a" * 64, " " + proof()])
def test_rejects_malformed_callback_proof(value):
    assert not AuthorityCallbackTransport(KEY, clock=lambda: NOW).verify(
        request_id=REQUEST, bearer=BEARER, proof=value,
    )
