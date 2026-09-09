"""Exact admin operation policy and durable audit; no live provider calls."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from talli_backend.modules.authority_connections.operations import AuthorityOperationsService
from talli_backend.modules.authority_connections.public import (
    AuthorityOperationCode as Code,
    AuthorityOperationError,
    AuthorityOperationKind as Kind,
    AuthorityOperationStatus as Status,
    AuthorityOperationIntent,
    AuthorityOperationRecord,
    AuthorityOperationCompletion,
    RunAuthorityOperationCommand,
)
from talli_backend.shared.kernel import ActorId, ActorKind, Timestamp, UserId


ACTOR = ActorId(ActorKind.USER, UserId("32345678-1234-4234-8234-123456789abc"))
OPERATION_ID = "22345678-1234-4234-8234-123456789abc"
CLIENT_ID = "10000000-0000-4000-8000-000000000001"
NOW = Timestamp(datetime(2026, 7, 16, 12, tzinfo=UTC))
LATER = Timestamp(datetime(2026, 7, 16, 12, 1, tzinfo=UTC))


def command(kind=Kind.REGISTER_RF1086_SYSTEM, **changes):
    confirmation = ("REGISTER TALLI RF1086 SYSTEM" if kind is Kind.REGISTER_RF1086_SYSTEM
                    else "SET TALLI SYSTEMBRUKER CALLBACK")
    return replace(RunAuthorityOperationCommand(ACTOR, OPERATION_ID, kind, confirmation), **changes)


class Persistence:
    def __init__(self):
        self.rows = {}
        self.authorizations = []
        self.start_error = None
        self.completion_error = None

    async def authorize_operator(self, actor_id, *, require_fresh_mfa):
        self.authorizations.append(require_fresh_mfa)

    async def begin_operation(self, command, intent):
        if self.start_error:
            raise self.start_error
        if command.operation_id in self.rows:
            raise AuthorityOperationError(Code.AUTHORITY_OPERATION_CONFLICT)
        record = AuthorityOperationRecord(command.operation_id, command.operation, command.actor_id.subject,
            Status.STARTED, intent.request_hash, Code.STARTED, intent.metadata, None, NOW, None)
        self.rows[record.operation_id] = record
        return record

    async def complete_operation(self, actor_id, operation_id, completion):
        if self.completion_error:
            raise self.completion_error
        existing = self.rows[operation_id]
        assert existing.status is Status.STARTED and existing.actor_id == actor_id.subject
        updated = replace(existing, status=completion.status, result_code=completion.result_code,
                          authority_http_status=completion.authority_http_status, completed_at=LATER)
        self.rows[operation_id] = updated
        return updated

    async def list_operations(self, actor_id, limit=10):
        return tuple(reversed(tuple(self.rows.values())))[:limit]


class Provider:
    def __init__(self, persistence):
        self.persistence = persistence
        self.calls = []
        self.prepare_error = None
        self.error = None
        self.result = None

    def prepare(self, operation):
        if self.prepare_error:
            raise self.prepare_error
        return AuthorityOperationIntent(operation, CLIENT_ID)

    async def execute(self, intent):
        started = tuple(self.persistence.rows.values())[-1]
        assert started.status is Status.STARTED and started.request_hash == intent.request_hash
        self.calls.append(intent)
        if self.error:
            raise self.error
        return self.result or AuthorityOperationCompletion(Status.SUCCEEDED,
            Code.CREATED_AND_VERIFIED if intent.operation is Kind.REGISTER_RF1086_SYSTEM
            else Code.CALLBACK_UPDATED_AND_VERIFIED, 200)


def setup():
    persistence = Persistence()
    provider = Provider(persistence)
    return AuthorityOperationsService(persistence, provider), persistence, provider


def test_operator_must_be_current_admin_with_fresh_mfa_before_any_provider_or_audit_effect():
    class Denied:
        async def authorize_operator(self, actor_id, *, require_fresh_mfa):
            assert actor_id == ACTOR and require_fresh_mfa is True
            raise AuthorityOperationError(Code.ADMIN_OPERATOR_REQUIRED)

    service = AuthorityOperationsService(Denied(), object())
    command = RunAuthorityOperationCommand(ACTOR, OPERATION_ID, Kind.REGISTER_RF1086_SYSTEM,
                                          "REGISTER TALLI RF1086 SYSTEM")
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command))
    assert error.value.code == Code.ADMIN_OPERATOR_REQUIRED


@pytest.mark.parametrize("kind,expected_hash,expected_body_hash", [
    (Kind.REGISTER_RF1086_SYSTEM, "e7bb4a835d1e57badd615340603e969150ebab696aef6a597f17fa6f64e431c1",
     "df80d43a5301b338202fcc075a24f5347a0756be79981696cebbe4186bc59404"),
    (Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK, "88450a24fecb27edbe59e609e0115330c419ed1b0ca8eb50ff6842497290fc2f",
     "36f1e14ca0791d33517b60f099842d1b21935799f8e484681b0b528104d9e01a"),
])
def test_fixed_intent_preserves_legacy_canonical_hash_and_exact_json_bytes(kind, expected_hash, expected_body_hash):
    # Literals independently captured from the unchanged legacy TypeScript
    # definition builders with the fixed synthetic client UUID above.
    intent = AuthorityOperationIntent(kind, CLIENT_ID)
    assert intent.request_hash == expected_hash
    assert sha256(intent.request_body).hexdigest() == expected_body_hash


@pytest.mark.parametrize("kind", list(Kind))
def test_exact_admin_operation_commits_started_before_provider_and_retains_immutable_audit(kind):
    service, persistence, provider = setup()
    result = asyncio.run(service.run(command(kind)))
    assert result.status is Status.SUCCEEDED and result.completed_at == LATER
    assert result.request_hash == provider.calls[0].request_hash
    assert result.metadata == provider.calls[0].metadata
    assert len(provider.calls) == 1 and persistence.authorizations == [True]
    assert asyncio.run(service.list_operations(ACTOR)) == (result,)
    assert persistence.authorizations[-1] is False


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("confirmation", ["", "REGISTER TALLI RF1086 SYSTEM ", " SET TALLI SYSTEMBRUKER CALLBACK"])
def test_confirmation_is_exact_and_does_not_create_an_audit(kind, confirmation):
    service, persistence, provider = setup()
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command(kind, confirmation=confirmation)))
    assert error.value.code == Code.AUTHORITY_OPERATION_INVALID
    assert persistence.rows == {} and provider.calls == []


@pytest.mark.parametrize("failure,expected", [
    (AuthorityOperationError(Code.AUTHORITY_OPS_DISABLED), Code.AUTHORITY_OPS_DISABLED),
    (AuthorityOperationError(Code.AUTHORITY_KEY_ID_INVALID), Code.AUTHORITY_KEY_ID_INVALID),
    (RuntimeError("private environment detail"), Code.AUTHORITY_ENVIRONMENT_INVALID),
])
def test_config_preparation_failure_has_no_audit_or_provider_activity(failure, expected):
    service, persistence, provider = setup()
    provider.prepare_error = failure
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == expected and "private" not in str(error.value)
    assert persistence.rows == {} and provider.calls == []


def test_duplicate_audit_uuid_cannot_reexecute_provider_and_new_explicit_action_can():
    service, persistence, provider = setup()
    first = asyncio.run(service.run(command()))
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == Code.AUTHORITY_OPERATION_CONFLICT
    assert len(provider.calls) == 1 and persistence.rows[OPERATION_ID] == first
    second = asyncio.run(service.run(command(operation_id="22345678-1234-4234-8234-123456789abd")))
    assert second.operation_id != first.operation_id and len(provider.calls) == 2


def test_unavailable_started_audit_prevents_external_io_and_redacts_storage_error():
    service, persistence, provider = setup()
    persistence.start_error = RuntimeError("private SQL request")
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == Code.AUTHORITY_AUDIT_START_FAILED
    assert "private" not in str(error.value) and provider.calls == []


@pytest.mark.parametrize("failure,expected,status", [
    (AuthorityOperationError(Code.AUTHORITY_TOKEN_ERROR), Code.AUTHORITY_TOKEN_ERROR, None),
    (AuthorityOperationError(Code.AUTHORITY_NETWORK_ERROR), Code.AUTHORITY_NETWORK_ERROR, None),
    (AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, 503), Code.AUTHORITY_HTTP_ERROR, 503),
    (AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID, 200), Code.AUTHORITY_RESPONSE_INVALID, 200),
    (AuthorityOperationError(Code.AUTHORITY_VERIFICATION_ERROR, 404), Code.AUTHORITY_VERIFICATION_ERROR, 404),
    (AuthorityOperationError(Code.AUTHORITY_ENVIRONMENT_INVALID), Code.AUTHORITY_OPERATION_FAILED, None),
    (RuntimeError("Bearer private-provider-body"), Code.AUTHORITY_OPERATION_FAILED, None),
])
def test_failure_is_committed_before_safe_error_and_does_not_reimpose_fresh_mfa(failure, expected, status):
    service, persistence, provider = setup()
    provider.error = failure
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == expected and error.value.authority_http_status == status
    assert "private" not in str(error.value)
    row = persistence.rows[OPERATION_ID]
    assert row.status is Status.FAILED and row.result_code is expected and row.completed_at == LATER
    assert persistence.authorizations == [True]


@pytest.mark.parametrize("provider_failure", [None, AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, 502)])
def test_completion_audit_failure_dominates_success_or_provider_failure(provider_failure):
    service, persistence, provider = setup()
    provider.error = provider_failure
    persistence.completion_error = RuntimeError("private SQL details")
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == Code.AUTHORITY_AUDIT_COMPLETION_FAILED
    assert persistence.rows[OPERATION_ID].status is Status.STARTED and len(provider.calls) == 1


def test_result_for_the_other_operation_is_failed_not_successfully_audited():
    service, persistence, provider = setup()
    provider.result = AuthorityOperationCompletion(Status.SUCCEEDED, Code.CALLBACK_ALREADY_VERIFIED, 200)
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == Code.AUTHORITY_RESPONSE_INVALID
    assert persistence.rows[OPERATION_ID].status is Status.FAILED


def test_conflict_is_a_durable_distinct_outcome():
    service, persistence, provider = setup()
    provider.result = AuthorityOperationCompletion(Status.CONFLICT, Code.DEFINITION_CONFLICT, 200)
    row = asyncio.run(service.run(command()))
    assert row.status is Status.CONFLICT and row.result_code is Code.DEFINITION_CONFLICT


@pytest.mark.parametrize("stage", ["begin", "complete"])
def test_store_cannot_substitute_another_immutable_intent(stage):
    service, persistence, provider = setup()
    original = persistence.begin_operation if stage == "begin" else persistence.complete_operation
    async def substitute(*args):
        return replace(await original(*args), request_hash="0" * 64)
    if stage == "begin":
        persistence.begin_operation = substitute
    else:
        persistence.complete_operation = substitute
    with pytest.raises(AuthorityOperationError) as error:
        asyncio.run(service.run(command()))
    assert error.value.code == (Code.AUTHORITY_AUDIT_START_FAILED if stage == "begin" else Code.AUTHORITY_AUDIT_COMPLETION_FAILED)
    assert len(provider.calls) == (0 if stage == "begin" else 1)
