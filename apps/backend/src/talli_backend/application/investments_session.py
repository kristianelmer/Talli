"""Request-scoped authentication and transaction ports for investments workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.banking.public import BankTransactionClaimPersistence
from talli_backend.modules.investments.public import InvestmentsPersistence, InvestmentsQueries
from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.shared.kernel import ActorId


class InvestmentsAuthenticationError(Exception):
    """The caller could not be bound to a verified investments session."""


class InvestmentsWorkflowTransaction(
    InvestmentsPersistence,
    LedgerPersistence,
    BankTransactionClaimPersistence,
    Protocol,
):
    @property
    def actor_id(self) -> ActorId: ...


class AuthenticatedInvestmentsSession(InvestmentsQueries, Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[InvestmentsWorkflowTransaction]: ...


class InvestmentsSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedInvestmentsSession: ...


__all__ = [
    "AuthenticatedInvestmentsSession",
    "InvestmentsAuthenticationError",
    "InvestmentsSessionFactory",
    "InvestmentsWorkflowTransaction",
]
