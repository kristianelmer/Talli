"""Closed preview workflow: real pure preparation, evidence bytes and held adapters."""
import asyncio
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import psycopg
import pytest

from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.corporate_governance.public import CorporateGovernanceError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear, UserId
from rf1086_preview_v2_fixture import PreviewHarnessV2
from test_rf1086_source_context_v2 import identity
from test_rf1086_source_preview import preview_source


@pytest.mark.parametrize('kind,count', [('formation',0), ('no_activity',0), ('dividend',0),
    ('cash_issue',0), ('cash_issue',1), ('cash_issue',2),
    ('loss_covering_reduction',0), ('loss_covering_reduction',1), ('loss_covering_reduction',2)])
def test_generation_binds_exact_source_originals_proof_and_canonical_saved_bytes(kind,count,monkeypatch):
    h = PreviewHarnessV2(monkeypatch,kind,count)
    wire = rf.serialize_rf1086_year_source_v2(h.source)
    expected, store = preview_source(h.source)
    preview_identity = 'rf1086-source-preview:full-year-v1:' + h.source.source_id.value + ':' + h.source.source_sha256 + ':' + rf.rf1086_year_source_digest(store.prepared.rendered)
    expected = replace(expected,preview_id=rf.PreviewId(str(uuid5(NAMESPACE_URL,preview_identity))))
    result = h.generate()
    assert result.preview == expected and result.payload_text == rf.serialize_rf1086_source_preview(expected)
    assert h.captures == {expected.preview_id.value:result}
    assert rf.serialize_rf1086_year_source_v2(h.source) == wire
    calls = [name for name,_ in h.base.calls]
    guard = next(i for i,name in enumerate(calls) if 'lock_year_source_v1' in name)
    proof = next(i for i,name in enumerate(calls) if 'prepare_rf_year_source_governance_proof' in name)
    append = next(i for i,name in enumerate(calls) if 'append_source_preview_v1' in name)
    assert guard < proof < append and all(i < guard for i,name in enumerate(calls) if name == 'bytes')
    assert sum(name == 'bytes' for name in calls) == len(h.base.records)
    assert h.base.committed and not h.base.guard and not h.admission.scope._active
    assert not any('bridge_source_preview' in name or 'claim_' in name or 'approval' in name for name in calls)


def test_new_owner_replays_exact_saved_creator_time_and_historical_source(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    first = h.generate()
    wire = rf.serialize_rf1086_year_source_v2(h.source)
    current = replace(h.base.store.actor_id,subject=UserId(identity(9910)))
    h.base.store._verified = replace(h.base.store._verified,actor_id=current)
    h.admission.authenticated_actors = {'synthetic-token':current}
    h.base.calls.clear();h.base.committed = False;h.held_proof_calls.clear()
    assert h.generate() == first
    assert first.created_by != str(current.subject) and h.source.confirmed_by != current
    assert rf.serialize_rf1086_year_source_v2(h.source) == wire
    assert len(h.captures) == 1 and len(h.held_proof_calls) == 1 and h.base.committed
    assert h.held_proof_calls[0] == (str(h.source.company_id),int(h.source.income_year),h.source.source_sha256,str(current.subject))


@pytest.mark.parametrize('field', ['company_id','income_year','source_id'])
def test_wrong_query_scope_never_enters_guard(field,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    arguments = h.arguments()
    arguments[field] = {'company_id':CompanyId(identity(9911)), 'income_year':IncomeYear(int(h.source.income_year)-1),
        'source_id':rf.Rf1086YearSourceId(identity(9912))}[field]
    with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086YearSourceError)):
        asyncio.run(h.workflow.generate('synthetic-token',**arguments))
    assert not h.captures and not h.held_proof_calls and not h.base.committed


@pytest.mark.parametrize('change',['owner','identity','document_metadata','document_bytes','governance','rf_observation','head'])
def test_changed_current_evidence_fails_before_proof_or_append(change,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    key = next(iter(h.base.records))
    if change == 'owner': h.base.before_guard = lambda: h.base.admission.update(acceptedOwner=False)
    if change == 'identity': h.base.before_guard = lambda: h.base.admission.update(legalName='Changed AS')
    if change == 'document_metadata': h.base.before_guard = lambda: h.base.records.update({key:replace(h.base.records[key],name='Changed.pdf')})
    if change == 'document_bytes': h.base.contents[key] = b'%PDF-1.7 changed'
    if change == 'governance': h.base.before_guard = lambda: setattr(h.base.basis,'view',replace(h.base.basis.view,register_chains=()))
    if change == 'rf_observation': h.base.before_guard = lambda: setattr(h.base.basis,'current',None)
    if change == 'head': h.base.before_guard = lambda: setattr(h.base,'current',None)
    with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086YearSourceError,DocumentsError,CorporateGovernanceError,psycopg.DatabaseError)):
        h.generate()
    assert not h.captures and not h.held_proof_calls and not h.base.committed and not h.base.guard


@pytest.mark.parametrize('field,value',[('filing','forged-obligation'), ('preview','forged'), ('hovedskjema_xml','<forged/>'),
    ('underskjema_xml',{}), ('status','blocked'), ('issues',(rf.Rf1086ReadinessIssue('warning','forged','Forged'),))])
def test_forged_prepared_render_is_rejected_by_held_canonical_check(field,value,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    _, store = preview_source(h.source)
    forged = replace(store.prepared,rendered=replace(store.prepared.rendered,**{field:value}))
    async def run():
        async with h.workflow._admission.admit_year_source('synthetic-token',**h.arguments()) as admitted:
            await admitted.transaction.capture_source_preview_v2(forged)
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_preview_mismatch'): asyncio.run(run())
    assert not h.captures and not h.held_proof_calls and not h.base.committed


@pytest.mark.parametrize('bad', ['prepared','rendered','source','company','year','head'])
def test_direct_held_writer_rejects_malformed_or_stale_inputs_before_proof(bad,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    _, store = preview_source(h.source)
    prepared = store.prepared
    if bad == 'prepared': prepared = object()
    if bad == 'rendered': prepared = replace(prepared,rendered=object())
    if bad == 'source': prepared = replace(prepared,source=replace(h.source,source_sha256='f'*64))
    if bad == 'company': prepared = replace(prepared,source=replace(h.source,company_id=CompanyId(identity(9913))))
    if bad == 'year': prepared = replace(prepared,source=replace(h.source,income_year=IncomeYear(int(h.source.income_year)-1)))
    async def run():
        async with h.workflow._admission.admit_year_source('synthetic-token',**h.arguments()) as admitted:
            if bad == 'head': h.base.current = None
            await admitted.transaction.capture_source_preview_v2(prepared)
    with pytest.raises(rf.Rf1086YearSourceError): asyncio.run(run())
    assert not h.captures and not h.held_proof_calls and not h.base.committed


def test_initial_render_is_outside_and_canonical_cpu_recheck_inside_guard(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    h = PreviewHarnessV2(monkeypatch)
    original = source_preview.render_rf1086_preview
    phases = []
    def render(case):
        phases.append(h.base.guard)
        return original(case)
    monkeypatch.setattr(source_preview,'render_rf1086_preview',render)
    h.generate()
    assert phases == [False,True]
    # Actual DocumentsService storage/retention already asserts outside guard.
    assert h.base.committed


@pytest.mark.parametrize('failure',['proof','append','after_append','cancel'])
def test_late_failure_and_cancellation_rollback_preview_and_close_scope(failure,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    if failure == 'proof': h.base.fail = 'prepare_rf_year_source_governance_proof'
    if failure == 'append': h.base.fail = 'append_source_preview_v1'
    error = asyncio.CancelledError() if failure == 'cancel' else h.base.failure
    if failure in ('after_append','cancel'): h.fail_after_append = error
    with pytest.raises(CorporateGovernanceError if failure == 'proof' else type(error)): h.generate()
    assert not h.captures and not h.base.committed and not h.base.guard and not h.admission.scope._active


@pytest.mark.parametrize('field,value',[('payload_text','invalid'), ('payload_sha256','f'*64),
    ('source_sha256','f'*64), ('created_by','invalid'), ('created_at','invalid')])
def test_invalid_saved_capture_aborts_append_transaction(field,value,monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    h.saved_transform = lambda row: dict(row,**{field:value})
    with pytest.raises((rf.Rf1086YearSourceError,rf.Rf1086ProductionError)): h.generate()
    assert not h.captures and not h.base.committed and not h.admission.scope._active


def test_expired_source_only_lease_rejects_preview_writes(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    _, store = preview_source(h.source)
    async def run():
        async with h.workflow._admission.admit_year_source('synthetic-token',**h.arguments()) as admitted: pass
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await admitted.transaction.capture_source_preview_v2(store.prepared)
    asyncio.run(run())
    assert not h.captures and not h.held_proof_calls


def test_changed_renderer_creates_new_capture_without_changing_retained_one(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    h = PreviewHarnessV2(monkeypatch)
    first = h.generate()
    renderer = source_preview.render_rf1086_preview
    monkeypatch.setattr(source_preview,'render_rf1086_preview',
        lambda case: replace(renderer(case),preview='Future review rendering'))
    second = h.generate()
    assert second.preview.preview_id != first.preview.preview_id
    assert h.captures[first.preview.preview_id.value] == first and len(h.captures) == 2
    rf.build_rf1086_retained_source_readiness_v2(h.source,first)


def test_replay_still_requires_fresh_complete_source_lease(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    first = h.generate()
    h.base.committed = False;h.held_proof_calls.clear()
    h.base.before_guard = lambda: setattr(h.base.basis,'current',None)
    with pytest.raises(rf.Rf1086YearSourceError): h.generate()
    assert h.captures == {first.preview.preview_id.value:first} and not h.held_proof_calls and not h.base.committed


def test_source_only_lease_never_reads_a_saved_preview(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    async def run():
        async with h.workflow._admission.admit_year_source('synthetic-token',**h.arguments()) as admitted:
            assert admitted.source == h.source
            assert set(x.document_id.value for x in admitted.originals) == set(h.base.records)
            assert h.base.guard
    asyncio.run(run())
    assert not any('source_previews' in name for name,_ in h.base.calls)
    assert not h.captures and not h.held_proof_calls


def test_saved_admission_keeps_capture_change_before_original_or_governance_checks(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    saved = h.admission
    h = saved
    async def changed_reader(connection,query,preview_id):
        if h.base.guard:
            return replace(h.capture,created_by=identity(9914))
        return h.capture
    monkeypatch.setattr(h.base.store,'_retained_source_preview_on_connection',changed_reader)
    h.base.before_guard = lambda: setattr(h.base.basis,'view',replace(h.base.basis.view,register_chains=()))
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_preview_stale'): h.read()
    assert not any('assert_retained_original_v1' in name or 'read_guarded_reporting_register_evidence_v1' in name
        for name,_ in h.base.calls)


def test_malformed_lease_source_cannot_reach_writer(monkeypatch):
    h = PreviewHarnessV2(monkeypatch)
    admission = h.workflow._admission.admit_year_source
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def different_source(*args,**kwargs):
        async with admission(*args,**kwargs) as admitted:
            # A fully admitted but different source value cannot authorize the
            # renderer's earlier input. The real held writer is not replaced.
            yield replace(admitted,source=replace(admitted.source,confirmed_at=admitted.source.confirmed_at.replace(year=2030)))
    monkeypatch.setattr(h.workflow._admission,'admit_year_source',different_source)
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_storage_invalid'): h.generate()
    assert not h.captures and not h.held_proof_calls and not h.base.committed
