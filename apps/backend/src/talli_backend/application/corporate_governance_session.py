"""Request-scoped authentication and transaction ports for governance workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.banking.public import BankTransactionClaimPersistence
from talli_backend.modules.corporate_governance.public import (
    CorporateGovernancePersistence,
)
from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId


class CorporateGovernanceAuthenticationError(Exception):
    """The caller could not be bound to a verified governance session."""


class CorporateGovernanceWorkflowTransaction(
    CorporateGovernancePersistence,
    LedgerPersistence,
    BankTransactionClaimPersistence,
    Protocol,
):
    @property
    def actor_id(self) -> ActorId: ...


class AuthenticatedCorporateGovernanceSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[CorporateGovernanceWorkflowTransaction]: ...


class CorporateGovernanceSessionFactory(Protocol):
    async def session(
        self,
        access_token: str,
    ) -> AuthenticatedCorporateGovernanceSession: ...


__all__ = [
    "AuthenticatedCorporateGovernanceSession",
    "CorporateGovernanceAuthenticationError",
    "CorporateGovernanceSessionFactory",
    "CorporateGovernanceWorkflowTransaction",
]

