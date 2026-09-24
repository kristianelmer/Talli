"""Immutable RF source capture through a real restricted local database role."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, CompanyId, IncomeYear, IdempotencyKey
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source import basis

pytestmark=pytest.mark.authority_database
DATABASE_URL=os.environ.get('DATABASE_URL','')
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20260923091509_rf1086_immutable_year_source.sql'


@pytest.fixture(autouse=True)
def remove_only_owned_source_fixture(admitted, rf_fixture_admin_access, backend_url):
    """Disposable fixture teardown; production API has no removal operation.

    All temporary owner-only DDL and exact fixture deletion share one transaction.
    Failure restores the immutable trigger and FORCE RLS through rollback.
    """
    yield
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute('delete from documents.evidence_references where company_id=%s',(admitted['company'],))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute('alter table shareholder_register_filing.year_source_versions disable trigger year_source_immutable')
        db.execute('alter table shareholder_register_filing.year_source_versions no force row level security')
        db.execute('alter table shareholder_register_filing.year_source_heads no force row level security')
        db.execute('delete from shareholder_register_filing.year_source_heads where company_id=%s',(admitted['company'],))
        db.execute('delete from shareholder_register_filing.year_source_versions where company_id=%s',(admitted['company'],))
        db.execute('alter table shareholder_register_filing.year_source_versions force row level security')
        db.execute('alter table shareholder_register_filing.year_source_heads force row level security')
        db.execute('alter table shareholder_register_filing.year_source_versions enable trigger year_source_immutable')


def session(seed, backend_url, actor=None):
    identity=ActorId(ActorKind.USER,UserId(str(actor or seed['owner'])))
    claims={'sub':str(identity.subject),'role':'authenticated','aal':'aal2',
        'amr':[{'method':'totp','timestamp':seed['now'].timestamp()}]}
    return PostgresShareholderRegisterFilingSession(LedgerSupabaseConfiguration('https://local.example.test','',backend_url),
        _VerifiedActor(identity,json.dumps(claims)),access_token='local-only',billing=None,documents=None,company_access=None)


def seed_documents(seed, store, documents):
    from psycopg.rows import dict_row
    from talli_backend.adapters.supabase_documents import _document
    from talli_backend.modules.documents.public import document_metadata_sha256
    result=[]
    with psycopg.connect(store._configuration.database_url,row_factory=dict_row) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(store.actor_id.subject),json.dumps({str(seed['company']):'owner'})))
        for original in documents:
            document_id=str(uuid4());year=2024
            request=dict(documentId=document_id,companyId=str(seed['company']),incomeYear=year,
                documentType='corporate_document',name='Independent original fixture',linkedTo='workspace',
                storageKey=f"{seed['company']}/{year}/{document_id}/original.pdf",contentType='application/pdf',
                declaredByteLength=original.byte_length,finalStatus='attached')
            db.execute('select * from documents.stage_upload_v1(%s::jsonb,%s)',(json.dumps(request),str(store.actor_id.subject)))
            row=db.execute('select * from documents.finalize_upload_v1(%s::uuid,%s,%s,%s)',
                (document_id,original.byte_length,original.content_sha256,str(store.actor_id.subject))).fetchone()
            doc=_document(row)
            result.append(replace(original,document_id=document_id,company_id=doc.company_id,
                source_income_year=doc.income_year,document_type=str(doc.document_type),integrity_status=str(doc.status),
                created_at=doc.created_at,metadata_sha256=document_metadata_sha256(doc)))
    return tuple(result)


def inputs(seed, store):
    command,context=basis();company=CompanyId(str(seed['company']));year=IncomeYear(2026)
    case=replace(command.case,company=replace(command.case.company,income_year=2026))
    docs=seed_documents(seed,store,command.documents)
    return replace(command,company_id=company,income_year=year,actor_id=store.actor_id,case=case,documents=docs,opening_document_ids=(docs[0].document_id,),
        closing_document_ids=(docs[0].document_id,),paid_in_document_ids=(docs[0].document_id,)),replace(
        context,company_id=company,income_year=year,actor_id=store.actor_id,company=case.company,documents=docs)


def capture(store,command,context,key=None):
    return asyncio.run(store.record_year_source(command,context=context,idempotency_key=key or IdempotencyKey(str(uuid4()))))


def query(command):return rf.Rf1086SourceQuery(command.company_id,command.income_year,command.actor_id)


def test_capture_current_history_identical_replay_and_correction(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()))
    assert asyncio.run(s.read_current_year_source(query(c))) is None
    first=capture(s,c,ctx,key)
    assert capture(s,c,ctx,key)==first
    assert asyncio.run(s.read_current_year_source(query(c)))==first
    correction=replace(c,supersedes_source_id=first.source_id,supersedes_source_sha256=first.source_sha256,correction_reason='Correct reviewed source evidence')
    second=capture(s,correction,ctx)
    assert second.version==2 and second.confirmed_at>first.confirmed_at
    assert asyncio.run(s.read_year_source(query(c),first.source_id))==first
    assert asyncio.run(s.read_current_year_source(query(c)))==second
    assert capture(s,c,ctx,key)==first


def test_idempotency_conflict_and_stale_forks_cannot_overwrite(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()));first=capture(s,c,ctx,key)
    with pytest.raises(rf.Rf1086YearSourceError,match='idempotency_conflict'):
        capture(s,replace(c,correction_reason='different'),ctx,key)
    with pytest.raises(rf.Rf1086YearSourceError,match='predecessor_mismatch'):
        capture(s,c,ctx)
    assert asyncio.run(s.read_current_year_source(query(c)))==first


def test_concurrent_identical_capture_returns_one_version(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()))
    async def run():return await asyncio.gather(*(session(admitted,backend_url).record_year_source(c,context=ctx,idempotency_key=key) for _ in range(2)))
    left,right=asyncio.run(run());assert left==right and left.version==1


def test_concurrent_fork_creates_exactly_one_successor(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);first=capture(s,c,ctx)
    correction=replace(c,supersedes_source_id=first.source_id,supersedes_source_sha256=first.source_sha256,correction_reason='Correct evidence')
    async def run():return await asyncio.gather(*(session(admitted,backend_url).record_year_source(correction,context=ctx,idempotency_key=IdempotencyKey(str(uuid4()))) for _ in range(2)),return_exceptions=True)
    results=asyncio.run(run());assert sum(isinstance(x,rf.Rf1086YearSourceSnapshot) for x in results)==1
    assert sum(isinstance(x,rf.Rf1086YearSourceError) for x in results)==1
    assert asyncio.run(s.read_current_year_source(query(c))).version==2


def test_tenant_concealment_and_wrong_year_history(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    other=session(admitted,backend_url,admitted['outsider'])
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(other.read_current_year_source(replace(query(c),actor_id=other.actor_id)))
    assert asyncio.run(s.read_year_source(replace(query(c),income_year=IncomeYear(2025)),source.source_id)) is None


def test_owner_revocation_beats_trusted_context_and_replay(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()));source=capture(s,c,ctx,key)
    with psycopg.connect(DATABASE_URL) as db:db.execute("update public.company_memberships set role='read_only' where company_id=%s",(admitted['company'],))
    with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,ctx,key)
    assert asyncio.run(s.read_year_source(query(c),source.source_id))==source


def test_unadmitted_year_and_forged_actor_are_rejected(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s)
    case=replace(c.case,company=replace(c.case.company,income_year=2025));bad=replace(c,income_year=IncomeYear(2025),case=case)
    with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,bad,replace(ctx,income_year=bad.income_year,company=case.company))
    with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,replace(ctx,actor_id=ActorId(ActorKind.USER,UserId(str(admitted['outsider'])))))


def test_executor_has_no_direct_mutations_and_browser_has_no_reads(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    async def mutate():
        async with s._transaction() as db:await db.execute("update shareholder_register_filing.year_source_versions set version=999 where id=%s::uuid",(source.source_id.value,))
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(mutate())
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role'):
            assert not db.execute("select has_table_privilege(%s,'shareholder_register_filing.year_source_versions','SELECT')",(role,)).fetchone()[0]
        assert db.execute("select bool_and(relforcerowsecurity) from pg_class where oid in ('shareholder_register_filing.year_source_versions'::regclass,'shareholder_register_filing.year_source_heads'::regclass)").fetchone()[0]


def test_migration_replay_rollback_recutover_preserve_history_and_roles(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    with psycopg.connect(DATABASE_URL) as db:
        before=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==before
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(s.read_current_year_source(query(c)))
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert asyncio.run(s.read_current_year_source(query(c)))==source


def test_late_source_failure_rolls_back_retention_source_and_head(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute("create function shareholder_register_filing.fixture_reject_source() returns trigger language plpgsql as $$begin raise exception 'fixture_late_reject'; end$$")
        db.execute('create trigger fixture_reject_source before insert on shareholder_register_filing.year_source_versions for each row execute function shareholder_register_filing.fixture_reject_source()')
    try:
        with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,ctx)
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role documents_store_owner')
            assert db.execute('select count(*) from documents.evidence_references where company_id=%s',(admitted['company'],)).fetchone()[0]==0
        assert asyncio.run(s.read_current_year_source(query(c))) is None
        async def count():
            async with s._transaction() as db:
                return (await (await db.execute('select count(*) as n from shareholder_register_filing.year_source_versions where company_id=%s',(admitted['company'],))).fetchone())['n']
        assert asyncio.run(count())==0
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('drop trigger fixture_reject_source on shareholder_register_filing.year_source_versions')
            db.execute('drop function shareholder_register_filing.fixture_reject_source()')


def test_original_source_blocks_frozen_predecessor_rehearsal(admitted,backend_url):
    from test_authority_connections_database_runtime import assert_retained_rf_original_refuses_predecessor_rehearsal
    store=session(admitted,backend_url);command,context=inputs(admitted,store)
    original=capture(store,command,context)
    assert_retained_rf_original_refuses_predecessor_rehearsal()
    assert asyncio.run(store.read_current_year_source(query(command)))==original
