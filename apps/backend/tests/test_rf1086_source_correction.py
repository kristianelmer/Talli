"""Correction receipts are verified outside locks and rebound inside source admission."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

import pytest

from talli_backend.application.shareholder_register_source_approval import ShareholderRegisterSourceApprovalWorkflow
from talli_backend.modules.documents.public import (DocumentRecord, DocumentId, DocumentStatus,
    VerifiedDocumentEvidence, RetainedDocumentOriginalReceipt, DocumentsError, document_metadata_sha256)
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_source import production_snapshot
from test_rf1086_source_approval import ApprovalHarness
from test_rf1086_year_source import ACTOR, NOW, COMPANY, YEAR


def predecessor_snapshot(status='accepted', count=2):
    from talli_backend.modules.shareholder_register_filing.preparation import _production_preview
    from talli_backend.modules.shareholder_register_filing.production import rf1086_current_manifest, rf1086_current_manifest_hash, rf1086_preview_payload_hash
    old = production_snapshot()
    preview=replace(old.previews[0],company_id=str(COMPANY),income_year=int(YEAR))
    rendered=_production_preview(preview)
    manifest=rf1086_current_manifest(rendered,actor_id=str(ACTOR.subject),organization_number='123456789')
    approval = replace(old.approvals[0],id=str(UUID(int=900)),entitlement_id=str(UUID(int=901)),
        company_id=str(COMPANY),income_year=int(YEAR),user_id=str(ACTOR.subject),approved_by=str(ACTOR.subject),
        manifest=manifest,manifest_hash=rf1086_current_manifest_hash(rendered,actor_id=str(ACTOR.subject),organization_number='123456789'),
        payload_hash=rf1086_preview_payload_hash(rendered))
    submission = replace(old.production_submissions[0],id=str(UUID(int=902)),approval_id=approval.id,
        entitlement_id=approval.entitlement_id,status=status,feedback_state=status,feedback_artifact_count=count,
        company_id=str(COMPANY),income_year=int(YEAR),user_id=str(ACTOR.subject),submitted_by=str(ACTOR.subject),payload_hash=approval.payload_hash)
    artifacts = tuple(replace(old.feedback_artifacts[0],id=str(UUID(int=910+i)),document_id=str(UUID(int=920+i)),
        company_id=str(COMPANY),submission_id=submission.id,classification=status,sha256=sha256(f'receipt-{i}'.encode()).hexdigest(),byte_length=9)
        for i in range(count))
    event = replace(old.production_events[0],id=str(UUID(int=930)),submission_id=submission.id,
        company_id=str(COMPANY),income_year=int(YEAR),resulting_status=status,artifact_hashes=tuple(a.sha256 for a in artifacts))
    return rf.Rf1086CorrectionPredecessorSnapshot(COMPANY,YEAR,submission,approval,preview,artifacts,(event,))


def predecessor(snapshot):
    return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(snapshot.submission.id),snapshot.approval.manifest_hash,'Reviewed correction')


def assert_valid(snapshot, prior=None):
    rf.assert_rf1086_correction_predecessor(snapshot,company_id=snapshot.company_id,
        income_year=snapshot.income_year,predecessor=prior or predecessor(snapshot))


class CorrectionHarness(ApprovalHarness):
    def __init__(self,status='accepted'):
        super().__init__()
        self.prior_snapshot=predecessor_snapshot(status)
        self.locked_snapshot=self.prior_snapshot
        self.prior=predecessor(self.prior_snapshot)
        self.prior_documents={}
        self.prior_failure=None
        self.original_failure=False
        self.document_actor=ACTOR
        for i,artifact in enumerate(self.prior_snapshot.artifacts):
            document=DocumentRecord(DocumentId(artifact.document_id),self.prior_snapshot.company_id,
                self.prior_snapshot.income_year,'authority_feedback','feedback.xml',
                'production_filing_submission:'+self.prior_snapshot.submission.id,DocumentStatus.STORED,
                10,'private/'+artifact.document_id,'application/xml',artifact.byte_length,artifact.sha256,
                ACTOR,NOW,None,None)
            receipt=RetainedDocumentOriginalReceipt(str(UUID(int=940+i)),document.document_id,document.company_id,
                document.income_year,document_metadata_sha256(document),artifact.sha256,artifact.byte_length,NOW)
            self.prior_documents[artifact.document_id]=VerifiedDocumentEvidence(document,artifact.sha256,
                artifact.byte_length,DocumentStatus.STORED,receipt)
        old_sessions=self.workflow._sessions;old_documents=self.workflow._documents;owner=self
        class Sessions:
            async def session(self,token):
                session=await old_sessions.session(token)
                async def read(query,submission_id):
                    assert not owner.held and query.actor_id==session.actor_id and submission_id==owner.prior.submission_id
                    owner.calls.append('prior_read');return owner.prior_snapshot
                session.read_correction_predecessor=read
                return session
        class Documents:
            async def session(self,token):
                original=await old_documents.session(token)
                class Session:
                    @property
                    def actor_id(self): return owner.document_actor
                    async def verify_document_evidence(self,document_id):
                        if document_id.value not in owner.prior_documents:
                            return await original.verify_document_evidence(document_id)
                        assert not owner.held
                        owner.calls.append('prior_bytes:'+document_id.value)
                        if owner.prior_failure: raise owner.prior_failure
                        return owner.prior_documents[document_id.value]
                return Session()
        old_assert=self.transaction.assert_original
        async def assert_original(receipt):
            if receipt.document_id.value in owner.prior_documents:
                assert owner.held
                owner.calls.append('prior_original')
                if owner.original_failure: raise DocumentsError.integrity_failed()
            else: await old_assert(receipt)
        async def locked(query,submission_id):
            assert owner.held and query.actor_id==owner.transaction.actor_id and submission_id==owner.prior.submission_id
            owner.calls.append('prior_lock');return owner.locked_snapshot
        self.transaction.assert_original=assert_original
        self.transaction.read_correction_predecessor=locked
        self.approval=ShareholderRegisterSourceApprovalWorkflow(Sessions(),Documents())


@pytest.mark.parametrize('status',['accepted','rejected'])
def test_exact_predecessor_receipts_and_replay_preserve_approval_identity(status):
    h=CorrectionHarness(status)
    assert h.approve(predecessor=h.prior)==h.result
    assert h.calls.index('prior_read') < h.calls.index('guard') < h.calls.index('prior_lock') < h.calls.index('review') < h.calls.index('append')
    byte_calls=[v for v in h.calls if v.startswith('prior_bytes:')]
    assert byte_calls==['prior_bytes:'+value for value in sorted(h.prior_documents)]
    assert all(h.calls.index(value) < h.calls.index('guard') for value in byte_calls)
    assert h.calls.count('prior_original')==2
    assert h.approve(predecessor=h.prior)==h.result
    assert h.writes[0]==h.writes[1]
    assert dict(h.writes[0].manifest['predecessor'])=={'submissionId':h.prior.submission_id.value,
        'manifestSha256':h.prior.manifest_sha256,'reason':h.prior.reason}


@pytest.mark.parametrize('change', ['no_artifacts','count','status','feedback','company','year','manifest','actor',
    'payload','duplicate_artifact','duplicate_document','duplicate_hash','classification','no_journal','journal_hash','journal_state','journal_company','unknown_profile'])
def test_rf_policy_rejects_incomplete_or_mismatched_terminal_evidence(change):
    snap=predecessor_snapshot();sub=snap.submission;approval=snap.approval;artifacts=snap.artifacts;events=snap.reconciliation_events
    if change=='no_artifacts':snap=replace(snap,artifacts=())
    if change=='count':snap=replace(snap,submission=replace(sub,feedback_artifact_count=True))
    if change=='status':snap=replace(snap,submission=replace(sub,status='processing'))
    if change=='feedback':snap=replace(snap,submission=replace(sub,feedback_state='unknown'))
    if change=='company':snap=replace(snap,submission=replace(sub,company_id=str(UUID(int=999))))
    if change=='year':snap=replace(snap,approval=replace(approval,income_year=2024))
    if change=='manifest':snap=replace(snap,approval=replace(approval,manifest={**approval.manifest,'unknown':True}))
    if change=='actor':snap=replace(snap,approval=replace(approval,approved_by=str(UUID(int=999))))
    if change=='payload':snap=replace(snap,submission=replace(sub,payload_hash='b'*64))
    if change=='duplicate_artifact':snap=replace(snap,artifacts=(artifacts[0],artifacts[0]))
    if change=='duplicate_document':snap=replace(snap,artifacts=(artifacts[0],replace(artifacts[1],document_id=artifacts[0].document_id)))
    if change=='duplicate_hash':snap=replace(snap,artifacts=(artifacts[0],replace(artifacts[1],sha256=artifacts[0].sha256)))
    if change=='classification':snap=replace(snap,artifacts=(replace(artifacts[0],classification='rejected'),artifacts[1]))
    if change=='no_journal':snap=replace(snap,reconciliation_events=())
    if change=='journal_hash':snap=replace(snap,reconciliation_events=(replace(events[0],artifact_hashes=('b'*64,)),))
    if change=='journal_state':snap=replace(snap,reconciliation_events=(replace(events[0],operation_state='unknown'),))
    if change=='journal_company':snap=replace(snap,reconciliation_events=(replace(events[0],company_id=str(UUID(int=999))),))
    if change=='unknown_profile':snap=replace(snap,approval=replace(approval,case_profile='rf1086_full_year_v1'))
    with pytest.raises(rf.Rf1086ProductionError):assert_valid(snap)


@pytest.mark.parametrize('change',['id','company','year','hash','length','content_type','type','link','removed','status','integrity','no_original','original_metadata','original_hash','original_id'])
def test_document_metadata_original_and_verified_bytes_must_match_parent_artifact(change):
    h=CorrectionHarness();key=sorted(h.prior_documents)[0];e=h.prior_documents[key];d=e.document;r=e.retained_original
    if change=='id':e=replace(e,document=replace(d,document_id=DocumentId(str(UUID(int=999)))))
    if change=='company':e=replace(e,document=replace(d,company_id=rf.CompanyId(str(UUID(int=999)))))
    if change=='year':e=replace(e,document=replace(d,income_year=rf.IncomeYear(2024)))
    if change=='hash':e=replace(e,content_sha256='b'*64)
    if change=='length':e=replace(e,byte_length=8)
    if change=='content_type':e=replace(e,document=replace(d,content_type='application/pdf'))
    if change=='type':e=replace(e,document=replace(d,document_type='invoice'))
    if change=='link':e=replace(e,document=replace(d,linked_to='production_filing_submission:'+str(UUID(int=999))))
    if change=='removed':e=replace(e,document=replace(d,removed_at=NOW))
    if change=='status':e=replace(e,document=replace(d,status=DocumentStatus.MISSING_ACCEPTED))
    if change=='integrity':e=replace(e,integrity_status=DocumentStatus.MISSING_ACCEPTED)
    if change=='no_original':e=replace(e,retained_original=None)
    if change=='original_metadata':e=replace(e,retained_original=replace(r,metadata_sha256='b'*64))
    if change=='original_hash':e=replace(e,retained_original=replace(r,content_sha256='b'*64))
    if change=='original_id':e=replace(e,retained_original=replace(r,document_id=DocumentId(str(UUID(int=999)))))
    h.prior_documents[key]=e
    with pytest.raises(rf.Rf1086ProductionError):h.approve(predecessor=h.prior)
    assert not h.held and 'guard' not in h.calls and not h.writes


@pytest.mark.parametrize('change',['bytes','document_actor','admission_actor','parent_race','artifact_race','receipt_race'])
def test_failed_preflight_or_locked_recheck_never_appends(change):
    h=CorrectionHarness()
    if change=='bytes':h.prior_failure=DocumentsError.integrity_failed()
    if change=='document_actor':h.document_actor=replace(ACTOR,subject=type(ACTOR.subject)(str(UUID(int=999))))
    if change=='admission_actor':h.on_guard=lambda:setattr(h.transaction,'actor_id',replace(ACTOR,subject=type(ACTOR.subject)(str(UUID(int=999)))))
    if change=='parent_race':h.on_guard=lambda:setattr(h,'locked_snapshot',replace(h.prior_snapshot,submission=replace(h.prior_snapshot.submission,updated_at='2026-01-02T00:00:00Z')))
    if change=='artifact_race':h.on_guard=lambda:setattr(h,'locked_snapshot',replace(h.prior_snapshot,artifacts=tuple(reversed(h.prior_snapshot.artifacts))))
    if change=='receipt_race':h.original_failure=True
    with pytest.raises((rf.Rf1086ProductionError,rf.Rf1086YearSourceError,DocumentsError)):h.approve(predecessor=h.prior)
    assert not h.held and not h.committed and not h.writes


@pytest.mark.parametrize('change',['submission_id','manifest_hash','reason','session_actor'])
def test_caller_cannot_substitute_opaque_predecessor_identity(change):
    h=CorrectionHarness();prior=h.prior
    if change=='submission_id':prior=replace(prior,submission_id='bad')
    if change=='manifest_hash':prior=replace(prior,manifest_sha256='b'*64)
    if change=='reason':prior=replace(prior,reason=' ')
    if change=='session_actor':h.actor=replace(ACTOR,subject=type(ACTOR.subject)(str(UUID(int=999))))
    with pytest.raises(rf.Rf1086ProductionError):h.approve(predecessor=prior)
    assert not any(call.startswith('prior_bytes:') for call in h.calls)
    assert 'guard' not in h.calls and not h.writes


@pytest.mark.parametrize('lock',[False,True])
def test_adapter_preserves_exact_predecessor_snapshot_and_uses_guarded_owner_lock(lock):
    from contextlib import asynccontextmanager
    from dataclasses import fields, asdict
    from types import SimpleNamespace
    from psycopg.pq import TransactionStatus
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
    from test_postgres_shareholder_register_filing import session
    store=session({});snapshot=predecessor_snapshot();calls=[];opened=[]
    query=rf.Rf1086SourceQuery(snapshot.company_id,snapshot.income_year,store.actor_id)
    submission_id=rf.SubmissionId(snapshot.submission.id)
    def record(row):return {field.name:getattr(row,field.name) for field in fields(row)}
    class Cursor:
        def __init__(self,rows):self.rows=rows
        async def fetchone(self):return self.rows[0] if self.rows else None
        async def fetchall(self):return self.rows
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args):
            calls.append((sql,args))
            assert 'set local role' not in sql and 'company_access_read_rf_admission' not in sql
            if 'assert_member' in sql:return Cursor([])
            if 'lock_correction_predecessor' in sql:
                assert lock and args==(submission_id.value,str(query.company_id),int(query.income_year),str(store.actor_id.subject))
                return Cursor([record(snapshot.submission)])
            if 'production_filing_submissions' in sql:
                assert not lock and args==(submission_id.value,str(query.company_id),int(query.income_year))
                assert 'for update' not in sql
                return Cursor([record(snapshot.submission)])
            if 'filing_approval_snapshots' in sql:return Cursor([record(snapshot.approval)])
            if 'filing_previews' in sql:
                row=record(snapshot.preview);row['issues']=[asdict(issue) for issue in snapshot.preview.issues]
                return Cursor([row])
            if 'production_feedback_artifacts' in sql:
                assert sql.endswith('order by document_id,id');return Cursor([record(row) for row in snapshot.artifacts])
            if 'production_filing_events' in sql:
                assert "operation_state='succeeded'" in sql;return Cursor([record(row) for row in snapshot.reconciliation_events])
            raise AssertionError(sql)
    connection=Connection()
    @asynccontextmanager
    async def transaction(*,snapshot):
        assert snapshot is True;opened.append(connection);yield connection
    store._transaction=transaction
    async def run():
        if not lock:return await store.read_correction_predecessor(query,submission_id)
        scope=_SourceAdmission(store,connection,query,None)
        result=await scope.read_correction_predecessor(query,submission_id)
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.read_correction_predecessor(replace(query,income_year=rf.IncomeYear(2024)),submission_id)
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.read_correction_predecessor(query,submission_id)
        return result
    assert asyncio.run(run())==snapshot
    if lock:
        assert not opened and 'lock_correction_predecessor_v1' in calls[0][0]
        assert len(calls)==5
    else:assert len(opened)==1 and 'assert_member' in calls[0][0]
