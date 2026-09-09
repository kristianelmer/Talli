"""Two exact admin authority operations with durable redacted audit."""

from talli_backend.modules.authority_connections.public import (
    AuthorityOperationCode as Code, AuthorityOperationCompletion, AuthorityOperationError,
    AuthorityOperationIntent, AuthorityOperationKind as Kind, AuthorityOperationRecord,
    AuthorityOperationStatus as Status, AuthorityOperationsPersistence,
    AuthorityOperationsProvider, RunAuthorityOperationCommand,
)
from talli_backend.shared.kernel import ActorId


_CONFIRMATIONS = {
    Kind.REGISTER_RF1086_SYSTEM: "REGISTER TALLI RF1086 SYSTEM",
    Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK: "SET TALLI SYSTEMBRUKER CALLBACK",
}
_SUCCESSES = {
    Kind.REGISTER_RF1086_SYSTEM: frozenset((Code.CREATED_AND_VERIFIED, Code.ALREADY_VERIFIED)),
    Kind.SET_RF1086_SYSTEMBRUKER_CALLBACK: frozenset((
        Code.CALLBACK_ALREADY_VERIFIED, Code.CALLBACK_UPDATED_AND_VERIFIED,
    )),
}
_PROVIDER_FAILURES = frozenset((
    Code.AUTHORITY_TOKEN_ERROR, Code.AUTHORITY_NETWORK_ERROR, Code.AUTHORITY_HTTP_ERROR,
    Code.AUTHORITY_RESPONSE_INVALID, Code.AUTHORITY_VERIFICATION_ERROR,
))


def _matches_intent(
    record: AuthorityOperationRecord, command: RunAuthorityOperationCommand, intent: AuthorityOperationIntent,
) -> bool:
    return (
        isinstance(record, AuthorityOperationRecord)
        and record.operation_id == command.operation_id and record.operation is command.operation
        and record.actor_id == command.actor_id.subject and record.request_hash == intent.request_hash
        and len(record.metadata) == len(intent.metadata) and dict(record.metadata) == dict(intent.metadata)
    )


class AuthorityOperationsService:
    def __init__(self, persistence: AuthorityOperationsPersistence, provider: AuthorityOperationsProvider) -> None:
        self._persistence = persistence
        self._provider = provider

    async def run(self, command: RunAuthorityOperationCommand) -> AuthorityOperationRecord:
        await self._persistence.authorize_operator(command.actor_id, require_fresh_mfa=True)
        if command.confirmation != _CONFIRMATIONS[command.operation]:
            raise AuthorityOperationError(Code.AUTHORITY_OPERATION_INVALID)
        try:
            intent = self._provider.prepare(command.operation)
            if not isinstance(intent, AuthorityOperationIntent) or intent.operation is not command.operation:
                raise AuthorityOperationError(Code.AUTHORITY_ENVIRONMENT_INVALID)
        except AuthorityOperationError:
            raise
        except Exception:
            raise AuthorityOperationError(Code.AUTHORITY_ENVIRONMENT_INVALID) from None
        try:
            started = await self._persistence.begin_operation(command, intent)
            if (not _matches_intent(started, command, intent) or started.status is not Status.STARTED
                    or started.authority_http_status is not None):
                raise ValueError("invalid started audit")
        except AuthorityOperationError as error:
            if error.code == Code.AUTHORITY_OPERATION_CONFLICT:
                raise
            raise AuthorityOperationError(Code.AUTHORITY_AUDIT_START_FAILED) from None
        except Exception:
            raise AuthorityOperationError(Code.AUTHORITY_AUDIT_START_FAILED) from None

        # No provider activity before the insert-once started audit is committed.
        # Each later explicit action receives a new audit UUID and reads provider
        # state before considering a write; this is not an execution replay API.
        try:
            completion = await self._provider.execute(intent)
            if (not isinstance(completion, AuthorityOperationCompletion)
                    or (completion.status is Status.SUCCEEDED
                        and completion.result_code not in _SUCCESSES[command.operation])):
                raise AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID)
        except Exception as error:
            safe_error = isinstance(error, AuthorityOperationError) and error.code in _PROVIDER_FAILURES
            completion = AuthorityOperationCompletion(
                Status.FAILED, Code(error.code) if safe_error else Code.AUTHORITY_OPERATION_FAILED,
                error.authority_http_status if safe_error else None,
            )
        try:
            completed = await self._persistence.complete_operation(command.actor_id, command.operation_id, completion)
            if (not _matches_intent(completed, command, intent) or completed.created_at != started.created_at
                    or completed.status is not completion.status or completed.result_code is not completion.result_code
                    or completed.authority_http_status != completion.authority_http_status):
                raise ValueError("invalid completed audit")
        except Exception:
            raise AuthorityOperationError(Code.AUTHORITY_AUDIT_COMPLETION_FAILED) from None
        if completion.status is Status.FAILED:
            raise AuthorityOperationError(completion.result_code, completion.authority_http_status) from None
        return completed

    async def list_operations(self, actor_id: ActorId, limit: int = 10) -> tuple[AuthorityOperationRecord, ...]:
        await self._persistence.authorize_operator(actor_id, require_fresh_mfa=False)
        if type(limit) is not int or not 1 <= limit <= 10:
            raise AuthorityOperationError(Code.AUTHORITY_OPERATION_INVALID)
        try:
            rows = await self._persistence.list_operations(actor_id, limit)
            if not isinstance(rows, tuple) or len(rows) > limit or any(
                not isinstance(row, AuthorityOperationRecord) for row in rows
            ):
                raise ValueError("invalid authority audit list")
            return rows
        except Exception:
            raise AuthorityOperationError(Code.AUTHORITY_AUDIT_UNAVAILABLE) from None
