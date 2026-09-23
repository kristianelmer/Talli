"""Documents retention on a disposable database with an actual restricted login."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_document_evidence import PostgresDocumentEvidenceRetention
from talli_backend.adapters.supabase_documents import _document
from talli_backend.modules.documents.public import DocumentEvidenceRetentionCommand, document_metadata_sha256
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access

pytestmark=pytest.mark.authority_database
DATABASE_URL=os.environ.get('DATABASE_URL','')
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20260923102419_documents_verified_rf_evidence_retention.sql'


@pytest.fixture
def originals(backend_url):
    owner, company=uuid4(),uuid4()
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('insert into auth.users(id,email) values(%s,%s)',(owner,str(owner)+'@retention.test'))
        db.execute("insert into public.companies(id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by) values(%s,%s,'Retention AS','AS','Example 1','0150','Oslo','Active','test',%s)",(company,str(100000000+company.int%899999999),owner))
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",(company,owner))
    documents=[]
    with psycopg.connect(backend_url,row_factory=dict_row) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(owner),json.dumps({str(company):'owner'})))
        for _ in range(2):
            identity=uuid4()
            request={'documentId':str(identity),'companyId':str(company),'incomeYear':2025,
                     'documentType':'accounting_document','linkedTo':'workspace','name':'Original ø.pdf',
                     'storageKey':f'{company}/2025/{identity}/original.pdf','contentType':'application/pdf',
                     'declaredByteLength':9,'finalStatus':'attached'}
            db.execute('select * from documents.stage_upload_v1(%s,%s)',(Jsonb(request),str(owner)))
            row=db.execute('select * from documents.finalize_upload_v1(%s,9,%s,%s)',(identity,'a'*64,str(owner))).fetchone()
            documents.append(_document(row))
    return {'owner':owner,'company':company,'documents':documents}


def command(seed,index=0,source=None,source_type='rf1086_year_source'):
    document=seed['documents'][index]
    return DocumentEvidenceRetentionCommand(source_type,str(source or uuid4()),document.document_id,
        document.company_id,document.income_year,document.status,document.content_sha256,document.byte_length,
        document_metadata_sha256(document))


async def scoped(url,seed):
    db=await psycopg.AsyncConnection.connect(url,row_factory=dict_row)
    await db.execute('set local role shareholder_register_filing_executor')
    await db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(seed['owner']),))
    return db,PostgresDocumentEvidenceRetention(db,ActorId(ActorKind.USER,UserId(str(seed['owner']))))


def retained_count(seed):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        return db.execute('select count(*) from documents.evidence_references where company_id=%s',(seed['company'],)).fetchone()[0]


def retain(url,seed,*commands):
    async def run():
        db,adapter=await scoped(url,seed)
        async with db:
            for item in commands:await adapter.retain_verified_evidence(item)
    asyncio.run(run())


def test_multiple_originals_replay_and_correction_retain_all_originals(originals,backend_url):
    source=uuid4();first=command(originals,source=source);second=command(originals,1,source)
    retain(backend_url,originals,first,second)
    retain(backend_url,originals,first,second)
    assert retained_count(originals)==2
    retain(backend_url,originals,command(originals))
    assert retained_count(originals)==3
    with psycopg.connect(backend_url) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
        with pytest.raises(psycopg.Error,match='documents_evidence_linked'):
            db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(first.document_id.value,'remove',str(originals['owner'])))


@pytest.mark.parametrize('column,value', [('name','Changed.pdf'),('storage_key','moved/original.pdf'),('retention_years',10),('linked_to','skattemelding'),('content_type','text/xml')])
def test_changed_complete_metadata_fails_and_rolls_back_earlier_retention(originals,backend_url,column,value):
    from psycopg import sql
    first=command(originals);second=command(originals,1)
    if column=='storage_key':value=f'{originals["company"]}/{value}'
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
        db.execute(sql.SQL('update public.documents set {}=%s where id=%s').format(sql.Identifier(column)),(value,second.document_id.value))
    with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
        retain(backend_url,originals,first,second)
    assert retained_count(originals)==0


@pytest.mark.parametrize('field,value',[('source_record_type','unsupported'),('source_income_year',2024),('content_sha256','b'*64),('byte_length',10),('status','stored')])
def test_exact_source_fields_fail_closed(originals,backend_url,field,value):
    from talli_backend.shared.kernel import IncomeYear
    if field=='source_income_year':value=IncomeYear(value)
    with pytest.raises(psycopg.Error):retain(backend_url,originals,replace(command(originals),**{field:value}))
    assert retained_count(originals)==0


def test_caught_metadata_mismatch_still_cannot_commit(originals,backend_url):
    bad=replace(command(originals),metadata_sha256='b'*64)
    async def run():
        db,adapter=await scoped(backend_url,originals)
        async with db:
            with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
                await adapter.retain_verified_evidence(bad)
            with pytest.raises(psycopg.errors.InFailedSqlTransaction):await db.execute('select 1')
    asyncio.run(run())
    assert retained_count(originals)==0


def test_later_source_failure_rolls_back_retention(originals,backend_url):
    async def run():
        db,adapter=await scoped(backend_url,originals)
        async with db:
            await adapter.retain_verified_evidence(command(originals))
            await db.execute('select 1/0')
    with pytest.raises(psycopg.errors.DivisionByZero):asyncio.run(run())
    assert retained_count(originals)==0


def test_revoked_owner_cannot_retain_even_with_valid_metadata(originals,backend_url):
    with psycopg.connect(DATABASE_URL) as db:db.execute("update public.company_memberships set role='read_only' where company_id=%s",(originals['company'],))
    with pytest.raises(psycopg.Error,match='documents_forbidden'):retain(backend_url,originals,command(originals))
    assert retained_count(originals)==0


def test_restricted_runtime_and_browser_cannot_bypass_owned_functions(originals,backend_url):
    with psycopg.connect(backend_url) as db:
        db.execute('set local role shareholder_register_filing_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):db.execute('select * from public.documents')
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role','documents_executor'):
            assert not db.execute("select has_function_privilege(%s,'documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid)','EXECUTE')",(role,)).fetchone()[0]


def test_rollback_preserves_references_deletion_guard_and_replay_restores_exact_roles(originals,backend_url):
    retain(backend_url,originals,command(originals))
    with psycopg.connect(DATABASE_URL) as db:
        before=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==before
    try:
        assert retained_count(originals)==1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):retain(backend_url,originals,command(originals))
        with psycopg.connect(backend_url) as db:
            db.execute('set local role documents_executor')
            db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
            with pytest.raises(psycopg.Error,match='documents_evidence_linked'):db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(originals['documents'][0].document_id.value,'remove',str(originals['owner'])))
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==before
    assert retained_count(originals)==1


def test_document_removal_cannot_win_after_capture_has_locked_original(originals,backend_url):
    async def run():
        capture,adapter=await scoped(backend_url,originals)
        async with capture:
            item=command(originals)
            await adapter.retain_verified_evidence(item)
            removal=await psycopg.AsyncConnection.connect(backend_url)
            async with removal:
                await removal.execute('set local role documents_executor')
                await removal.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
                await removal.execute("set local lock_timeout='200ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    await removal.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(item.document_id.value,'race',str(originals['owner'])))
    asyncio.run(run())
    assert retained_count(originals)==1
    with psycopg.connect(backend_url) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
        with pytest.raises(psycopg.Error,match='documents_evidence_linked'):
            db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(originals['documents'][0].document_id.value,'race',str(originals['owner'])))


def test_stored_original_status_is_preserved_for_observation_capture(originals,backend_url):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
        db.execute("update public.documents set status='stored' where id=%s",(originals['documents'][0].document_id.value,))
    from talli_backend.modules.documents.public import DocumentStatus
    originals['documents'][0]=replace(originals['documents'][0],status=DocumentStatus.STORED)
    retain(backend_url,originals,command(originals,source_type='rf1086_register_observation'))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        assert db.execute('select document_status from documents.evidence_references where company_id=%s',(originals['company'],)).fetchone()[0]=='stored'


def test_retention_refuses_autocommit_without_an_existing_source_transaction(originals,backend_url):
    from talli_backend.modules.documents.public import DocumentsError
    async def run():
        db=await psycopg.AsyncConnection.connect(backend_url,row_factory=dict_row,autocommit=True)
        async with db:
            adapter=PostgresDocumentEvidenceRetention(db,ActorId(ActorKind.USER,UserId(str(originals['owner']))))
            with pytest.raises(DocumentsError):await adapter.retain_verified_evidence(command(originals))
    asyncio.run(run())
    assert retained_count(originals)==0


def test_legacy_registry_api_is_not_broadened_to_unverified_attached_documents(originals):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(originals['owner']),))
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("select documents.register_evidence_reference_v1('corporate_governance','legacy_record',%s,%s,%s,2025,null,'attached',%s,9,%s)",
                (uuid4(),originals['documents'][0].document_id.value,originals['company'],'a'*64,originals['owner']))
    assert retained_count(originals)==0


@pytest.mark.parametrize('same_company', [True, False])
def test_ledger_memo_guard_is_company_scoped_and_unlinked_removal_still_works(originals, same_company):
    """Exercise the published Ledger guard under Documents' restricted role."""
    from psycopg import sql
    with psycopg.connect(DATABASE_URL) as db:
        try:
            principal = db.execute('select current_user').fetchone()[0]
            other_company = uuid4()
            db.execute("insert into public.companies(id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by) values(%s,%s,'Other fixture AS','AS','Example 2','0150','Oslo','Active','test',%s)",
                       (other_company,str(100000000+other_company.int%899999999),originals['owner']))
            db.execute(sql.SQL('grant ledger_store_owner, documents_executor to {} with set true granted by {}').format(sql.Identifier(principal),sql.Identifier(principal)))
            db.execute('set local role ledger_store_owner')
            db.execute(sql.SQL('grant insert on ledger.entries to {}').format(sql.Identifier(principal)))
            db.execute('reset role')
            document_id = originals['documents'][0].document_id.value
            db.execute("insert into ledger.entries(company_id,income_year,entry_kind,memo,lines,created_by,source_capability,source_record_id,correlation_id) values(%s,2025,'MANUAL_JOURNAL',%s,%s,%s,'LEDGER',%s,%s)",
                       (originals['company'] if same_company else other_company,'Original '+document_id,Jsonb([{'account':'1920','description':'fixture','debit':1,'credit':0},{'account':'2000','description':'fixture','debit':0,'credit':1}]),originals['owner'],str(uuid4()),str(uuid4())))
            db.execute('reset role')
            db.execute('set local role documents_executor')
            db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(originals['owner']),json.dumps({str(originals['company']):'owner'})))
            db.execute('savepoint linked_removal')
            if same_company:
                with pytest.raises(psycopg.Error, match='documents_evidence_linked'):
                    db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(document_id,'remove',str(originals['owner'])))
                db.execute('rollback to savepoint linked_removal')
            else:
                db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(document_id,'remove',str(originals['owner'])))
            db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(originals['documents'][1].document_id.value,'unlinked',str(originals['owner'])))
        finally:
            # Undo fixture rows, removals, and the temporary Ledger fixture role.
            db.rollback()


def test_ledger_guard_rollback_and_replay_preserve_all_other_predicates_and_privileges(originals):
    migration='20260923125730_documents_ledger_evidence_guard.sql'
    with psycopg.connect(DATABASE_URL) as db:
        def state():
            return (
                db.execute("select pg_get_functiondef(oid),proowner,proacl,prosecdef,proconfig from pg_proc where oid='documents.has_evidence_references_v1(uuid)'::regprocedure").fetchone(),
                db.execute("select nspacl from pg_namespace where nspname='documents'").fetchone(),
                db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall(),
            )
        before=state()
        assert 'public.ledger_entries' not in before[0][0]
        assert 'ledger.has_document_memo_reference_v1' in before[0][0]
        for _ in range(2):
            db.execute((ROOT/'supabase/rollback'/migration).read_text())
            assert state()==before
            db.execute((ROOT/'supabase/migrations'/migration).read_text())
            assert state()==before
        for role in ('anon','authenticated','service_role','documents_executor','shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,'ledger.has_document_memo_reference_v1(uuid,uuid)','EXECUTE')",(role,)).fetchone()[0]
        assert not db.execute("select has_table_privilege('documents_store_owner','ledger.entries','SELECT')").fetchone()[0]
