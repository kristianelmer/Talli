"""Existing RF owner connection behavior at the public service/port boundary."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from talli_backend.modules.authority_connections.public import (
    StartSystemUserRequestCommand,
    ReconcileSystemUserRequestCommand,
    SystemUserCallbackOperation,
    SystemUserFlowResult,
    SystemUserIdentity,
    SystemUserOwner,
    SystemUserRequest,
    SystemUserRequestObservation,
    SystemUserStateUpdate,
    SystemUserRequestStatus as Status,
    QueriedSystemUser,
    AuthorityFailureCode as Failure,
    AuthorityProviderError,
    AuthorityConnectionsError,
    AuthorityConnectionsErrorCode as Code,
)
from talli_backend.modules.authority_connections.service import AuthorityConnectionsService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, Timestamp, UserId


COMPANY = CompanyId("12345678-1234-4234-8234-123456789abc")
OWNER_ID = UserId("32345678-1234-4234-8234-123456789abc")
ACTOR = ActorId(ActorKind.USER, OWNER_ID)
REQUEST_ID = "22345678-1234-4234-8234-123456789abc"
PROVIDER_ID = "42345678-1234-4234-8234-123456789abc"
EXTERNAL_REF = "A" * 43
OWNER = SystemUserOwner(COMPANY, ACTOR, "310279617")
IDENTITY = SystemUserIdentity(COMPANY, OWNER_ID, "310279617", EXTERNAL_REF)
NOW = Timestamp(datetime(2026, 7, 16, 12, tzinfo=UTC))
CONFIRM_URL = f"https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id={PROVIDER_ID}"
START = StartSystemUserRequestCommand(COMPANY, ACTOR, REQUEST_ID)
RECONCILE = ReconcileSystemUserRequestCommand(COMPANY, ACTOR, REQUEST_ID)


def row(status=Status.CREATING, **changes):
    return replace(SystemUserRequest(
        request_id=REQUEST_ID, identity=IDENTITY, status=status,
        provider_request_id=None if status is Status.CREATING else PROVIDER_ID,
        confirmation_url=CONFIRM_URL if status is Status.NEW else None,
        created_at=NOW, updated_at=NOW,
    ), **changes)


def observation(status=Status.NEW, **changes):
    return replace(SystemUserRequestObservation(
        provider_request_id=PROVIDER_ID, external_reference=EXTERNAL_REF,
        organization_number="310279617", system_id="930835978_talli",
        right="ske-innrapportering-aksjonaerregisteroppgave",
        callback_url="https://talli.no/auth/systembruker/confirm", status=status,
        confirmation_url=CONFIRM_URL if status is Status.NEW else None,
    ), **changes)


class MemoryPersistence:
    """Transactional boundary fake; state is read through service public queries."""

    def __init__(self, request=None):
        self.request = request
        self.authorized = True
        self.fresh_mfa = True
        self.effects = []
        self.fail_writes = 0
        self.suspended_linked_grant = False
        self.callback = SystemUserCallbackOperation(
            "set_rf1086_systembruker_callback", "succeeded", "callback_updated_and_verified",
            (("systemId", "930835978_talli"), ("callbackPath", "/auth/systembruker/confirm")),
        )

    async def authorize_owner(self, company_id, actor_id, *, require_fresh_mfa):
        if not self.authorized or company_id != COMPANY or actor_id != ACTOR:
            raise AuthorityConnectionsError(Code.OWNER_REQUIRED)
        if require_fresh_mfa and not self.fresh_mfa:
            raise AuthorityConnectionsError(Code.STEP_UP_REQUIRED)
        return OWNER

    async def latest_callback_operation(self, owner):
        self.effects.append("callback_audit")
        return self.callback

    async def begin_request(self, owner, request_id, external_reference):
        if self.request is not None:
            raise RuntimeError("duplicate original request")
        self.effects.append("persist_creating")
        self.request = row()
        return self.request

    async def read_request(self, owner, request_id):
        if self.request is None or self.request.request_id != request_id:
            raise AuthorityConnectionsError(Code.REQUEST_NOT_FOUND)
        return self.request

    async def resolve_request_owner(self, request_id, actor_id):
        await self.authorize_owner(COMPANY, actor_id, require_fresh_mfa=False)
        await self.read_request(OWNER, request_id)
        return OWNER

    async def list_requests(self, company_ids, actor_id):
        await self.authorize_owner(COMPANY, actor_id, require_fresh_mfa=False)
        return (self.request,) if self.request and COMPANY in company_ids else ()

    async def record_authority_state(self, owner, update):
        await self.authorize_owner(owner.company_id, owner.actor_id, require_fresh_mfa=False)
        if self.fail_writes:
            self.fail_writes -= 1
            raise RuntimeError("private database write detail")
        self.effects.append(f"persist_{update.status}")
        if self.request.status is Status.ACCEPTED and update.status is Status.VERIFICATION_FAILED:
            self.suspended_linked_grant = True
        self.request = replace(
            self.request, status=update.status, provider_request_id=update.provider_request_id,
            confirmation_url=update.confirmation_url, failure_code=update.failure_code,
            preflight_verified_at=self.request.preflight_verified_at if update.status is Status.ACCEPTED else None,
        )
        return self.request

    async def verify_preflight(self, owner, request_id, expected_external_reference):
        await self.authorize_owner(owner.company_id, owner.actor_id, require_fresh_mfa=False)
        assert request_id == REQUEST_ID and expected_external_reference == EXTERNAL_REF
        self.effects.append("verify_preflight")
        self.request = replace(self.request, preflight_verified_at=NOW)
        return self.request


class FakeProvider:
    def __init__(self, persistence):
        self.store = persistence
        self.calls = []
        self.create_error = None
        self.find_error = None
        self.delegation_error = None
        self.created = observation()
        self.found = observation()
        self.observed = observation(Status.ACCEPTED)
        self.queried = QueriedSystemUser(
            "52345678-1234-4234-8234-123456789abc", "930835978_talli",
            "310279617", EXTERNAL_REF, "standard", False,
        )

    async def create_request(self, identity):
        # This is the external side-effect boundary: durable intent must exist
        # before the provider could observe a create, including failure cases.
        assert self.store.request.status is Status.CREATING
        assert self.store.request.identity == identity
        self.calls.append(("create", identity))
        if self.create_error:
            raise self.create_error
        return self.created

    async def find_request(self, identity):
        self.calls.append(("find", identity))
        if self.find_error:
            raise self.find_error
        return self.found

    async def get_request(self, identity, provider_request_id):
        assert provider_request_id == PROVIDER_ID
        self.calls.append(("get", identity))
        return self.observed

    async def query_system_user(self, identity):
        self.calls.append(("query", identity))
        return self.queried

    async def verify_delegation(self, identity):
        self.calls.append(("delegate", identity))
        if self.delegation_error:
            raise self.delegation_error


def setup(request=None):
    persistence = MemoryPersistence(request)
    provider = FakeProvider(persistence)
    service = AuthorityConnectionsService(
        persistence, provider, generate_external_reference=lambda: EXTERNAL_REF,
    )
    return service, persistence, provider


def test_owner_start_requires_current_authorization_before_any_other_effect() -> None:
    class DeniedPersistence:
        async def authorize_owner(self, company_id, actor_id, *, require_fresh_mfa):
            assert require_fresh_mfa is True
            raise PermissionError("denied")

    service = AuthorityConnectionsService(DeniedPersistence(), object())
    command = StartSystemUserRequestCommand(
        company_id=CompanyId("12345678-1234-4234-8234-123456789abc"),
        actor_id=ActorId(ActorKind.USER, UserId("32345678-1234-4234-8234-123456789abc")),
        request_id="22345678-1234-4234-8234-123456789abc",
    )
    try:
        asyncio.run(service.start(command))
    except PermissionError:
        return
    raise AssertionError("an unauthorized owner cannot initiate a provider request")


def test_start_persists_fixed_original_intent_before_one_provider_create_and_returns_safe_result():
    service, persistence, provider = setup()
    result = asyncio.run(service.start(START))
    assert result == SystemUserFlowResult(REQUEST_ID, COMPANY, Status.NEW, None, CONFIRM_URL, None)
    assert asyncio.run(service.read(RECONCILE)) == result
    assert persistence.effects == ["callback_audit", "persist_creating", "persist_new"]
    assert provider.calls == [("create", IDENTITY)]
    assert EXTERNAL_REF not in repr(result)
    assert "310279617" not in repr(result)


@pytest.mark.parametrize("code", [
    Failure.MASKINPORTEN_NETWORK_ERROR, Failure.MASKINPORTEN_HTTP_ERROR,
    Failure.MASKINPORTEN_TOKEN_ERROR,
])
def test_pre_create_token_failure_leaves_original_creating_intent_recoverable(code):
    service, persistence, provider = setup()
    provider.create_error = AuthorityProviderError(code)
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.start(START))
    assert failure.value.code == Code.SYSTEM_USER_REQUEST_RECOVERY_PENDING
    assert asyncio.run(service.read(RECONCILE)).status is Status.CREATING
    assert persistence.effects == ["callback_audit", "persist_creating"]
    assert [call[0] for call in provider.calls] == ["create"]


@pytest.mark.parametrize("code", [Failure.NETWORK_ERROR, Failure.DUPLICATE_SYSTEM_USER_REQUEST])
def test_ambiguous_create_reconciles_same_external_reference_without_another_create(code):
    service, _, provider = setup()
    provider.create_error = AuthorityProviderError(code, retryable=True)
    result = asyncio.run(service.start(START))
    assert result.status is Status.NEW
    assert provider.calls == [("create", IDENTITY), ("find", IDENTITY)]


def test_lost_post_create_persistence_response_retries_by_original_reference_without_create():
    service, persistence, provider = setup()
    persistence.fail_writes = 1
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.start(START))
    assert failure.value.code == Code.SYSTEM_USER_REQUEST_RECOVERY_PENDING
    assert asyncio.run(service.read(RECONCILE)).status is Status.CREATING
    recovered = asyncio.run(service.retry(RECONCILE))
    assert recovered.status is Status.NEW
    assert provider.calls == [("create", IDENTITY), ("find", IDENTITY)]


def test_accepted_reconciliation_verifies_actual_system_user_then_exact_delegation_before_preflight():
    service, persistence, provider = setup(row(Status.NEW))
    result = asyncio.run(service.reconcile(RECONCILE))
    assert result.status is Status.ACCEPTED and result.preflight_verified_at == NOW
    assert provider.calls == [("get", IDENTITY), ("query", IDENTITY), ("delegate", IDENTITY)]
    assert persistence.effects == ["persist_accepted", "verify_preflight"]


def test_already_verified_request_still_checks_actual_system_user_without_issuing_another_grant():
    service, _, provider = setup(row(Status.ACCEPTED, preflight_verified_at=NOW))
    result = asyncio.run(service.retry(RECONCILE))
    assert result.preflight_verified_at == NOW
    assert provider.calls == [("get", IDENTITY), ("query", IDENTITY)]


@pytest.mark.parametrize("changes", [
    {"deleted": True}, {"organization_number": "999999999"},
    {"external_reference": "B" * 43}, {"system_id": "other_system"},
    {"user_type": "agent"},
])
def test_wrong_or_deleted_resulting_system_user_fails_closed_without_preflight(changes):
    service, _, provider = setup(row(Status.NEW))
    provider.queried = replace(provider.queried, **changes)
    result = asyncio.run(service.reconcile(RECONCILE))
    assert result.status is Status.VERIFICATION_FAILED
    assert result.failure_code is Failure.RESPONSE_CONTRACT_MISMATCH
    assert result.preflight_verified_at is None
    assert [kind for kind, _ in provider.calls] == ["get", "query"]


def test_failed_preflight_uses_state_workflow_and_preserves_linked_grant_suspension():
    service, persistence, provider = setup(row(Status.NEW))
    provider.delegation_error = AuthorityProviderError(Failure.MASKINPORTEN_HTTP_ERROR, status=400)
    result = asyncio.run(service.reconcile(RECONCILE))
    assert result.status is Status.VERIFICATION_FAILED
    assert result.failure_code is Failure.MASKINPORTEN_HTTP_ERROR
    assert persistence.suspended_linked_grant is True
    assert persistence.effects == ["persist_accepted", "persist_verification_failed"]


def test_callback_composition_preserves_owner_auth_without_new_fresh_mfa_requirement():
    service, persistence, provider = setup(row(Status.NEW))
    persistence.fresh_mfa = False
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.reconcile(RECONCILE))
    assert failure.value.code == Code.STEP_UP_REQUIRED
    assert provider.calls == []
    resolved = asyncio.run(service.resolve_owner(REQUEST_ID, ACTOR))
    assert resolved == OWNER
    result = asyncio.run(service.reconcile(replace(RECONCILE, require_fresh_mfa=False)))
    assert result.status is Status.ACCEPTED


@pytest.mark.parametrize("callback", [
    None,
    SystemUserCallbackOperation("set_rf1086_systembruker_callback", "failed", "callback_updated_and_verified", ()),
    SystemUserCallbackOperation("register_rf1086_system", "succeeded", "created_and_verified", ()),
    SystemUserCallbackOperation("set_rf1086_systembruker_callback", "succeeded", "callback_already_verified", (
        ("systemId", "930835978_talli"), ("callbackPath", "/auth/systembruker/confirm"), ("extra", "value"),
    )),
])
def test_missing_or_inexact_latest_callback_audit_blocks_start_before_persistence_or_provider(callback):
    service, persistence, provider = setup()
    persistence.callback = callback
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.start(START))
    assert failure.value.code == Code.CALLBACK_NOT_VERIFIED
    assert persistence.request is None and provider.calls == []


def test_explicit_retry_creates_original_reference_only_after_independent_absence_and_callback_recheck():
    service, persistence, provider = setup(row())
    provider.find_error = AuthorityProviderError(Failure.AUTHORITY_HTTP_ERROR, status=404)
    result = asyncio.run(service.retry(RECONCILE))
    assert result.status is Status.NEW
    assert provider.calls == [("find", IDENTITY), ("create", IDENTITY)]
    assert persistence.effects == ["callback_audit", "persist_new"]


@pytest.mark.parametrize("find_error", [
    AuthorityProviderError(Failure.NETWORK_ERROR, retryable=True),
    AuthorityProviderError(Failure.AUTHORITY_HTTP_ERROR, status=500, retryable=True),
    AuthorityProviderError(Failure.MASKINPORTEN_HTTP_ERROR, status=404),
])
def test_unknown_or_token_failure_is_not_independent_absence_and_never_creates(find_error):
    service, _, provider = setup(row())
    provider.find_error = find_error
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.retry(RECONCILE))
    assert failure.value.code == Code.SYSTEM_USER_REQUEST_RECOVERY_PENDING
    assert provider.calls == [("find", IDENTITY)]
    assert asyncio.run(service.read(RECONCILE)).status is Status.CREATING


def test_initial_ambiguous_create_does_not_recreate_even_if_immediate_lookup_says_absent():
    service, _, provider = setup()
    provider.create_error = AuthorityProviderError(Failure.NETWORK_ERROR, retryable=True)
    provider.find_error = AuthorityProviderError(Failure.AUTHORITY_HTTP_ERROR, status=404)
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.start(START))
    assert failure.value.code == Code.SYSTEM_USER_REQUEST_RECOVERY_PENDING
    assert provider.calls == [("create", IDENTITY), ("find", IDENTITY)]


def test_retry_ambiguous_create_stops_without_another_lookup_or_create_in_same_attempt():
    service, _, provider = setup(row())
    provider.find_error = AuthorityProviderError(Failure.AUTHORITY_HTTP_ERROR, status=404)
    provider.create_error = AuthorityProviderError(Failure.DUPLICATE_SYSTEM_USER_REQUEST)
    with pytest.raises(AuthorityConnectionsError):
        asyncio.run(service.retry(RECONCILE))
    assert provider.calls == [("find", IDENTITY), ("create", IDENTITY)]


@pytest.mark.parametrize("changes", [
    {"organization_number": "999999999"}, {"external_reference": "B" * 43},
    {"system_id": "other"}, {"right": "other_right"},
    {"callback_url": "https://evil.invalid/callback"},
    {"confirmation_url": "https://evil.invalid/confirm"},
])
def test_mismatched_recovery_observation_persists_only_allowlisted_failure(changes):
    service, _, provider = setup(row())
    provider.found = observation(**changes)
    result = asyncio.run(service.retry(RECONCILE))
    assert result.status is Status.VERIFICATION_FAILED
    assert result.failure_code is Failure.RESPONSE_CONTRACT_MISMATCH
    assert result.confirmation_url is None
    assert provider.calls == [("find", IDENTITY)]


def test_create_accepts_only_new_and_never_marks_an_unexpected_accepted_response_verified():
    service, _, provider = setup()
    provider.created = observation(Status.ACCEPTED)
    result = asyncio.run(service.start(START))
    assert result.status is Status.VERIFICATION_FAILED
    assert result.confirmation_url is None and result.preflight_verified_at is None
    assert provider.calls == [("create", IDENTITY)]


@pytest.mark.parametrize("status", [Status.REJECTED, Status.DENIED, Status.TIMEDOUT])
def test_terminal_authority_outcome_cannot_be_reopened_by_provider_response(status):
    service, persistence, provider = setup(row(status))
    provider.observed = observation(Status.NEW)
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.reconcile(RECONCILE))
    assert failure.value.code == Code.INVALID_TRANSITION
    assert asyncio.run(service.read(RECONCILE)).status is status
    assert persistence.effects == []


def test_repeated_start_identity_cannot_cause_a_second_create():
    service, _, provider = setup()
    asyncio.run(service.start(START))
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.start(START))
    assert failure.value.code == Code.SYSTEM_USER_REQUEST_START_FAILED
    assert provider.calls == [("create", IDENTITY)]


def test_existing_accepted_lookup_is_not_preflight_evidence_until_normal_reconciliation():
    service, _, provider = setup(row())
    provider.found = observation(Status.ACCEPTED)
    recovered = asyncio.run(service.retry(RECONCILE))
    assert recovered.status is Status.ACCEPTED and recovered.preflight_verified_at is None
    assert provider.calls == [("find", IDENTITY)]
    verified = asyncio.run(service.retry(RECONCILE))
    assert verified.preflight_verified_at == NOW


def test_owner_reads_preserve_order_and_original_identity_without_requiring_fresh_mfa():
    service, persistence, provider = setup(row(Status.NEW))
    persistence.fresh_mfa = False
    assert asyncio.run(service.read(RECONCILE)).request_id == REQUEST_ID
    listed = asyncio.run(service.list_requests(company_ids=(COMPANY,), actor_id=ACTOR))
    assert listed == (persistence.request,)
    assert listed[0].identity == IDENTITY
    assert provider.calls == []


@pytest.mark.parametrize("changed", [
    replace(IDENTITY, owner_id=UserId("62345678-1234-4234-8234-123456789abc")),
    replace(IDENTITY, company_id=CompanyId("72345678-1234-4234-8234-123456789abc")),
])
def test_wrong_owner_or_company_record_is_not_returned_or_used_for_provider_calls(changed):
    service, _, provider = setup(row(Status.NEW, identity=changed))
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.reconcile(RECONCILE))
    assert failure.value.code == Code.SYSTEM_USER_RELATIONSHIP_MISMATCH
    with pytest.raises(AuthorityConnectionsError):
        asyncio.run(service.list_requests(company_ids=(COMPANY,), actor_id=ACTOR))
    assert provider.calls == []


def test_preflight_result_cannot_switch_the_original_provider_request_identity():
    service, persistence, _ = setup(row(Status.NEW))

    async def wrong_preflight(owner, request_id, expected_external_reference):
        return replace(
            persistence.request, preflight_verified_at=NOW,
            provider_request_id="82345678-1234-4234-8234-123456789abc",
        )

    persistence.verify_preflight = wrong_preflight
    result = asyncio.run(service.reconcile(RECONCILE))
    assert result.status is Status.VERIFICATION_FAILED
    assert result.failure_code is Failure.RESPONSE_CONTRACT_MISMATCH
    assert persistence.suspended_linked_grant is True


def test_unbound_stored_preflight_evidence_cannot_be_reported_ready():
    service, _, _ = setup(row(Status.ACCEPTED, provider_request_id=None, preflight_verified_at=NOW))
    with pytest.raises(AuthorityConnectionsError) as failure:
        asyncio.run(service.read(RECONCILE))
    assert failure.value.code == Code.SYSTEM_USER_RELATIONSHIP_MISMATCH


@pytest.mark.parametrize("changes", [
    {"identity": {"company": "mutable"}}, {"status": "new"},
    {"failure_code": "raw provider diagnostic"}, {"confirmation_url": ["mutable"]},
])
def test_state_write_contract_rejects_mutable_or_untyped_authority_facts(changes):
    values = dict(
        request_id=REQUEST_ID, identity=IDENTITY, provider_request_id=PROVIDER_ID,
        status=Status.NEW, confirmation_url=CONFIRM_URL, failure_code=None,
    )
    values.update(changes)
    with pytest.raises(ValueError):
        SystemUserStateUpdate(**values)
