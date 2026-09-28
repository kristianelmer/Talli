"""Full-year corrections rebuild historical source approval and its durable claim."""
from dataclasses import replace
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_approval_archive import source_archive
from test_rf1086_source_correction import predecessor_snapshot, assert_valid, CorrectionHarness
from test_rf1086_year_source import ACTOR


def full_year_predecessor(kind='no_activity',status='accepted'):
    archive=source_archive(kind)
    approval,preview,lineage=archive.approvals[0],archive.previews[0],archive.source_approval_lineage[0]
    old=predecessor_snapshot(status)
    assert old.company_id==archive.company_id and old.income_year==archive.income_year
    submission=replace(old.submission,approval_id=approval.id,entitlement_id=approval.entitlement_id,
        case_profile=approval.case_profile,adapter_version=approval.adapter_version,payload_hash=approval.payload_hash)
    claim=rf.Rf1086SourceSubmissionClaim(rf.SubmissionId(submission.id),rf.ApprovalId(approval.id),
        archive.company_id,archive.income_year,approval.manifest_hash,approval.payload_hash,None,ACTOR,approval.approved_at)
    return replace(old,submission=submission,approval=approval,preview=preview,
        source_approval_lineage=lineage,source_claim=claim)


@pytest.mark.parametrize('kind',['no_activity','formation','dividend','cash_issue','loss_covering_reduction'])
@pytest.mark.parametrize('status',['accepted','rejected'])
def test_full_year_predecessor_rebuilds_original_source_manifest_and_claim(kind,status):
    snapshot=full_year_predecessor(kind,status)
    # A later invalidation does not erase the evidence of a filing already sent.
    snapshot=replace(snapshot,approval=replace(snapshot.approval,invalidated_at=snapshot.approval.approved_at,
        invalidation_reason='Later source version'))
    assert_valid(snapshot)


@pytest.mark.parametrize('change',['missing-lineage','missing-claim','untyped-lineage','untyped-claim',
    'source','preview','bridge','review','manifest','claim-submission','claim-approval','claim-company',
    'claim-year','claim-payload','claim-manifest','claim-parent','journal-parent','claim-time','projection'])
def test_missing_or_changed_full_year_retained_identity_cannot_authorize_correction(change):
    snapshot=full_year_predecessor();line=snapshot.source_approval_lineage;claim=snapshot.source_claim
    if change=='missing-lineage':snapshot=replace(snapshot,source_approval_lineage=None)
    if change=='missing-claim':snapshot=replace(snapshot,source_claim=None)
    if change=='untyped-lineage':snapshot=replace(snapshot,source_approval_lineage={})
    if change=='untyped-claim':snapshot=replace(snapshot,source_claim={})
    if change=='source':line=replace(line,source=replace(line.source,source_sha256='e'*64))
    if change=='preview':line=replace(line,source_preview=replace(line.source_preview,preview_text='changed'))
    if change=='bridge':line=replace(line,bridge=replace(line.bridge,payload_sha256='e'*64))
    if change=='review':line=replace(line,review_text='{}')
    if change=='manifest':line=replace(line,manifest_text=line.manifest_text+' ')
    if change=='claim-submission':claim=replace(claim,submission_id=rf.SubmissionId(str(UUID(int=888))))
    if change=='claim-approval':claim=replace(claim,approval_id=rf.ApprovalId(str(UUID(int=888))))
    if change=='claim-company':claim=replace(claim,company_id=rf.CompanyId(str(UUID(int=888))))
    if change=='claim-year':claim=replace(claim,income_year=rf.IncomeYear(2024))
    if change=='claim-payload':claim=replace(claim,payload_sha256='e'*64)
    if change=='claim-manifest':claim=replace(claim,manifest_sha256='e'*64)
    if change=='claim-parent':claim=replace(claim,predecessor_submission_id=rf.SubmissionId(str(UUID(int=888))))
    if change=='journal-parent':snapshot=replace(snapshot,submission=replace(snapshot.submission,supersedes_submission_id=str(UUID(int=888))))
    if change=='claim-time':claim=replace(claim,claimed_at='2026-01-01T00:00:00')
    if change=='projection':snapshot=replace(snapshot,preview=replace(snapshot.preview,underskjema_xml={'changed':'xml'}))
    if change in ('source','preview','bridge','review','manifest'):snapshot=replace(snapshot,source_approval_lineage=line)
    if change.startswith('claim-'):snapshot=replace(snapshot,source_claim=claim)
    with pytest.raises(rf.Rf1086ProductionError):assert_valid(snapshot)


@pytest.mark.parametrize('change',['source-fields-on-legacy','legacy-profile-with-source-data'])
def test_profiles_cannot_mix_or_fall_back_to_legacy_validation(change):
    source=full_year_predecessor()
    if change=='source-fields-on-legacy':
        snapshot=replace(predecessor_snapshot(),source_approval_lineage=source.source_approval_lineage,source_claim=source.source_claim)
    else:
        snapshot=replace(source,approval=replace(source.approval,case_profile='rf1086_no_activity_v1'),
            submission=replace(source.submission,case_profile='rf1086_no_activity_v1'))
    with pytest.raises(rf.Rf1086ProductionError):assert_valid(snapshot)


@pytest.mark.parametrize('status',['accepted','rejected'])
def test_application_verifies_full_year_feedback_bytes_and_locked_lineage_before_approval(status):
    h=CorrectionHarness(snapshot=full_year_predecessor('formation',status))
    assert h.approve(predecessor=h.prior)==h.result and h.committed
    assert h.calls.count('prior_original')==2
    assert h.calls.index('prior_read') < h.calls.index('guard') < h.calls.index('prior_lock') < h.calls.index('append')
    assert h.writes[0].manifest['predecessor']['manifestSha256']==h.prior_snapshot.approval.manifest_hash


def test_claim_change_during_byte_preflight_aborts_correction_approval():
    h=CorrectionHarness(snapshot=full_year_predecessor())
    # Even an otherwise valid timestamp change means the retained snapshot moved.
    claim=replace(h.locked_snapshot.source_claim,claimed_at='2026-01-02T00:00:00+00:00')
    h.locked_snapshot=replace(h.locked_snapshot,source_claim=claim)
    with pytest.raises(rf.Rf1086ProductionError):h.approve(predecessor=h.prior)
    assert not h.committed and not h.writes


@pytest.mark.parametrize('locked',[False,True])
@pytest.mark.parametrize('missing',[None,'binding','source','bridge','claim'])
def test_adapter_reads_full_year_lineage_and_claim_on_the_predecessor_connection(locked,missing):
    import asyncio
    from contextlib import asynccontextmanager
    from dataclasses import fields,asdict
    from types import SimpleNamespace
    from psycopg.pq import TransactionStatus
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
    from talli_backend.adapters.supabase_ledger import _VerifiedActor
    from test_postgres_shareholder_register_filing import session
    snapshot=full_year_predecessor();line=snapshot.source_approval_lineage;claim=snapshot.source_claim
    store=session({});store._verified=_VerifiedActor(ACTOR,'{}');calls=[]
    def row(record):return {f.name:getattr(record,f.name) for f in fields(record)}
    binding={k:v for k,v in row(line).items() if k not in ('source','source_preview','bridge')}
    claim_row={'submission_id':claim.submission_id.value,'approval_id':claim.approval_id.value,
        'company_id':str(claim.company_id),'income_year':int(claim.income_year),
        'manifest_sha256':claim.manifest_sha256,'payload_sha256':claim.payload_sha256,
        'predecessor_submission_id':None,'claimed_by':str(ACTOR.subject),'claimed_at':claim.claimed_at}
    class Cursor:
        def __init__(self,rows):self.rows=rows
        async def fetchone(self):return self.rows[0] if self.rows else None
        async def fetchall(self):return self.rows
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args):
            calls.append((sql,args))
            assert not any(key in sql for key in ('year_source_heads','documents.','billing.','authority_connections.'))
            if 'assert_member' in sql:return Cursor([])
            if 'lock_correction_predecessor' in sql:
                assert locked;return Cursor([row(snapshot.submission)])
            if 'production_filing_submissions' in sql:
                assert not locked;return Cursor([row(snapshot.submission)])
            if 'filing_approval_snapshots' in sql:return Cursor([row(snapshot.approval)])
            if 'filing_previews' in sql:
                value=row(snapshot.preview);value['issues']=[asdict(i) for i in snapshot.preview.issues]
                return Cursor([value])
            if 'production_feedback_artifacts' in sql:return Cursor([row(a) for a in snapshot.artifacts])
            if 'production_filing_events' in sql:return Cursor([row(e) for e in snapshot.reconciliation_events])
            if 'source_approval_bindings' in sql:
                assert args==(snapshot.approval.id,str(snapshot.company_id),int(snapshot.income_year))
                return Cursor([] if missing=='binding' else [binding])
            if 'year_source_versions' in sql:
                assert args==(line.source_id,str(snapshot.company_id),int(snapshot.income_year))
                return Cursor([] if missing=='source' else [{'retained':True}])
            if 'source_review_bridges' in sql:return Cursor([] if missing=='bridge' else [row(line.bridge)])
            if 'read_source_submission_claim' in sql:
                assert args==(snapshot.approval.id,snapshot.approval.manifest_hash,str(ACTOR.subject))
                return Cursor([] if missing=='claim' else [claim_row])
            raise AssertionError(sql)
    connection=Connection()
    @asynccontextmanager
    async def transaction(*,snapshot):
        assert snapshot is True and not locked
        yield connection
    store._transaction=transaction
    store._year_source=lambda row:line.source if row else None
    async def source_preview(conn,preview_id):
        assert conn is connection and preview_id==line.source_preview.preview_id
        return line.source_preview
    store._read_source_preview=source_preview
    query=rf.Rf1086SourceQuery(snapshot.company_id,snapshot.income_year,ACTOR)
    async def run():
        if not locked:return await store.read_correction_predecessor(query,claim.submission_id)
        scope=_SourceAdmission(store,connection,query,None)
        result=await scope.read_correction_predecessor(query,claim.submission_id)
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.read_correction_predecessor(query,claim.submission_id)
        return result
    if missing:
        with pytest.raises((rf.Rf1086ProductionError,rf.ShareholderRegisterFilingError)):asyncio.run(run())
    else:
        actual=asyncio.run(run());assert actual==snapshot;assert_valid(actual)
        assert ('lock_correction_predecessor' in calls[0][0]) is locked


def test_predecessor_can_itself_be_a_correction_when_claim_and_manifest_bind_same_parent():
    snapshot=full_year_predecessor();line=snapshot.source_approval_lineage;approval=snapshot.approval
    parent=rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(str(UUID(int=888))),'e'*64,'Earlier correction')
    manifest=rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        line.source,line.source_preview,ACTOR,approval.entitlement_id,line.review_sha256,
        tuple(approval.manifest['review']['acknowledgedWarningCodes']),parent))
    snapshot=replace(snapshot,
        approval=replace(approval,manifest=manifest.manifest,manifest_hash=manifest.manifest_sha256),
        submission=replace(snapshot.submission,supersedes_submission_id=parent.submission_id.value),
        source_approval_lineage=replace(line,manifest_text=rf.serialize_rf1086_source_approval_manifest(manifest),
            manifest_sha256=manifest.manifest_sha256),
        source_claim=replace(snapshot.source_claim,manifest_sha256=manifest.manifest_sha256,
            predecessor_submission_id=parent.submission_id))
    assert_valid(snapshot)
    # Complete-history admission separately proves the ancestor chain. This
    # snapshot must at least bind its retained manifest to the same parent.
    with pytest.raises(rf.Rf1086ProductionError):
        assert_valid(replace(snapshot,submission=replace(snapshot.submission,supersedes_submission_id=None)))
