"""Request-scoped authentication and transaction ports for ledger workflows."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from talli_backend.application.new_year_opening import (
    OpeningSnapshotCursor,
    OpeningSnapshotPage,
)
from talli_backend.modules.ledger.public import LedgerPersistence, PostedLedgerEntry
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId


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

    async def record_opening_snapshot(
        self,
        command: RecordOpeningSnapshotCommand,
    ) -> OpeningSnapshotId: ...

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
        result: dict[str, object],
    ) -> None: ...

    async def prepare_administrative_cost(
        self, command: object
    ) -> dict[str, object]: ...

    async def complete_administrative_cost(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]: ...

    async def prepare_tax_settlement(self, command: object) -> dict[str, object]: ...
    async def complete_tax_settlement(
        self, command: object, posted_entry: PostedLedgerEntry, prepared: dict[str, object]
    ) -> dict[str, object]: ...
class AuthenticatedLedgerSession(LedgerPersistence, Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[LedgerWorkflowTransaction]: ...

    async def list_opening_snapshots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: OpeningSnapshotCursor | None,
        limit: int,
    ) -> OpeningSnapshotPage: ...


class LedgerSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedLedgerSession: ...


__all__ = [
    "AuthenticatedLedgerSession",
    "LedgerAuthenticationError",
    "LedgerSessionFactory",
    "LedgerWorkflowTransaction",
]
