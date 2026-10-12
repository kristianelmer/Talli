"""Saved v2 admission: real adapters/bytes, explicitly doubled SQL/authority/annual owners."""
import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
import psycopg

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp, UserId
from rf1086_admission_v2_fixture import AdmissionHarnessV2
from test_rf1086_source_context_v2 import identity
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering


@pytest.mark.parametrize('kind,count', [('formation',0), ('no_activity',0), ('dividend',0),
    ('cash_issue',0), ('cash_issue',1), ('cash_issue',2),
    ('loss_covering_reduction',0), ('loss_covering_reduction',1), ('loss_covering_reduction',2)])
def test_saved_admission_reads_exact_source_preview_and_originals_without_rendering(kind,count,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch,kind,count)
    source_wire = rf.serialize_rf1086_year_source_v2(h.source)
    expected = rf.build_rf1086_source_readiness_v2(h.source,h.preview)
    close_fresh_rendering(monkeypatch)
    admitted = h.read()
    assert admitted.source == h.source and admitted.retained_preview == h.capture
    assert admitted.source_readiness == expected
    assert rf.serialize_rf1086_year_source_v2(admitted.source) == source_wire
    assert set(item.document_id.value for item in admitted.originals) == set(h.base.records)
    assert h.capture_reads == [(False,(str(h.preview.preview_id),str(h.source.company_id),int(h.source.income_year))),
        (True,(str(h.preview.preview_id),str(h.source.company_id),int(h.source.income_year)))]
    assert h.base.committed and not h.base.guard and not admitted.transaction._active
    names = [call[0] for call in h.base.calls]
    guard = next(i for i,name in enumerate(names) if 'lock_year_source_v1' in name)
    assert all(i < guard for i,name in enumerate(names) if name == 'bytes')
    assert not any('prepare_rf_year_source_governance_proof' in name or 'append_' in name
        or 'bridge_source_preview' in name for name in names)


def test_current_owner_can_read_unavailable_historical_actor_without_rewriting_retained_wire(monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    wire = rf.serialize_rf1086_year_source_v2(h.source)
    historical = h.source.confirmed_by
    current = replace(historical,subject=UserId(identity(9901)))
    h.base.store._verified = replace(h.base.store._verified,actor_id=current)
    h.authenticated_actors = {'synthetic-token':current}
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(h.workflow._sessions.session('historical-token'))
    h.authentication_calls.clear()
    close_fresh_rendering(monkeypatch)
    admitted = h.read()
    assert admitted.transaction.actor_id == current and admitted.source.confirmed_by == historical
    assert admitted.retained_preview.created_by == str(historical.subject)
    assert rf.serialize_rf1086_year_source_v2(admitted.source) == wire
    assert all(record.created_by == historical for record in h.base.records.values())
    assert historical not in h.authenticated_actors.values() and h.authentication_calls == [current]


@pytest.mark.parametrize('field,value',[('created_by',identity(9902)),
    ('created_at','2030-01-01T00:00:00+00:00'), ('payload_text','truncated'), ('payload_sha256','f'*64)])
def test_waiting_capture_change_cannot_enter_admission(field,value,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    h.held_transform = lambda row: dict(row,**{field:value})
    close_fresh_rendering(monkeypatch)
    with pytest.raises((rf.Rf1086YearSourceError,rf.Rf1086ProductionError)): h.read()
    assert not h.base.committed and not h.base.guard


@pytest.mark.parametrize('missing',['current_source','stored_source'])
def test_missing_source_fails_without_observation_commit(missing,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    if missing == 'current_source': h.base.before_guard = lambda: setattr(h.base,'current',None)
    else: h.stored_source = None
    with pytest.raises(rf.Rf1086YearSourceError): h.read()
    assert not h.base.committed and not h.base.guard


@pytest.mark.parametrize('field',[ 'company_id', 'income_year', 'preview_id' ])
def test_preflight_query_is_bound_to_requested_scope(field,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    arguments = h.arguments()
    arguments[field] = {'company_id':CompanyId(identity(9903)),
        'income_year':IncomeYear(int(h.source.income_year)-1), 'preview_id':rf.PreviewId(identity(9904))}[field]
    async def run():
        async with h.workflow.admit('synthetic-token',**arguments): raise AssertionError('foreign scope admitted')
    with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(run())
    assert not any(name == 'bytes' for name,_ in h.base.calls) and not h.base.committed


def test_expired_scope_rejects_all_live_reads(monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    admitted = h.read()
    async def run():
        reads = (admitted.transaction.company_identity, admitted.transaction.current_source,
            lambda: admitted.transaction.retained_source_preview(h.preview.preview_id),
            lambda: admitted.transaction.assert_original(admitted.originals[0]),
            lambda: admitted.transaction.governance_register_evidence(h.arguments()['correlation_id']),
            *[getattr(admitted.transaction,name) for name in h.annual])
        for read in reads:
            with pytest.raises(rf.ShareholderRegisterFilingError): await read()
    asyncio.run(run())


def test_caller_cancellation_closes_scope_without_commit(monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    cancellation = asyncio.CancelledError('owned admission cancelled')
    async def run():
        async with h.workflow.admit('synthetic-token',**h.arguments()): raise cancellation
    with pytest.raises(asyncio.CancelledError) as result: asyncio.run(run())
    assert result.value is cancellation and not h.base.committed and not h.base.guard
    assert not h.scope._active


@pytest.mark.parametrize('state',['ready','warning','blocked','missing_interview'])
def test_annual_owner_order_and_policy_use_saved_preview_inside_live_scope(state,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch,'no_activity',0)
    if state == 'warning':
        value = h.annual['annual_ledger_inputs'];h.annual['annual_ledger_inputs'] = replace(value,period_locks=())
    if state == 'blocked':
        value = h.annual['bank_year_evidence']
        h.annual['bank_year_evidence'] = replace(value,reconciliation=replace(value.reconciliation,unmatched_count=1))
    if state == 'missing_interview': h.annual['annual_interview'] = None
    close_fresh_rendering(monkeypatch)
    proof = h.read_annual()
    assert proof.readiness_status == ('warning' if state == 'missing_interview' else state)
    assert h.annual_calls == list(h.annual) and h.base.committed and not h.scope._active
    assert proof.not_evaluated == ('current_review_comments','filing_overrides','authority_permission',
        'billing_entitlement','technical_release','warning_acknowledgements')


@pytest.mark.parametrize('reader',['annual_opening_inputs','annual_ledger_inputs','bank_year_evidence',
    'annual_interview','annual_document_inputs'])
def test_failed_annual_owner_read_aborts_instead_of_becoming_empty_inputs(reader,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    h.annual[reader] = rf.ShareholderRegisterFilingError.unavailable()
    with pytest.raises(rf.ShareholderRegisterFilingError): h.read_annual()
    assert not h.base.committed and not h.scope._active


@pytest.mark.parametrize('reader',['annual_opening_inputs','annual_ledger_inputs','annual_interview','annual_document_inputs'])
def test_foreign_annual_owner_scope_is_rejected(reader,monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    h.annual[reader] = replace(h.annual[reader],income_year=IncomeYear(int(h.source.income_year)-1))
    with pytest.raises(rf.Rf1086YearSourceError): h.read_annual()
    assert not h.base.committed and not h.scope._active


def test_observation_time_change_does_not_change_readiness_proof(monkeypatch):
    h = AdmissionHarnessV2(monkeypatch)
    first = h.read_annual()
    bank = h.annual['bank_year_evidence']
    h.annual['bank_year_evidence'] = replace(bank,reconciliation=replace(bank.reconciliation,
        observed_at=Timestamp(bank.reconciliation.observed_at.value+timedelta(seconds=1))))
    assert h.read_annual() == first


@pytest.mark.parametrize('change',['owner','identity','document_metadata','document_bytes','governance','rf_observation'])
def test_changed_current_evidence_cannot_enter_saved_admission(change,monkeypatch):
    from talli_backend.modules.documents.public import DocumentsError
    from talli_backend.modules.corporate_governance.public import CorporateGovernanceError
    h = AdmissionHarnessV2(monkeypatch)
    key = next(iter(h.base.records))
    if change == 'owner': h.base.before_guard = lambda: h.base.admission.update(acceptedOwner=False)
    if change == 'identity': h.base.before_guard = lambda: h.base.admission.update(legalName='Changed AS')
    if change == 'document_metadata':
        h.base.before_guard = lambda: h.base.records.update({key:replace(h.base.records[key],name='Changed.pdf')})
    if change == 'document_bytes': h.base.contents[key] = b'%PDF-1.7 changed bytes'
    if change == 'governance':
        h.base.before_guard = lambda: setattr(h.base.basis,'view',replace(h.base.basis.view,register_chains=()))
    if change == 'rf_observation':
        h.base.before_guard = lambda: setattr(h.base.basis,'current',None)
    with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086YearSourceError,DocumentsError,
            CorporateGovernanceError,psycopg.DatabaseError)) as result:
        h.read()
    assert not isinstance(result.value,AssertionError)
    assert not h.base.committed and not h.base.guard


def test_changed_renderer_and_fresh_builders_cannot_rewrite_saved_observations(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    h = AdmissionHarnessV2(monkeypatch)
    original = h.read()
    annual = h.read_annual()
    renderer = rf.render_rf1086_preview
    calls = []
    def changed_renderer(case):
        calls.append('renderer')
        return replace(renderer(case),preview='Future rendering',hovedskjema_xml='<future/>')
    def changed_source(*args):
        calls.append('fresh source builder')
        return replace(original.source_readiness,proof_sha256='f'*64)
    def changed_annual(*args):
        calls.append('fresh annual builder')
        return replace(annual,proof_sha256='f'*64)
    monkeypatch.setattr(source_preview,'render_rf1086_preview',changed_renderer)
    monkeypatch.setattr(rf,'render_rf1086_preview',changed_renderer)
    monkeypatch.setattr(rf,'build_rf1086_source_readiness_v2',changed_source)
    monkeypatch.setattr(rf,'build_rf1086_annual_readiness_v2',changed_annual)
    current = h.read()
    assert current.retained_preview == original.retained_preview
    assert current.source_readiness == original.source_readiness
    assert h.read_annual() == annual and not calls
