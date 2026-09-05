"""Request-scoped authentication port for billing workflows."""

from typing import Protocol

from talli_backend.modules.billing.public import BillingPersistence
from talli_backend.shared.kernel import ActorId


class BillingAuthenticationError(Exception):
    """The bearer could not be bound to a verified billing session."""


class AuthenticatedBillingSession(BillingPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class BillingSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedBillingSession: ...


__all__ = [
    "AuthenticatedBillingSession",
    "BillingAuthenticationError",
    "BillingSessionFactory",
]
