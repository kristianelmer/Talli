"""Request-scoped authentication and transaction ports for ledger workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.modules.ledger.public import LedgerPersistence
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
)
from talli_backend.shared.kernel import ActorId, Money


class LedgerAuthenticationError(Exception):
    """The bearer could not be authenticated at the application boundary."""


class LedgerWorkflowTransaction(LedgerPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def claim_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
    ) -> dict[str, object] | None: ...

    async def record_legacy_opening_snapshot(
        self,
        command: RecordOpeningSnapshotCommand,
        *,
        ledger_bank_balance: Money,
    ) -> OpeningSnapshotId: ...

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        result: dict[str, object],
    ) -> None: ...


class AuthenticatedLedgerSession(LedgerPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[LedgerWorkflowTransaction]: ...


class LedgerSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedLedgerSession: ...


__all__ = [
    "AuthenticatedLedgerSession",
    "LedgerAuthenticationError",
    "LedgerSessionFactory",
    "LedgerWorkflowTransaction",
]
