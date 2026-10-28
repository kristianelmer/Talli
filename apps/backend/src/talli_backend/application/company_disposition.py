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
        record.record_id, record.income_year, record.generation, record.content_sha256, permit.plan.generation,
        sha256(permit.model_dump_json().encode()).hexdigest())


async def _preflight_records(permit, stores, later_erases=()):
    # A later exact erase can supersede an earlier retain only after its owner
    # proves the later receipt and actual absence. Never rewrite original history.
    for record in permit.plan.records:
        if record.action != 'retain':
            continue
        superseded = False
        for later_permit, later_record in reversed(later_erases):
            if (later_permit.plan.company_id == permit.plan.company_id
                    and later_record.owner == record.owner and later_record.record_id == record.record_id
                    and later_record.generation == record.generation
                    and later_record.content_sha256 == record.content_sha256):
                outcome = await stores[record.owner].reconcile(_command(later_permit, later_record))
                if outcome == 'UNKNOWN':
                    raise ValueError('document_disposition_outcome_unknown')
                superseded = outcome == 'ERASED'
                break
        if not superseded and not await stores[record.owner].retained_matches(_command(permit, record)):
            raise ValueError('deletion_replay_retained_evidence_changed')
    # Resolve every selected erase before the first destructive I/O. Prepared
    # fences are durable known prefixes; an unavailable/partial outcome is not.
    pending = []
    for record in permit.plan.records:
        if record.action == 'erase':
            command = _command(permit, record)
            outcome = await stores[record.owner].reconcile(command)
            if outcome not in {'NOT_APPLIED', 'READY', 'ERASED'}:
                raise ValueError('document_disposition_outcome_unknown')
            if outcome == 'NOT_APPLIED':
                pending.append((stores[record.owner], command))
    return pending


async def _apply(journal, target, sequence, permit, stores, later_erases=()):
    for record in permit.plan.records:
        if record.owner != 'documents' or record.owner not in stores:
            raise ValueError('deletion_replay_owner_unavailable')
    # The owner must compare and durably fence its whole current company
    # inventory before crossing into object I/O. No table-wide admin bypass.
    if permit.plan.records:
        await stores['documents'].fence_inventory(tuple(_command(permit, r) for r in permit.plan.records))
    pending = await _preflight_records(permit, stores, later_erases)
    for store, command in pending:
        await store.prepare(command)
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
    # Fence the complete owner/company cut, then preflight every historical
    # decision before any destructive I/O, including unknown later operations.
    companies = {}
    for permit in entries:
        companies.setdefault(permit.plan.company_id, []).extend(_command(permit, r) for r in permit.plan.records)
    for commands in companies.values():
        await stores['documents'].fence_inventory(tuple(commands))
    for sequence, permit in enumerate(entries, 1):
        later = tuple((p, r) for p in entries[sequence:] for r in p.plan.records if r.action == 'erase')
        await _preflight_records(permit, stores, later)
    for sequence, permit in enumerate(entries, 1):
        later_erases = tuple((p, r) for p in entries[sequence:] for r in p.plan.records if r.action == 'erase')
        await _apply(journal, target, sequence, permit, stores, later_erases)
    if journal.read(minimum=minimum)[0] != head:
        raise ValueError('deletion_journal_changed_during_replay')
    receipt.publish(target, head)
    return head
