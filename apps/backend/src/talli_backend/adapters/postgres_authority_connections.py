"""Verified-actor PostgreSQL persistence for Authority Connections."""

from __future__ import annotations

from asyncio import timeout
from collections.abc import Awaitable, Callable, Mapping
import os
from typing import TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor, _timestamp,
)
from talli_backend.application.authority_connections_session import AuthorityConnectionsAuthenticationError
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.application.authority_connections_state_workflow import record_authority_state as record_state_workflow
from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError, AuthorityConnectionsErrorCode, AuthorityFailureCode,
    SystemUserCallbackOperation, SystemUserIdentity, SystemUserOwner, SystemUserPersistence,
    SystemUserRequest, SystemUserRequestStatus, SystemUserStateUpdate, SystemUserStateTransaction,
    system_user_persistence_adapter,
    AuthorityOperationCode, AuthorityOperationCompletion, AuthorityOperationError,
    AuthorityOperationIntent, AuthorityOperationKind, AuthorityOperationRecord,
    AuthorityOperationStatus, AuthorityOperationsPersistence, RunAuthorityOperationCommand,
    authority_operations_persistence_adapter,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.modules.billing.public import (
    AuthorityFailurePilotSuspension, SuspendProductionPilotForAuthorityFailureCommand,
    billing_persistence_adapter,
)
from talli_backend.shared.kernel import ActorId, CompanyId, ErrorCategory, UserId


Result = TypeVar("Result")


def _unavailable() -> AuthorityConnectionsError:
    return AuthorityConnectionsError(
        AuthorityConnectionsErrorCode.DEPENDENCY_UNAVAILABLE, ErrorCategory.DEPENDENCY_UNAVAILABLE,
    )


def _database_error(error: psycopg.DatabaseError) -> AuthorityConnectionsError:
    message = str(error)
    if "authority_step_up_required" in message:
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.STEP_UP_REQUIRED)
    if "authority_owner_required" in message:
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
    if "system_user_request_not_found" in message:
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.REQUEST_NOT_FOUND, ErrorCategory.NOT_FOUND)
    if "relationship_mismatch" in message:
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)
    if ("invalid_system_user_transition" in message or "terminal_evidence_immutable" in message
        or "preflight_not_allowed" in message):
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.INVALID_TRANSITION)
    if "invalid_confirmation_url" in message or "failure_code_invalid" in message:
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.INVALID_SYSTEM_USER_REQUEST)
    if isinstance(error, psycopg.errors.UniqueViolation):
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_REQUEST_START_FAILED)
    if isinstance(error, (psycopg.errors.CheckViolation, psycopg.errors.InvalidTextRepresentation)):
        return AuthorityConnectionsError(AuthorityConnectionsErrorCode.INVALID_SYSTEM_USER_REQUEST)
    return _unavailable()


def _request(row: Mapping[str, object], organization_number: str) -> SystemUserRequest:
    def identifier(name: str) -> str | None:
        return str(row[name]) if row.get(name) is not None else None

    def timestamp(name: str):
        return _timestamp(row[name]) if row.get(name) is not None else None

    return SystemUserRequest(
        request_id=str(row["id"]),
        identity=SystemUserIdentity(
            CompanyId(str(row["company_id"])), UserId(str(row["initiating_owner_user_id"])),
            organization_number, str(row["external_ref"]),
        ),
        status=SystemUserRequestStatus(str(row["status"])),
        provider_request_id=identifier("altinn_request_id"),
        confirmation_url=identifier("confirm_url"),
        preflight_verified_at=timestamp("preflight_verified_at"),
        failure_code=AuthorityFailureCode(str(row["failure_code"])) if row.get("failure_code") else None,
        obligation=str(row["obligation"]),
        requested_at=timestamp("requested_at"), last_status_checked_at=timestamp("last_status_checked_at"),
        accepted_at=timestamp("accepted_at"), resolved_at=timestamp("resolved_at"),
        created_at=timestamp("created_at"), updated_at=timestamp("updated_at"),
        operator_evidence_id=identifier("operator_evidence_id"),
    )


def _operation(row: Mapping[str, object]) -> AuthorityOperationRecord:
    return AuthorityOperationRecord(
        operation_id=str(row["id"]), operation=AuthorityOperationKind(str(row["operation"])),
        actor_id=UserId(str(row["actor_id"])), status=AuthorityOperationStatus(str(row["status"])),
        request_hash=str(row["request_hash"]), result_code=AuthorityOperationCode(str(row["result_code"])),
        metadata=tuple((str(key),str(value)) for key,value in row["metadata"].items()),
        authority_http_status=row["authority_http_status"], created_at=_timestamp(row["created_at"]),
        completed_at=_timestamp(row["completed_at"]) if row.get("completed_at") is not None else None,
    )


def _operation_database_error(error: psycopg.DatabaseError) -> AuthorityOperationError:
    message=str(error)
    for code in (
        AuthorityOperationCode.ADMIN_OPERATOR_REQUIRED, AuthorityOperationCode.AUTHORITY_STEP_UP_REQUIRED,
        AuthorityOperationCode.AUTHORITY_AUDIT_START_FAILED, AuthorityOperationCode.AUTHORITY_AUDIT_COMPLETION_FAILED,
        AuthorityOperationCode.AUTHORITY_OPERATION_CONFLICT, AuthorityOperationCode.AUTHORITY_OPERATION_INVALID,
    ):
        if code.value in message:
            category=(ErrorCategory.FORBIDDEN if code==AuthorityOperationCode.ADMIN_OPERATOR_REQUIRED
                      else ErrorCategory.INVALID_INPUT if code==AuthorityOperationCode.AUTHORITY_OPERATION_INVALID
                      else ErrorCategory.PRECONDITION_FAILED)
            return AuthorityOperationError(code,category=category)
    if isinstance(error,psycopg.errors.UniqueViolation):
        return AuthorityOperationError(AuthorityOperationCode.AUTHORITY_OPERATION_CONFLICT)
    if isinstance(error,(psycopg.errors.CheckViolation,psycopg.errors.InvalidTextRepresentation)):
        return AuthorityOperationError(AuthorityOperationCode.AUTHORITY_OPERATION_INVALID,category=ErrorCategory.INVALID_INPUT)
    return AuthorityOperationError(AuthorityOperationCode.AUTHORITY_AUDIT_UNAVAILABLE,
                                   category=ErrorCategory.DEPENDENCY_UNAVAILABLE)


class PostgresAuthorityConnectionsAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls) -> PostgresAuthorityConnectionsAdapter:
        return cls(LedgerSupabaseConfiguration(
            url=os.environ.get("SUPABASE_URL", ""),
            anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
            database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
        ))

    async def session(self, access_token: str) -> PostgresAuthorityConnectionsSession:
        try:
            session = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise AuthorityConnectionsAuthenticationError from None
        except LedgerError:
            raise _unavailable() from None
        return PostgresAuthorityConnectionsSession(self._configuration.database_url, session._verified)


@authority_operations_persistence_adapter(AuthorityOperationsPersistence)
@system_user_persistence_adapter(SystemUserPersistence)
class PostgresAuthorityConnectionsSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self) -> ActorId:
        return self._verified.actor_id

    def _assert_actor(self, actor_id: ActorId) -> None:
        if actor_id != self.actor_id:
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)

    async def _transaction(
        self, work: Callable[[psycopg.AsyncConnection], Awaitable[Result]],
    ) -> Result:
        if not self._database_url:
            raise _unavailable()
        try:
            async with timeout(10), await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row,
                options="-c statement_timeout=5000 -c lock_timeout=1000",
            ) as connection, connection.transaction():
                await connection.execute("set local role authority_connections_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true), "
                    "pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (str(self.actor_id.subject), self._verified.claims_json),
                )
                return await work(connection)
        except AuthorityConnectionsError:
            raise
        except (TimeoutError, psycopg.OperationalError):
            raise _unavailable() from None
        except psycopg.DatabaseError as error:
            raise _database_error(error) from None

    async def _owner(
        self, connection: psycopg.AsyncConnection, company_id: CompanyId, *, fresh: bool = False,
    ) -> SystemUserOwner:
        cursor = await connection.execute(
            "select authority_connections.assert_owner_v1(%s::uuid,%s::boolean) as identity",
            (str(company_id), fresh),
        )
        row = await cursor.fetchone()
        if not row or not isinstance(row["identity"], Mapping):
            raise _unavailable()
        return SystemUserOwner(company_id, self.actor_id, str(row["identity"]["organizationNumber"]))

    async def authorize_owner(self, company_id, actor_id, *, require_fresh_mfa):
        self._assert_actor(actor_id)
        async def work(connection):
            return await self._owner(connection, company_id, fresh=require_fresh_mfa)
        return await self._transaction(work)

    async def resolve_request_owner(self, request_id, actor_id):
        self._assert_actor(actor_id)
        async def work(connection):
            cursor = await connection.execute(
                "select company_id from authority_connections.system_user_requests where id=%s::uuid",
                (request_id,),
            )
            row = await cursor.fetchone()
            if not row:
                raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.REQUEST_NOT_FOUND, ErrorCategory.NOT_FOUND)
            return await self._owner(connection, CompanyId(str(row["company_id"])))
        return await self._transaction(work)

    async def list_requests(self, company_ids, actor_id):
        self._assert_actor(actor_id)
        async def work(connection):
            cursor = await connection.execute(
                "select * from authority_connections.system_user_requests "
                "where company_id=any(%s::uuid[]) order by created_at desc",
                ([str(company) for company in company_ids],),
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                owner = await self._owner(connection, CompanyId(str(row["company_id"])))
                result.append(_request(row, owner.organization_number))
            return tuple(result)
        return await self._transaction(work)

    async def latest_callback_operation(self, owner):
        self._assert_actor(owner.actor_id)
        async def work(connection):
            await self._owner(connection, owner.company_id)
            cursor = await connection.execute(
                "select authority_connections.latest_callback_operation_v1(%s::uuid) as result",
                (str(owner.company_id),),
            )
            row = await cursor.fetchone()
            await self._owner(connection, owner.company_id)
            data = row["result"] if row else None
            if data is None:
                return None
            return SystemUserCallbackOperation(
                str(data["operation"]), str(data["status"]), str(data["result_code"]),
                tuple((str(key), str(value)) for key, value in data["metadata"].items()),
            )
        return await self._transaction(work)

    async def _request_command(self, owner, query, parameters, *, fresh=False):
        self._assert_actor(owner.actor_id)
        async def work(connection):
            current = await self._owner(connection, owner.company_id, fresh=fresh)
            if current != owner:
                raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            if len(rows) != 1 or not isinstance(rows[0]["result"], Mapping):
                raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.REQUEST_NOT_FOUND, ErrorCategory.NOT_FOUND)
            result = _request(rows[0]["result"], current.organization_number)
            if result.identity.company_id != owner.company_id or result.identity.owner_id != self.actor_id.subject:
                raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)
            await self._owner(connection, owner.company_id, fresh=fresh)
            return result
        return await self._transaction(work)

    async def begin_request(self, owner, request_id, external_reference):
        return await self._request_command(owner,
            "select authority_connections.begin_request_v1(%s::uuid,%s::uuid,%s::text) as result",
            (request_id, str(owner.company_id), external_reference), fresh=True,
        )

    async def read_request(self, owner, request_id):
        return await self._request_command(owner,
            "select pg_catalog.to_jsonb(request) as result from authority_connections.system_user_requests request "
            "where id=%s::uuid and company_id=%s::uuid",
            (request_id, str(owner.company_id)),
        )

    async def record_authority_state(self, owner, update: SystemUserStateUpdate):
        self._assert_actor(owner.actor_id)
        if update.identity != SystemUserIdentity(
            owner.company_id, owner.actor_id.subject, owner.organization_number, update.identity.external_reference,
        ):
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        async def work(connection):
            transaction = _AuthorityStateTransaction(self, connection)
            return await record_state_workflow(transaction, _PilotSuspension(connection), owner, update)
        return await self._transaction(work)

    async def verify_preflight(self, owner, request_id, expected_external_reference):
        return await self._request_command(owner,
            "select authority_connections.verify_preflight_v1(%s::uuid,%s::uuid,%s::text) as result",
            (request_id, str(owner.company_id), expected_external_reference),
        )


    def _assert_operator_actor(self, actor_id: ActorId) -> None:
        if actor_id != self.actor_id:
            raise AuthorityOperationError(AuthorityOperationCode.ADMIN_OPERATOR_REQUIRED,category=ErrorCategory.FORBIDDEN)

    async def _operator_transaction(self, work):
        async def operation_work(connection):
            try:
                return await work(connection)
            except psycopg.DatabaseError as error:
                raise _operation_database_error(error) from None
        try:
            return await self._transaction(operation_work)
        except AuthorityConnectionsError:
            raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_AUDIT_UNAVAILABLE,
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE) from None

    async def authorize_operator(self, actor_id, *, require_fresh_mfa):
        self._assert_operator_actor(actor_id)
        async def work(connection):
            await connection.execute("select authority_connections.assert_operator_v1(%s::boolean)",(require_fresh_mfa,))
        await self._operator_transaction(work)

    async def begin_operation(self, command: RunAuthorityOperationCommand, intent: AuthorityOperationIntent):
        self._assert_operator_actor(command.actor_id)
        if command.operation != intent.operation:
            raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_OPERATION_INVALID,category=ErrorCategory.INVALID_INPUT)
        async def work(connection):
            cursor=await connection.execute(
                "select authority_connections.begin_operation_v1(%s::uuid,%s::text,%s::text,%s::jsonb) as result",
                (command.operation_id,intent.operation.value,intent.request_hash,Jsonb(dict(intent.metadata))),
            )
            row=await cursor.fetchone()
            if not row or not isinstance(row["result"],Mapping):
                raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_AUDIT_START_FAILED)
            return _operation(row["result"])
        return await self._operator_transaction(work)

    async def complete_operation(self, actor_id, operation_id, completion: AuthorityOperationCompletion):
        self._assert_operator_actor(actor_id)
        async def work(connection):
            cursor=await connection.execute(
                "select authority_connections.complete_operation_v1(%s::uuid,%s::text,%s::text,%s::integer) as result",
                (operation_id,completion.status.value,completion.result_code.value,completion.authority_http_status),
            )
            row=await cursor.fetchone()
            if not row or not isinstance(row["result"],Mapping):
                raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_AUDIT_COMPLETION_FAILED)
            return _operation(row["result"])
        return await self._operator_transaction(work)

    async def list_operations(self, actor_id, limit=10):
        self._assert_operator_actor(actor_id)
        if type(limit) is not int or not 1<=limit<=10:
            raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_OPERATION_INVALID,category=ErrorCategory.INVALID_INPUT)
        async def work(connection):
            cursor=await connection.execute("select authority_connections.list_operations_v1(%s::integer) as result",(limit,))
            row=await cursor.fetchone()
            if not row or not isinstance(row["result"],list):
                raise AuthorityOperationError(AuthorityOperationCode.AUTHORITY_AUDIT_UNAVAILABLE)
            return tuple(_operation(item) for item in row["result"])
        return await self._operator_transaction(work)


@system_user_persistence_adapter(SystemUserStateTransaction)
class _AuthorityStateTransaction:
    def __init__(self, session: PostgresAuthorityConnectionsSession, connection: psycopg.AsyncConnection):
        self._session = session
        self._connection = connection

    async def assert_current_owner(self, owner: SystemUserOwner) -> None:
        current = await self._session._owner(self._connection, owner.company_id)
        if current != owner:
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)

    async def _request(self, owner, query, parameters):
        await self.assert_current_owner(owner)
        cursor = await self._connection.execute(query, parameters)
        rows = await cursor.fetchall()
        if len(rows) != 1 or not isinstance(rows[0]["result"], Mapping):
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.REQUEST_NOT_FOUND, ErrorCategory.NOT_FOUND)
        result = _request(rows[0]["result"], owner.organization_number)
        if result.identity.company_id != owner.company_id or result.identity.owner_id != owner.actor_id.subject:
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.SYSTEM_USER_RELATIONSHIP_MISMATCH)
        return result

    async def lock_request(self, owner, request_id):
        return await self._request(owner,
            "select authority_connections.lock_owned_request_v1(%s::uuid,%s::uuid) as result",
            (request_id,str(owner.company_id)),
        )

    async def apply_state(self, owner, update):
        return await self._request(owner,
            "select authority_connections.record_authority_state_v1(%s::uuid,%s::uuid,%s::uuid,%s::text,%s::text,%s::text,%s::text) as result",
            (update.request_id,str(owner.company_id),update.provider_request_id,
             update.identity.external_reference,update.status.value,update.confirmation_url,
             update.failure_code.value if update.failure_code else None),
        )


@billing_persistence_adapter(AuthorityFailurePilotSuspension)
class _PilotSuspension:
    def __init__(self, connection: psycopg.AsyncConnection):
        self._connection = connection

    async def suspend_for_authority_failure(self, command: SuspendProductionPilotForAuthorityFailureCommand) -> None:
        await self._connection.execute(
            "select billing.suspend_pilot_for_authority_failure_v1(%s::uuid,%s::uuid,%s::uuid)",
            (str(command.system_user_request_id),str(command.company_id),str(command.owner_id)),
        )


__all__ = ["PostgresAuthorityConnectionsAdapter", "PostgresAuthorityConnectionsSession"]
