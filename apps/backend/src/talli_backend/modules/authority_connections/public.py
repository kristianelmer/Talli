"""Immutable RF owner connection contracts and credential-free outbound ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Protocol, TypeVar
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId, CompanyId, DomainError, ErrorCategory, Timestamp, UserId,
)


SYSTEM_USER_SYSTEM_ID = "930835978_talli"
SYSTEM_USER_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave"
SYSTEM_USER_OBLIGATION = "aksjonaerregisteroppgaven"
SYSTEM_USER_CALLBACK_URL = "https://talli.no/auth/systembruker/confirm"
SYSTEM_USER_CALLBACK_PATH = "/auth/systembruker/confirm"
SYSTEM_USER_CONFIRMATION_PREFIX = "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id="


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid system user identifier") from None


def _organization_number(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{9}", value):
        raise ValueError("invalid system user organization number")


class SystemUserRequestStatus(StrEnum):
    CREATING = "creating"
    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DENIED = "denied"
    TIMEDOUT = "timedout"
    VERIFICATION_FAILED = "verification_failed"


class AuthorityFailureCode(StrEnum):
    INVALID_ENVIRONMENT = "invalid_environment"
    INVALID_TIMEOUT = "invalid_timeout"
    INVALID_BEARER_TOKEN = "invalid_bearer_token"
    INVALID_ORGANIZATION_NUMBER = "invalid_organization_number"
    INVALID_EXTERNAL_REFERENCE = "invalid_external_reference"
    INVALID_REQUEST_ID = "invalid_request_id"
    NETWORK_ERROR = "network_error"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_CONTRACT_MISMATCH = "response_contract_mismatch"
    INVALID_CONFIRMATION_URL = "invalid_confirmation_url"
    DUPLICATE_SYSTEM_USER_REQUEST = "duplicate_system_user_request"
    AUTHORITY_HTTP_ERROR = "authority_http_error"
    MASKINPORTEN_GRANT_SIGNING_FAILED = "maskinporten_grant_signing_failed"
    MASKINPORTEN_NETWORK_ERROR = "maskinporten_network_error"
    MASKINPORTEN_HTTP_ERROR = "maskinporten_http_error"
    MASKINPORTEN_RESPONSE_INVALID = "maskinporten_response_invalid"
    MASKINPORTEN_TOKEN_ERROR = "maskinporten_token_error"


class AuthorityProviderError(Exception):
    """Sanitized provider failure; never retains raw response or credentials."""

    def __init__(
        self,
        code: AuthorityFailureCode,
        *,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = AuthorityFailureCode(code)
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise ValueError("invalid authority HTTP status")
        if type(retryable) is not bool:
            raise ValueError("invalid authority retry classification")
        self.status = status
        self.retryable = retryable
        super().__init__(self.code.value)


class AuthorityConnectionsErrorCode(StrEnum):
    CALLBACK_NOT_VERIFIED = "callback_not_verified"
    INVALID_SYSTEM_USER_REQUEST = "invalid_system_user_request"
    SYSTEM_USER_RELATIONSHIP_MISMATCH = "system_user_relationship_mismatch"
    SYSTEM_USER_REQUEST_START_FAILED = "system_user_request_start_failed"
    SYSTEM_USER_REQUEST_RECOVERY_PENDING = "system_user_request_recovery_pending"
    OWNER_REQUIRED = "system_user_request_owner_required"
    REQUEST_NOT_FOUND = "system_user_request_not_found"
    INVALID_TRANSITION = "invalid_system_user_transition"
    STEP_UP_REQUIRED = "step_up_required"
    DEPENDENCY_UNAVAILABLE = "authority_connections_unavailable"


class AuthorityConnectionsError(DomainError):
    def __init__(
        self,
        code: AuthorityConnectionsErrorCode,
        category: ErrorCategory = ErrorCategory.PRECONDITION_FAILED,
    ) -> None:
        super().__init__(code=AuthorityConnectionsErrorCode(code).value, category=category)


@dataclass(frozen=True, slots=True)
class SystemUserOwner:
    """Current owner/company facts returned only by a verified authorization port."""

    company_id: CompanyId
    actor_id: ActorId
    organization_number: str

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, CompanyId) or not isinstance(self.actor_id, ActorId):
            raise ValueError("invalid system user owner identity")
        _organization_number(self.organization_number)


@dataclass(frozen=True, slots=True)
class SystemUserIdentity:
    company_id: CompanyId
    owner_id: UserId
    organization_number: str
    external_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, CompanyId) or not isinstance(self.owner_id, UserId):
            raise ValueError("invalid system user identity")
        _organization_number(self.organization_number)
        if not isinstance(self.external_reference, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", self.external_reference
        ):
            raise ValueError("invalid system user external reference")


@dataclass(frozen=True, slots=True)
class StartSystemUserRequestCommand:
    company_id: CompanyId
    actor_id: ActorId
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, CompanyId) or not isinstance(self.actor_id, ActorId):
            raise ValueError("invalid system user command identity")
        object.__setattr__(self, "request_id", _uuid(self.request_id))


@dataclass(frozen=True, slots=True)
class ReconcileSystemUserRequestCommand:
    company_id: CompanyId
    actor_id: ActorId
    request_id: str
    # Composition selects False only for the authenticated callback. This flag
    # is never an HTTP request-body field or caller-supplied authorization fact.
    require_fresh_mfa: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, CompanyId) or not isinstance(self.actor_id, ActorId):
            raise ValueError("invalid system user command identity")
        object.__setattr__(self, "request_id", _uuid(self.request_id))
        if type(self.require_fresh_mfa) is not bool:
            raise ValueError("invalid system user authorization requirement")


@dataclass(frozen=True, slots=True)
class SystemUserCallbackOperation:
    operation: str
    status: str
    result_code: str
    metadata: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (self.operation, self.status, self.result_code)):
            raise ValueError("invalid system user callback evidence")
        if not isinstance(self.metadata, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2
            or any(not isinstance(value, str) for value in item)
            for item in self.metadata
        ):
            raise ValueError("invalid system user callback evidence")


@dataclass(frozen=True, slots=True)
class SystemUserRequest:
    request_id: str
    identity: SystemUserIdentity
    status: SystemUserRequestStatus
    provider_request_id: str | None = None
    confirmation_url: str | None = None
    preflight_verified_at: Timestamp | None = None
    failure_code: AuthorityFailureCode | None = None
    operator_evidence_id: str | None = None
    obligation: str = SYSTEM_USER_OBLIGATION
    requested_at: Timestamp | None = None
    last_status_checked_at: Timestamp | None = None
    accepted_at: Timestamp | None = None
    resolved_at: Timestamp | None = None
    created_at: Timestamp | None = None
    updated_at: Timestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SystemUserIdentity) or not isinstance(self.obligation, str):
            raise ValueError("invalid system user request identity")
        if self.confirmation_url is not None and not isinstance(self.confirmation_url, str):
            raise ValueError("invalid system user confirmation URL")
        for value in (
            self.preflight_verified_at, self.requested_at, self.last_status_checked_at,
            self.accepted_at, self.resolved_at, self.created_at, self.updated_at,
        ):
            if value is not None and not isinstance(value, Timestamp):
                raise ValueError("invalid system user timestamp")
        object.__setattr__(self, "request_id", _uuid(self.request_id))
        if self.provider_request_id is not None:
            object.__setattr__(self, "provider_request_id", _uuid(self.provider_request_id))
        if self.operator_evidence_id is not None:
            object.__setattr__(self, "operator_evidence_id", _uuid(self.operator_evidence_id))
        if not isinstance(self.status, SystemUserRequestStatus):
            raise ValueError("invalid system user request status")
        if self.failure_code is not None and not isinstance(self.failure_code, AuthorityFailureCode):
            raise ValueError("invalid system user failure code")


@dataclass(frozen=True, slots=True)
class SystemUserRequestObservation:
    provider_request_id: str
    external_reference: str
    organization_number: str
    system_id: str
    right: str
    callback_url: str
    status: SystemUserRequestStatus
    confirmation_url: str | None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (
            self.external_reference, self.organization_number, self.system_id, self.right, self.callback_url,
        )) or (self.confirmation_url is not None and not isinstance(self.confirmation_url, str)):
            raise ValueError("invalid system user request observation")
        object.__setattr__(self, "provider_request_id", _uuid(self.provider_request_id))
        if not isinstance(self.status, SystemUserRequestStatus) or self.status in (
            SystemUserRequestStatus.CREATING, SystemUserRequestStatus.VERIFICATION_FAILED,
        ):
            raise ValueError("invalid provider system user request status")


@dataclass(frozen=True, slots=True)
class QueriedSystemUser:
    system_user_id: str
    system_id: str
    organization_number: str
    external_reference: str
    user_type: str
    deleted: bool

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (
            self.system_id, self.organization_number, self.external_reference, self.user_type,
        )):
            raise ValueError("invalid queried system user")
        object.__setattr__(self, "system_user_id", _uuid(self.system_user_id))
        if type(self.deleted) is not bool:
            raise ValueError("invalid system user deletion state")


@dataclass(frozen=True, slots=True)
class SystemUserStateUpdate:
    request_id: str
    identity: SystemUserIdentity
    provider_request_id: str | None
    status: SystemUserRequestStatus
    confirmation_url: str | None
    failure_code: AuthorityFailureCode | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _uuid(self.request_id))
        if self.provider_request_id is not None:
            object.__setattr__(self, "provider_request_id", _uuid(self.provider_request_id))
        if (
            not isinstance(self.identity, SystemUserIdentity)
            or not isinstance(self.status, SystemUserRequestStatus)
            or (self.failure_code is not None and not isinstance(self.failure_code, AuthorityFailureCode))
            or (self.confirmation_url is not None and not isinstance(self.confirmation_url, str))
        ):
            raise ValueError("invalid system user state update")


@dataclass(frozen=True, slots=True)
class SystemUserFlowResult:
    """Safe owner-facing result; no provider identity, organization or secrets."""

    request_id: str
    company_id: CompanyId
    status: SystemUserRequestStatus
    preflight_verified_at: Timestamp | None
    confirmation_url: str | None
    failure_code: AuthorityFailureCode | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _uuid(self.request_id))
        if (
            not isinstance(self.company_id, CompanyId)
            or not isinstance(self.status, SystemUserRequestStatus)
            or (self.failure_code is not None and not isinstance(self.failure_code, AuthorityFailureCode))
            or (self.confirmation_url is not None and not isinstance(self.confirmation_url, str))
            or (self.preflight_verified_at is not None and not isinstance(self.preflight_verified_at, Timestamp))
        ):
            raise ValueError("invalid system user flow result")


class SystemUserAuthorityProvider(Protocol):
    """Fixed RF authority operations; adapter acquires/discards scoped tokens.

    create/query use the fixed control write scope; get/find the read scope;
    verify_delegation acquires and discards the exact RF delegated grant.
    All response shape/field-count validation remains mandatory at the adapter.
    A token failure before create raises a maskinporten_* code and must not be
    confused with an ambiguous provider create.
    """

    async def create_request(self, identity: SystemUserIdentity) -> SystemUserRequestObservation: ...
    async def get_request(
        self, identity: SystemUserIdentity, provider_request_id: str,
    ) -> SystemUserRequestObservation: ...
    async def find_request(self, identity: SystemUserIdentity) -> SystemUserRequestObservation: ...
    async def query_system_user(self, identity: SystemUserIdentity) -> QueriedSystemUser: ...
    async def verify_delegation(self, identity: SystemUserIdentity) -> None: ...


class SystemUserPersistence(Protocol):
    """Request-bound authorization and short, committed persistence operations.

    authorize_owner derives current facts from verified Company Access context.
    Every method rechecks current owner authorization in its own transaction;
    immutable request/provider identity and legal transitions are locked and
    checked again at writes. No transaction spans an outbound provider call.

    record_authority_state is bound to the named authority-state workflow:
    accepted -> verification_failed and suspension of existing linked pilot
    authorization commit atomically through its owning public contract. The
    authority service neither reads billing tables nor decides billing policy.
    begin_request inserts once or fails; it must never return an old creating
    request as newly inserted. Retry recovers the original stored identity.
    """

    async def authorize_owner(
        self, company_id: CompanyId, actor_id: ActorId, *, require_fresh_mfa: bool,
    ) -> SystemUserOwner: ...
    async def resolve_request_owner(self, request_id: str, actor_id: ActorId) -> SystemUserOwner: ...
    async def list_requests(
        self, company_ids: tuple[CompanyId, ...], actor_id: ActorId,
    ) -> tuple[SystemUserRequest, ...]: ...
    async def latest_callback_operation(self, owner: SystemUserOwner) -> SystemUserCallbackOperation | None: ...
    async def begin_request(
        self, owner: SystemUserOwner, request_id: str, external_reference: str,
    ) -> SystemUserRequest: ...
    async def read_request(self, owner: SystemUserOwner, request_id: str) -> SystemUserRequest: ...
    async def record_authority_state(
        self, owner: SystemUserOwner, update: SystemUserStateUpdate,
    ) -> SystemUserRequest: ...
    async def verify_preflight(
        self, owner: SystemUserOwner, request_id: str, expected_external_reference: str,
    ) -> SystemUserRequest: ...


class SystemUserStateTransaction(Protocol):
    """Authority half of the named atomic state/invalidation workflow.

    The transaction locks the original request before the existing linked
    authorization effect. apply_state preserves identity and legal transitions;
    assert_current_owner prevents committing after current authority is lost.
    Billing remains behind its own narrow public transaction contract.
    """

    async def lock_request(self, owner: SystemUserOwner, request_id: str) -> SystemUserRequest: ...
    async def apply_state(self, owner: SystemUserOwner, update: SystemUserStateUpdate) -> SystemUserRequest: ...
    async def assert_current_owner(self, owner: SystemUserOwner) -> None: ...


class AuthorityConnectionsCommands(Protocol):
    async def start(self, command: StartSystemUserRequestCommand) -> SystemUserFlowResult: ...
    async def retry(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult: ...
    async def reconcile(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult: ...


class AuthorityConnectionsQueries(Protocol):
    async def read(self, command: ReconcileSystemUserRequestCommand) -> SystemUserFlowResult: ...
    async def resolve_owner(self, request_id: str, actor_id: ActorId) -> SystemUserOwner: ...
    async def list_requests(
        self, *, company_ids: tuple[CompanyId, ...], actor_id: ActorId,
    ) -> tuple[SystemUserRequest, ...]: ...


AuthorityAdapter = TypeVar("AuthorityAdapter", bound=type[object])


def system_user_persistence_adapter(contract: type[object]) -> Callable[[AuthorityAdapter], AuthorityAdapter]:
    """Declare a persistence/workflow binding without runtime registration."""
    def declare(adapter: AuthorityAdapter) -> AuthorityAdapter:
        _ = contract
        return adapter
    return declare


def system_user_authority_provider_adapter(contract: type[object]) -> Callable[[AuthorityAdapter], AuthorityAdapter]:
    """Declare a credential-free provider port binding."""
    def declare(adapter: AuthorityAdapter) -> AuthorityAdapter:
        _ = contract
        return adapter
    return declare


class AuthorityOperationKind(StrEnum):
    REGISTER_RF1086_SYSTEM = "register_rf1086_system"
    SET_RF1086_SYSTEMBRUKER_CALLBACK = "set_rf1086_systembruker_callback"


class AuthorityOperationStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CONFLICT = "conflict"


class AuthorityOperationCode(StrEnum):
    STARTED = "started"
    CREATED_AND_VERIFIED = "created_and_verified"
    ALREADY_VERIFIED = "already_verified"
    DEFINITION_CONFLICT = "definition_conflict"
    CALLBACK_ALREADY_VERIFIED = "callback_already_verified"
    CALLBACK_UPDATED_AND_VERIFIED = "callback_updated_and_verified"
    AUTHORITY_TOKEN_ERROR = "authority_token_error"
    AUTHORITY_NETWORK_ERROR = "authority_network_error"
    AUTHORITY_HTTP_ERROR = "authority_http_error"
    AUTHORITY_RESPONSE_INVALID = "authority_response_invalid"
    AUTHORITY_VERIFICATION_ERROR = "authority_verification_error"
    AUTHORITY_OPERATION_FAILED = "authority_operation_failed"
    AUTHORITY_OPS_DISABLED = "authority_ops_disabled"
    AUTHORITY_OPS_UNAVAILABLE = "authority_ops_unavailable"
    ADMIN_OPERATOR_REQUIRED = "admin_operator_required"
    AUTHORITY_STEP_UP_REQUIRED = "authority_step_up_required"
    AUTHORITY_STEP_UP_FAILED = "authority_step_up_failed"
    AUTHORITY_OPERATION_INVALID = "authority_operation_invalid"
    AUTHORITY_CLIENT_ID_INVALID = "authority_client_id_invalid"
    AUTHORITY_KEY_ID_INVALID = "authority_key_id_invalid"
    AUTHORITY_PRIVATE_KEY_INVALID = "authority_private_key_invalid"
    AUTHORITY_ENVIRONMENT_INVALID = "authority_environment_invalid"
    AUTHORITY_AUDIT_UNAVAILABLE = "authority_audit_unavailable"
    AUTHORITY_AUDIT_START_FAILED = "authority_audit_start_failed"
    AUTHORITY_AUDIT_COMPLETION_FAILED = "authority_audit_completion_failed"
    AUTHORITY_OPERATION_CONFLICT = "authority_operation_conflict"


class AuthorityOperationError(DomainError):
    """Closed operator-facing code with optional safe upstream HTTP status."""

    def __init__(
        self, code: AuthorityOperationCode, authority_http_status: int | None = None,
        *, category: ErrorCategory = ErrorCategory.PRECONDITION_FAILED,
    ) -> None:
        if authority_http_status is not None and (
            type(authority_http_status) is not int or not 100 <= authority_http_status <= 599
        ):
            raise ValueError("invalid authority HTTP status")
        self.authority_http_status = authority_http_status
        super().__init__(code=AuthorityOperationCode(code).value, category=category)


@dataclass(frozen=True, slots=True)
class RunAuthorityOperationCommand:
    actor_id: ActorId
    operation_id: str
    operation: AuthorityOperationKind
    confirmation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _uuid(self.operation_id))
        if (not isinstance(self.actor_id, ActorId) or not isinstance(self.operation, AuthorityOperationKind)
                or not isinstance(self.confirmation, str)):
            raise ValueError("invalid authority operation command")


def _fixed_authority_definition(operation: AuthorityOperationKind, client_id: str) -> dict[str, object]:
    definition: dict[str, object] = {
        "id": SYSTEM_USER_SYSTEM_ID,
        "vendor": {"authority": "iso6523-actorid-upis", "ID": "0192:930835978"},
        "name": {"nb": "Talli", "nn": "Talli", "en": "Talli"},
        "description": {
            "nb": "Talli leverer aksjonærregisteroppgaven (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet selv.",
            "nn": "Talli leverer aksjonærregisteroppgåva (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet sjølv.",
            "en": "Talli files the shareholder register statement (RF-1086) for simple holding companies (AS) on behalf of the company itself.",
        },
        "rights": [{"resource": [{"id": "urn:altinn:resource", "value": SYSTEM_USER_RIGHT}]}],
        "accessPackages": [], "clientId": [client_id],
    }
    if operation is AuthorityOperationKind.REGISTER_RF1086_SYSTEM:
        definition["allowedredirecturls"] = []
        definition["isVisible"] = True
    else:
        definition["isVisible"] = True
        definition["allowedRedirectUrls"] = [SYSTEM_USER_CALLBACK_URL]
        definition["isDeleted"] = False
    return definition


@dataclass(frozen=True, slots=True)
class AuthorityOperationIntent:
    """Only the two fixed existing definitions; callers cannot supply registry JSON."""

    operation: AuthorityOperationKind
    client_id: str
    request_body: bytes = field(init=False, repr=False)
    request_hash: str = field(init=False)
    metadata: tuple[tuple[str, str], ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.operation, AuthorityOperationKind):
            raise ValueError("invalid authority operation")
        if not isinstance(self.client_id, str) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", self.client_id, re.I,
        ):
            raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_CLIENT_ID_INVALID)
        definition = _fixed_authority_definition(self.operation, self.client_id)
        object.__setattr__(self, "request_body", json.dumps(
            definition, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"))
        object.__setattr__(self, "request_hash", sha256(json.dumps(
            definition, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest())
        object.__setattr__(self, "metadata", (
            (("systemId", SYSTEM_USER_SYSTEM_ID), ("clientId", self.client_id), ("right", SYSTEM_USER_RIGHT))
            if self.operation is AuthorityOperationKind.REGISTER_RF1086_SYSTEM else
            (("systemId", SYSTEM_USER_SYSTEM_ID), ("callbackPath", SYSTEM_USER_CALLBACK_PATH))
        ))


_OPERATION_FAILURE_CODES = frozenset((
    AuthorityOperationCode.AUTHORITY_TOKEN_ERROR, AuthorityOperationCode.AUTHORITY_NETWORK_ERROR,
    AuthorityOperationCode.AUTHORITY_HTTP_ERROR, AuthorityOperationCode.AUTHORITY_RESPONSE_INVALID,
    AuthorityOperationCode.AUTHORITY_VERIFICATION_ERROR, AuthorityOperationCode.AUTHORITY_OPERATION_FAILED,
))


@dataclass(frozen=True, slots=True)
class AuthorityOperationCompletion:
    status: AuthorityOperationStatus
    result_code: AuthorityOperationCode
    authority_http_status: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AuthorityOperationStatus) or not isinstance(self.result_code, AuthorityOperationCode):
            raise ValueError("invalid authority completion")
        allowed = {
            AuthorityOperationStatus.SUCCEEDED: frozenset((
                AuthorityOperationCode.CREATED_AND_VERIFIED, AuthorityOperationCode.ALREADY_VERIFIED,
                AuthorityOperationCode.CALLBACK_ALREADY_VERIFIED, AuthorityOperationCode.CALLBACK_UPDATED_AND_VERIFIED,
            )),
            AuthorityOperationStatus.CONFLICT: frozenset((AuthorityOperationCode.DEFINITION_CONFLICT,)),
            AuthorityOperationStatus.FAILED: _OPERATION_FAILURE_CODES,
        }
        if self.result_code not in allowed.get(self.status, ()):
            raise ValueError("invalid authority completion outcome")
        if self.authority_http_status is not None and (
            type(self.authority_http_status) is not int or not 100 <= self.authority_http_status <= 599
        ):
            raise ValueError("invalid authority HTTP status")


@dataclass(frozen=True, slots=True)
class AuthorityOperationRecord:
    operation_id: str
    operation: AuthorityOperationKind
    actor_id: UserId
    status: AuthorityOperationStatus
    request_hash: str
    result_code: AuthorityOperationCode
    metadata: tuple[tuple[str, str], ...]
    authority_http_status: int | None
    created_at: Timestamp
    completed_at: Timestamp | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _uuid(self.operation_id))
        if (not isinstance(self.operation, AuthorityOperationKind) or not isinstance(self.actor_id, UserId)
                or not isinstance(self.status, AuthorityOperationStatus) or not isinstance(self.result_code, AuthorityOperationCode)
                or not isinstance(self.request_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", self.request_hash)
                or not isinstance(self.created_at, Timestamp)
                or (self.completed_at is not None and not isinstance(self.completed_at, Timestamp))
                or not isinstance(self.metadata, tuple) or any(
                    not isinstance(item, tuple) or len(item) != 2 or any(not isinstance(value, str) for value in item)
                    for item in self.metadata
                )):
            raise ValueError("invalid authority audit record")
        if self.status is AuthorityOperationStatus.STARTED:
            if self.result_code is not AuthorityOperationCode.STARTED or self.completed_at is not None:
                raise ValueError("invalid started authority audit")
        else:
            if self.completed_at is None:
                raise ValueError("missing completed authority audit time")
            AuthorityOperationCompletion(self.status, self.result_code, self.authority_http_status)
        allowed_metadata = (
            frozenset(("systemId", "clientId", "right"))
            if self.operation is AuthorityOperationKind.REGISTER_RF1086_SYSTEM
            else frozenset(("systemId", "callbackPath"))
        )
        if len(dict(self.metadata)) != len(self.metadata) or any(key not in allowed_metadata for key, _ in self.metadata):
            raise ValueError("invalid authority audit metadata")
        if self.authority_http_status is not None and (
            type(self.authority_http_status) is not int or not 100 <= self.authority_http_status <= 599
        ):
            raise ValueError("invalid authority HTTP status")


class AuthorityOperationsPersistence(Protocol):
    """Current-admin authorization and insert-once audit, each in a short transaction.

    Begin rechecks fresh MFA and never returns a prior started row as a new
    claim. A duplicate UUID fails closed without provider execution. Completion
    rechecks current admin/original actor, keeps immutable intent, and cannot
    overwrite another or already completed audit. It does not reimpose MFA
    freshness after provider I/O. Listing preserves current-admin-only visibility
    and created_at descending order; it does not require fresh MFA.
    """

    async def authorize_operator(self, actor_id: ActorId, *, require_fresh_mfa: bool) -> None: ...
    async def begin_operation(
        self, command: RunAuthorityOperationCommand, intent: AuthorityOperationIntent,
    ) -> AuthorityOperationRecord: ...
    async def complete_operation(
        self, actor_id: ActorId, operation_id: str, completion: AuthorityOperationCompletion,
    ) -> AuthorityOperationRecord: ...
    async def list_operations(self, actor_id: ActorId, limit: int = 10) -> tuple[AuthorityOperationRecord, ...]: ...


class AuthorityOperationsProvider(Protocol):
    """Prepare reads gated configuration only; execute uses the exact bound intent.

    Both operations are production-off by default. No credentials are in intent
    or result, and no provider I/O may precede the committed started audit.
    Execution reads the fixed system before its sole permitted write and verifies
    its result. Callback PUT uncertainty is resolved by a read in the same attempt;
    an explicit later attempt always reads before considering a new write.
    """

    def prepare(self, operation: AuthorityOperationKind) -> AuthorityOperationIntent: ...
    async def execute(self, intent: AuthorityOperationIntent) -> AuthorityOperationCompletion: ...


class AuthorityOperationsCommands(Protocol):
    async def run(self, command: RunAuthorityOperationCommand) -> AuthorityOperationRecord: ...


class AuthorityOperationsQueries(Protocol):
    async def list_operations(self, actor_id: ActorId, limit: int = 10) -> tuple[AuthorityOperationRecord, ...]: ...


def authority_operations_persistence_adapter(contract: type[object]) -> Callable[[AuthorityAdapter], AuthorityAdapter]:
    """Declare the narrow operator authorization/audit adapter."""
    def declare(adapter: AuthorityAdapter) -> AuthorityAdapter:
        _ = contract
        return adapter
    return declare


def authority_operations_provider_adapter(contract: type[object]) -> Callable[[AuthorityAdapter], AuthorityAdapter]:
    """Declare the two fixed admin provider operations."""
    def declare(adapter: AuthorityAdapter) -> AuthorityAdapter:
        _ = contract
        return adapter
    return declare


__all__ = [
    "AuthorityConnectionsCommands", "AuthorityConnectionsError", "AuthorityConnectionsErrorCode",
    "AuthorityConnectionsQueries", "AuthorityFailureCode", "AuthorityProviderError", "QueriedSystemUser",
    "ReconcileSystemUserRequestCommand", "StartSystemUserRequestCommand", "SystemUserAuthorityProvider",
    "SystemUserCallbackOperation", "SystemUserFlowResult", "SystemUserIdentity", "SystemUserOwner",
    "SystemUserPersistence", "SystemUserRequest", "SystemUserRequestObservation", "SystemUserRequestStatus",
    "SystemUserStateTransaction", "SystemUserStateUpdate", "SYSTEM_USER_CALLBACK_PATH", "SYSTEM_USER_CALLBACK_URL",
    "SYSTEM_USER_CONFIRMATION_PREFIX", "SYSTEM_USER_OBLIGATION", "SYSTEM_USER_RIGHT", "SYSTEM_USER_SYSTEM_ID",
    "system_user_authority_provider_adapter", "system_user_persistence_adapter",
    "AuthorityOperationCode", "AuthorityOperationCompletion", "AuthorityOperationError",
    "AuthorityOperationIntent", "AuthorityOperationKind", "AuthorityOperationRecord", "AuthorityOperationStatus",
    "AuthorityOperationsCommands", "AuthorityOperationsPersistence", "AuthorityOperationsProvider",
    "AuthorityOperationsQueries", "RunAuthorityOperationCommand",
    "authority_operations_persistence_adapter", "authority_operations_provider_adapter",
]
