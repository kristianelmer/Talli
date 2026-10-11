"""Closed main preflight uses real retained RF/Docs code; Auth/SQL are doubles."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.application.shareholder_register_source_dispatch_v3 import (
    PreparedRf1086MainOperationV3, ShareholderRegisterSourceDispatchV3)
from talli_backend.application.shareholder_register_source_correction import VerifiedRf1086Correction
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from test_rf1086_source_claim_v3 import ClaimHarnessV3
from test_rf1086_source_context_v2 import identity
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering
from test_rf1086_retained_source_dispatch import pending_v3, retained_submission, retained_value
from test_rf1086_source_dispatch import annual_submission
from test_rf1086_source_submission_archive import source_submission_archive


def setup_preflight(monkeypatch, kind='no_activity', depth=0):
    owner = ClaimHarnessV3(monkeypatch, kind, depth)
    claim = owner.run().claim
    retained = rf.Rf1086RetainedSourceApproval(owner.approval, owner.text)
    workflow = ShareholderRegisterSourceDispatchV3(owner.h.admission.workflow._sessions,
        owner.h.admission.workflow._documents)
    owner.h.base.calls.clear()
    owner.h.admission.annual_calls.clear()
    close_fresh_rendering(monkeypatch)
    return owner, claim, retained, workflow


def prepare(owner, claim, retained, workflow):
    return asyncio.run(workflow.prepare_main_intent_v3('synthetic-token', owner.h.base.store,
        claim=claim, retained=retained, correlation_id=owner.h.arguments()['correlation_id']))


@pytest.mark.parametrize('kind,depth', [('formation',0), ('no_activity',0), ('dividend',0),
    ('cash_issue',0), ('cash_issue',1), ('cash_issue',2),
    ('loss_covering_reduction',0), ('loss_covering_reduction',1), ('loss_covering_reduction',2)])
def test_main_preflight_reuses_owned_saved_rendering_without_fresh_scope_or_annual_inputs(monkeypatch, kind, depth):
    owner, claim, retained, workflow = setup_preflight(monkeypatch, kind, depth)
    result = prepare(owner, claim, retained, workflow)
    assert type(result) is PreparedRf1086MainOperationV3
    assert result.claim == claim and result.retained == retained
    assert result.preview.source == owner.h.source and result.preview.retained_preview == owner.h.capture
    assert result.correction is None and owner.h.admission.annual_calls == []
    names = [name for name, _ in owner.h.base.calls]
    assert 'read_source_submission_claim_v1' in names[0]
    assert not any('lock_source_' in name or 'company_access_read_rf_admission' in name
        or 'append_source_' in name or 'prepare_source_operation' in name for name in names)
    assert [field.name for field in fields(result)] == ['claim', 'retained', 'preview', 'correction']
    with pytest.raises(FrozenInstanceError):
        result.correction = 'forged-authority'


@pytest.mark.parametrize('change', ['submission', 'approval', 'company', 'year', 'manifest',
    'payload', 'actor', 'predecessor', 'claimed-at', 'unowned-header'])
def test_preflight_rejects_forged_owned_identity_before_original_io(monkeypatch, change):
    owner, claim, retained, workflow = setup_preflight(monkeypatch)
    changed = {
        'submission': {'submission_id': rf.SubmissionId(identity(9301))},
        'approval': {'approval_id': rf.ApprovalId(identity(9302))},
        'company': {'company_id': CompanyId(identity(9303))},
        'year': {'income_year': IncomeYear(int(claim.income_year)-1)},
        'manifest': {'manifest_sha256': '0'*64},
        'payload': {'payload_sha256': '0'*64},
        'actor': {'claimed_by': ActorId(ActorKind.USER, UserId(identity(9304)))},
        'predecessor': {'predecessor_submission_id': rf.SubmissionId(identity(9305))},
        'claimed-at': {'claimed_at': '2026-10-12T00:00:00+00:00'},
    }
    if change == 'unowned-header':
        retained = replace(retained, approval=replace(retained.approval, invalidated_at='2026-10-12T00:00:00+00:00'))
    else:
        claim = replace(claim, **changed[change])
    with pytest.raises(rf.Rf1086ProductionError):
        prepare(owner, claim, retained, workflow)
    assert not any(name == 'bytes' for name, _ in owner.h.base.calls)
    assert owner.h.admission.annual_calls == []


@pytest.mark.parametrize('change', ['source-id', 'source-company', 'source-year', 'source-sha',
    'source-version', 'capture-sha', 'capture-text', 'preview-id'])
def test_saved_source_and_capture_cannot_relabel_the_retained_main_manifest(monkeypatch, change):
    owner, claim, retained, _ = setup_preflight(monkeypatch)
    source, capture = owner.h.source, owner.h.capture
    if change == 'source-id': source = replace(source, source_id=rf.Rf1086YearSourceId(identity(9311)))
    if change == 'source-company': source = replace(source, company_id=CompanyId(identity(9312)))
    if change == 'source-year': source = replace(source, income_year=IncomeYear(int(source.income_year)-1))
    if change == 'source-sha': source = replace(source, source_sha256='0'*64)
    if change == 'source-version': source = replace(source, version=source.version+1)
    if change == 'capture-sha': capture = replace(capture, payload_sha256='0'*64)
    if change == 'capture-text': capture = replace(capture, payload_text=capture.payload_text+' ')
    if change == 'preview-id': capture = replace(capture, preview=replace(capture.preview, preview_id=rf.PreviewId(identity(9313))))
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assert_rf1086_source_main_preflight_v3(claim, retained, source, capture,
            actor_id=owner.h.base.store.actor_id)


@pytest.mark.parametrize('failure', ['missing', 'company', 'year', 'actor', 'predecessor'])
def test_required_correction_cannot_disappear_or_change_scope_before_source_original_io(monkeypatch, failure):
    owner, claim, retained, workflow = setup_preflight(monkeypatch)
    # Owned-header/claim SQL double: a declared parent requires real correction
    # verification. The malformed result below is never a historical receipt.
    parent = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(identity(9321)),
        'a'*64, 'Owned negative correction fixture')
    manifest = json.loads(retained.manifest_text)
    manifest['predecessor'] = {'submissionId': parent.submission_id.value,
        'manifestSha256': parent.manifest_sha256, 'reason': parent.reason}
    text = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = sha256(text.encode()).hexdigest()
    owner.approval = replace(owner.approval, manifest_hash=digest, manifest=manifest)
    owner.text = text
    owner.existing = dict(owner.existing, manifest_sha256=digest,
        predecessor_submission_id=parent.submission_id.value)
    claim = replace(claim, manifest_sha256=digest, predecessor_submission_id=parent.submission_id)
    retained = rf.Rf1086RetainedSourceApproval(owner.approval, text)
    correction = VerifiedRf1086Correction(claim.company_id, claim.income_year, claim.claimed_by,
        parent, None, (), None)
    if failure == 'missing': correction = None
    if failure == 'company': correction = replace(correction, company_id=CompanyId(identity(9322)))
    if failure == 'year': correction = replace(correction, income_year=IncomeYear(int(claim.income_year)-1))
    if failure == 'actor': correction = replace(correction, actor_id=ActorId(ActorKind.USER, UserId(identity(9323))))
    if failure == 'predecessor': correction = replace(correction, predecessor=replace(parent, reason='changed fixture'))
    async def prepare_correction(*args, **kwargs):
        assert kwargs['claim'] == claim and kwargs['retained'] == retained
        assert rf.inspect_rf1086_source_operation_identity_v3(claim,retained,actor_id=claim.claimed_by) == parent
        return correction
    monkeypatch.setattr(workflow._correction, 'prepare_claimed_operation_v3', prepare_correction)
    with pytest.raises(rf.Rf1086ProductionError):
        prepare(owner, claim, retained, workflow)
    assert not any(name == 'bytes' for name, _ in owner.h.base.calls)


def history_session(monkeypatch, archive):
    """Physical SQL/Auth doubles; actual scope and strict RF assessment run."""
    claim = archive.source_submission_claims[0]
    events = []
    connection = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    store = PostgresShareholderRegisterFilingSession(None, SimpleNamespace(actor_id=claim.claimed_by),
        access_token='synthetic-token', billing=None, documents=None, company_access=None, environment={})
    async def execute(statement, args):
        assert connection.info.transaction_status == TransactionStatus.INTRANS
        assert 'lock_source_claim_recovery_v3' in statement
        assert args == (claim.approval_id.value, claim.manifest_sha256, str(claim.claimed_by.subject))
        events.append('historical-lock')
        async def fetchone():
            return {'scope': {'companyId': str(claim.company_id), 'incomeYear': int(claim.income_year)}}
        return SimpleNamespace(fetchone=fetchone)
    connection.execute = execute
    @asynccontextmanager
    async def transaction(**options):
        assert options == {} and connection.info.transaction_status == TransactionStatus.IDLE
        connection.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield connection
        finally:
            connection.info.transaction_status = TransactionStatus.IDLE
            events.append('released')
    async def read_claim(held, approval, digest, head):
        assert held is connection
        assert (approval, digest, head) == (claim.approval_id, claim.manifest_sha256, claim.predecessor_submission_id)
        events.append('claim')
        return claim
    async def read_archive(held, query, *, include_production):
        assert held is connection and include_production is True
        assert (query.company_id, query.income_year, query.actor_id) == (claim.company_id, claim.income_year, claim.claimed_by)
        events.append('archive')
        return archive
    monkeypatch.setattr(store, '_transaction', transaction)
    monkeypatch.setattr(store, '_read_source_submission_claim', read_claim)
    monkeypatch.setattr(store, '_archive_source_on_connection', read_archive)
    return store, claim, connection, events


@pytest.mark.parametrize('status,disposition', [('approved', 'current_admission_required'), ('accepted', 'confirmed')])
def test_history_scope_returns_complete_saved_assessment_on_same_connection_then_closes(monkeypatch, status, disposition):
    archive = retained_submission('formation', 0, status, correction=False)
    store, claim, physical, events = history_session(monkeypatch, archive)
    async def read():
        async with store.source_operation_recovery_v3(claim) as scoped:
            result = await scoped.read_operation_recovery()
            assert type(result) is rf.Rf1086SourceOperationRecoveryV3
            assert result.claim == claim and result.retained_archive == archive
            assert result.assessment.disposition == disposition
            assert [field.name for field in fields(result)] == ['claim', 'retained_archive', 'assessment']
        before = list(events)
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scoped.read_operation_recovery()
        assert events == before
        return result
    asyncio.run(read())
    assert events == ['historical-lock', 'claim', 'archive', 'released']


@pytest.mark.parametrize('fault', ['inactive', 'transaction', 'connection', 'query', 'claim', 'actor', 'mid-read-close'])
def test_history_ports_refuse_lost_lifetime_or_swapped_identity_before_more_sql(monkeypatch, fault):
    store, claim, connection, events = history_session(monkeypatch,
        retained_submission('formation', 0, correction=False))
    async def read():
        async with store.source_operation_recovery_v3(claim) as scoped:
            if fault == 'inactive': scoped.close()
            if fault == 'transaction': connection.info.transaction_status = TransactionStatus.IDLE
            if fault == 'connection': scoped._connection = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))
            if fault == 'query': scoped._query = replace(scoped._query, company_id=CompanyId(identity(9331)))
            if fault == 'claim': scoped._claim = replace(claim, payload_sha256='0'*64)
            if fault == 'actor': store._verified.actor_id = ActorId(ActorKind.USER, UserId(identity(9332)))
            if fault == 'mid-read-close':
                original = store._read_source_submission_claim
                async def close_after_claim(*args):
                    value = await original(*args)
                    scoped.close()
                    return value
                monkeypatch.setattr(store, '_read_source_submission_claim', close_after_claim)
            with pytest.raises(rf.ShareholderRegisterFilingError):
                await scoped.read_operation_recovery()
    asyncio.run(read())
    assert events == (['historical-lock', 'claim', 'released'] if fault == 'mid-read-close'
        else ['historical-lock', 'released'])


@pytest.mark.parametrize('version', [1,2,3])
def test_fixed_owned_approval_reader_selects_only_the_actual_stored_version(monkeypatch, version):
    archive = (source_submission_archive('formation', 'approved') if version == 1 else
        annual_submission('formation', 'approved') if version == 2 else
        retained_submission('formation', 0, correction=False))
    retained = retained_value(archive)
    actor = archive.source_submission_claims[0].claimed_by
    store = PostgresShareholderRegisterFilingSession(None, SimpleNamespace(actor_id=actor),
        access_token='synthetic-token', billing=None, documents=None, company_access=None, environment={})
    calls = []
    async def execute(statement, args):
        assert 'a.user_id=shareholder_register_filing.actor_v1()' in statement
        assert 'company_access_is_accepted_owner_v1' in statement
        assert args == (retained.approval.id,)
        calls.append('owned-header')
        async def fetchone():
            return {**{field.name: getattr(retained.approval, field.name) for field in fields(retained.approval)},
                'manifest_text': retained.manifest_text}
        return SimpleNamespace(fetchone=fetchone)
    @asynccontextmanager
    async def transaction(**options):
        assert options == {'snapshot': True}
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(store, '_transaction', transaction)
    result = asyncio.run(store.read_source_operation_approval_v3(rf.ApprovalId(retained.approval.id)))
    assert result == retained and calls == ['owned-header']


def install_fresh_identity(connection, claim, events):
    original = connection.execute
    async def execute(statement, args):
        if 'company_access_read_rf_admission_v1' in statement:
            assert events[-2:] == ['claim', 'archive']
            assert args == (str(claim.company_id), int(claim.income_year), str(claim.claimed_by.subject))
            events.append('fresh-company')
            async def fetchone():
                return {'admission': {'companyId': str(claim.company_id), 'incomeYear': int(claim.income_year),
                    'acceptedOwner': True, 'consequentialOperationsAllowed': True, 'entityType': 'AS',
                    'organizationNumber': '923609016', 'legalName': 'Owned scope double AS',
                    'address': 'Fixtureveien 1', 'postalCode': '0001', 'city': 'Oslo',
                    'identityConfirmedAt': '2026-01-01T00:00:00+00:00', 'identityLockedAt': '2026-01-01T00:00:00+00:00'}}
            return SimpleNamespace(fetchone=fetchone)
        if "set_config('talli.authorized_company_roles'" in statement:
            assert json.loads(args[0]) == {str(claim.company_id): 'owner'}
            events.append('fresh-roles')
            return None
        if 'lock_year_source_v1' in statement:
            assert args == (str(claim.company_id), int(claim.income_year))
            events.append('fresh-year')
            return None
        return await original(statement, args)
    connection.execute = execute


def test_fixed_fresh_transition_rechecks_history_then_keeps_one_physical_connection(monkeypatch):
    store, claim, connection, events = history_session(monkeypatch,
        retained_submission('formation', 0, correction=False))
    install_fresh_identity(connection, claim, events)
    async def read():
        async with store.source_operation_recovery_v3(claim) as historical:
            async with historical.fresh_operation_admission_v3() as fresh:
                assert fresh._held._connection is connection
                assert (await fresh.company_identity()).company.name == 'Owned scope double AS'
                assert not hasattr(fresh, 'append_source_approval_v3')
                assert not hasattr(fresh, 'capture_source_preview_v2')
            before = list(events)
            with pytest.raises(rf.ShareholderRegisterFilingError):
                await fresh.company_identity()
            assert events == before
    asyncio.run(read())
    assert events == ['historical-lock', 'claim', 'archive', 'fresh-company', 'fresh-roles', 'fresh-year', 'released']


@pytest.mark.parametrize('state', ['unknown', 'blocked', 'confirmed', 'legacy'])
def test_historical_disposition_or_legacy_header_cannot_enter_fresh_transition(monkeypatch, state):
    archive = (pending_v3(0, failure=state) if state in ('unknown', 'blocked') else
        retained_submission('formation', 0, 'accepted', correction=False) if state == 'confirmed' else
        annual_submission('formation', 'approved'))
    store, claim, _, events = history_session(monkeypatch, archive)
    async def read():
        async with store.source_operation_recovery_v3(claim) as historical:
            with pytest.raises((rf.Rf1086ProductionError, rf.Rf1086UnknownProductionOutcomeError,
                    rf.Rf1086BlockedProductionOperationError)):
                async with historical.fresh_operation_admission_v3():
                    pytest.fail('historical/legacy state yielded fresh scope')
    asyncio.run(read())
    assert events == ['historical-lock', 'claim', 'archive', 'released']


@pytest.mark.parametrize('fault', ['parent-close', 'held-close', 'foreign-connection', 'foreign-query', 'transaction'])
def test_fresh_read_port_rejects_lost_parent_held_or_physical_binding(monkeypatch, fault):
    store, claim, connection, events = history_session(monkeypatch,
        retained_submission('formation', 0, correction=False))
    install_fresh_identity(connection, claim, events)
    async def read():
        async with store.source_operation_recovery_v3(claim) as historical:
            async with historical.fresh_operation_admission_v3() as fresh:
                if fault == 'parent-close': historical.close()
                if fault == 'held-close': fresh._held.close()
                if fault == 'foreign-connection': fresh._held._connection = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))
                if fault == 'foreign-query': fresh._held._query = replace(fresh._held._query, company_id=CompanyId(identity(9341)))
                if fault == 'transaction': connection.info.transaction_status = TransactionStatus.IDLE
                before = list(events)
                with pytest.raises(rf.ShareholderRegisterFilingError):
                    await fresh.company_identity()
                assert events == before
    asyncio.run(read())


def workflow_history_session(monkeypatch, archive):
    store, claim, physical, events = history_session(monkeypatch, archive)
    async def read_claim(*args):
        events.append('initial-claim')
        assert args == (claim.approval_id, claim.manifest_sha256, claim.predecessor_submission_id)
        return claim
    monkeypatch.setattr(store, 'read_source_submission_claim', read_claim)
    async def session(token):
        assert token == 'synthetic-token'
        return store
    workflow = ShareholderRegisterSourceDispatchV3(SimpleNamespace(session=session), None)
    return store, claim, physical, events, workflow


def run_send(claim, workflow):
    return asyncio.run(workflow.send('synthetic-token', approval_id=claim.approval_id,
        manifest_sha256=claim.manifest_sha256, expected_head=claim.predecessor_submission_id,
        correlation_id='synthetic-correlation'))


@pytest.mark.parametrize('version,kind', [(version, kind) for version in (1, 2, 3)
    for kind in ('no_activity', 'formation', 'dividend', 'cash_issue',
        'cash_nominal_increase', 'loss_covering_reduction', 'mixed')
    if version != 3 or kind != 'cash_nominal_increase'])
def test_confirmed_send_returns_saved_identity_before_configuration_originals_billing_or_provider(monkeypatch, version, kind):
    archive = (source_submission_archive(kind, 'accepted') if version == 1 else
        annual_submission(kind, 'accepted') if version == 2 else
        retained_submission(kind, 0, 'accepted', correction=False))
    store, claim, _, events, workflow = workflow_history_session(monkeypatch, archive)
    def configuration(): pytest.fail('confirmed history consulted current configuration')
    monkeypatch.setattr(store, 'require_configuration', configuration)
    result = run_send(claim, workflow)
    assert result == rf.Rf1086SendResult(claim.submission_id.value)
    assert events == ['initial-claim', 'historical-lock', 'claim', 'archive', 'released']


@pytest.mark.parametrize('failure', ['unknown', 'blocked'])
@pytest.mark.parametrize('index', [0, 1, 2])
def test_uncertain_or_blocked_saved_operation_stops_before_current_dependencies(monkeypatch, failure, index):
    store, claim, _, events, workflow = workflow_history_session(monkeypatch, pending_v3(index, failure=failure))
    monkeypatch.setattr(store, 'require_configuration', lambda: pytest.fail('historical denial consulted config'))
    expected = rf.Rf1086UnknownProductionOutcomeError if failure == 'unknown' else rf.Rf1086BlockedProductionOperationError
    with pytest.raises(expected): run_send(claim, workflow)
    assert events == ['initial-claim', 'historical-lock', 'claim', 'archive', 'released']


@pytest.mark.parametrize('denial', ['preflight', 'configuration'])
@pytest.mark.parametrize('raced', [False, True])
def test_current_denial_closes_scope_before_separate_complete_historical_recovery(monkeypatch, denial, raced):
    archive = retained_submission('formation', 0, correction=False)
    completed_archive = retained_submission('formation', 0, 'accepted', correction=False)
    store, claim, _, events, workflow = workflow_history_session(monkeypatch, archive)
    async def preflight(*args, **kwargs):
        assert events[-1] == 'released'
        events.append('preflight')
        if denial == 'preflight': raise rf.Rf1086ProductionError('basis_unavailable')
        return object()  # This ordering fixture never reaches a write port.
    def configuration():
        assert events[-1] == 'preflight'
        events.append('configuration')
        raise rf.Rf1086ProductionError('configuration_unavailable')
    original = store._archive_source_on_connection
    reads = 0
    async def archive_read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if raced and reads > 1:
            events.append('archive')
            return completed_archive
        return await original(*args, **kwargs)
    monkeypatch.setattr(store, '_archive_source_on_connection', archive_read)
    monkeypatch.setattr(workflow, 'prepare_main_intent_v3', preflight)
    monkeypatch.setattr(store, 'require_configuration', configuration)
    if raced:
        assert run_send(claim, workflow) == rf.Rf1086SendResult(claim.submission_id.value)
    else:
        with pytest.raises(rf.Rf1086ProductionError): run_send(claim, workflow)
    assert events[-4:] == ['historical-lock', 'claim', 'archive', 'released']
    assert events.count('released') == 2


def test_preflight_cancellation_propagates_without_historical_recovery_or_provider(monkeypatch):
    store, claim, _, events, workflow = workflow_history_session(monkeypatch,
        retained_submission('formation', 0, correction=False))
    async def cancelled(*args, **kwargs):
        assert events[-1] == 'released'
        raise asyncio.CancelledError()
    monkeypatch.setattr(workflow, 'prepare_main_intent_v3', cancelled)
    with pytest.raises(asyncio.CancelledError): run_send(claim, workflow)
    assert events == ['initial-claim', 'historical-lock', 'claim', 'archive', 'released']


@pytest.mark.parametrize('version', [1, 2])
def test_absent_legacy_claim_cannot_delegate_to_a_fresh_old_first_effect(monkeypatch, version):
    archive = (source_submission_archive if version == 1 else annual_submission)('formation')
    store, claim, _, events, workflow = workflow_history_session(monkeypatch, archive)
    async def absent(*args):
        events.append('initial-claim')
        return None
    async def header(*args):
        events.append('header')
        return retained_value(archive)
    async def claim_fresh(*args, **kwargs): pytest.fail('legacy delegated to fresh claim')
    monkeypatch.setattr(store, 'read_source_submission_claim', absent)
    monkeypatch.setattr(store, 'read_source_operation_approval_v3', header)
    monkeypatch.setattr(workflow._claim, 'claim', claim_fresh)
    @asynccontextmanager
    async def history(approval,digest):
        assert (approval,digest)==(claim.approval_id,claim.manifest_sha256)
        events.append('claim-history')
        async def absent_again(*args):return None
        try:yield SimpleNamespace(read_source_submission_claim=absent_again)
        finally:events.append('claim-history-closed')
    monkeypatch.setattr(store,'source_claim_recovery_v3',history)
    with pytest.raises(rf.Rf1086ProductionError): run_send(claim, workflow)
    assert events == ['initial-claim', 'header', 'claim-history', 'claim-history-closed']


def install_writer_result(monkeypatch, owner, claim, *, transform=lambda value: value):
    from talli_backend.adapters.postgres_shareholder_register_filing import (
        _SourceOperationRecoveryV3, _SourceOperationAdmissionV3)
    store, physical = owner.h.base.store, owner.h.base.connection
    original = physical.execute
    key = identity(9361)
    async def execute(sql, args=()):
        cursor = await original(sql, args)
        if 'prepare_source_operation_v3(' in sql:
            assert owner.h.base.guard and physical.info.transaction_status == TransactionStatus.INTRANS
            assert args[:2] == (claim.submission_id.value, claim.manifest_sha256)
            owner.writes.append(args)
            template = owner.writer_template
            event = replace(template, id=identity(9362), company_id=str(claim.company_id),
                income_year=int(claim.income_year), submission_id=claim.submission_id.value,
                operation_name=args[2], body_hash=args[3], idempotency_key=args[4],
                operation_state='prepared', authority_reference=None, failure_class=None,
                resulting_status='sending', attempt=1)
            cursor.row = {'result': transform({'operation':{field.name:getattr(event,field.name)
                for field in fields(event)}, 'newlyPrepared':True})}
        return cursor
    physical.execute = execute
    owner.writes = []
    @asynccontextmanager
    async def scope():
        query = rf.Rf1086SourceQuery(claim.company_id, claim.income_year, claim.claimed_by)
        async with store.source_admission(query) as held:
            recovery = _SourceOperationRecoveryV3(store, physical, query, claim)
            fresh = _SourceOperationAdmissionV3(recovery, held)
            async def owned(supplied):
                fresh._require_active()
                assert supplied == claim
                return rf.Rf1086RetainedSourceApproval(owner.approval, owner.text), SimpleNamespace(source=owner.h.source), None
            monkeypatch.setattr(fresh, '_owned_operation_binding_v3', owned)
            async def history():
                fresh._require_active()
                return (claimed_history_row(claim, rf.Rf1086RetainedSourceApproval(owner.approval, owner.text)),)
            monkeypatch.setattr(held, 'submission_history', history)
            try: yield fresh
            finally: fresh.close(); recovery.close()
    return key, scope


@pytest.mark.parametrize('kind,depth', [('formation',0), ('no_activity',0), ('cash_issue',0),
    ('cash_issue',2), ('loss_covering_reduction',0), ('loss_covering_reduction',2)])
def test_main_writer_rebuilds_full_current_manifest_from_held_owner_inputs(monkeypatch, kind, depth):
    template = retained_submission('formation', 0, 'accepted', correction=False).production_events[0]
    owner, claim, retained, workflow = setup_preflight(monkeypatch, kind, depth)
    prepared = prepare(owner, claim, retained, workflow)
    owner.writer_template = template
    key, scope = install_writer_result(monkeypatch, owner, claim)
    connection = rf.Rf1086Connection(identity(9363), str(claim.company_id),
        str(claim.claimed_by.subject), 'aksjonaerregisteroppgaven', 'owned-external', 'accepted', True)
    async def run():
        async with scope() as fresh:
            await workflow.validate_held_main_intent_v3(prepared, fresh, owner.h.arguments()['correlation_id'])
            result = await fresh.prepare_main_operation_v3(prepared, idempotency_key=key,
                expected_event_id=None, connection=connection, correlation_id=owner.h.arguments()['correlation_id'])
            assert result.newly_prepared and result.event.body_hash == retained.approval.manifest['documentHashes'][0]['sha256']
    asyncio.run(run())
    assert len(owner.writes) == 1 and json.loads(owner.writes[0][6])['codec'] == 'rf1086-annual-readiness-v2'
    assert owner.h.admission.annual_calls == list(owner.h.admission.annual)
    assert owner.h.base.committed


@pytest.mark.parametrize('operation', ['child', 'confirm'])
def test_child_confirm_writer_uses_saved_source_without_main_originals_current_head_or_annual(monkeypatch, operation):
    template = retained_submission('formation', 0, 'accepted', correction=False).production_events[0]
    owner, claim, _, _ = setup_preflight(monkeypatch)
    owner.writer_template = template
    key, scope = install_writer_result(monkeypatch, owner, claim)
    owner.h.base.current = None
    owner.h.admission.stored_source = None
    for name in owner.h.admission.annual: owner.h.admission.annual[name] = RuntimeError('must not read current annual')
    connection = rf.Rf1086Connection(identity(9363), str(claim.company_id),
        str(claim.claimed_by.subject), 'aksjonaerregisteroppgaven', 'owned-external', 'accepted', True)
    async def run():
        async with scope() as fresh:
            args = dict(body_sha256='a'*64, idempotency_key=key, expected_event_id=None,
                connection=connection, correlation_id=owner.h.arguments()['correlation_id'])
            if operation == 'child': await fresh.prepare_child_operation_v3(claim, document_name='underskjema_owner', **args)
            else: await fresh.prepare_confirm_operation_v3(claim, **args)
    asyncio.run(run())
    assert len(owner.writes) == 1 and owner.writes[0][6] is None
    assert not owner.h.admission.annual_calls and not any(name=='bytes' for name,_ in owner.h.base.calls)
    assert any('prepare_rf_year_source_governance_proof' in name for name,_ in owner.h.base.calls)


@pytest.mark.parametrize('failure', ['none', 'commit', 'cancel'])
def test_journal_preparation_cannot_escape_a_failed_commit_or_cancelled_scope(monkeypatch, failure):
    from talli_backend.application.shareholder_register_source_dispatch_v3 import _OperationJournalV3
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceOperationAdmissionV3
    archive = retained_submission('formation', 0, correction=False)
    template = retained_submission('formation', 0, 'accepted', correction=False).production_events[0]
    store, claim, physical, events = history_session(monkeypatch, archive)
    install_fresh_identity(physical, claim, events)
    connection = rf.Rf1086Connection(identity(9371), str(claim.company_id),
        str(claim.claimed_by.subject), 'aksjonaerregisteroppgaven', 'owned-external', 'accepted', True)
    key = identity(9372)
    prepared_event = replace(template, id=identity(9373), submission_id=claim.submission_id.value,
        operation_state='prepared', failure_class=None, authority_reference=None,
        idempotency_key=key, resulting_status='sending')
    async def preflight(*args, **kwargs):
        assert physical.info.transaction_status == TransactionStatus.IDLE
        events.append('originals-outside-scope')
        return object()  # Ordering double; real main validator is tested above.
    async def validate(*args):
        assert physical.info.transaction_status == TransactionStatus.INTRANS
        events.append('held-validation')
    workflow = SimpleNamespace(prepare_main_intent_v3=preflight, validate_held_main_intent_v3=validate)
    async def write(self, prepared, **args):
        self._require_active()
        assert self._held._connection is physical and args['idempotency_key'] == key
        events.append('held-write')
        if failure == 'cancel': raise asyncio.CancelledError()
        return rf.Rf1086SourceOperationPreparation(prepared_event, True)
    monkeypatch.setattr(_SourceOperationAdmissionV3, 'prepare_main_operation_v3', write)
    transaction = store._transaction
    @asynccontextmanager
    async def committing(**options):
        async with transaction(**options) as owned:
            yield owned
        if failure == 'commit' and 'held-write' in events:
            events.append('commit-failed')
            raise rf.ShareholderRegisterFilingError.unavailable()
    monkeypatch.setattr(store, '_transaction', committing)
    journal = _OperationJournalV3(workflow, store, 'synthetic-token', claim, connection, 'correlation')
    async def run():
        result = await journal.prepare(submission_id=claim.submission_id.value, name='post_hovedskjema',
            body_hash=template.body_hash, idempotency_key=key)
        assert physical.info.transaction_status == TransactionStatus.IDLE
        assert events[-1] == 'released'
        return result
    if failure == 'none':
        assert asyncio.run(run()) == rf.Rf1086SourceOperationPreparation(prepared_event, True)
        assert events.count('historical-lock') == 2
    elif failure == 'cancel':
        with pytest.raises(asyncio.CancelledError): asyncio.run(run())
        assert events.count('historical-lock') == 2
    else:
        with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(run())
        assert events.count('historical-lock') == 3
    assert physical.info.transaction_status == TransactionStatus.IDLE
    assert events.index('originals-outside-scope') < events.index('fresh-company') < events.index('held-write')


@pytest.mark.parametrize('lost_response', [None, 'main', 'child', 'confirm'])
def test_complete_dispatch_uses_committed_intents_and_never_replays_unknown_provider_outcome(monkeypatch, lost_response):
    from datetime import datetime, timedelta
    from uuid import uuid4
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceOperationAdmissionV3
    archive = retained_submission('formation', 0, correction=False)
    template = retained_submission('formation', 0, 'accepted', correction=False).production_events[0]
    store, claim, physical, events, workflow = workflow_history_session(monkeypatch, archive)
    install_fresh_identity(physical, claim, events)
    retained = {'archive':archive}
    provider_calls = []
    async def read_archive(held, query, *, include_production):
        assert held is physical and include_production and physical.info.transaction_status == TransactionStatus.INTRANS
        events.append('archive')
        return retained['archive']
    monkeypatch.setattr(store, '_archive_source_on_connection', read_archive)
    def save_event(event):
        current = retained['archive']
        rows = (*current.production_events, event)
        refs = {row.operation_name:row.authority_reference for row in rows if row.operation_state=='succeeded'}
        retained['archive'] = replace(current, production_events=rows,
            production_submissions=(replace(current.production_submissions[0],
                status='received' if event.operation_name=='confirm' and event.operation_state=='succeeded' else
                    'unknown' if event.operation_state=='unknown' else 'sending',
                feedback_state='received' if event.operation_name=='confirm' and event.operation_state=='succeeded' else 'sent',
                authority_references=refs),))
    async def preflight(*args, **kwargs):
        assert physical.info.transaction_status == TransactionStatus.IDLE
        events.append('preflight')
        return object()  # Explicit orchestration double; fixed main proof has separate real tests.
    async def validate(*args):
        assert physical.info.transaction_status == TransactionStatus.INTRANS
    monkeypatch.setattr(workflow, 'prepare_main_intent_v3', preflight)
    monkeypatch.setattr(workflow, 'validate_held_main_intent_v3', validate)
    def configured():
        assert events.index('preflight') < len(events)
        events.append('configuration')
    monkeypatch.setattr(store, 'require_configuration', configured)
    assessment = rf.assess_rf1086_retained_source_dispatch(archive,
        query=rf.Rf1086ArchiveQuery(claim.company_id,claim.income_year,claim.claimed_by),submission_id=claim.submission_id)
    company = SimpleNamespace(id=str(claim.company_id), role='owner', org_number=assessment.organization_number)
    connection = rf.Rf1086Connection(identity(9381), str(claim.company_id), str(claim.claimed_by.subject),
        'aksjonaerregisteroppgaven', 'owned-external', 'accepted', True)
    async def company_record(*args): return company
    async def snapshot(*args):
        return SimpleNamespace(pilot_entitlements=(SimpleNamespace(entitlement_id=archive.approvals[0].entitlement_id,
            company_id=claim.company_id,user_id=claim.claimed_by.subject,income_year=claim.income_year,
            obligation='aksjonaerregisteroppgaven',case_profile='rf1086_full_year_v1',
            system_user_request_id=connection.id,system_user_external_reference=connection.external_ref),))
    async def read_connection(*args): return connection
    monkeypatch.setattr(store, 'company_record', company_record)
    monkeypatch.setattr(store, 'read_connection', read_connection)
    store._billing = SimpleNamespace(snapshot=snapshot)
    async def write(fresh, name, body, args):
        fresh._require_active()
        assert physical.info.transaction_status == TransactionStatus.INTRANS
        assert args['expected_event_id'] is None
        event = replace(template,id=str(uuid4()),operation_name=name,body_hash=body,
            idempotency_key=args['idempotency_key'],operation_state='prepared',attempt=1,
            failure_class=None,authority_reference=None,resulting_status='sending',
            created_at=(datetime.fromisoformat(template.created_at)+timedelta(seconds=len(retained['archive'].production_events))).isoformat())
        save_event(event)
        return rf.Rf1086SourceOperationPreparation(event,True)
    async def main(fresh, prepared, **args):
        return await write(fresh,'post_hovedskjema',archive.approvals[0].manifest['documentHashes'][0]['sha256'],args)
    async def child(fresh, supplied, *, document_name,body_sha256,**args):
        assert supplied==claim
        return await write(fresh,'post_underskjema:'+document_name.removeprefix('underskjema_'),body_sha256,args)
    async def confirm(fresh, supplied, *, body_sha256,**args):
        assert supplied==claim
        return await write(fresh,'confirm',body_sha256,args)
    monkeypatch.setattr(_SourceOperationAdmissionV3,'prepare_main_operation_v3',main)
    monkeypatch.setattr(_SourceOperationAdmissionV3,'prepare_child_operation_v3',child)
    monkeypatch.setattr(_SourceOperationAdmissionV3,'prepare_confirm_operation_v3',confirm)
    async def finish(submission,intent,*,state,reference,failure):
        assert submission==claim.submission_id and physical.info.transaction_status==TransactionStatus.IDLE
        prepared = next(row for row in retained['archive'].production_events if row.id==intent)
        event = replace(prepared,id=str(uuid4()),operation_state=state,authority_reference=reference,
            failure_class=failure,resulting_status='received' if state=='succeeded' and prepared.operation_name=='confirm' else 'sending',
            created_at=(datetime.fromisoformat(prepared.created_at)+timedelta(seconds=1)).isoformat())
        save_event(event)
        return event
    monkeypatch.setattr(store,'finish_source_operation',finish)
    def called(name,key=None):
        assert physical.info.transaction_status==TransactionStatus.IDLE
        if key is not None:
            row=retained['archive'].production_events[-1]
            assert row.operation_state=='prepared' and row.idempotency_key==key
        provider_calls.append(name)
        if name==lost_response:
            raise rf.Rf1086AuthorityError(code='SYNTHETIC_LOST_RESPONSE',status=None)
    async def post_main(**args):
        called('main',args['idempotency_key']);return SimpleNamespace(hovedskjema_id='committed-main')
    async def post_child(**args): called('child',args['idempotency_key'])
    async def confirmation(**args):
        called('confirm',args['idempotency_key']);return SimpleNamespace(dialog_id=identity(9382),forsendelse_id=identity(9383))
    async def documents(**args): called('list');return SimpleNamespace(documents=())
    binding = SimpleNamespace(authority=SimpleNamespace(post_hovedskjema=post_main,post_underskjema=post_child,
        confirm=confirmation,list_documents=documents),discard=lambda:events.append('binding-discarded'))
    async def bind(*args):
        assert physical.info.transaction_status==TransactionStatus.IDLE
        return binding
    monkeypatch.setattr(store,'bind_mutation_authority',bind)
    async def prepare_read(**args):
        assert physical.info.transaction_status==TransactionStatus.IDLE and args['name']=='list_documents'
        return rf.ProductionOperation(identity(9384),'list_documents','prepared',1,None,None,None,None)
    async def read_finished(*args): assert physical.info.transaction_status==TransactionStatus.IDLE
    monkeypatch.setattr(store,'operation_journal',lambda _:SimpleNamespace(prepare=prepare_read,succeed=read_finished,fail=read_finished))
    if lost_response is None:
        assert run_send(claim,workflow)==rf.Rf1086SendResult(claim.submission_id.value)
        assert provider_calls==['main',*(['child']*len(assessment.payload.document_order)),'confirm','list']
        before=list(provider_calls);assert run_send(claim,workflow)==rf.Rf1086SendResult(claim.submission_id.value)
        assert provider_calls==before
    else:
        with pytest.raises(rf.Rf1086UnknownProductionOutcomeError):run_send(claim,workflow)
        before=list(provider_calls)
        with pytest.raises(rf.Rf1086UnknownProductionOutcomeError):run_send(claim,workflow)
        assert provider_calls==before and retained['archive'].production_events[-1].operation_state=='unknown'
    assert events.count('preflight')==1 and events.count('configuration')==1 and events.count('binding-discarded')==1


def claimed_history_row(claim, retained):
    return rf.Rf1086ProductionSubmissionRecord(id=claim.submission_id.value,
        approval_id=claim.approval_id.value, entitlement_id=retained.approval.entitlement_id,
        company_id=str(claim.company_id), user_id=str(claim.claimed_by.subject),
        income_year=int(claim.income_year), obligation='aksjonaerregisteroppgaven',
        case_profile='rf1086_full_year_v1', payload_hash=claim.payload_sha256,
        adapter_version='rf1086-source-production-v1',environment='production',status='sending',
        authority_references={},failure_class=None,
        supersedes_submission_id=None if claim.predecessor_submission_id is None else claim.predecessor_submission_id.value,
        submitted_by=str(claim.claimed_by.subject),feedback_state='sent',feedback_artifact_count=0,
        feedback_last_checked_at=None,feedback_last_changed_at=None,feedback_safe_error_code=None,
        feedback_correlation_id=None,created_at=claim.claimed_at,updated_at=claim.claimed_at)


def test_claimed_main_history_binds_current_leaf_without_applying_first_claim_policy_twice():
    archive=retained_submission('formation',0,correction=False)
    claim=archive.source_submission_claims[0];retained=retained_value(archive)
    row=claimed_history_row(claim,retained)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assert_rf1086_submission_predecessor((row,),company_id=claim.company_id,
            income_year=claim.income_year,predecessor=None)
    rf.assert_rf1086_source_operation_history_v3(claim,retained,(row,),actor_id=claim.claimed_by)
    assert row.id==claim.submission_id.value and row.status=='sending'


@pytest.mark.parametrize('fault',['missing','duplicate','foreign-company','foreign-year','year-bool',
    'foreign-actor','submitter','approval','entitlement','payload','environment','profile',
    'parent','competing-root','competing-successor'])
def test_claimed_leaf_check_preserves_all_actor_history_and_rejects_rebinding_or_hidden_successor(fault):
    archive=retained_submission('formation',0,correction=False)
    claim=archive.source_submission_claims[0];retained=retained_value(archive);row=claimed_history_row(claim,retained)
    changes={'foreign-company':{'company_id':identity(9391)},'foreign-year':{'income_year':int(claim.income_year)-1},
        'year-bool':{'income_year':True},'foreign-actor':{'user_id':identity(9392)},
        'submitter':{'submitted_by':identity(9392)},'approval':{'approval_id':identity(9393)},
        'entitlement':{'entitlement_id':identity(9394)},'payload':{'payload_hash':'f'*64},
        'environment':{'environment':'test'},'profile':{'case_profile':'rf1086_no_activity_v1'},
        'parent':{'supersedes_submission_id':identity(9395)}}
    history=() if fault=='missing' else (row,row) if fault=='duplicate' else (
        (row,replace(row,id=identity(9396),user_id=identity(9397),submitted_by=identity(9397),
            supersedes_submission_id=row.id if fault=='competing-successor' else None))
        if fault.startswith('competing-') else (replace(row,**changes[fault]),))
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assert_rf1086_source_operation_history_v3(claim,retained,history,actor_id=claim.claimed_by)


@pytest.mark.parametrize('documents_configured', [False, True])
@pytest.mark.parametrize('authenticated', [False, True])
def test_staged_factory_delegates_existing_auth_before_composing_genuine_correction_receiver(monkeypatch,
        documents_configured, authenticated):
    from talli_backend.adapters.postgres_shareholder_register_filing import (
        PostgresShareholderRegisterSourceDispatchV3Adapter)
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
    from talli_backend.application.ledger_workflow import LedgerAuthenticationError
    from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
    from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
    from test_rf1086_year_source import ACTOR
    calls=[];documents=SimpleNamespace() if documents_configured else None
    async def auth(token):
        calls.append('existing-current-auth')
        assert token=='synthetic-token'
        if not authenticated: raise LedgerAuthenticationError()
        return SimpleNamespace(_verified=SimpleNamespace(actor_id=ACTOR,claims_json='{}'))
    async def billing(token):
        calls.append('existing-billing-construction')
        return SimpleNamespace()
    factory=PostgresShareholderRegisterSourceDispatchV3Adapter(
        LedgerSupabaseConfiguration('http://localhost:54321','synthetic-anon',''),
        billing_queries_factory=billing,documents_session_factory=documents,company_access_service=None,environment={})
    monkeypatch.setattr(factory._authentication,'session',auth)
    if not authenticated:
        with pytest.raises(ShareholderRegisterFilingAuthenticationError): asyncio.run(factory.session('synthetic-token'))
        assert calls==['existing-current-auth']
    else:
        result=asyncio.run(factory.session('synthetic-token'))
        assert result.actor_id==ACTOR and calls==['existing-current-auth','existing-billing-construction']
        receiver=getattr(result,'_source_correction_v3',None)
        if documents_configured:
            assert type(receiver) is ShareholderRegisterSourceCorrection
            assert receiver._sessions is factory and receiver._documents is documents
        else: assert receiver is None


@pytest.mark.parametrize('fault',['none','missing','type','company','year','actor','predecessor',
    'receiver','stale-parent','stale-selection','original-receipt'])
def test_fixed_main_writer_itself_reuses_genuine_required_correction_receiver_before_sql(monkeypatch,fault):
    from test_rf1086_claimed_correction_v3 import claimed_correction_fixture, configured_correction
    from talli_backend.application.shareholder_register_source_admission_v2 import PreparedRf1086SourceAdmissionV2
    from talli_backend.application.shareholder_register_source_dispatch_v3 import PreparedRf1086MainOperationV3
    from talli_backend.modules.shareholder_register_filing.retained_readiness import parse_annual_binding
    item=claimed_correction_fixture()
    parent=configured_correction(item)
    claim,retained=item.claim,item.retained
    verified=asyncio.run(parent.correction.prepare_claimed_operation_v3('token',claim=claim,retained=retained))
    source=item.lineage.source
    capture=next(row for row in item.archive.source_history.source_previews
        if row.preview.preview_id.value==item.lineage.preview_id)
    originals={value.original.receipt.document_id.value:value.original.receipt
        for value in item.parent_fixture.originals.values()}
    source_receipts=tuple(originals[row.document_id] for row in source.command.documents)
    preview=PreparedRf1086SourceAdmissionV2(rf.Rf1086SourceQuery(claim.company_id,claim.income_year,claim.claimed_by),
        source,capture,source_receipts)
    correction=verified
    if fault=='missing': correction=None
    elif fault=='type': correction=object()
    elif fault=='company': correction=replace(verified,company_id=CompanyId(identity(9401)))
    elif fault=='year': correction=replace(verified,income_year=IncomeYear(int(claim.income_year)-1))
    elif fault=='actor': correction=replace(verified,actor_id=ActorId(ActorKind.USER,UserId(identity(9402))))
    elif fault=='predecessor': correction=replace(verified,predecessor=replace(parent.prior,reason='changed'))
    elif fault=='stale-parent': correction=replace(verified,snapshot=replace(verified.snapshot,
        submission=replace(verified.snapshot.submission,updated_at='2026-10-12T00:00:00+00:00')))
    elif fault=='stale-selection': correction=replace(verified,selected_evidence=None)
    elif fault=='original-receipt': parent.original_failure=True
    prepared=PreparedRf1086MainOperationV3(claim,retained,preview,correction)
    owner,_,_,_=setup_preflight(monkeypatch)
    owner.writer_template=item.archive.production_events[0]
    key,scope=install_writer_result(monkeypatch,owner,claim)
    owner.h.base.store._source_correction_v3=parent.correction if fault!='receiver' else None
    connection=rf.Rf1086Connection(identity(9403),str(claim.company_id),str(claim.claimed_by.subject),
        'aksjonaerregisteroppgaven','owned-external','accepted',True)
    annual=parse_annual_binding(retained.approval.manifest['annualReadiness'],source,capture.preview,
        preview_payload_sha256=capture.payload_sha256,preview_payload_text=capture.payload_text)
    async def run():
        async with scope() as fresh:
            # Explicit SQL/current-state doubles, with the complete canonical
            # parent+current claim archive retained for the actual correction policy.
            async def owned(supplied):
                fresh._require_active();assert supplied==claim
                return retained,item.lineage,item.parent_fixture.predecessor
            async def history():return item.archive.production_submissions
            async def state(*args):
                fresh._require_active()
                return source,capture,annual,SimpleNamespace(can_approve=True,
                    review_sha256=retained.approval.manifest['review']['sha256'],
                    warning_codes=tuple(retained.approval.manifest['review']['acknowledgedWarningCodes']))
            async def original(receipt):
                fresh._require_active()
                assert receipt in source_receipts
            monkeypatch.setattr(fresh,'_owned_operation_binding_v3',owned)
            monkeypatch.setattr(fresh._held,'submission_history',history)
            monkeypatch.setattr(fresh._held,'_source_approval_state_v3',state)
            monkeypatch.setattr(fresh._held,'read_retained_correction_archive',parent.transaction.read_retained_correction_archive)
            monkeypatch.setattr(fresh._held,'assert_historical_original',parent.transaction.assert_historical_original)
            monkeypatch.setattr(fresh._held,'assert_original',original)
            parent.held=True
            try:
                return await fresh.prepare_main_operation_v3(prepared,idempotency_key=key,
                    expected_event_id=None,connection=connection,correlation_id=owner.h.arguments()['correlation_id'])
            finally: parent.held=False
    if fault=='none':
        result=asyncio.run(run());assert result.newly_prepared and len(owner.writes)==1
        assert parent.calls.count('historical_original')==len(verified.originals)
    else:
        from talli_backend.modules.documents.public import DocumentsError
        with pytest.raises((rf.Rf1086ProductionError,DocumentsError)):asyncio.run(run())
        assert not owner.writes


@pytest.mark.parametrize('generation',[2,3])
def test_absent_initial_claim_current_header_or_docs_denial_recovers_exact_raced_history(monkeypatch,generation):
    archive=annual_submission('formation','accepted') if generation==2 else retained_submission('formation',0,'accepted',correction=False)
    store,claim,_,events,workflow=workflow_history_session(monkeypatch,archive)
    async def first_missing(*args):events.append('initial-claim');return None
    async def header(*args):events.append('header');return retained_value(archive)
    @asynccontextmanager
    async def history(approval,digest):
        assert (approval,digest)==(claim.approval_id,claim.manifest_sha256)
        events.append('claim-history')
        async def exact(*args):
            assert args==(claim.approval_id,claim.manifest_sha256,claim.predecessor_submission_id)
            return claim
        try:yield SimpleNamespace(read_source_submission_claim=exact)
        finally:events.append('claim-history-closed')
    monkeypatch.setattr(store,'read_source_submission_claim',first_missing)
    monkeypatch.setattr(store,'read_source_operation_approval_v3',header)
    monkeypatch.setattr(store,'source_claim_recovery_v3',history)
    monkeypatch.setattr(store,'require_configuration',lambda:pytest.fail('raced confirmation consulted current configuration'))
    assert workflow._documents is None
    assert run_send(claim,workflow)==rf.Rf1086SendResult(claim.submission_id.value)
    assert events[:4]==['initial-claim','header','claim-history','claim-history-closed']
    assert events[-4:]==['historical-lock','claim','archive','released']


def test_fixed_main_writer_rejects_unexpected_correction_when_owned_header_has_no_predecessor(monkeypatch):
    template=retained_submission('formation',0,'accepted',correction=False).production_events[0]
    owner,claim,retained,workflow=setup_preflight(monkeypatch)
    prepared=replace(prepare(owner,claim,retained,workflow),correction=object())
    owner.writer_template=template;key,scope=install_writer_result(monkeypatch,owner,claim)
    connection=rf.Rf1086Connection(identity(9411),str(claim.company_id),str(claim.claimed_by.subject),
        'aksjonaerregisteroppgaven','owned-external','accepted',True)
    async def run():
        async with scope() as fresh:
            await fresh.prepare_main_operation_v3(prepared,idempotency_key=key,expected_event_id=None,
                connection=connection,correlation_id=owner.h.arguments()['correlation_id'])
    with pytest.raises(rf.Rf1086ProductionError):asyncio.run(run())
    assert not owner.writes and not owner.h.admission.annual_calls


@pytest.mark.parametrize('pending', [False, True])
def test_race_fixture_drains_failing_waiter_and_restores_owner_before_reporting(pending):
    from test_rf1086_source_operation_v3_database import drain_race_waiter
    async def run():
        started=asyncio.Event()
        restored=[]
        failure=RuntimeError('controlled waiter cleanup failure')
        primary=AssertionError('controlled missing advisory wait')
        async def task():
            started.set()
            if pending:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: raise failure
            raise failure
        async def restore(): restored.append('owner')
        waiter=asyncio.create_task(task())
        await started.wait()
        if not pending:
            await asyncio.sleep(0)
            assert waiter.done()
        with pytest.raises(BaseExceptionGroup) as result:
            await drain_race_waiter(waiter, restore, primary_failure=primary)
        assert result.value.exceptions == (primary, failure)
        assert restored == ['owner'] and waiter.done()
    asyncio.run(run())


def test_race_fixture_does_not_repeat_consumed_expected_failure_but_drains_task():
    from test_rf1086_source_operation_v3_database import drain_race_waiter
    async def run():
        async def task(): raise RuntimeError('already asserted refusal')
        waiter=asyncio.create_task(task())
        with pytest.raises(RuntimeError): await waiter
        restored=[]
        async def restore(): restored.append('owner')
        await drain_race_waiter(waiter, restore, consumed=True)
        assert restored == ['owner'] and waiter.done()
    asyncio.run(run())
