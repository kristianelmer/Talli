"""Immutable Documents originals under restricted executors on an owned local DB."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
from talli_backend.adapters.supabase_documents import _document
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from talli_backend.modules.documents.public import DocumentId
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access

pytestmark=pytest.mark.authority_database
DATABASE_URL=os.environ.get('DATABASE_URL','')
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20260924062717_documents_immutable_retained_originals.sql'
PDF=b'%PDF-1.7\noriginal bytes\x00\xff'


@pytest.fixture
def original(backend_url):
    owner,outsider,company,document=[uuid4() for _ in range(4)]
    with psycopg.connect(DATABASE_URL) as db:
        for user in (owner,outsider):db.execute('insert into auth.users(id,email) values(%s,%s)',(user,str(user)+'@original.test'))
        db.execute("insert into public.companies(id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by) values(%s,%s,'Original AS','AS','Example 1','0150','Oslo','Active','test',%s)",(company,str(100000000+company.int%899999999),owner))
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",(company,owner))
    with psycopg.connect(backend_url,row_factory=dict_row) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",(str(owner),json.dumps({str(company):'owner'})))
        request={'documentId':str(document),'companyId':str(company),'incomeYear':2025,'documentType':'accounting_document',
            'linkedTo':'workspace','name':'Original.pdf','storageKey':f'{company}/2025/{document}/original.pdf',
            'contentType':'application/pdf','declaredByteLength':len(PDF),'finalStatus':'attached'}
        db.execute('select * from documents.stage_upload_v1(%s,%s)',(Jsonb(request),str(owner)))
        row=db.execute('select * from documents.finalize_upload_v1(%s,%s,%s,%s)',(document,len(PDF),sha256(PDF).hexdigest(),str(owner))).fetchone()
    return {'owner':owner,'outsider':outsider,'company':company,'document':_document(row),'url':backend_url}


async def connect(seed,*,role='documents_executor',actor=None):
    identity=actor or seed['owner']
    db=await psycopg.AsyncConnection.connect(seed['url'],row_factory=dict_row)
    await db.execute('set local role '+role)
    await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
        (str(identity),json.dumps({str(seed['company']):'owner'})))
    return db,PostgresDocumentOriginals(db,ActorId(ActorKind.USER,UserId(str(identity))))


def retain(seed,content=PDF,document=None):
    async def run():
        db,adapter=await connect(seed)
        async with db:return await adapter.retain_verified_original(document or seed['document'],content)
    return asyncio.run(run())


def read(seed,receipt,*,actor=None,company=None):
    async def run():
        db,adapter=await connect(seed,actor=actor)
        async with db:return await adapter.read_retained_original(receipt.original_id,company or receipt.company_id)
    return asyncio.run(run())


def assert_original(seed,receipt):
    async def run():
        db,adapter=await connect(seed,role='shareholder_register_filing_executor')
        async with db:await adapter.assert_retained_original(receipt)
    asyncio.run(run())


def count(seed):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(seed['owner']),))
        return db.execute('select count(*) from documents.retained_originals where company_id=%s',(seed['company'],)).fetchone()[0]


def test_exact_bytes_receipt_replay_and_narrow_assertion(original):
    first=retain(original);second=retain(original)
    assert first==second and count(original)==1
    copy=read(original,first)
    assert copy.receipt==first and copy.content==PDF
    assert_original(original,first)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(original['owner']),))
        assert db.execute('select count(*) from documents.evidence_references where document_id=%s',(original['document'].document_id.value,)).fetchone()[0]==0


@pytest.mark.parametrize('kind',['empty','changed','oversized'])
def test_invalid_empty_or_oversized_bytes_never_retain(original,kind):
    content=b'' if kind=='empty' else b'changed original' if kind=='changed' else b'x'*(10485760+1)
    document=replace(original['document'],byte_length=len(content),content_sha256=sha256(content).hexdigest()) if kind=='oversized' else None
    with pytest.raises(psycopg.Error,match='documents_invalid_input'):retain(original,content,document)
    assert count(original)==0


@pytest.mark.parametrize('change',['name','storage_key','retention_years','source_year'])
def test_metadata_changed_before_copy_rolls_back_insert_even_when_exception_caught(original,change):
    field={'source_year':'income_year'}.get(change,change)
    value={'name':'Changed.pdf','storage_key':f"{original['company']}/moved.pdf",'retention_years':10,'source_year':2024}[change]
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(original['owner']),json.dumps({str(original['company']):'owner'})))
        db.execute(psycopg.sql.SQL('update public.documents set {}=%s where id=%s').format(psycopg.sql.Identifier(field)),(value,original['document'].document_id.value))
    async def run():
        db,adapter=await connect(original)
        async with db:
            with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
                await adapter.retain_verified_original(original['document'],PDF)
            with pytest.raises(psycopg.errors.InFailedSqlTransaction):await db.execute('select 1')
    asyncio.run(run());assert count(original)==0


def test_changed_original_does_not_change_retained_bytes_but_blocks_current_assertion(original):
    receipt=retain(original)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(original['owner']),json.dumps({str(original['company']):'owner'})))
        db.execute('update public.documents set name=%s where id=%s',('Different.pdf',original['document'].document_id.value))
    assert read(original,receipt).content==PDF
    with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):assert_original(original,receipt)
    assert count(original)==1


@pytest.mark.parametrize('field,value',[('metadata_sha256','f'*64),('content_sha256','e'*64),('byte_length',1),('original_id',str(uuid4())),
    ('document_id',DocumentId(str(uuid4()))),('source_income_year',IncomeYear(2024))],
    ids=['metadata-hash','content-hash','byte-length','original-id','document-id','source-year'])
def test_receipt_binding_mismatch_aborts_consequential_assertion(original,field,value):
    receipt=retain(original)
    with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
        assert_original(original,replace(receipt,**{field:value}))


def test_receipt_retention_time_is_bound(original):
    receipt=retain(original)
    with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
        assert_original(original,replace(receipt,retained_at=receipt.retained_at+timedelta(seconds=1)))


def test_outsider_cached_owner_and_removed_membership_cannot_read_or_retain(original):
    receipt=retain(original)
    with pytest.raises(psycopg.Error,match='documents_forbidden'):read(original,receipt,actor=original['outsider'])
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('delete from public.company_memberships where company_id=%s',(original['company'],))
    with pytest.raises(psycopg.Error,match='documents_forbidden'):read(original,receipt)
    with pytest.raises(psycopg.Error,match='documents_forbidden'):retain(original)


def test_current_owner_cannot_query_other_company_receipt(original):
    receipt=retain(original)
    with pytest.raises(psycopg.Error,match='documents_forbidden'):
        read(original,receipt,company=CompanyId(str(uuid4())))


def test_executors_have_no_table_or_foreign_byte_read_authority(original):
    with psycopg.connect(DATABASE_URL) as db:
        owner,rls,force=db.execute("select pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity from pg_class where oid='documents.retained_originals'::regclass").fetchone()
        assert owner=='documents_store_owner' and rls and force
        for role in ('anon','authenticated','service_role','documents_executor','shareholder_register_filing_executor'):
            assert not db.execute("select has_table_privilege(%s,'documents.retained_originals','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",(role,)).fetchone()[0]
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,'documents.read_retained_original_v1(uuid,uuid,text)','EXECUTE')",(role,)).fetchone()[0]
        assert db.execute("select has_function_privilege('shareholder_register_filing_executor','documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)','EXECUTE')").fetchone()[0]


@pytest.mark.parametrize('operation',["update documents.retained_originals set content=content",'delete from documents.retained_originals','truncate documents.retained_originals'])
def test_table_owner_cannot_mutate_original_even_without_forced_rls(original,operation):
    retain(original)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute('alter table documents.retained_originals no force row level security')
        with pytest.raises(psycopg.Error,match='documents_retained_original_immutable'):db.execute(operation)
    assert count(original)==1


def test_migration_replay_preserves_original_and_nonempty_rollback_refuses(original):
    receipt=retain(original)
    def authority():
        with psycopg.connect(DATABASE_URL) as db:
            return db.execute("select member,grantor,admin_option,inherit_option,set_option from pg_auth_members "
                "where roleid='documents_store_owner'::regrole order by member,grantor").fetchall()
    before=authority()
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        guarded=db.execute("select to_regprocedure('documents.lock_company_write_v1(uuid,text)') is not null").fetchone()[0]
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        if guarded:
            db.execute((ROOT/'supabase/migrations/20260924080249_documents_rf_consequential_company_guards.sql').read_text())
    assert read(original,receipt).content==PDF
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        with pytest.raises(psycopg.Error,match='documents_retained_original_rollback_requires_empty'):
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
    assert read(original,receipt).receipt==receipt
    assert authority()==before
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute("select relforcerowsecurity from pg_class where oid='documents.retained_originals'::regclass").fetchone()[0]


def test_owner_of_two_companies_cannot_rebind_retained_original_to_other_company(original):
    receipt=retain(original);other=uuid4()
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.companies(id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by) values(%s,%s,'Second AS','AS','Example 2','0150','Oslo','Active','test',%s)",
            (other,str(100000000+other.int%899999999),original['owner']))
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",(other,original['owner']))
    with pytest.raises(psycopg.Error,match='documents_not_found'):
        read(original,receipt,company=CompanyId(str(other)))
    with pytest.raises(psycopg.Error,match='documents_evidence_mismatch'):
        assert_original(original,replace(receipt,company_id=CompanyId(str(other))))
    assert read(original,receipt).content==PDF


def test_maximum_ten_mib_original_retains_exact_bytes(original):
    content=b'%PDF-'+b'x'*(10485760-5);identity=uuid4()
    with psycopg.connect(original['url'],row_factory=dict_row) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(original['owner']),json.dumps({str(original['company']):'owner'})))
        request={'documentId':str(identity),'companyId':str(original['company']),'incomeYear':2025,
            'documentType':'accounting_document','linkedTo':'workspace','name':'Maximum.pdf',
            'storageKey':f"{original['company']}/2025/{identity}/maximum.pdf",'contentType':'application/pdf',
            'declaredByteLength':len(content),'finalStatus':'attached'}
        db.execute('select * from documents.stage_upload_v1(%s,%s)',(Jsonb(request),str(original['owner'])))
        row=db.execute('select * from documents.finalize_upload_v1(%s,%s,%s,%s)',
            (identity,len(content),sha256(content).hexdigest(),str(original['owner']))).fetchone()
    receipt=retain(original,content,_document(row))
    assert receipt.byte_length==10485760
    assert read(original,receipt).content==content


@pytest.mark.parametrize('binding',['missing','mismatched'])
def test_verified_actor_binding_required_despite_cached_owner(original,binding):
    async def run():
        db,adapter=await connect(original)
        async with db:
            identity='' if binding=='missing' else str(original['outsider'])
            await db.execute("select set_config('talli.verified_actor_id',%s,true)",(identity,))
            with pytest.raises(psycopg.Error,match='documents_forbidden'):
                await adapter.retain_verified_original(original['document'],PDF)
            with pytest.raises(psycopg.errors.InFailedSqlTransaction):await db.execute('select 1')
    asyncio.run(run())
    assert count(original)==0
