"""Bind the connection and operator policy paths to one verified session actor."""

from talli_backend.application.authority_connections_session import AuthenticatedAuthorityConnectionsSession
from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError, AuthorityConnectionsErrorCode,
    AuthorityOperationsProvider, ReconcileSystemUserRequestCommand,
    RunAuthorityOperationCommand, StartSystemUserRequestCommand, SystemUserAuthorityProvider,
)
from talli_backend.modules.authority_connections.service import AuthorityConnectionsService
from talli_backend.modules.authority_connections.operations import AuthorityOperationsService
from talli_backend.shared.kernel import ActorId, CompanyId, ErrorCategory


class AuthorityConnectionsWorkflow:
    def __init__(self, persistence: AuthenticatedAuthorityConnectionsSession,
                 provider: SystemUserAuthorityProvider) -> None:
        self._persistence = persistence
        self._service = AuthorityConnectionsService(persistence, provider)

    def _actor(self, actor_id: ActorId) -> None:
        if actor_id != self._persistence.actor_id:
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)

    async def start(self, command: StartSystemUserRequestCommand):
        self._actor(command.actor_id)
        return await self._service.start(command)

    async def retry(self, command: ReconcileSystemUserRequestCommand):
        self._actor(command.actor_id)
        return await self._service.retry(command)

    async def reconcile(self, command: ReconcileSystemUserRequestCommand):
        self._actor(command.actor_id)
        return await self._service.reconcile(command)

    async def read(self, command: ReconcileSystemUserRequestCommand):
        self._actor(command.actor_id)
        return await self._service.read(command)

    async def resolve_owner(self, request_id: str, actor_id: ActorId):
        self._actor(actor_id)
        return await self._service.resolve_owner(request_id, actor_id)

    async def list_requests(self, *, company_ids: tuple[CompanyId, ...], actor_id: ActorId):
        self._actor(actor_id)
        return await self._service.list_requests(company_ids=company_ids, actor_id=actor_id)


class AuthorityOperationsWorkflow:
    def __init__(self, persistence: AuthenticatedAuthorityConnectionsSession,
                 provider: AuthorityOperationsProvider) -> None:
        self._persistence = persistence
        self._service = AuthorityOperationsService(persistence, provider)

    async def run(self, command: RunAuthorityOperationCommand):
        if command.actor_id != self._persistence.actor_id:
            raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.OWNER_REQUIRED, ErrorCategory.FORBIDDEN)
        return await self._service.run(command)

    async def list_operations(self, limit: int = 10):
        return await self._service.list_operations(self._persistence.actor_id, limit)


__all__ = ["AuthorityConnectionsWorkflow", "AuthorityOperationsWorkflow"]
