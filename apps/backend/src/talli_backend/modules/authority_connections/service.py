"""Private owner System User lifecycle; persistence and provider I/O use ports."""

from __future__ import annotations

from collections.abc import Callable
import secrets

from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError, AuthorityConnectionsErrorCode as Code,
    AuthorityFailureCode as Failure, AuthorityProviderError,
    ReconcileSystemUserRequestCommand, StartSystemUserRequestCommand,
    SystemUserAuthorityProvider, SystemUserFlowResult, SystemUserIdentity,
    SystemUserOwner, SystemUserPersistence, SystemUserRequest,
    SystemUserRequestObservation, SystemUserRequestStatus as Status,
    SystemUserStateUpdate, SYSTEM_USER_CALLBACK_PATH, SYSTEM_USER_CALLBACK_URL,
    SYSTEM_USER_CONFIRMATION_PREFIX, SYSTEM_USER_OBLIGATION, SYSTEM_USER_RIGHT,
    SYSTEM_USER_SYSTEM_ID,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, ErrorCategory


_TRANSITIONS = {
    Status.CREATING: frozenset(Status),
    Status.NEW: frozenset(Status) - {Status.CREATING},
    Status.ACCEPTED: frozenset((Status.ACCEPTED, Status.VERIFICATION_FAILED)),
    Status.VERIFICATION_FAILED: frozenset((Status.VERIFICATION_FAILED, Status.ACCEPTED)),
    Status.REJECTED: frozenset((Status.REJECTED,)),
    Status.DENIED: frozenset((Status.DENIED,)),
    Status.TIMEDOUT: frozenset((Status.TIMEDOUT,)),
}
_TOKEN_FAILURES = frozenset((
    Failure.MASKINPORTEN_GRANT_SIGNING_FAILED, Failure.MASKINPORTEN_NETWORK_ERROR,
    Failure.MASKINPORTEN_HTTP_ERROR, Failure.MASKINPORTEN_RESPONSE_INVALID,
    Failure.MASKINPORTEN_TOKEN_ERROR,
))


def _assert_transition(current: Status, observed: Status) -> None:
    if observed not in _TRANSITIONS[current]:
        raise AuthorityConnectionsError(Code.INVALID_TRANSITION)


def _failure_code(error: Exception) -> Failure:
    return error.code if isinstance(error, AuthorityProviderError) else Failure.RESPONSE_CONTRACT_MISMATCH


def _ambiguous_create(error: Exception) -> bool:
    return isinstance(error, AuthorityProviderError) and error.code not in _TOKEN_FAILURES and (
        error.code in (Failure.DUPLICATE_SYSTEM_USER_REQUEST, Failure.NETWORK_ERROR) or error.retryable
    )


def _recovery_pending() -> AuthorityConnectionsError:
    return AuthorityConnectionsError(Code.SYSTEM_USER_REQUEST_RECOVERY_PENDING, ErrorCategory.DEPENDENCY_UNAVAILABLE)


def _result(request: SystemUserRequest) -> SystemUserFlowResult:
    return SystemUserFlowResult(
        request.request_id, request.identity.company_id, request.status,
        request.preflight_verified_at, request.confirmation_url, request.failure_code,
    )


def _assert_request(
    request: SystemUserRequest,
    owner: SystemUserOwner,
    request_id: str,
    identity: SystemUserIdentity | None = None,
) -> None:
    if (
        request.request_id != request_id
        or request.identity.company_id != owner.company_id
        or request.identity.owner_id != owner.actor_id.subject
        or request.identity.organization_number != owner.organization_number
        or request.obligation != SYSTEM_USER_OBLIGATION
        or (identity is not None and request.identity != identity)
        or (request.preflight_verified_at is not None and (
            request.status is not Status.ACCEPTED or request.provider_request_id is None
        ))
        or (request.confirmation_url is not None and (
            request.provider_request_id is None
            or request.confirmation_url != SYSTEM_USER_CONFIRMATION_PREFIX + request.provider_request_id
        ))
    ):
        raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)


def _assert_observation(observation: SystemUserRequestObservation, request: SystemUserRequest) -> None:
    if (
        observation.external_reference != request.identity.external_reference
        or observation.organization_number != request.identity.organization_number
        or observation.system_id != SYSTEM_USER_SYSTEM_ID
        or observation.right != SYSTEM_USER_RIGHT
        or observation.callback_url != SYSTEM_USER_CALLBACK_URL
        or (request.provider_request_id is not None
            and observation.provider_request_id != request.provider_request_id)
        or (observation.confirmation_url is not None and
            observation.confirmation_url != SYSTEM_USER_CONFIRMATION_PREFIX + observation.provider_request_id)
    ):
        raise AuthorityProviderError(Failure.RESPONSE_CONTRACT_MISMATCH)


class AuthorityConnectionsService:
    def __init__(
        self, persistence: SystemUserPersistence, provider: SystemUserAuthorityProvider,
        *, generate_external_reference: Callable[[], str] | None = None,
    ) -> None:
        self._persistence = persistence
        self._provider = provider
        self._generate_external_reference = generate_external_reference or (lambda: secrets.token_urlsafe(32))

    async def _owner(
        self, company_id: CompanyId, actor_id: ActorId, *, require_fresh_mfa: bool,
    ) -> SystemUserOwner:
        if actor_id.kind is not ActorKind.USER:
            raise AuthorityConnectionsError(Code.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
        owner = await self._persistence.authorize_owner(
            company_id, actor_id, require_fresh_mfa=require_fresh_mfa,
        )
        if owner.company_id != company_id or owner.actor_id != actor_id:
            raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        return owner

    async def _verify_callback(self, owner: SystemUserOwner) -> None:
        try:
            evidence = await self._persistence.latest_callback_operation(owner)
        except Exception:
            raise AuthorityConnectionsError(Code.CALLBACK_NOT_VERIFIED) from None
        if (
            evidence is None
            or evidence.operation != "set_rf1086_systembruker_callback"
            or evidence.status != "succeeded"
            or evidence.result_code not in ("callback_already_verified", "callback_updated_and_verified")
            or sorted(evidence.metadata) != [
                ("callbackPath", SYSTEM_USER_CALLBACK_PATH), ("systemId", SYSTEM_USER_SYSTEM_ID),
            ]
        ):
            raise AuthorityConnectionsError(Code.CALLBACK_NOT_VERIFIED)

    async def start(self, command: StartSystemUserRequestCommand) -> SystemUserFlowResult:
        owner = await self._owner(command.company_id, command.actor_id, require_fresh_mfa=True)
        await self._verify_callback(owner)
        try:
            identity = SystemUserIdentity(
                owner.company_id, owner.actor_id.subject, owner.organization_number,
                self._generate_external_reference(),
            )
        except (ValueError, TypeError):
            raise AuthorityConnectionsError(Code.INVALID_SYSTEM_USER_REQUEST, ErrorCategory.INVALID_INPUT) from None
        try:
            request = await self._persistence.begin_request(owner, command.request_id, identity.external_reference)
        except Exception:
            raise AuthorityConnectionsError(Code.SYSTEM_USER_REQUEST_START_FAILED) from None
        _assert_request(request, owner, command.request_id, identity)
        if request.status is not Status.CREATING or request.provider_request_id is not None:
            raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        try:
            observation = await self._provider.create_request(request.identity)
        except Exception as error:
            if isinstance(error, AuthorityProviderError) and error.code in _TOKEN_FAILURES:
                raise _recovery_pending() from None
            if _ambiguous_create(error):
                try:
                    return _result(await self._recover_creating(owner, request, allow_create_if_absent=False))
                except AuthorityConnectionsError:
                    raise
                except Exception:
                    raise _recovery_pending() from None
            return _result(await self._failure_or_recovery(owner, request, _failure_code(error)))
        return _result(await self._persist_created(owner, request, observation))

    async def _persist_response(
        self, owner: SystemUserOwner, request: SystemUserRequest, observation: SystemUserRequestObservation,
    ) -> SystemUserRequest:
        _assert_observation(observation, request)
        _assert_transition(request.status, observation.status)
        updated = await self._persistence.record_authority_state(owner, SystemUserStateUpdate(
            request.request_id, request.identity, observation.provider_request_id,
            observation.status, observation.confirmation_url, None,
        ))
        _assert_request(updated, owner, request.request_id, request.identity)
        if updated.status is not observation.status or updated.provider_request_id != observation.provider_request_id:
            raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        return updated

    async def _persist_failure(
        self, owner: SystemUserOwner, request: SystemUserRequest, failure: Failure,
    ) -> SystemUserRequest:
        _assert_transition(request.status, Status.VERIFICATION_FAILED)
        updated = await self._persistence.record_authority_state(owner, SystemUserStateUpdate(
            request.request_id, request.identity, request.provider_request_id,
            Status.VERIFICATION_FAILED, request.confirmation_url, failure,
        ))
        _assert_request(updated, owner, request.request_id, request.identity)
        if (
            updated.status is not Status.VERIFICATION_FAILED or updated.failure_code is not failure
            or updated.provider_request_id != request.provider_request_id
        ):
            raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        return updated

    async def _failure_or_recovery(
        self, owner: SystemUserOwner, request: SystemUserRequest, failure: Failure,
    ) -> SystemUserRequest:
        try:
            return await self._persist_failure(owner, request, failure)
        except Exception:
            raise _recovery_pending() from None

    async def _persist_created(
        self, owner: SystemUserOwner, request: SystemUserRequest, observation: SystemUserRequestObservation,
    ) -> SystemUserRequest:
        try:
            if observation.status is not Status.NEW:
                raise AuthorityProviderError(Failure.RESPONSE_CONTRACT_MISMATCH)
            _assert_observation(observation, request)
            _assert_transition(request.status, observation.status)
        except Exception as error:
            return await self._failure_or_recovery(owner, request, _failure_code(error))
        try:
            return await self._persist_response(owner, request, observation)
        except Exception:
            raise _recovery_pending() from None

    async def _persist_recovered(
        self, owner: SystemUserOwner, request: SystemUserRequest, observation: SystemUserRequestObservation,
    ) -> SystemUserRequest:
        try:
            _assert_observation(observation, request)
            _assert_transition(request.status, observation.status)
        except Exception as error:
            return await self._failure_or_recovery(owner, request, _failure_code(error))
        try:
            return await self._persist_response(owner, request, observation)
        except Exception:
            raise _recovery_pending() from None

    async def _recover_creating(
        self, owner: SystemUserOwner, request: SystemUserRequest, *, allow_create_if_absent: bool,
    ) -> SystemUserRequest:
        try:
            recovered = await self._provider.find_request(request.identity)
        except Exception as error:
            if isinstance(error, AuthorityProviderError) and error.code is Failure.RESPONSE_CONTRACT_MISMATCH:
                return await self._failure_or_recovery(owner, request, error.code)
            independently_absent = (
                isinstance(error, AuthorityProviderError) and error.code is Failure.AUTHORITY_HTTP_ERROR
                and error.status == 404
            )
            if not independently_absent or not allow_create_if_absent:
                raise _recovery_pending() from None
        else:
            return await self._persist_recovered(owner, request, recovered)

        await self._verify_callback(owner)
        try:
            created = await self._provider.create_request(request.identity)
        except Exception as error:
            if _ambiguous_create(error) or (
                isinstance(error, AuthorityProviderError) and error.code in _TOKEN_FAILURES
            ):
                raise _recovery_pending() from None
            return await self._failure_or_recovery(owner, request, _failure_code(error))
        return await self._persist_created(owner, request, created)

    async def retry(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult:
        owner = await self._owner(
            command.company_id, command.actor_id, require_fresh_mfa=command.require_fresh_mfa,
        )
        request = await self._persistence.read_request(owner, command.request_id)
        _assert_request(request, owner, command.request_id)
        if request.status is Status.CREATING:
            return _result(await self._recover_creating(owner, request, allow_create_if_absent=True))
        return await self._reconcile_request(owner, request)

    async def reconcile(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult:
        owner = await self._owner(
            command.company_id, command.actor_id, require_fresh_mfa=command.require_fresh_mfa,
        )
        request = await self._persistence.read_request(owner, command.request_id)
        _assert_request(request, owner, command.request_id)
        return await self._reconcile_request(owner, request)

    async def _reconcile_request(
        self, owner: SystemUserOwner, request: SystemUserRequest,
    ) -> SystemUserFlowResult:
        # A failed status read does not assert a new authority state. The
        # callback/ordinary transports retain their fixed safe retry outcome.
        observation = (
            await self._provider.find_request(request.identity)
            if request.provider_request_id is None else
            await self._provider.get_request(request.identity, request.provider_request_id)
        )
        _assert_observation(observation, request)
        if observation.status is not Status.ACCEPTED:
            return _result(await self._persist_response(owner, request, observation))

        current = request
        try:
            system_user = await self._provider.query_system_user(request.identity)
            if (
                system_user.system_id != SYSTEM_USER_SYSTEM_ID
                or system_user.organization_number != request.identity.organization_number
                or system_user.external_reference != request.identity.external_reference
                or system_user.user_type != "standard"
                or system_user.deleted
            ):
                raise AuthorityProviderError(Failure.RESPONSE_CONTRACT_MISMATCH)
            current = await self._persist_response(owner, request, observation)
            if current.preflight_verified_at is not None:
                return _result(current)
            # Adapter acquires and discards the exact delegated token before
            # this committed preflight mark; no credential enters this module.
            await self._provider.verify_delegation(request.identity)
            verified = await self._persistence.verify_preflight(
                owner, request.request_id, request.identity.external_reference,
            )
            _assert_request(verified, owner, request.request_id, request.identity)
            if (
                verified.status is not Status.ACCEPTED or verified.preflight_verified_at is None
                or verified.provider_request_id != current.provider_request_id
            ):
                raise AuthorityProviderError(Failure.RESPONSE_CONTRACT_MISMATCH)
            return _result(verified)
        except Exception as error:
            # The existing accepted path treats provider/contract failures as
            # safe verification failure; the named state workflow owns any
            # atomic suspension of already-linked authorization.
            failure = error.code if isinstance(error, AuthorityProviderError) else (
                Failure.MASKINPORTEN_HTTP_ERROR if isinstance(getattr(error, "status", None), int)
                else Failure.MASKINPORTEN_TOKEN_ERROR
            )
            return _result(await self._persist_failure(owner, current, failure))

    async def read(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult:
        owner = await self._owner(command.company_id, command.actor_id, require_fresh_mfa=False)
        request = await self._persistence.read_request(owner, command.request_id)
        _assert_request(request, owner, command.request_id)
        return _result(request)

    async def resolve_owner(self, request_id: str, actor_id: ActorId) -> SystemUserOwner:
        if actor_id.kind is not ActorKind.USER:
            raise AuthorityConnectionsError(Code.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
        owner = await self._persistence.resolve_request_owner(request_id, actor_id)
        if owner.actor_id != actor_id:
            raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        return owner

    async def list_requests(
        self, *, company_ids: tuple[CompanyId, ...], actor_id: ActorId,
    ) -> tuple[SystemUserRequest, ...]:
        if actor_id.kind is not ActorKind.USER:
            raise AuthorityConnectionsError(Code.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
        requests = await self._persistence.list_requests(company_ids, actor_id)
        for request in requests:
            if request.identity.company_id not in company_ids or request.identity.owner_id != actor_id.subject:
                raise AuthorityConnectionsError(Code.SYSTEM_USER_RELATIONSHIP_MISMATCH)
            _assert_request(request, SystemUserOwner(
                request.identity.company_id, actor_id, request.identity.organization_number,
            ), request.request_id)
        return requests
