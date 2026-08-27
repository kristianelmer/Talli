"""Request-scoped authentication boundary for ledger application workflows."""

from typing import Protocol

from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId


class LedgerAuthenticationError(Exception):
    """The bearer could not be authenticated at the application boundary."""


class AuthenticatedLedgerSession(LedgerPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class LedgerSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedLedgerSession: ...


__all__ = [
    "AuthenticatedLedgerSession",
    "LedgerAuthenticationError",
    "LedgerSessionFactory",
]
