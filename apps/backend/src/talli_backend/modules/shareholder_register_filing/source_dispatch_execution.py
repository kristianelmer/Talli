"""Consume committed send grants; historical retry state never grants new I/O."""
from . import public as rf
from .production import execute_journaled_rf1086_production


class _DurableJournal:
    def __init__(self, submission_id, journal, reads):
        self.submission_id, self.journal, self.reads = submission_id, journal, reads
        self.intents = {}
        self.read_ids = set()

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        if submission_id != self.submission_id:
            raise rf.Rf1086ProductionError('basis_unavailable')
        if body_hash is None:
            if name != 'list_documents' or idempotency_key is not None:
                raise rf.Rf1086ProductionError('basis_unavailable')
            operation = await self.reads.prepare(submission_id=submission_id, name=name,
                body_hash=None, idempotency_key=None)
            self.read_ids.add(operation.id)
            return operation
        result = await self.journal.prepare(submission_id=submission_id, name=name,
            body_hash=body_hash, idempotency_key=idempotency_key)
        if not isinstance(result, rf.Rf1086SourceOperationPreparation) or type(result.newly_prepared) is not bool:
            raise rf.Rf1086ProductionError('basis_unavailable')
        event = result.event
        if (not isinstance(event, rf.Rf1086ArchiveProductionEventRecord)
                or event.submission_id != submission_id or event.operation_name != name
                or event.body_hash != body_hash or not event.idempotency_key
                or type(event.attempt) is not int or not 1 <= event.attempt <= 20):
            raise rf.Rf1086ProductionError('basis_unavailable')
        if result.newly_prepared:
            if (event.operation_state != 'prepared' or event.authority_reference is not None
                    or event.failure_class is not None or event.resulting_status != 'sending'):
                raise rf.Rf1086ProductionError('basis_unavailable')
            self.intents[event.id] = event
            state = 'prepared'
        elif event.operation_state == 'succeeded':
            if event.failure_class is not None or not event.authority_reference:
                raise rf.Rf1086ProductionError('basis_unavailable')
            state = 'succeeded'
        elif event.operation_state in ('prepared', 'unknown') or event.failure_class == 'unknown':
            state = 'unknown'
        else:
            # In particular, a stale expected-event retry may return a failed
            # retryable row. Only a newly committed intent authorizes that retry.
            raise rf.Rf1086BlockedProductionOperationError(name)
        return rf.ProductionOperation(event.id, name, state, event.attempt,
            event.body_hash, event.idempotency_key, event.authority_reference, event.failure_class)

    async def _finish(self, operation_id, *, state, reference=None, failure=None):
        intent = self.intents[operation_id]
        outcome = await self.journal.finish(intent, state=state, reference=reference, failure=failure)
        if (not isinstance(outcome, rf.Rf1086ArchiveProductionEventRecord)
                or any(getattr(outcome, name) != getattr(intent, name) for name in (
                    'company_id', 'income_year', 'submission_id', 'operation_name',
                    'attempt', 'body_hash', 'idempotency_key'))
                or outcome.operation_state != state or outcome.authority_reference != reference
                or outcome.failure_class != failure):
            raise rf.Rf1086ProductionError('basis_unavailable')

    async def succeed(self, operation_id, authority_reference):
        if operation_id in self.read_ids:
            return await self.reads.succeed(operation_id, authority_reference)
        await self._finish(operation_id, state='succeeded', reference=authority_reference)

    async def fail(self, operation_id, failure):
        if operation_id in self.read_ids:
            return await self.reads.fail(operation_id, failure)
        # An unclassified exception can include a response/persistence failure
        # after the provider applied the request. It never proves non-delivery.
        classification = 'unknown' if failure.code == 'RF1086_OPERATION_ERROR' else failure.classification
        await self._finish(operation_id, state='unknown' if classification == 'unknown' else 'failed',
            failure=classification)


async def execute(payload, *, journal, read_journal, authority_client):
    return await execute_journaled_rf1086_production(payload,
        journal=_DurableJournal(payload.submission_id, journal, read_journal),
        authority_client=authority_client)
