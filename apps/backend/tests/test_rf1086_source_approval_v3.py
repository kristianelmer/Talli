"""Closed retained approval uses current held owners; no genuine SQL/Auth proof."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_approval_v3_fixture import ApprovalHarnessV3
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering
from test_rf1086_source_context_v2 import identity


@pytest.mark.parametrize('kind,depth', [('formation', 0), ('no_activity', 0), ('dividend', 0),
    ('cash_issue', 0), ('cash_issue', 1), ('cash_issue', 2),
    ('loss_covering_reduction', 0), ('loss_covering_reduction', 1), ('loss_covering_reduction', 2)])
def test_actual_held_review_and_append_rebuild_annual_inputs_and_preserve_capture(monkeypatch, kind, depth):
    h = ApprovalHarnessV3(monkeypatch, kind, depth)
    close_fresh_rendering(monkeypatch)
    context = h.review()
    assert context.review.can_approve
    assert h.admission.annual_calls == list(h.admission.annual)
    h.admission.annual_calls.clear()
    result = h.approve(context)
    assert h.admission.annual_calls == list(h.admission.annual) * 2
    assert result.company_id == h.source.company_id and result.income_year == h.source.income_year
    assert h.base.committed and not h.admission.scope._active
    assert h.admission.capture == h.capture and len(h.approvals) == 1
    saved = next(iter(h.approvals.values()))
    assert saved['actor'] == str(h.base.store.actor_id.subject)
    assert 'production-source-approval-v3' in saved['payload_text']
    assert h.approve(context) == result and len(h.approvals) == 1


@pytest.mark.parametrize('state', ['ready', 'warning', 'blocked'])
def test_review_reports_actual_current_annual_policy_and_exact_warnings(monkeypatch, state):
    h = ApprovalHarnessV3(monkeypatch)
    if state == 'warning':
        h.admission.annual['annual_ledger_inputs'] = replace(h.admission.annual['annual_ledger_inputs'], period_locks=())
    if state == 'blocked':
        bank = h.admission.annual['bank_year_evidence']
        h.admission.annual['bank_year_evidence'] = replace(bank, reconciliation=replace(bank.reconciliation, unmatched_count=1))
    close_fresh_rendering(monkeypatch)
    context = h.review()
    assert context.annual_readiness.readiness_status == state
    assert context.review.warning_codes == context.annual_readiness.required_warning_codes
    assert context.review.can_approve is (state != 'blocked')
    if state == 'blocked':
        with pytest.raises(rf.Rf1086ProductionError): h.approve(context)
        assert not h.approvals
    else:
        h.approve(context)
        if state == 'warning':
            with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
                h.approve(context, acknowledged_warning_codes=())


@pytest.mark.parametrize('field, value', [('companyId', identity(8802)), ('incomeYear', 2027),
    ('reviewSha256', 'invalid'), ('warningCodes', ['forged']), ('blockers', ['z', 'a']), ('extra', True)])
def test_malformed_sql_projection_aborts_held_review(monkeypatch, field, value):
    h = ApprovalHarnessV3(monkeypatch)
    h.context_transform = lambda row: dict(row, **{field: value})
    with pytest.raises(rf.Rf1086ProductionError): h.review()
    assert not h.base.committed and not h.bridges and not h.approvals


def test_annual_owner_changes_between_review_and_write_cannot_use_forged_ready_manifest(monkeypatch):
    h = ApprovalHarnessV3(monkeypatch)
    context = h.review()
    bank = h.admission.annual['bank_year_evidence']
    h.after_context = lambda: h.admission.annual.update(bank_year_evidence=replace(bank,
        reconciliation=replace(bank.reconciliation, unmatched_count=1)))
    h.base.committed = False
    close_fresh_rendering(monkeypatch)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): h.approve(context)
    assert not h.approvals and not h.base.committed
    assert len(h.admission.annual_calls) == 15


@pytest.mark.parametrize('failure', [RuntimeError('late append'), asyncio.CancelledError('owned cancellation')])
def test_late_failure_rolls_back_new_approval_and_bridge(monkeypatch, failure):
    h = ApprovalHarnessV3(monkeypatch)
    context = h.review()
    h.bridges.clear()
    h.base.committed = False
    def fail(): raise failure
    h.after_append = fail
    with pytest.raises(type(failure)) as result: h.approve(context)
    assert result.value is failure
    assert not h.approvals and not h.bridges and not h.base.committed
    assert not h.admission.scope._active


def test_closed_scope_denies_review_and_append_ports(monkeypatch):
    h = ApprovalHarnessV3(monkeypatch)
    h.review()
    async def run():
        for invoke in [lambda: h.admission.scope.read_source_approval_context_v3(
            h.capture.preview.preview_id, h.entitlement_id, h.arguments()['correlation_id']),
            lambda: h.admission.scope.append_source_approval_v3(h.capture.preview.preview_id,
                h.entitlement_id, None, 'f' * 64, h.arguments()['correlation_id'])]:
            with pytest.raises(rf.ShareholderRegisterFilingError): await invoke()
    asyncio.run(run())


def test_self_consistent_forged_annual_manifest_is_rejected_by_current_owner_reads(monkeypatch):
    h = ApprovalHarnessV3(monkeypatch)
    close_fresh_rendering(monkeypatch)
    async def run():
        async with h.workflow._admission.admit('synthetic-token', **h.admission.arguments()) as admitted:
            transaction = admitted.transaction
            context = await transaction.read_source_approval_context_v3(h.capture.preview.preview_id,
                h.entitlement_id, h.arguments()['correlation_id'])
            forged_inputs = replace(context.annual_readiness.annual_inputs, period_lock_ids=(identity(8803),))
            forged_annual = rf.build_rf1086_retained_annual_readiness_v2(h.source, h.capture, forged_inputs)
            assert forged_annual.readiness_status == 'ready'
            assert forged_annual.proof_sha256 != context.annual_readiness.proof_sha256
            basis = rf.Rf1086SourceApprovalManifestBasisV3(h.source, h.capture.preview, forged_annual,
                transaction.actor_id, h.entitlement_id, context.review.review_sha256, context.review.warning_codes)
            manifest = rf.build_rf1086_retained_source_approval_manifest_v3(basis, h.capture)
            await transaction.append_source_approval_v3(h.capture.preview.preview_id, h.entitlement_id,
                manifest, context.review.review_sha256, h.arguments()['correlation_id'])
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): asyncio.run(run())
    assert not h.approvals and not h.bridges and not h.base.committed
    assert h.admission.annual_calls == list(h.admission.annual) * 2


@pytest.mark.parametrize('failure', [None, 'preflight', 'held', 'history'])
def test_v3_correction_requires_preflight_complete_history_and_held_revalidation(monkeypatch, failure):
    """Exercise new workflow delegation; correction owner ports are explicit doubles."""
    from test_rf1086_source_correction import predecessor_snapshot, predecessor
    h = ApprovalHarnessV3(monkeypatch)
    context = h.review()
    snapshot = predecessor_snapshot()
    prior = predecessor(snapshot)
    row = replace(snapshot.submission, company_id=str(h.source.company_id), income_year=int(h.source.income_year))
    history = (replace(row, status='sending') if failure == 'history' else row,)
    phases = []
    selected = object()
    async def prepare(*args, **kwargs):
        assert not h.base.guard and kwargs['predecessor'] == prior
        phases.append('preflight')
        if failure == 'preflight': raise rf.Rf1086ProductionError('basis_unavailable')
        return selected
    async def assert_admitted(value, scope):
        assert value is selected and h.base.guard and scope._active
        phases.append('held')
        if failure == 'held': raise rf.Rf1086ProductionError('basis_unavailable')
    h.workflow._correction.prepare = prepare
    h.workflow._correction.assert_admitted = assert_admitted
    admission = h.base.store.source_admission
    @asynccontextmanager
    async def with_history(query):
        async with admission(query) as scope:
            async def complete_history():
                assert h.base.guard
                phases.append('history')
                return history
            scope.submission_history = complete_history
            yield scope
    h.base.store.source_admission = with_history
    before_contexts = len(h.contexts)
    if failure is None:
        h.approve(context, predecessor=prior)
        assert phases == ['preflight', 'history', 'held'] and len(h.contexts) == before_contexts+2
        manifest = json.loads(next(iter(h.approvals.values()))['payload_text'])
        assert manifest['predecessor'] == dict(submissionId=prior.submission_id.value,
            manifestSha256=prior.manifest_sha256, reason=prior.reason)
    else:
        with pytest.raises(rf.Rf1086ProductionError): h.approve(context, predecessor=prior)
        assert not h.approvals and len(h.contexts) == before_contexts
