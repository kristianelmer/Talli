"""Synthetic authority crash windows consume only committed new intent grants."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_dispatch import annual_submission, assess, KINDS
from test_shareholder_register_filing_production import Authority, OperationJournal


class DurableJournal:
    def __init__(self, payload):
        self.payload = payload
        self.events = []
        self.grant_retry = True
        self.crash_after_prepare = False
        self.fail_outcome = False

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        previous = next((row for row in reversed(self.events) if row.operation_name == name), None)
        if previous is not None and (previous.operation_state != 'failed'
                or previous.failure_class != 'retryable' or not self.grant_retry):
            return rf.Rf1086SourceOperationPreparation(previous, False)
        event = rf.Rf1086ArchiveProductionEventRecord(str(uuid4()), str(uuid4()), self.payload.income_year,
            submission_id, name, 'prepared', 1 if previous is None else previous.attempt + 1,
            body_hash, idempotency_key if previous is None else previous.idempotency_key,
            None, None, 'sending', (), None, None, datetime.now(timezone.utc).isoformat())
        self.events.append(event)
        if self.crash_after_prepare:
            raise asyncio.CancelledError()
        return rf.Rf1086SourceOperationPreparation(event, True)

    async def finish(self, intent, *, state, reference, failure):
        if self.fail_outcome:
            raise OSError('synthetic persistence outage')
        event = replace(intent, id=str(uuid4()), operation_state=state,
            authority_reference=reference, failure_class=failure)
        self.events.append(event)
        return event


async def execute(payload, journal, authority, reads=None):
    return await rf.execute_rf1086_source_dispatch(payload, journal=journal,
        read_journal=reads or OperationJournal(), authority_client=authority)


@pytest.mark.parametrize('kind', KINDS)
def test_all_profiles_send_original_bytes_once_and_replay_without_posts(kind):
    payload = assess(annual_submission(kind)).payload
    journal, authority, reads = DurableJournal(payload), Authority(), OperationJournal()
    asyncio.run(execute(payload, journal, authority, reads))
    posts = [(name, args) for name, args in authority.calls if name != 'list']
    assert posts[0][1]['xml'] == payload.hovedskjema_xml
    assert [args['xml'] for name, args in posts if name == 'sub'] == [payload.underskjema_xml[k] for k in payload.document_order]
    assert len({args['idempotency_key'] for _, args in posts}) == len(posts)
    calls = list(authority.calls)
    asyncio.run(execute(payload, journal, authority, reads))
    assert authority.calls == calls


@pytest.mark.parametrize('stage', ['post_hovedskjema', 'post_underskjema', 'confirm'])
@pytest.mark.parametrize('kind', ['timeout', 'unclassified', 'cancelled', 'outcome-outage'])
def test_uncertain_operation_never_posts_again(stage, kind):
    payload = assess(annual_submission()).payload
    journal, authority = DurableJournal(payload), Authority()
    original = getattr(authority, stage)
    async def fault(**args):
        result = await original(**args)
        if kind == 'timeout': raise rf.Rf1086AuthorityError('LOST_RESPONSE')
        if kind == 'unclassified': raise OSError('response lost after provider effect')
        if kind == 'cancelled': raise asyncio.CancelledError()
        journal.fail_outcome = True
        return result
    setattr(authority, stage, fault)
    with pytest.raises((Exception, asyncio.CancelledError)):
        asyncio.run(execute(payload, journal, authority))
    calls = list(authority.calls)
    journal.fail_outcome = False
    setattr(authority, stage, original)
    with pytest.raises(rf.Rf1086UnknownProductionOutcomeError):
        asyncio.run(execute(payload, journal, authority))
    assert authority.calls == calls


def test_crash_after_committed_intent_before_io_blocks_replay():
    payload = assess(annual_submission()).payload
    journal, authority = DurableJournal(payload), Authority()
    journal.crash_after_prepare = True
    with pytest.raises(asyncio.CancelledError): asyncio.run(execute(payload, journal, authority))
    journal.crash_after_prepare = False
    with pytest.raises(rf.Rf1086UnknownProductionOutcomeError): asyncio.run(execute(payload, journal, authority))
    assert not authority.calls


def test_retry_uses_a_new_committed_attempt_and_original_key():
    payload = assess(annual_submission()).payload
    journal = DurableJournal(payload)
    authority = Authority(main_error=rf.Rf1086AuthorityError('RETRY', status=503, retryable=True))
    with pytest.raises(rf.Rf1086AuthorityError): asyncio.run(execute(payload, journal, authority))
    key = journal.events[0].idempotency_key
    authority.main_error = None
    asyncio.run(execute(payload, journal, authority))
    attempts = [event for event in journal.events if event.operation_name == 'post_hovedskjema' and event.operation_state == 'prepared']
    assert [row.attempt for row in attempts] == [1, 2]
    assert all(row.idempotency_key == key for row in attempts)
    assert [args['idempotency_key'] for name, args in authority.calls if name == 'main'] == [key, key]


def test_failed_retryable_row_without_new_grant_cannot_execute():
    payload = assess(annual_submission()).payload
    journal = DurableJournal(payload)
    authority = Authority(main_error=rf.Rf1086AuthorityError('RETRY', status=503, retryable=True))
    with pytest.raises(rf.Rf1086AuthorityError): asyncio.run(execute(payload, journal, authority))
    calls = list(authority.calls)
    journal.grant_retry = False
    authority.main_error = None
    with pytest.raises(rf.Rf1086BlockedProductionOperationError): asyncio.run(execute(payload, journal, authority))
    assert authority.calls == calls


def test_competing_dispatch_cannot_reuse_an_inflight_intent():
    payload = assess(annual_submission()).payload
    async def run():
        journal, authority = DurableJournal(payload), Authority()
        entered, release = asyncio.Event(), asyncio.Event()
        original = authority.post_hovedskjema
        async def hold(**args):
            entered.set()
            await release.wait()
            return await original(**args)
        authority.post_hovedskjema = hold
        first = asyncio.create_task(execute(payload, journal, authority))
        try:
            await entered.wait()
            with pytest.raises(rf.Rf1086UnknownProductionOutcomeError):
                await execute(payload, journal, authority)
        finally:
            release.set()
            await first
        assert len([name for name, _ in authority.calls if name == 'main']) == 1
    asyncio.run(run())
