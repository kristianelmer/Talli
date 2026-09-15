"""Production configuration parity at the canonical RF boundary."""

from uuid import uuid4
import asyncio
import json
from types import SimpleNamespace

import pytest

from talli_backend.adapters.maskinporten import MaskinportenClient, SYSTEM_USER_TAX_SCOPE
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.modules.shareholder_register_filing.public import Rf1086ProductionError
from talli_backend.shared.kernel import ActorId, ActorKind, UserId


VALID = {
    "TALLI_RF1086_PRODUCTION_ENABLED": "true",
    "TALLI_PROD_MASKINPORTEN_CLIENT_ID": "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
    "TALLI_PROD_MASKINPORTEN_KEY_ID": "2d275f93-10a2-4839-993e-b14da2b84ad8",
    # The configuration gate only accepts inline PEM; signing independently
    # validates RSA type/strength and contents before making a token request.
    "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": "-----BEGIN " "PRIVATE KEY-----\nZmFrZQ==\n-----END PRIVATE KEY-----",
    "TALLI_PROD_RF1086_SCOPE": SYSTEM_USER_TAX_SCOPE,
}


@pytest.mark.parametrize("mutation", [False, True])
def test_rf_and_dialog_tokens_share_exact_delegation_and_are_both_discarded(mutation):
    from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_DIALOGPORTEN_SCOPE
    store = session(VALID.copy())
    calls, tokens = [], []
    class TokenClient:
        async def request_token(self, scope, **delegation):
            calls.append((scope, delegation))
            token = MaskinportenAccessToken("local-" + str(len(calls)), "Bearer", 120, scope, "production")
            tokens.append(token)
            return token
    store._maskinporten = TokenClient()
    company, connection = SimpleNamespace(org_number="310279617"), SimpleNamespace(external_ref="A" * 43)
    method = store.bind_mutation_authority if mutation else store.bind_read_only_authority
    binding = asyncio.run(method(company, connection))
    assert [scope for scope, _ in calls] == [SYSTEM_USER_TAX_SCOPE, SYSTEM_USER_DIALOGPORTEN_SCOPE]
    assert all(delegation == {"system_user_org_number": "310279617", "system_user_external_ref": "A" * 43}
        for _, delegation in calls)
    assert binding.feedback_discovery is not None
    binding.discard()
    assert all(token.access_token == "" for token in tokens)


def test_dialog_token_failure_discards_already_acquired_rf_token():
    from talli_backend.adapters.maskinporten import MaskinportenAccessToken
    store = session(VALID.copy())
    token = MaskinportenAccessToken("local-rf", "Bearer", 120, SYSTEM_USER_TAX_SCOPE, "production")
    class TokenClient:
        async def request_token(self, scope, **_delegation):
            if scope == SYSTEM_USER_TAX_SCOPE:
                return token
            raise RuntimeError("scope unavailable")
    store._maskinporten = TokenClient()
    with pytest.raises(RuntimeError):
        asyncio.run(store.bind_mutation_authority(SimpleNamespace(org_number="310279617"),
            SimpleNamespace(external_ref="A" * 43)))
    assert token.access_token == ""


@pytest.mark.parametrize("confirmation,expected", [
    ({"dialogId": "20000000-0000-4000-8000-000000000002", "forsendelseId": "30000000-0000-4000-8000-000000000003"}, True),
    ({"dialogId": "invalid", "forsendelseId": "30000000-0000-4000-8000-000000000003"}, False),
    ({"dialogId": "20000000-0000-4000-8000-000000000002", "forsendelseId": "other"}, False),
    ({"dialogId": True, "forsendelseId": "30000000-0000-4000-8000-000000000003"}, False),
    ({}, False), ([], False),
])
def test_dialog_identity_comes_from_matching_leased_confirmation(confirmation, expected):
    store = session({})
    async def rows(sql, values):
        assert "feedback_reconciliation_lease_id=%s::uuid" in sql
        assert "e.operation_name='confirm'" in sql and "e.operation_state='succeeded'" in sql
        assert values == ("submission", "lease")
        return [{"authority_reference": json.dumps(confirmation),
            "feedback_forsendelse_id": "30000000-0000-4000-8000-000000000003"}]
    store._rows = rows
    if expected:
        assert asyncio.run(store.read_claimed_dialog_id("submission", "lease")) == confirmation["dialogId"]
    else:
        with pytest.raises(Rf1086ProductionError):
            asyncio.run(store.read_claimed_dialog_id("submission", "lease"))


def session(environment):
    return PostgresShareholderRegisterFilingSession(
        LedgerSupabaseConfiguration("", "", ""),
        _VerifiedActor(ActorId(ActorKind.USER, UserId(str(uuid4()))), "{}"),
        access_token="", billing=None, documents=None, company_access=None,
        environment=environment,
    )


def assert_unavailable(environment):
    store = session(environment)
    assert store._maskinporten is None
    with pytest.raises(Rf1086ProductionError) as caught:
        store.require_configuration()
    assert caught.value.code == "configuration_unavailable"
    assert str(caught.value) == "configuration_unavailable"
    assert store._maskinporten is None


def test_strict_complete_production_configuration_constructs_only_backend_client():
    store = session(VALID.copy())
    store.require_configuration()
    client = store._maskinporten
    assert isinstance(client, MaskinportenClient)
    assert client.environment == "production"
    store.require_configuration()
    assert store._maskinporten is client


@pytest.mark.parametrize("flag", [None, "", "false", "off", "0", "1", "TRUE", "true ", " true", "malformed"],
    ids=["missing", "empty", "false", "off", "zero", "one", "uppercase", "trailing-space", "leading-space", "malformed"])
def test_production_remains_unavailable_unless_flag_is_exact_true(flag):
    environment = VALID | {"TALLI_RF1086_PRODUCTION_ENABLED": flag}
    if flag is None:
        environment.pop("TALLI_RF1086_PRODUCTION_ENABLED")
    assert_unavailable(environment)


@pytest.mark.parametrize("field", list(VALID), ids=["flag", "client", "key-id", "private-key", "scope"])
def test_each_missing_production_configuration_field_fails_closed(field):
    environment = VALID.copy()
    environment.pop(field)
    assert_unavailable(environment)


@pytest.mark.parametrize("field,value", [
    ("TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM", "/Users/example/talli-test.key"),
    ("TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM", ""),
    ("TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM", "-----BEGIN PUBLIC KEY-----\nZmFrZQ==\n-----END PUBLIC KEY-----"),
    ("TALLI_PROD_MASKINPORTEN_CLIENT_ID", "test-client"),
    ("TALLI_PROD_MASKINPORTEN_KEY_ID", "test-key"),
    ("TALLI_PROD_MASKINPORTEN_CLIENT_ID", " " + VALID["TALLI_PROD_MASKINPORTEN_CLIENT_ID"]),
    ("TALLI_PROD_MASKINPORTEN_KEY_ID", VALID["TALLI_PROD_MASKINPORTEN_KEY_ID"] + " "),
    ("TALLI_PROD_MASKINPORTEN_KEY_ID", ""),
    ("TALLI_PROD_RF1086_SCOPE", "another:scope"),
    ("TALLI_PROD_RF1086_SCOPE", SYSTEM_USER_TAX_SCOPE + " another:scope"),
    ("TALLI_PROD_RF1086_SCOPE", SYSTEM_USER_TAX_SCOPE + " "),
], ids=["file-path", "empty-pem", "public-key", "test-client", "test-key", "untrimmed-client", "untrimmed-key",
        "empty-key", "wrong-scope", "extra-scope", "untrimmed-scope"])
def test_file_paths_test_identifiers_partial_keys_and_nonfixed_scope_are_unavailable(field, value):
    assert_unavailable(VALID | {field: value})


def test_ambient_test_credentials_never_enable_missing_production_configuration(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key.replace("TALLI_PROD_", "TALLI_TEST_"), value)
    assert_unavailable({})
