"""Production configuration parity at the frozen backend RF boundary."""

from uuid import uuid4

import pytest

from talli_backend.adapters.maskinporten import MaskinportenClient, SYSTEM_USER_TAX_SCOPE
from talli_backend.adapters.postgres_legacy_rf1086_authority import PostgresLegacyRf1086AuthoritySession
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.compatibility.rf1086_authority_workflow import LegacyRf1086Error
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


def session(environment):
    return PostgresLegacyRf1086AuthoritySession(
        LedgerSupabaseConfiguration("", "", ""),
        _VerifiedActor(ActorId(ActorKind.USER, UserId(str(uuid4()))), "{}"),
        access_token="", billing=None, documents=None, company_access=None,
        environment=environment,
    )


def assert_unavailable(environment):
    store = session(environment)
    assert store._maskinporten is None
    with pytest.raises(LegacyRf1086Error) as caught:
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
