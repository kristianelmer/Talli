"""Actual V3 workflow/adapters; SQL, guards, Auth and owner inputs are doubles."""
import asyncio
from dataclasses import fields, replace
from datetime import datetime
import json

import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.application.shareholder_register_source_claim_v3 import ShareholderRegisterSourceClaimV3
from talli_backend.modules.company_access.public import CompanyAccessError
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_approval_v3_fixture import ApprovalHarnessV3
from test_rf1086_source_context_v2 import identity
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering


class ClaimHarnessV3:
    def __init__(self, monkeypatch, kind='no_activity', depth=0):
        self.h = h = ApprovalHarnessV3(monkeypatch, kind, depth)
        result = h.approve(h.review())
        saved = h.approvals[result.record_id]
        manifest = json.loads(saved['payload_text'])
        self.approval_id = rf.ApprovalId(result.record_id)
        self.digest = saved['payload_sha256']
        self.approval = rf.Rf1086ApprovalRecord(id=result.record_id, entitlement_id=h.entitlement_id,
            preview_id=h.capture.preview.preview_id.value, company_id=str(h.source.company_id),
            user_id=str(h.base.store.actor_id.subject), income_year=int(h.source.income_year),
            obligation='aksjonaerregisteroppgaven', case_profile='rf1086_full_year_v1',
            adapter_version='rf1086-source-production-v1', payload_hash=h.capture.payload_sha256,
            manifest_hash=self.digest, manifest=manifest, approved_by=str(h.base.store.actor_id.subject),
            approved_at=h.capture.created_at, invalidated_at=None, invalidation_reason=None)
        self.text = saved['payload_text']
        self.claim_row = dict(submission_id=identity(8901), approval_id=self.approval_id.value,
            company_id=str(h.source.company_id), income_year=int(h.source.income_year),
            manifest_sha256=self.digest, payload_sha256=h.capture.payload_sha256,
            predecessor_submission_id=None, claimed_by=str(h.base.store.actor_id.subject),
            claimed_at=h.capture.created_at)
        self.existing = None
        self.expected_head = None
        self.after_header = lambda: None
        self.after_guard = lambda: None
        self.result_transform = lambda value: value
        self.recovery_failure = None
        self.recovery_scope = None
        execute = h.base.connection.execute
        owner = self

        async def execute_claim(sql, args=()):
            cursor = await execute(sql, args)
            if 'read_source_submission_claim_v1(' in sql:
                if owner.recovery_failure is not None:
                    raise owner.recovery_failure
                if not h.base.owner:
                    raise rf.ShareholderRegisterFilingError.forbidden()
                cursor.row = owner.existing
            elif 'filing_approval_snapshots a ' in sql:
                if not h.base.owner:
                    cursor.row = None
                else:
                    cursor.row = dict({field.name:getattr(owner.approval,field.name) for field in fields(owner.approval)}, manifest_text=owner.text)
                    owner.after_header()
            elif 'lock_source_claim_recovery_v3(' in sql:
                owner.after_guard()
                if not h.base.owner:
                    raise rf.ShareholderRegisterFilingError.forbidden()
                cursor.row = {'scope': dict(companyId=str(h.source.company_id), incomeYear=int(h.source.income_year))}
            elif 'claim_source_submission_v3(' in sql:
                assert h.base.guard
                assert args[:3] == (owner.approval_id.value, owner.digest, None if owner.expected_head is None else owner.expected_head.value)
                assert json.loads(args[3])['codec'] == 'rf1086-annual-readiness-v2'
                owner.existing = dict(owner.claim_row)
                cursor.row = {'result': owner.result_transform(dict(claim=owner.claim_row, newlyClaimed=True))}
            return cursor
        h.base.connection.execute = execute_claim
        for name in h.admission.annual:
            async def read(scope, *args, name=name):
                scope._require_active()
                assert h.base.guard and scope._connection is h.base.connection
                h.admission.annual_calls.append(name)
                value = h.admission.annual[name]
                if isinstance(value, BaseException):
                    raise value
                return value
            monkeypatch.setattr(_SourceAdmission, name, read)
        self.workflow = ShareholderRegisterSourceClaimV3(h.admission.workflow._sessions, h.admission.workflow._documents)
        h.base.calls.clear()
        h.admission.annual_calls.clear()
        h.base.committed = False

    def arguments(self):
        return dict(approval_id=self.approval_id, manifest_sha256=self.digest, expected_head=self.expected_head,
            correlation_id=self.h.arguments()['correlation_id'])

    def run(self, **changes):
        return asyncio.run(self.workflow.claim('synthetic-token', **dict(self.arguments(), **changes)))


@pytest.mark.parametrize('kind,depth', [('formation',0), ('no_activity',0), ('dividend',0),
    ('cash_issue',0), ('cash_issue',1), ('cash_issue',2),
    ('loss_covering_reduction',0), ('loss_covering_reduction',1), ('loss_covering_reduction',2)])
def test_actual_workflow_and_held_effect_rebuild_saved_v3_claim(monkeypatch, kind, depth):
    c = ClaimHarnessV3(monkeypatch, kind, depth)
    close_fresh_rendering(monkeypatch)
    result = c.run()
    assert result.newly_claimed and result.claim.approval_id == c.approval_id
    assert result.claim.payload_sha256 == c.h.capture.payload_sha256
    assert c.h.admission.annual_calls == list(c.h.admission.annual) * 2
    names = [name for name,_ in c.h.base.calls]
    historical = next(i for i,name in enumerate(names) if 'lock_source_claim_recovery_v3' in name)
    fresh = next(i for i,name in enumerate(names) if 'company_access_read_rf_admission_v1' in name)
    assert all(i < historical for i,name in enumerate(names) if name == 'bytes')
    assert 'read_source_submission_claim_v1' in names[historical+1] and historical < fresh
    assert c.h.base.committed
    c.h.base.calls.clear()
    replay = c.run()
    assert replay.claim == result.claim and replay.newly_claimed is False
    assert len(c.h.base.calls) == 1 and 'read_source_submission_claim_v1' in c.h.base.calls[0][0]


@pytest.mark.parametrize('change', ['invalidated', 'source', 'annual', 'documents'])
def test_initial_exact_recovery_skips_every_current_input(monkeypatch, change):
    c = ClaimHarnessV3(monkeypatch)
    expected = c.run().claim
    if change == 'invalidated': c.approval = replace(c.approval, invalidated_at=c.approval.approved_at)
    if change == 'source': c.h.admission.stored_source = None
    if change == 'annual': c.h.admission.annual['annual_ledger_inputs'] = RuntimeError('must not read')
    if change == 'documents': c.h.base.contents.clear()
    c.h.base.calls.clear()
    assert c.run() == rf.Rf1086SourceSubmissionClaimResult(expected, False)
    assert len(c.h.base.calls) == 1


@pytest.mark.parametrize('failure', [DocumentsError.forbidden(), CompanyAccessError(status=403, code='company_access_forbidden', title='Forbidden', detail='Access revoked'),
    rf.Rf1086YearSourceError('rf1086_source_changed'), rf.Rf1086ProductionError('payload_changed')])
def test_typed_preflight_denial_recovers_competing_exact_commit(monkeypatch, failure):
    c = ClaimHarnessV3(monkeypatch)
    async def preflight(*args, **kwargs):
        c.existing = c.claim_row
        raise failure
    c.workflow._admission.prepare_preview = preflight
    result = c.run()
    assert result.newly_claimed is False and result.claim.submission_id.value == c.claim_row['submission_id']
    assert not any('lock_source_claim_recovery_v3' in sql for sql,_ in c.h.base.calls)


def test_preflight_denial_without_commit_preserves_original_error(monkeypatch):
    c = ClaimHarnessV3(monkeypatch)
    failure = DocumentsError.forbidden()
    async def preflight(*args, **kwargs): raise failure
    c.workflow._admission.prepare_preview = preflight
    with pytest.raises(DocumentsError) as caught: c.run()
    assert caught.value is failure and c.existing is None


def test_failed_recovery_is_fail_closed(monkeypatch):
    c = ClaimHarnessV3(monkeypatch)
    async def preflight(*args, **kwargs):
        c.existing = c.claim_row
        c.recovery_failure = rf.ShareholderRegisterFilingError.unavailable()
        raise DocumentsError.forbidden()
    c.workflow._admission.prepare_preview = preflight
    with pytest.raises(rf.ShareholderRegisterFilingError): c.run()
    assert not any('claim_source_submission_v3(' in sql for sql,_ in c.h.base.calls)


def test_cancellation_propagates_without_recovery_or_effect(monkeypatch):
    c = ClaimHarnessV3(monkeypatch)
    failure = asyncio.CancelledError('owned request cancelled')
    async def preflight(*args, **kwargs): raise failure
    c.workflow._admission.prepare_preview = preflight
    with pytest.raises(asyncio.CancelledError) as caught: c.run()
    assert caught.value is failure
    assert sum('read_source_submission_claim_v1' in sql for sql,_ in c.h.base.calls) == 1


@pytest.mark.parametrize('change', ['invalidated', 'eligibility', 'annual', 'owner_revoked'])
def test_postwait_recovery_precedes_live_checks_but_preserves_owner(monkeypatch, change):
    c = ClaimHarnessV3(monkeypatch)
    def after_guard():
        c.existing = c.claim_row
        if change == 'invalidated': c.approval = replace(c.approval, invalidated_at=c.approval.approved_at)
        if change == 'eligibility': c.h.base.admission['consequentialOperationsAllowed'] = False
        if change == 'annual': c.h.admission.annual['annual_ledger_inputs'] = RuntimeError('must not read')
        if change == 'owner_revoked': c.h.base.owner = False
    c.after_guard = after_guard
    if change == 'owner_revoked':
        with pytest.raises(rf.ShareholderRegisterFilingError): c.run()
    else:
        assert c.run().newly_claimed is False
    assert not c.h.admission.annual_calls
    assert not any('company_access_read_rf_admission_v1' in sql for sql,_ in c.h.base.calls)


@pytest.mark.parametrize('field,value', [('approval_id',rf.ApprovalId(identity(8902))),
    ('manifest_sha256','f'*64), ('expected_head',rf.SubmissionId(identity(8903)))])
def test_exact_replay_denies_wrong_identity(monkeypatch, field, value):
    c = ClaimHarnessV3(monkeypatch)
    c.run()
    with pytest.raises(rf.Rf1086ProductionError): c.run(**{field:value})


@pytest.mark.parametrize('change', ['invalidated','source','annual','eligibility'])
def test_no_committed_claim_keeps_all_first_effect_checks(monkeypatch, change):
    c = ClaimHarnessV3(monkeypatch)
    if change == 'invalidated': c.approval = replace(c.approval, invalidated_at=c.approval.approved_at)
    if change == 'source': c.h.admission.stored_source = None
    if change == 'annual':
        bank = c.h.admission.annual['bank_year_evidence']
        c.h.admission.annual['bank_year_evidence'] = replace(bank,reconciliation=replace(bank.reconciliation,unmatched_count=1))
    if change == 'eligibility': c.h.base.admission['consequentialOperationsAllowed'] = False
    with pytest.raises((rf.Rf1086ProductionError,rf.Rf1086YearSourceError,rf.ShareholderRegisterFilingError)): c.run()
    assert c.existing is None


def test_held_effect_exact_recovery_precedes_current_owner_reads_and_proof_writes(monkeypatch):
    c=ClaimHarnessV3(monkeypatch)
    first=c.run()
    async def run():
        async with c.h.admission.workflow.admit('synthetic-token',**c.h.admission.arguments()) as admitted:
            c.h.base.calls.clear();c.h.admission.annual_calls.clear()
            c.h.base.current=None
            c.h.admission.annual['annual_ledger_inputs']=RuntimeError('must not read')
            result=await admitted.transaction.claim_source_submission_v3(c.approval_id,c.digest,None,
                c.arguments()['correlation_id'])
            assert result==rf.Rf1086SourceSubmissionClaimResult(first.claim,False)
            assert not c.h.admission.annual_calls and len(c.h.base.calls)==1
    asyncio.run(run())


def test_released_historical_scope_cannot_read_or_transition(monkeypatch):
    c=ClaimHarnessV3(monkeypatch)
    async def run():
        async with c.h.base.store.source_claim_recovery_v3(c.approval_id,c.digest) as recovery:
            assert await recovery.read_source_submission_claim(c.approval_id,c.digest,None) is None
        for read in [lambda:recovery.read_source_submission_claim(c.approval_id,c.digest,None),
                lambda:recovery.read_source_claim_approval_v3(c.approval_id)]:
            with pytest.raises(rf.ShareholderRegisterFilingError):await read()
        with pytest.raises(rf.ShareholderRegisterFilingError):
            async with recovery.fresh_admission_v3():raise AssertionError('released scope entered')
    asyncio.run(run())


@pytest.mark.parametrize('failure', [None,'preflight','held','history'])
def test_correction_delegates_complete_history_and_held_original_revalidation(monkeypatch,failure):
    """Workflow delegation only; correction originals/history are explicit doubles."""
    from test_rf1086_source_correction import predecessor_snapshot, predecessor
    from hashlib import sha256
    c=ClaimHarnessV3(monkeypatch)
    snapshot=predecessor_snapshot();prior=predecessor(snapshot)
    context=c.h.review()
    basis=rf.Rf1086SourceApprovalManifestBasisV3(c.h.source,c.h.capture.preview,
        context.annual_readiness,c.h.base.store.actor_id,c.h.entitlement_id,
        context.review.review_sha256,context.review.warning_codes,prior)
    manifest=rf.build_rf1086_retained_source_approval_manifest_v3(basis,c.h.capture)
    c.text=rf.serialize_rf1086_source_approval_manifest_v3(manifest);c.digest=sha256(c.text.encode()).hexdigest()
    c.approval=replace(c.approval,manifest=manifest.manifest,manifest_hash=c.digest)
    c.expected_head=prior.submission_id;c.claim_row.update(manifest_sha256=c.digest,
        predecessor_submission_id=prior.submission_id.value)
    row=replace(snapshot.submission,company_id=str(c.h.source.company_id),income_year=int(c.h.source.income_year))
    phases=[];selected=object()
    async def prepare(*args,**kwargs):
        phases.append('preflight');assert not c.h.base.guard and kwargs['predecessor']==prior
        if failure=='preflight':raise rf.Rf1086ProductionError('basis_unavailable')
        return selected
    async def admitted(value,scope):
        phases.append('held');assert value is selected and c.h.base.guard
        if failure=='held':raise rf.Rf1086ProductionError('basis_unavailable')
    async def history(scope):
        scope._require_active();phases.append('history')
        return (replace(row,status='sending') if failure=='history' else row,)
    c.workflow._correction.prepare=prepare;c.workflow._correction.assert_admitted=admitted
    monkeypatch.setattr(_SourceAdmission,'submission_history',history)
    if failure is None:
        assert c.run().newly_claimed
        assert phases==['preflight','history','held','history']
    else:
        with pytest.raises(rf.Rf1086ProductionError):c.run()
        assert c.existing is None


@pytest.mark.parametrize('foreign', ['approval','hash'])
def test_historical_scope_pins_the_original_approval_and_hash(monkeypatch,foreign):
    c=ClaimHarnessV3(monkeypatch)
    async def run():
        async with c.h.base.store.source_claim_recovery_v3(c.approval_id,c.digest) as recovery:
            with pytest.raises(rf.Rf1086ProductionError):
                await recovery.read_source_submission_claim(
                    rf.ApprovalId(identity(8999)) if foreign=='approval' else c.approval_id,
                    'f'*64 if foreign=='hash' else c.digest,None)
            if foreign=='approval':
                with pytest.raises(rf.Rf1086ProductionError):
                    await recovery.read_source_claim_approval_v3(rf.ApprovalId(identity(8999)))
    asyncio.run(run())
