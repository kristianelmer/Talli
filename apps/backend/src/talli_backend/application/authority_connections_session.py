"""Verified request authentication for the Authority Connections workflows."""

from typing import Protocol

from talli_backend.modules.authority_connections.public import SystemUserPersistence, AuthorityOperationsPersistence
from talli_backend.shared.kernel import ActorId


class AuthorityConnectionsAuthenticationError(Exception):
    """The bearer could not be bound to a verified current session."""


class AuthenticatedAuthorityConnectionsSession(SystemUserPersistence, AuthorityOperationsPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class AuthorityConnectionsSessionFactory(Protocol):
    async def session(
        self, access_token: str
    ) -> AuthenticatedAuthorityConnectionsSession: ...


__all__ = [
    "AuthenticatedAuthorityConnectionsSession",
    "AuthorityConnectionsAuthenticationError",
    "AuthorityConnectionsSessionFactory",
]
