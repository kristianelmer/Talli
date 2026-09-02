"""Request-scoped authentication and transaction ports for banking workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.banking.public import (
    BankConnectionPersistence,
    BankFilePersistence,
    BankingPersistence,
    BankSyncPersistence,
)
from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId


class BankingAuthenticationError(Exception):
    """The bearer could not be authenticated at the application boundary."""


class BankingWorkflowTransaction(BankingPersistence, LedgerPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...


class AuthenticatedBankingSession(
    BankingPersistence,
    BankConnectionPersistence,
    BankFilePersistence,
    BankSyncPersistence,
    Protocol,
):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[BankingWorkflowTransaction]: ...


class BankingSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedBankingSession: ...


__all__ = [
    "AuthenticatedBankingSession",
    "BankingAuthenticationError",
    "BankingSessionFactory",
    "BankingWorkflowTransaction",
]
