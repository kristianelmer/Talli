"""Offline sequencing of public Company Access/Documents disposition contracts.

This finite slice binds Documents only. Missing capability ownership or evidence
cannot open a target. Policy and reconciliation decisions remain with owners.
"""
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Protocol

from talli_backend.application.disposition_receipts import progress_receipts

from talli_backend.modules.company_access.public import AuthorizedCompanyDisposition
from talli_backend.modules.documents.public import (
    DocumentDisposition, DocumentDispositionStore,
    apply_document_dispositions, validate_document_dispositions,
)


@dataclass(frozen=True)
class JournalHead:
    stream: str
    sequence: int
    sha256: str


class DeletionJournal(Protocol):
    def append(self, permit: AuthorizedCompanyDisposition) -> JournalHead: ...
    def read(self, *, minimum: JournalHead | None = None) -> tuple[JournalHead, tuple[AuthorizedCompanyDisposition, ...]]: ...
    def applied(self, target: str, sequence: int, record: str, receipt: str, *, compatible_receipts: tuple[str, ...] = ()) -> None: ...


class ReplayReceiptStore(Protocol):
    def clear(self) -> None: ...
    def publish(self, target: str, head: JournalHead) -> None: ...


def _commands(permit):
    commitment = sha256(permit.model_dump_json().encode()).hexdigest()
    return tuple(DocumentDisposition(permit.plan.operation_id, permit.plan.company_id,
        r.record_id, r.income_year, r.generation, r.content_sha256, permit.plan.generation,
        commitment, r.action) for r in permit.plan.records)


def _require_owners(entries, stores):
    if any(r.owner != 'documents' or r.owner not in stores for p in entries for r in p.plan.records):
        raise ValueError('deletion_replay_owner_unavailable')


def _progress_receipts(command):
    fields = ('operation_id','company_id','document_id','income_year','generation',
              'content_sha256','company_generation','plan_sha256','action')
    return progress_receipts({name:getattr(command,name) for name in fields})


async def _apply(journal, target, sequence, commands, later_commands, store):
    completed = await apply_document_dispositions(commands, later_commands, store)
    for command in completed:
        receipt, compatible = _progress_receipts(command)
        journal.applied(target, sequence, str(command.document_id), receipt, compatible_receipts=compatible)


async def execute_authorized_disposition(permit: AuthorizedCompanyDisposition, *, journal: DeletionJournal,
                                         target: str, stores: Mapping[str, DocumentDispositionStore]):
    _require_owners((permit,), stores)
    head = journal.append(permit)  # durable, outside every customer snapshot
    _, entries = journal.read(minimum=head)
    sequence = next(i for i, p in enumerate(entries, 1) if p.plan.operation_id == permit.plan.operation_id)
    commands = _commands(permit)
    await stores['documents'].fence_inventory(commands)
    await _apply(journal, target, sequence, commands, (), stores['documents'])
    return head


async def replay_company_dispositions(*, journal: DeletionJournal, target: str, receipt: ReplayReceiptStore,
                                      minimum: JournalHead, stores: Mapping[str, DocumentDispositionStore]):
    receipt.clear()
    head, entries = journal.read(minimum=minimum)
    _require_owners(entries, stores)
    cuts = tuple(_commands(p) for p in entries)
    companies = {}
    for commands in cuts:
        companies.setdefault(commands[0].company_id, []).extend(commands)
    # Owners distinguish historical compatibility from a current source fence;
    # neither the workflow nor a selected-year marker supplies that decision.
    for commands in companies.values():
        await stores['documents'].fence_replay_history(tuple(commands))
    for index, commands in enumerate(cuts):
        later = tuple(c for following in cuts[index+1:] for c in following)
        await validate_document_dispositions(commands, later, stores['documents'])
    for index, commands in enumerate(cuts):
        later = tuple(c for following in cuts[index+1:] for c in following)
        await _apply(journal, target, index+1, commands, later, stores['documents'])
    if journal.read(minimum=minimum)[0] != head:
        raise ValueError('deletion_journal_changed_during_replay')
    receipt.publish(target, head)
    return head
