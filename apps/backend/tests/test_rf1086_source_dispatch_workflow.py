"""Application dispatch commits admission before synthetic provider operations."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.application import shareholder_register_source_dispatch as dispatch
from talli_backend.application.shareholder_register_source_admission import AdmittedRf1086Source
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_dispatch import annual_submission, assess, events_for, with_events, KINDS
from test_rf1086_source_dispatch_execution import DurableJournal
from test_shareholder_register_filing_production import Authority, OperationJournal


class Harness:
    def __init__(self, monkeypatch, kind='formation', archive=None):
        self.archive = archive or annual_submission(kind)
        self.assessment = assess(self.archive)
        self.claim = self.assessment.claim
        self.actor = self.claim.claimed_by
        self.calls, self.committed = [], set()
        self.held = self.commit_error = self.configuration_error = False
        self.authorized = True
        self.after_bind = lambda: None
        self.journal = DurableJournal(self.assessment.payload)
        self.journal.events = list(self.archive.production_events)
        self.authority, self.reads = Authority(), OperationJournal()
        self.connection = rf.Rf1086Connection(str(uuid4()),str(self.claim.company_id),str(self.actor.subject),
            'aksjonaerregisteroppgaven','original-connection','accepted',True)
        self.current_connection = self.connection
        self.annual = object()
        h = self
        for method, label in [('post_hovedskjema','main'),('post_underskjema','sub'),('confirm','confirm'),('list_documents','list')]:
            original = getattr(self.authority, method)
            async def checked(*, _original=original, _label=label, **args):
                assert not h.held
                if _label != 'list': assert args['idempotency_key'] in h.committed
                h.calls.append(_label)
                return await _original(**args)
            setattr(self.authority, method, checked)
        class Scope:
            actor_id = h.actor
            async def company_identity(self):
                assert h.held
                return SimpleNamespace(company=SimpleNamespace(org_number=h.assessment.organization_number))
            async def prepare_source_operation(self, claim, **args):
                assert h.held and claim == h.claim
                if not h.authorized or args['connection'] != h.current_connection:
                    raise rf.Rf1086ProductionError('basis_unavailable')
                if args['operation_name'] == 'post_hovedskjema': assert args['annual'] is h.annual
                result = await h.journal.prepare(submission_id=claim.submission_id.value,
                    name=args['operation_name'],body_hash=args['body_sha256'],idempotency_key=args['idempotency_key'])
                if result.newly_prepared:
                    event = replace(result.event,company_id=str(claim.company_id))
                    h.journal.events[-1] = event
                    result = replace(result,event=event)
                return result
        self.scope = Scope()
        @asynccontextmanager
        async def guarded(*args, **kwargs):
            assert not h.held
            h.calls.append('guard'); h.held = True
            start = len(h.journal.events)
            try:
                yield h.scope
                if h.commit_error: raise OSError('synthetic commit rollback')
                h.committed.update(row.idempotency_key for row in h.journal.events[start:])
                h.calls.append('commit')
            except BaseException:
                del h.journal.events[start:]
                raise
            finally:
                h.held = False
                h.calls.append('release')
        @asynccontextmanager
        async def admitted(*args, **kwargs):
            h.calls.append('current-source')
            async with guarded() as scope:
                line = h.archive.source_approval_lineage[0]
                yield AdmittedRf1086Source(line.source,line.source_preview,(),scope)
        async def annual(admitted, correlation):
            assert h.held and admitted.transaction is h.scope
            h.calls.append('annual')
            return h.annual
        monkeypatch.setattr(dispatch,'read_annual_readiness',annual)
        class Session:
            actor_id = h.actor
            def require_configuration(self):
                if h.configuration_error: raise rf.Rf1086ProductionError('configuration_unavailable')
            async def archive_source(self, query):
                assert not h.held
                return with_events(h.archive,h.journal.events) if h.journal.events else h.archive
            async def company_record(self, company):
                return SimpleNamespace(id=company,role='owner',org_number=h.assessment.organization_number)
            async def snapshot(self, query):
                return SimpleNamespace(pilot_entitlements=(SimpleNamespace(
                    entitlement_id=h.archive.approvals[0].entitlement_id,company_id=h.claim.company_id,
                    user_id=h.actor.subject,income_year=h.claim.income_year,obligation='aksjonaerregisteroppgaven',
                    case_profile='rf1086_full_year_v1',system_user_request_id=h.connection.id,
                    system_user_external_reference=h.connection.external_ref),))
            async def read_connection(self, *args): return h.connection
            async def bind_mutation_authority(self, *args):
                assert not h.held
                h.calls.append('bind'); h.after_bind()
                return SimpleNamespace(authority=h.authority,discard=lambda:h.calls.append('discard'))
            def operation_journal(self, submission): return h.reads
            source_admission = staticmethod(guarded)
            async def finish_source_operation(self, submission, intent_id, **args):
                assert not h.held and submission == h.claim.submission_id
                intent = next(row for row in h.journal.events if row.id == intent_id)
                h.calls.append('outcome')
                return await h.journal.finish(intent,**args)
        self.session = Session(); self.session.billing = self.session
        class Sessions:
            async def session(self, token): return h.session
        self.workflow = dispatch.ShareholderRegisterSourceDispatchWorkflow(Sessions(),None)
        async def claim(*args, **kwargs):
            h.calls.append('claim')
            return rf.Rf1086SourceSubmissionClaimResult(h.claim,False)
        self.workflow._claim = SimpleNamespace(claim=claim)
        self.workflow._admission = SimpleNamespace(admit=admitted)

    def run(self):
        return asyncio.run(self.workflow.send('token',approval_id=self.claim.approval_id,
            manifest_sha256=self.claim.manifest_sha256,expected_head=self.claim.predecessor_submission_id,
            correlation_id=CorrelationId('synthetic-dispatch')))


@pytest.mark.parametrize('kind', KINDS)
def test_full_year_dispatch_commits_each_intent_before_original_byte_io(monkeypatch, kind):
    h = Harness(monkeypatch,kind)
    assert h.run().submission_id == h.claim.submission_id.value
    assert h.calls.index('bind') < h.calls.index('guard') < h.calls.index('annual') < h.calls.index('commit') < h.calls.index('main')
    assert h.calls.count('annual') == h.calls.count('current-source') == 1
    assert h.calls[-1] == 'discard' and not h.held
    assert h.calls.count('commit') == len(h.assessment.payload.document_order) + 2


def test_confirmed_archive_returns_without_credentials_or_source_reads(monkeypatch):
    h = Harness(monkeypatch,archive=annual_submission(status='accepted'))
    # Preserve the terminal archive and its independently verified feedback.
    async def read(query): return h.archive
    h.session.archive_source = read
    assert h.run().submission_id == h.claim.submission_id.value
    assert h.calls == ['claim']


def test_configuration_gate_precedes_claim_and_credentials(monkeypatch):
    h = Harness(monkeypatch); h.configuration_error = True
    with pytest.raises(rf.Rf1086ProductionError): h.run()
    assert not h.calls


def test_commit_failure_cannot_escape_as_a_send_grant(monkeypatch):
    h = Harness(monkeypatch); h.commit_error = True
    with pytest.raises(OSError): h.run()
    assert not h.authority.calls and not h.journal.events and h.calls[-1] == 'discard'


@pytest.mark.parametrize('change',['connection','authorization'])
def test_changes_during_credential_acquisition_block_before_io(monkeypatch, change):
    h = Harness(monkeypatch)
    def changed():
        if change == 'connection': h.current_connection = replace(h.connection,external_ref='reconnected')
        else: h.authorized = False
    h.after_bind = changed
    with pytest.raises(rf.Rf1086ProductionError): h.run()
    assert not h.authority.calls and h.calls[-1] == 'discard'


def test_started_filing_continues_original_bytes_after_approval_invalidation(monkeypatch):
    archive = events_for(annual_submission(),0,[(1,'succeeded',None)])
    archive = replace(archive,approvals=(replace(archive.approvals[0],
        invalidated_at=archive.approvals[0].approved_at,invalidation_reason='New annual answers'),))
    h = Harness(monkeypatch,archive=archive)
    h.run()
    assert 'current-source' not in h.calls and 'annual' not in h.calls and 'main' not in h.calls
    assert h.calls[-1] == 'discard'


@pytest.mark.parametrize('stage',['post_hovedskjema','post_underskjema','confirm'])
def test_lost_response_replay_stops_before_new_credentials(monkeypatch, stage):
    h = Harness(monkeypatch)
    original = getattr(h.authority,stage)
    async def lose(**args):
        await original(**args)
        raise rf.Rf1086AuthorityError('RESPONSE_LOST')
    setattr(h.authority,stage,lose)
    with pytest.raises(rf.Rf1086UnknownProductionOutcomeError): h.run()
    provider_calls = list(h.authority.calls)
    with pytest.raises(rf.Rf1086UnknownProductionOutcomeError): h.run()
    assert h.authority.calls == provider_calls and h.calls.count('bind') == 1
