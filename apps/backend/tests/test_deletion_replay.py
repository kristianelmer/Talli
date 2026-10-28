"""Finite synthetic vertical slice; fixture adapter physically deletes local rows/files.

This adapter is deliberately NOT registered as production Supabase purge authority.
The current product has no such adapter; unsupported owner stores remain closed.
"""
import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from talli_backend.adapters.deletion_journal import (
    GENESIS, JournalHead, LocalDeletionJournal, LocalReplayReceipt, replay_is_current,
)
from talli_backend.application.company_disposition import execute_authorized_disposition, replay_company_dispositions
from talli_backend.modules.billing.public import disposition_access_period
from talli_backend.modules.billing.public import AnnualPurchasePage, AnnualPurchaseSummary, AnnualPurchaseId, AnnualPurchaseStatus, AnnualOperationCounts
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp
from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    CompanyDispositionPlan, DispositionAuthorizationFacts, DispositionExport,
    DispositionRecord, DispositionSession, authorize_company_disposition,
)
from talli_backend.modules.documents.public import DocumentErrorCode, DocumentsError, DocumentTransferKind
from talli_backend.modules.documents.service import DocumentsService

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
PDF = b'%PDF-1.7\nSynthetic unlinked object; never a real customer document.\n'


def synthetic_billing_purchases(company,years):
    purchases = tuple(AnnualPurchaseSummary(
        purchase_id=AnnualPurchaseId(str(uuid4())), company_id=CompanyId(str(company)), income_year=IncomeYear(y),
        status=AnnualPurchaseStatus.PAID, accepted_at=Timestamp(NOW-timedelta(days=400)),
        offer_version='synthetic-recorded-terms-v1', terms_digest='e'*64, terms_text='Synthetic recorded terms',
        currency='NOK', gross_minor=100, net_minor=100, vat_minor=0, vat_basis_points=0,
        captured_minor=100, refunded_minor=0, captured_at=Timestamp(NOW-timedelta(days=400)),
        recurring_consent=False, renewal_canceled_at=None, paid_through=(NOW-timedelta(days=101)).date(),
        export_through=(NOW-timedelta(days=11)).date(), renewal_date=(NOW-timedelta(days=100)).date(),
        recorded_refund_minor=0, refund_initiate_by=None, refund_request_count=0,
        latest_refund_requested_at=None, refund_operations=AnnualOperationCounts(0,0,0,0,0)) for y in years)
    return AnnualPurchasePage(purchases)


def document_body(record_id):
    return PDF + ('document:' + str(record_id)).encode()


def synthetic_archive_sha(plan,year):
    records=[r for r in plan.records if r.income_year==year]
    raw=json.dumps({'year':year,'records':[r.model_dump(mode='json') for r in records],
                    'originals':[document_body(r.record_id).hex() for r in records]},sort_keys=True).encode()
    return sha256(raw).hexdigest()


def authorization_fixture():
    company, owner, reviewer = uuid4(), uuid4(), uuid4()
    def record(year,action):
        record_id=uuid4()
        return DispositionRecord(owner='documents',record_id=record_id,income_year=year,
            generation='object-generation-2',content_sha256=sha256(document_body(record_id)).hexdigest(),action=action,
            retention_until=NOW+timedelta(days=30) if action=='retain' else NOW-timedelta(days=1),
            hold_basis='synthetic bounded investigation case' if action=='retain' else None,
            hold_until=NOW+timedelta(days=15) if action=='retain' else None)
    records=(record(2025,'erase'),record(2026,'retain'))
    plan = CompanyDispositionPlan(operation_id=uuid4(), company_id=company, choice='delete',
        years=(2025, 2026), generation='company-generation-17', records=records,
        inventory_sha256='0'*64, support_case_id=uuid4())
    plan = plan.model_copy(update={'inventory_sha256': plan.inventory_digest()})
    def session(subject, role):
        return DispositionSession(subject=subject, session_id=uuid4(), role=role, company_id=company,
                                  mfa_at=NOW-timedelta(seconds=20))
    purchases = synthetic_billing_purchases(company,plan.years)
    period=disposition_access_period(purchases,company_id=company,all_company_years=plan.years)
    facts = DispositionAuthorizationFacts(company_id=company, all_company_years=plan.years,
        current_generation=plan.generation, current_inventory_sha256=plan.inventory_sha256,
        paid_access_expires_at=period.paid_expires_at, read_export_until=period.read_export_until,
        exports=tuple(DispositionExport(income_year=y, receipt_id=uuid4(), archive_sha256=synthetic_archive_sha(plan,y), inventory_sha256=plan.inventory_sha256,
                                       complete=True) for y in plan.years),
        owner=session(owner, 'owner'), reviewer=session(reviewer, 'reviewer'), support_case_id=plan.support_case_id,
        review_plan_sha256=sha256(plan.model_dump_json().encode()).hexdigest(), inventory_complete=True)
    return plan, facts


@pytest.mark.parametrize('case', ['choice', 'paid_period', 'short_export_period', 'missing_billing', 'active_hold',
    'incomplete_export', 'generation', 'years', 'outsider', 'self_review', 'revoked', 'old_mfa',
    'future_mfa', 'case', 'changed_review', 'unattributed', 'inventory_digest', 'blank_hold'])
def test_every_authorization_negative_before_destructive_execution(case):
    plan, facts = authorization_fixture()
    if case == 'choice': plan = plan.model_copy(update={'choice': None})
    elif case == 'paid_period': facts = facts.model_copy(update={'read_export_until': NOW+timedelta(days=1)})
    elif case == 'short_export_period': facts = facts.model_copy(update={'read_export_until': facts.paid_access_expires_at+timedelta(days=89)})
    elif case == 'missing_billing': facts = facts.model_copy(update={'paid_access_expires_at': None})
    elif case in ('active_hold','blank_hold'):
        changed = plan.records[0].model_copy(update={'hold_basis': 'bounded hold' if case=='active_hold' else '   ', 'hold_until': NOW+timedelta(days=1) if case=='active_hold' else NOW-timedelta(days=1)})
        plan = plan.model_copy(update={'records': (changed, plan.records[1])})
        plan = plan.model_copy(update={'inventory_sha256': plan.inventory_digest()})
        facts = facts.model_copy(update={'current_inventory_sha256': plan.inventory_sha256,
            'exports': tuple(e.model_copy(update={'inventory_sha256': plan.inventory_sha256}) for e in facts.exports),
            'review_plan_sha256': sha256(plan.model_dump_json().encode()).hexdigest()})
    elif case == 'incomplete_export': facts = facts.model_copy(update={'exports': (facts.exports[0],)})
    elif case == 'generation': facts = facts.model_copy(update={'current_generation': 'changed'})
    elif case == 'years': facts = facts.model_copy(update={'all_company_years': (2025, 2026, 2027)})
    elif case == 'outsider': facts = facts.model_copy(update={'owner': facts.owner.model_copy(update={'company_id': uuid4()})})
    elif case == 'self_review': facts = facts.model_copy(update={'reviewer': facts.reviewer.model_copy(update={'subject': facts.owner.subject})})
    elif case in ('revoked', 'old_mfa', 'future_mfa'):
        delta = {'revoked': {'revoked': True}, 'old_mfa': {'mfa_at': NOW-timedelta(minutes=6)},
                 'future_mfa': {'mfa_at': NOW+timedelta(seconds=1)}}[case]
        facts = facts.model_copy(update={'owner': facts.owner.model_copy(update=delta)})
    elif case == 'case': facts = facts.model_copy(update={'support_case_id': uuid4()})
    elif case == 'changed_review': facts = facts.model_copy(update={'review_plan_sha256': 'f'*64})
    elif case == 'unattributed': facts = facts.model_copy(update={'inventory_complete': False})
    elif case == 'inventory_digest': facts = facts.model_copy(update={'current_inventory_sha256': 'f'*64})
    with pytest.raises(ValueError): authorize_company_disposition(plan, facts, now=NOW)


class SyntheticDocumentStore:
    """Real SQLite row + ordinary object-version files under one disposable root.

    Synchronous transactions are short; no concurrent writer exists in this
    quarantined fixture. No immutability trigger, production RLS or service key is
    bypassed. Filesystem unlink/SQL DELETE are not forensic secure media erasure.
    """
    aal2 = True
    clock = NOW
    def __init__(self, root, *, plan=None):
        self.root = root; self.erase_calls = 0; self.drop_response = False; self.fail_after_objects = False; self.drop_prepare_record = None
        if plan:
            root.mkdir()
            with self.db() as db:
                db.executescript('create table documents(id text primary key,company text,year integer,generation text,sha text,retained integer,actor text,retention_until text,hold_until text); create table company_state(company text primary key,generation text,fence text); create table receipts(operation text,document text,plan text,company text,year integer,generation text,sha text,status text,primary key(operation,document));')
                db.execute('insert into company_state values(?,?,null)',(str(plan.company_id),plan.generation))
                for record in plan.records:
                    db.execute('insert into documents values(?,?,?,?,?,?,?,?,?)', (str(record.record_id),str(plan.company_id),record.income_year,record.generation,record.content_sha256,int(record.action=='retain'),'original-author-identity',record.retention_until.isoformat(),record.hold_until.isoformat() if record.hold_until else None))
                    directory=root/str(record.record_id);directory.mkdir()
                    for generation in ('1','2'): (directory/generation).write_bytes(document_body(record.record_id))
    def db(self): return sqlite3.connect(self.root/'documents.sqlite')
    def row(self, document):
        with self.db() as db: return db.execute('select * from documents where id=?',(str(document),)).fetchone()
    def receipt(self, c):
        with self.db() as db:
            r=db.execute('select plan,company,year,generation,sha,status from receipts where operation=? and document=?',(str(c.operation_id),str(c.document_id))).fetchone()
        if r and r[:5] != (c.plan_sha256,str(c.company_id),c.income_year,c.generation,c.content_sha256):
            raise ValueError('owner_receipt_conflict')
        return r
    def objects(self, document):
        p=self.root/str(document)
        return sorted(p.iterdir()) if p.exists() else []
    async def fence_inventory(self, commands):
        assert commands and len({c.company_id for c in commands})==1
        if len({c.company_generation for c in commands})!=1: raise ValueError('owner_company_generation_changed')
        first=commands[0]
        with self.db() as db:
            db.execute('begin immediate')
            state=db.execute('select generation,fence from company_state where company=?',(str(first.company_id),)).fetchone()
            if not state or state[0]!=first.company_generation or (state[1] not in (None,first.plan_sha256) and db.execute("select count(*) from receipts where status!='erased'").fetchone()[0]):
                raise ValueError('owner_company_generation_changed')
            current={r[0] for r in db.execute('select id from documents where company=?',(str(first.company_id),))}
            erased={r[0] for r in db.execute('select document from receipts where company=? and status=?',(str(first.company_id),'erased'))} & {str(c.document_id) for c in commands}
            if current|erased!={str(c.document_id) for c in commands}:
                raise ValueError('owner_inventory_incomplete')
            db.execute('update company_state set fence=? where company=?',(first.plan_sha256,str(first.company_id)))
    async def fence_replay_history(self,commands):
        # This fixture has no concurrent writer. A production owner must keep
        # this complete-cut fence durable against its ordinary writer paths.
        assert commands and len({c.company_id for c in commands})==1
        first=commands[0];expected={str(c.document_id) for c in commands}
        approved={(str(c.operation_id),str(c.document_id),c.plan_sha256,str(c.company_id),
                   c.income_year,c.generation,c.content_sha256) for c in commands}
        with self.db() as db:
            db.execute('begin immediate')
            state=db.execute('select generation from company_state where company=?',(str(first.company_id),)).fetchone()
            if not state or state[0] not in {c.company_generation for c in commands}:
                raise ValueError('owner_company_generation_changed')
            rows=db.execute('select * from documents where company=?',(str(first.company_id),)).fetchall()
            if any(row[0] not in expected or not any(str(c.document_id)==row[0] and
                    row[1:5]==(str(c.company_id),c.income_year,c.generation,c.content_sha256) for c in commands) for row in rows):
                raise ValueError('owner_inventory_incomplete')
            receipts=db.execute('select * from receipts where company=?',(str(first.company_id),)).fetchall()
            if any(r[:7] not in approved for r in receipts if r[-1]!='erased'):
                raise ValueError('owner_unrelated_pending_command')
            missing=expected-{r[0] for r in rows}
            for record in missing:
                if self.objects(record) or not any(r[:7] in approved and r[1]==record and r[-1]=='erased' for r in receipts):
                    raise ValueError('owner_inventory_incomplete')
            cut=sha256('\n'.join(repr(c) for c in commands).encode()).hexdigest()
            db.execute('update company_state set fence=? where company=?',(cut,str(first.company_id)))
    async def retained_matches(self,c):
        row=self.row(c.document_id)
        return bool(row and row[1:5]==(str(c.company_id),c.income_year,c.generation,c.content_sha256)
            and row[5]==1 and len(self.objects(c.document_id))==2
            and all(sha256(p.read_bytes()).hexdigest()==c.content_sha256 for p in self.objects(c.document_id)))
    def erasable(self,row):
        return datetime.fromisoformat(row[7])<=self.clock and (row[8] is None or datetime.fromisoformat(row[8])<=self.clock)
    async def reconcile(self,c):
        r=self.receipt(c);row=self.row(c.document_id);objects=self.objects(c.document_id)
        if r and r[-1]=='erased' and row is None and not objects: return 'ERASED'
        if r and r[-1]=='fenced' and row and row[1:5]==(str(c.company_id),c.income_year,c.generation,c.content_sha256) and self.erasable(row) and len(objects)==2 and all(sha256(p.read_bytes()).hexdigest()==c.content_sha256 for p in objects): return 'READY'
        if r: return 'UNKNOWN'
        if row and row[1:5]==(str(c.company_id),c.income_year,c.generation,c.content_sha256) and self.erasable(row) and len(objects)==2 and all(sha256(p.read_bytes()).hexdigest()==c.content_sha256 for p in objects): return 'NOT_APPLIED'
        return 'UNKNOWN'
    async def prepare(self,c):
        if await self.reconcile(c)!='NOT_APPLIED': raise ValueError('owner_inventory_changed')
        with self.db() as db:
            db.execute('insert into receipts values(?,?,?,?,?,?,?,?)',(str(c.operation_id),str(c.document_id),c.plan_sha256,str(c.company_id),c.income_year,c.generation,c.content_sha256,'fenced'))
        if self.drop_prepare_record==c.document_id:
            self.drop_prepare_record=None;raise ConnectionError('synthetic response lost after durable prepare')
    async def erase(self,c):
        assert self.receipt(c)[-1]=='fenced'
        self.erase_calls+=1
        for path in self.objects(c.document_id): path.unlink()
        (self.root/str(c.document_id)).rmdir()
        if self.fail_after_objects: raise ConnectionError('synthetic partial owner failure')
        with self.db() as db:
            db.execute('delete from documents where id=?',(str(c.document_id),))
            db.execute('update receipts set status=? where operation=? and document=?',('erased',str(c.operation_id),str(c.document_id)))
        if self.drop_response:
            self.drop_response=False;raise ConnectionError('synthetic response lost after durable commit')
    async def get_document(self, document):
        assert self.row(document) is None
        return None


def run(awaitable): return asyncio.run(awaitable)


def restore_settings(monkeypatch, root, journal, minimum, target, receipt):
    values={'TARGET_ID':target,'JOURNAL_PATH':str(journal.path),'JOURNAL_STREAM':journal.stream,
            'CUSTOMER_ROOT':str(root),'REPLAY_RECEIPT':str(receipt),'MIN_SEQUENCE':str(minimum.sequence),
            'MIN_SHA256':minimum.sha256}
    for name,value in values.items(): monkeypatch.setenv('TALLI_RESTORE_'+name,value)


def test_predeletion_backup_disposition_restore_replay_and_denied_download(tmp_path, monkeypatch):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    source=SyntheticDocumentStore(tmp_path/'source',plan=plan)
    backup=tmp_path/'predeletion-customer-backup';shutil.copytree(source.root,backup)
    retained_before=source.row(plan.records[1].record_id)
    journal=LocalDeletionJournal.initialize(tmp_path/'outside-customer-journal.sqlite',customer_root=source.root)
    source.drop_response=True
    with pytest.raises(ConnectionError):
        run(execute_authorized_disposition(permit,journal=journal,target='source',stores={'documents':source}))
    # Durable tombstone exists although success was never released to the caller.
    head,entries=journal.read();assert len(entries)==1 and source.row(plan.records[0].record_id) is None
    assert not source.objects(plan.records[0].record_id)
    assert run(execute_authorized_disposition(permit,journal=journal,target='source',stores={'documents':source}))==head
    assert source.erase_calls==1
    restored_root=tmp_path/'restored-customer';shutil.copytree(backup,restored_root)
    restored=SyntheticDocumentStore(restored_root);target=str(uuid4());receipt=restored_root/'replay-ready.json'
    restore_settings(monkeypatch,restored_root,journal,head,target,receipt)
    async def healthy(): return True
    app=create_app(readiness_probe=healthy);client=TestClient(app)
    assert client.get('/health/live').status_code==200
    assert client.get('/health/ready').status_code==503
    blocked=client.get('/api/v1/documents/'+str(plan.records[0].record_id))
    assert blocked.status_code==503 and blocked.headers['content-type'].startswith('application/problem+json')
    from talli_backend.main import ProblemDetails
    problem=ProblemDetails.model_validate(blocked.json())
    assert problem.code=='RESTORE_QUARANTINED' and problem.request_id==blocked.headers['x-request-id']

    assert restored.row(plan.records[0].record_id) is not None
    run(replay_company_dispositions(journal=journal,target=target,receipt=LocalReplayReceipt(receipt),minimum=head,stores={'documents':restored}))
    assert client.get('/health/ready').status_code==200
    assert restored.row(plan.records[0].record_id) is None and not restored.objects(plan.records[0].record_id)
    assert restored.row(plan.records[1].record_id)==retained_before
    assert len(restored.objects(plan.records[1].record_id))==2
    # The real owning Documents transfer policy denies the erased record.
    with pytest.raises(DocumentsError) as denied:
        run(DocumentsService(restored,object()).create_transfer(plan.records[0].record_id,DocumentTransferKind.DOWNLOAD))
    assert denied.value.code is DocumentErrorCode.NOT_FOUND
    assert replay_is_current(journal,receipt=receipt,target=target,minimum=head)
    saved_receipt=receipt.read_bytes();corrupt=json.loads(saved_receipt);corrupt['sequence']=True
    receipt.write_text(json.dumps(corrupt));assert not replay_is_current(journal,receipt=receipt,target=target,minimum=head)
    receipt.write_bytes(saved_receipt)
    assert not replay_is_current(journal,receipt=receipt,target=str(uuid4()),minimum=head)
    assert not replay_is_current(journal,receipt=receipt,target=target,minimum=JournalHead(journal.stream,2,'f'*64))
    next_plan,next_facts=authorization_fixture()
    journal.append(authorize_company_disposition(next_plan,next_facts,now=NOW))
    assert client.get('/health/ready').status_code==503  # no positive cached bypass after a newer tombstone
    receipt.unlink();assert client.get('/health/ready').status_code==503
    assert source.row(plan.records[1].record_id)==retained_before
    (tmp_path/'exercise-result.json').write_text(json.dumps({'status':'PASS','companyId':str(plan.company_id),
        'externalJournalHead':asdict(head),'deletedRows':1,'unlinkedObjectVersionFiles':2,'retainedRows':1,
        'retainedObjectVersionFiles':2,'unknownSuccessReconciledWithoutDuplicateErase':True,
        'restoredReadyBeforeReplay':False,'erasedOwningDownload':'NOT_FOUND','productionSupabaseAdapter':False,
        'physicalScope':'SQLite DELETE and filesystem unlink, not forensic media erasure or encrypted-backup expiry'},indent=2))


@pytest.mark.parametrize('failure',['missing_journal','tampered','rollback','missing_owner','unknown_outcome','retained_changed','stale_owner_generation','unattributed_store_record'])
def test_incomplete_or_unavailable_replay_never_opens_target(tmp_path,monkeypatch,failure):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    store=SyntheticDocumentStore(tmp_path/'customer',plan=plan)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=store.root)
    head=journal.append(permit);target=str(uuid4());receipt=store.root/'ready.json'
    restore_settings(monkeypatch,store.root,journal,head,target,receipt)
    stores={'documents':store}
    if failure=='missing_journal': journal.path.unlink()
    elif failure=='tampered':
        with sqlite3.connect(journal.path) as db: db.execute("update tombstones set digest=?",('f'*64,))
    elif failure=='rollback':
        with sqlite3.connect(journal.path) as db: db.execute('delete from tombstones')
    elif failure=='missing_owner': stores={}
    elif failure=='unknown_outcome': store.fail_after_objects=True
    elif failure=='retained_changed': store.objects(plan.records[1].record_id)[0].write_bytes(b'changed')
    elif failure=='stale_owner_generation':
        with store.db() as db: db.execute('update company_state set generation=?',('changed',))
    elif failure=='unattributed_store_record':
        with store.db() as db:
            db.execute('insert into documents values(?,?,?,?,?,?,?,?,?)',(str(uuid4()),str(plan.company_id),2026,'unknown','f'*64,0,'unknown-original',(NOW-timedelta(days=1)).isoformat(),None))

    with pytest.raises(Exception):
        run(replay_company_dispositions(journal=journal,target=target,receipt=LocalReplayReceipt(receipt),minimum=head,stores=stores))
    async def healthy(): return True
    client=TestClient(create_app(readiness_probe=healthy))
    assert client.get('/health/ready').status_code==503
    assert client.get('/api/v1/company-access/context').status_code==503
    assert not receipt.exists()
    if failure=='unknown_outcome':
        with pytest.raises(ValueError,match='outcome_unknown'):
            run(replay_company_dispositions(journal=journal,target=target,receipt=LocalReplayReceipt(receipt),minimum=head,stores=stores))
        assert store.erase_calls==1


def test_unconfigured_or_partial_restore_state_and_journal_location(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='inside_customer_snapshot'):
        LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=tmp_path)
    monkeypatch.setenv('TALLI_RESTORE_TARGET_ID',str(uuid4()))
    async def healthy(): return True
    client=TestClient(create_app(readiness_probe=healthy))
    assert client.get('/health/ready').status_code==503
    assert client.get('/health/live').status_code==200


def test_exact_operation_conflict_and_unsupported_owner_are_not_success(tmp_path):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    store=SyntheticDocumentStore(tmp_path/'customer',plan=plan)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=store.root)
    head=journal.append(permit)
    changed=permit.model_copy(update={'authorization_sha256':'f'*64})
    with pytest.raises(ValueError,match='idempotency_conflict'):journal.append(changed)
    assert journal.read()[0]==head
    record=plan.records[0].model_copy(update={'owner':'unknown-owner'})
    changed_plan=plan.model_copy(update={'operation_id':uuid4(),'records':(record,plan.records[1])})
    changed_permit=permit.model_copy(update={'plan':changed_plan})
    with pytest.raises(ValueError,match='owner_unavailable'):
        run(execute_authorized_disposition(changed_permit,journal=journal,target='source',stores={'documents':store}))
    assert store.erase_calls==0 and journal.read()[0]==head


def revised_authorization(plan,facts,*,now=NOW):
    plan=plan.model_copy(update={'inventory_sha256':plan.inventory_digest()})
    facts=facts.model_copy(update={'current_generation':plan.generation,'current_inventory_sha256':plan.inventory_sha256,
        'owner':facts.owner.model_copy(update={'mfa_at':now}),
        'reviewer':facts.reviewer.model_copy(update={'mfa_at':now}),
        'review_plan_sha256':sha256(plan.model_dump_json().encode()).hexdigest(),
        'exports':tuple(e.model_copy(update={'inventory_sha256':plan.inventory_sha256,'archive_sha256':synthetic_archive_sha(plan,e.income_year)}) for e in facts.exports)})
    return authorize_company_disposition(plan,facts,now=now)


def test_unknown_second_erase_is_preflighted_before_first_physical_deletion(tmp_path):
    plan,facts=authorization_fixture()
    second=plan.records[1].model_copy(update={'action':'erase','retention_until':NOW-timedelta(days=1),
                                           'hold_basis':None,'hold_until':None})
    permit=revised_authorization(plan.model_copy(update={'records':(plan.records[0],second)}),facts)
    store=SyntheticDocumentStore(tmp_path/'customer',plan=permit.plan)
    store.objects(second.record_id)[0].write_bytes(b'unknown second object outcome')
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=store.root)
    with pytest.raises(ValueError,match='outcome_unknown'):
        run(execute_authorized_disposition(permit,journal=journal,target='source',stores={'documents':store}))
    assert store.erase_calls==0 and all(store.row(r.record_id) is not None for r in permit.plan.records)
    assert len(store.objects(plan.records[0].record_id))==2


@pytest.mark.parametrize('interrupted',[False,True])
def test_later_authorized_erase_supersedes_historical_retain_on_every_retry(tmp_path,interrupted):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    source=SyntheticDocumentStore(tmp_path/'source',plan=plan)
    backup=tmp_path/'pre-first-deletion';shutil.copytree(source.root,backup)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=source.root)
    run(execute_authorized_disposition(permit,journal=journal,target='source',stores={'documents':source}))
    after_hold=NOW+timedelta(days=31);source.clock=after_hold
    former_retain=plan.records[1].model_copy(update={'action':'erase'})
    later=revised_authorization(plan.model_copy(update={'operation_id':uuid4(),'generation':'company-generation-18','records':(former_retain,)}),facts,now=after_hold)
    with source.db() as db:db.execute('update company_state set generation=?',('company-generation-18',))
    head=run(execute_authorized_disposition(later,journal=journal,target='source',stores={'documents':source}))
    assert source.row(former_retain.record_id) is None
    root=tmp_path/'restored';shutil.copytree(backup,root);store=SyntheticDocumentStore(root);store.clock=after_hold
    target=str(uuid4());receipt=LocalReplayReceipt(root/'ready.json')
    if interrupted:
        store.drop_prepare_record=former_retain.record_id
        with pytest.raises(ConnectionError,match='durable prepare'):
            run(replay_company_dispositions(journal=journal,target=target,receipt=receipt,minimum=head,stores={'documents':store}))
        assert not receipt.path.exists() and store.erase_calls==1
        with store.db() as db:
            assert db.execute('select status from receipts where document=?',(str(former_retain.record_id),)).fetchone()==('fenced',)
        assert store.row(former_retain.record_id) is not None and len(store.objects(former_retain.record_id))==2
    for _ in range(3):
        run(replay_company_dispositions(journal=journal,target=target,receipt=receipt,minimum=head,stores={'documents':store}))
        assert replay_is_current(journal,receipt=receipt.path,target=target,minimum=head)
        assert all(store.row(r.record_id) is None and not store.objects(r.record_id) for r in plan.records)
    assert store.erase_calls==2  # one per record across all three complete replays


@pytest.mark.parametrize('case',['pagination','missing_year','outsider','pending','created_refund','unknown_refund','uncancelled_renewal','uncaptured'])
def test_disposition_uses_complete_recorded_billing_history(case):
    company=uuid4();page=synthetic_billing_purchases(company,(2025,2026));first=page.purchases[0]
    if case=='pagination':page=replace(page,next_purchase_id=AnnualPurchaseId(str(uuid4())))
    elif case=='missing_year':page=replace(page,purchases=(first,))
    else:
        if case=='outsider':first=replace(first,company_id=CompanyId(str(uuid4())))
        elif case=='pending':first=replace(first,status=AnnualPurchaseStatus.PENDING)
        elif case=='created_refund':first=replace(first,refund_operations=replace(first.refund_operations,created=1))
        elif case=='unknown_refund':first=replace(first,refund_operations=replace(first.refund_operations,unknown=1))
        elif case=='uncancelled_renewal':first=replace(first,recurring_consent=True,renewal_canceled_at=None)
        elif case=='uncaptured':first=replace(first,captured_at=None)
        page=replace(page,purchases=(first,page.purchases[1]))
    with pytest.raises(ValueError,match='billing_history_incomplete'):
        disposition_access_period(page,company_id=company,all_company_years=(2025,2026))


def test_journal_refuses_constructed_permit_with_invalid_authorization(tmp_path):
    plan,facts=authorization_fixture();permit=authorize_company_disposition(plan,facts,now=NOW)
    journal=LocalDeletionJournal.initialize(tmp_path/'journal.sqlite',customer_root=tmp_path/'customer')
    invalid=permit.model_copy(update={'plan':plan.model_copy(update={'choice':None})})
    with pytest.raises(ValueError,match='customer_choice_required'):journal.append(invalid)
    assert journal.read()[0].sequence==0
