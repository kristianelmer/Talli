"""Restricted Documents disposition seam; no generic bucket-delete authority."""
from .public import DocumentDisposition, DocumentDispositionStore




async def dispose_document(command: DocumentDisposition, store: DocumentDispositionStore) -> None:
    if command.action != "erase":
        raise ValueError("document_disposition_erase_required")
    outcome = await store.reconcile(command)
    if outcome == "ERASED":
        return
    if outcome not in {"NOT_APPLIED", "READY", "RESUMABLE"}:
        raise ValueError("document_disposition_outcome_unknown")
    if outcome == "NOT_APPLIED":
        await store.prepare(command)
    # A dropped response leaves a durable fenced prefix. Do not optimistically
    # retry erase: the next invocation reconciles the same exact command first.
    await store.erase(command)
    if await store.reconcile(command) != "ERASED":
        raise ValueError("document_disposition_outcome_unknown")


async def _pending_commands(commands, later_commands, store):
    for command in commands:
        if command.action != 'retain':
            continue
        superseded = False
        for later in reversed(later_commands):
            if (later.action == 'erase' and later.company_id == command.company_id
                    and later.document_id == command.document_id and later.generation == command.generation
                    and later.content_sha256 == command.content_sha256):
                outcome = await store.reconcile(later)
                if outcome not in {'NOT_APPLIED', 'READY', 'RESUMABLE', 'ERASED'}:
                    raise ValueError('document_disposition_outcome_unknown')
                superseded = outcome == 'ERASED'
                break
        if not superseded and not await store.retained_matches(command):
            raise ValueError('deletion_replay_retained_evidence_changed')
    pending = []
    for command in commands:
        if command.action == 'erase':
            outcome = await store.reconcile(command)
            if outcome not in {'NOT_APPLIED', 'READY', 'RESUMABLE', 'ERASED'}:
                raise ValueError('document_disposition_outcome_unknown')
            if outcome == 'NOT_APPLIED':
                pending.append(command)
    return tuple(pending)


async def validate_document_dispositions(commands: tuple[DocumentDisposition, ...],
                                         later_commands: tuple[DocumentDisposition, ...],
                                         store: DocumentDispositionStore) -> None:
    """Owner policy preflight for a complete cut, before any destructive I/O."""
    await _pending_commands(commands, later_commands, store)


async def apply_document_dispositions(commands: tuple[DocumentDisposition, ...],
                                      later_commands: tuple[DocumentDisposition, ...],
                                      store: DocumentDispositionStore) -> tuple[DocumentDisposition, ...]:
    """Retained checks, supersession and reconciliation belong to Documents."""
    pending = await _pending_commands(commands, later_commands, store)
    for command in pending:
        await store.prepare(command)
    for command in commands:
        if command.action == 'erase':
            await dispose_document(command, store)
    return commands
