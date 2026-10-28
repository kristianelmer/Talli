"""Offline disposition/replay sequencing; each owner executes its own policy.

This finite vertical slice binds Documents only. An unknown owner, missing store,
unattributed record or incomplete retained evidence cannot open the target.
"""
from hashlib import sha256
from dataclasses import dataclass
from typing import Mapping, Protocol

from talli_backend.modules.company_access.public import AuthorizedCompanyDisposition
from talli_backend.modules.documents.public import (
    DocumentDisposition, DocumentDispositionStore, dispose_document,
)



@dataclass(frozen=True)
class JournalHead:
    stream: str
    sequence: int
    sha256: str


class DeletionJournal(Protocol):
    def append(self, permit: AuthorizedCompanyDisposition) -> JournalHead: ...
    def read(self, *, minimum: JournalHead | None = None) -> tuple[JournalHead, tuple[AuthorizedCompanyDisposition, ...]]: ...
    def applied(self, target: str, sequence: int, record: str, receipt: str) -> None: ...


class ReplayReceiptStore(Protocol):
    def clear(self) -> None: ...
    def publish(self, target: str, head: JournalHead) -> None: ...


def _command(permit, record):
    return DocumentDisposition(permit.plan.operation_id, permit.plan.company_id,
        record.record_id, record.income_year, record.generation, record.content_sha256,
        sha256(permit.model_dump_json().encode()).hexdigest())


async def _apply(journal, target, sequence, permit, stores):
    for record in permit.plan.records:
        if record.owner != 'documents' or record.owner not in stores:
            raise ValueError('deletion_replay_owner_unavailable')
    # All retained evidence is verified before any destructive owner operation.
    for record in permit.plan.records:
        if record.action == 'retain' and not await stores[record.owner].retained_matches(_command(permit, record)):
            raise ValueError('deletion_replay_retained_evidence_changed')
    for record in permit.plan.records:
        command = _command(permit, record)
        if record.action == 'erase':
            await dispose_document(command, stores[record.owner])
        journal.applied(target, sequence, str(record.record_id),
                        sha256((repr(command) + ':' + record.action).encode()).hexdigest())


async def execute_authorized_disposition(permit: AuthorizedCompanyDisposition, *, journal: DeletionJournal,
                                         target: str, stores: Mapping[str, DocumentDispositionStore]):
    if any(r.owner != 'documents' or r.owner not in stores for r in permit.plan.records):
        raise ValueError('deletion_replay_owner_unavailable')
    head = journal.append(permit)  # durable, outside every customer snapshot
    _, entries = journal.read(minimum=head)
    sequence = next(i for i, p in enumerate(entries, 1) if p.plan.operation_id == permit.plan.operation_id)
    await _apply(journal, target, sequence, permit, stores)
    return head


async def replay_company_dispositions(*, journal: DeletionJournal, target: str, receipt: ReplayReceiptStore,
                                      minimum: JournalHead, stores: Mapping[str, DocumentDispositionStore]):
    receipt.clear()  # close any previous readiness before work
    head, entries = journal.read(minimum=minimum)
    # Preflight every owner in the cut before erasing anything.
    if any(r.owner != 'documents' or r.owner not in stores for p in entries for r in p.plan.records):
        raise ValueError('deletion_replay_owner_unavailable')
    for sequence, permit in enumerate(entries, 1):
        await _apply(journal, target, sequence, permit, stores)
    if journal.read(minimum=minimum)[0] != head:
        raise ValueError('deletion_journal_changed_during_replay')
    receipt.publish(target, head)
    return head
