"""Restricted Documents disposition seam; no generic bucket-delete authority."""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentDisposition:
    operation_id: UUID
    company_id: UUID
    document_id: UUID
    income_year: int
    generation: str
    content_sha256: str
    company_generation: str
    plan_sha256: str


class DocumentDispositionStore(Protocol):
    """Implementations serialize against evidence writes and keep immutable receipts.

    prepare must compare exact company/year/generation/bytes, reject any retained
    original/evidence reference, and durably fence the item before returning.
    erase removes every enumerated object generation and raw metadata, then commits
    its receipt. reconcile distinguishes NOT_APPLIED, ERASED and UNKNOWN from the
    actual stores; READY means an exact durable fence with all selected bytes intact.
    Unavailable reads must never look like absence. No production
    adapter or general purge endpoint is supplied by this contract.
    """
    async def fence_inventory(self, commands: tuple[DocumentDisposition, ...]) -> None: ...
    async def prepare(self, command: DocumentDisposition) -> None: ...
    async def erase(self, command: DocumentDisposition) -> None: ...
    async def reconcile(self, command: DocumentDisposition) -> str: ...
    async def retained_matches(self, command: DocumentDisposition) -> bool: ...


async def dispose_document(command: DocumentDisposition, store: DocumentDispositionStore) -> None:
    outcome = await store.reconcile(command)
    if outcome == "ERASED":
        return
    if outcome not in {"NOT_APPLIED", "READY"}:
        raise ValueError("document_disposition_outcome_unknown")
    if outcome == "NOT_APPLIED":
        await store.prepare(command)
    # A dropped response leaves a durable fenced prefix. Do not optimistically
    # retry erase: the next invocation reconciles the same exact command first.
    await store.erase(command)
    if await store.reconcile(command) != "ERASED":
        raise ValueError("document_disposition_outcome_unknown")
