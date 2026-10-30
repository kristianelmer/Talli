"""New capture interface; actual adapters/producers with SQL/authority doubles."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import psycopg
import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.documents import public as docs
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.shared.kernel import IdempotencyKey
from rf1086_guarded_capture_v2_fixture import CaptureHarness, source_row, KEY, CORRELATION
from test_shareholder_register_source_workflow import Harness
from test_rf1086_source_context_v2 import context, identity, NOW
from talli_backend.application.shareholder_register_source_capture_v2 import assert_source_capture_originals_v2
from talli_backend.shared.kernel import CompanyId, IncomeYear, UserId


@pytest.mark.parametrize('kind,count',[('formation',0),('no_activity',0),('dividend',0),
    ('cash_issue',0),('cash_issue',1),('cash_issue',2),
    ('loss_covering_reduction',0),('loss_covering_reduction',1),('loss_covering_reduction',2)])
def test_actual_capture_preflight_and_same_connection_append(kind,count,monkeypatch):
    h=CaptureHarness(monkeypatch,kind,count)
    result=h.capture()
    rf.assert_rf1086_year_source_integrity_v2(result)
    assert result.command==h.command and result.governance_projection.chain_count==(1 if count or kind in ('cash_issue','loss_covering_reduction') else 0)
    assert h.committed and not h.guard
    assert set(h.retained)=={row.document_id for row in h.command.documents}
    assert rf.serialize_rf1086_year_source_v2(result)==h.append_args[10]
    names=[call[0] for call in h.calls]
    guard=next(i for i,n in enumerate(names) if 'lock_year_source_capture_v2' in n)
    proof=next(i for i,n in enumerate(names) if 'prepare_rf_year_source_governance_proof_v1' in n)
    append=next(i for i,n in enumerate(names) if 'append_year_source_v2(' in n)
    assert all(i<guard for i,n in enumerate(names) if n=='bytes')
    assert proof<append and all(i<proof for i,n in enumerate(names) if 'retain_verified_rf_evidence_v1' in n)


@pytest.mark.parametrize('version',[1,2])
def test_committed_original_replay_bypasses_broken_fresh_inputs(version,monkeypatch):
    h=CaptureHarness(monkeypatch,'no_activity',0)
    source=Harness().capture() if version==1 else h.capture()
    h.command=source.command;h.replay=source_row(source);h.calls=[]
    h.company=None;h.records={};h.contents={};h.fail='company_access_read_rf_admission_v1'
    result=h.capture()
    assert result==source and h.calls[0][0].startswith('select public.company_access_is_accepted_owner_v1')
    assert len(h.calls)==2 and not h.guard


@pytest.mark.parametrize('version',[1,2])
def test_committed_replay_conflict_fails_before_any_mutable_refresh(version,monkeypatch):
    h=CaptureHarness(monkeypatch,'no_activity',0)
    source=Harness().capture() if version==1 else h.capture()
    h.command=replace(source.command,paid_in_reviewed=False);h.replay=source_row(source);h.calls=[];h.company=None
    with pytest.raises(rf.Rf1086YearSourceError):h.capture()
    assert len(h.calls)==2 and not h.guard


def test_racing_receipt_under_guard_precedes_fresh_eligibility_and_original_rechecks(monkeypatch):
    h=CaptureHarness(monkeypatch)
    original=h.capture();h.current=None;h.committed=False;h.calls=[]
    def race():
        h.replay=source_row(original);h.admission['acceptedOwner']=False
        for key,record in h.records.items():h.records[key]=replace(record,name='Changed after preflight')
    h.before_guard=race
    result=h.capture()
    assert result==original and h.committed
    names=[c[0] for c in h.calls]
    assert not any('company_access_read_rf_admission_v1' in n or 'assert_retained_original_v1' in n for n in names)
    assert any(n=='bytes' for n in names) and not any('append_year_source_v2(' in n for n in names)


def test_direct_atomic_replay_ignores_unavailable_fresh_original_union(monkeypatch):
    h=CaptureHarness(monkeypatch);original=h.capture();h.replay=source_row(original);h.calls=[]
    result=asyncio.run(h.store.record_year_source_v2(h.command,originals=(),idempotency_key=KEY,correlation_id=CORRELATION))
    assert result==original and len(h.calls)==2


@pytest.mark.parametrize('stage',['company_access_read_rf_admission_v1','documents.assert_retained_original_v1',
    'read_guarded_reporting_register_evidence_v1','retain_verified_rf_evidence_v1',
    'prepare_rf_year_source_governance_proof_v1','append_year_source_v2('])
def test_guarded_dependency_failure_never_commits_source(stage,monkeypatch):
    h=CaptureHarness(monkeypatch);h.fail=stage
    expected=gov.CorporateGovernanceError if stage in (
        'read_guarded_reporting_register_evidence_v1','prepare_rf_year_source_governance_proof_v1') else psycopg.DatabaseError
    with pytest.raises(expected):h.capture()
    assert h.current is None and not h.committed and not h.guard


@pytest.mark.parametrize('stage',['read_guarded_reporting_register_evidence_v1','prepare_rf_year_source_governance_proof_v1','append_year_source_v2('])
def test_guarded_cancellation_propagates_without_commit(stage,monkeypatch):
    h=CaptureHarness(monkeypatch);h.fail=stage;h.failure=asyncio.CancelledError('owned capture cancelled')
    with pytest.raises(asyncio.CancelledError) as failure:h.capture()
    assert failure.value is h.failure and h.current is None and not h.committed and not h.guard


@pytest.mark.parametrize('field,value',[('source_sha256','f'*64),('snapshot_text','truncated'),('actor_id',identity(991))])
def test_malformed_saved_row_aborts_append_transaction(field,value,monkeypatch):
    h=CaptureHarness(monkeypatch);h.saved_transform=lambda row:dict(row,**{field:value})
    with pytest.raises(rf.Rf1086YearSourceError):h.capture()
    assert h.current is None and not h.committed and not h.guard


def test_metadata_changed_between_byte_preflight_and_guard_aborts_before_retention(monkeypatch):
    h=CaptureHarness(monkeypatch)
    def mutate():
        key=next(iter(h.records));h.records[key]=replace(h.records[key],name='Changed metadata')
    h.before_guard=mutate
    with pytest.raises(psycopg.DatabaseError):h.capture()
    assert h.retained and h.current is None and not h.committed
    assert not any('retain_verified_rf_evidence_v1' in call[0] for call in h.calls)


@pytest.mark.parametrize('version',[1,2])
def test_fresh_v2_capture_preserves_exact_v1_or_v2_predecessor(version,monkeypatch):
    h=CaptureHarness(monkeypatch,'cash_issue',0)
    if version==2:previous=h.capture()
    else:
        value=context(h.basis)
        old=rf.Rf1086VerifiedYearSourceContext(value.actor_id,True,value.company_id,value.income_year,
            value.company,value.company_identity_sha256,value.documents,
            tuple(row.original for row in value.governance_receipts),True,value.governance_projection.original_enumeration_sha256)
        previous=rf.prepare_rf1086_year_source(h.command,context=old,source_id=rf.Rf1086YearSourceId(identity(1800)),
            confirmed_at=NOW+timedelta(days=1))
    h.current=source_row(previous);h.clock=previous.confirmed_at+timedelta(days=1);h.committed=False
    h.key=IdempotencyKey('guarded-source-v2-capture-002')
    h.command=replace(h.command,supersedes_source_id=previous.source_id,supersedes_source_sha256=previous.source_sha256,
        correction_reason='Recheck current complete evidence')
    current=h.capture()
    assert current.version==previous.version+1 and current.command.supersedes_source_id==previous.source_id
    assert h.append_args[7:10]==(previous.source_id.value,previous.source_sha256,h.command.correction_reason)
    assert h.committed


@pytest.mark.parametrize('field,value',[('role','read_only'),('entity_type','ENK'),
    ('identity_confirmed_at',None),('identity_locked_at',None),('id',identity(987)),('name','Changed legal name')])
def test_preflight_current_company_mismatch_stops_before_document_bytes(field,value,monkeypatch):
    h=CaptureHarness(monkeypatch)
    setattr(h.company,field,value)
    with pytest.raises(rf.Rf1086YearSourceError):h.capture()
    assert not any(call[0]=='bytes' for call in h.calls)
    assert not h.committed and h.current is None


@pytest.mark.parametrize('attack',['foreign_company','duplicate','wrong_type'])
def test_entire_document_union_is_checked_before_any_original_download(attack,monkeypatch):
    h=CaptureHarness(monkeypatch);documents=h.command.documents
    if attack=='foreign_company':documents=(*documents[:-1],replace(documents[-1],company_id=CompanyId(identity(987))))
    elif attack=='duplicate':documents=(*documents,documents[-1])
    else:documents=(*documents[:-1],object())
    h.command=replace(h.command,documents=documents)
    with pytest.raises(rf.Rf1086YearSourceError):h.capture()
    assert not any(call[0]=='bytes' for call in h.calls)
    assert not h.guard and not h.committed


@pytest.mark.parametrize('field,value',[('acceptedOwner',False),('entityType','ENK'),
    ('consequentialOperationsAllowed',False),('companyId',identity(987)),
    ('incomeYear',2024),('legalName','Changed after preflight')])
def test_held_admission_change_after_byte_preflight_cannot_append(field,value,monkeypatch):
    h=CaptureHarness(monkeypatch)
    h.before_guard=lambda:h.admission.update({field:value})
    with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086YearSourceError)):h.capture()
    assert any(call[0]=='bytes' for call in h.calls)
    assert not any('append_year_source_v2(' in call[0] for call in h.calls)
    assert not h.committed and h.current is None


@pytest.mark.parametrize('attack',['missing','extra','duplicate','list','foreign_company','source_year','metadata','content','length'])
def test_verified_receipts_must_bind_the_exact_command_document_union(attack,monkeypatch):
    h=CaptureHarness(monkeypatch);h.capture()
    originals=tuple(h.retained.values());first=originals[0]
    if attack=='missing':originals=originals[1:]
    elif attack=='extra':originals=(*originals,replace(first,document_id=docs.DocumentId(identity(987))))
    elif attack=='duplicate':originals=(first,*originals[1:-1],first)
    elif attack=='list':originals=list(originals)
    else:
        field,value={'foreign_company':('company_id',CompanyId(identity(987))),
            'source_year':('source_income_year',IncomeYear(int(first.source_income_year)+1)),'metadata':('metadata_sha256','f'*64),
            'content':('content_sha256','f'*64),'length':('byte_length',first.byte_length+1)}[attack]
        assert getattr(first,field)!=value
        originals=(replace(first,**{field:value}),*originals[1:])
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_documents_unverified'):
        assert_source_capture_originals_v2(h.command,originals)


def test_wrong_current_actor_cannot_replay_another_actors_committed_receipt(monkeypatch):
    h=CaptureHarness(monkeypatch);source=h.capture();h.replay=source_row(source);h.calls=[]
    h.command=replace(h.command,actor_id=replace(h.command.actor_id,subject=UserId(identity(987))))
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_owner_required'):h.capture()
    assert h.calls==[]
