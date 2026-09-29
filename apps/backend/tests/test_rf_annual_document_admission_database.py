"""Active Documents metadata stays owner-authorized inside the RF company guard."""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL, ROOT
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from test_document_originals_database import original
from talli_backend.modules.documents.public import DocumentStatus
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear

pytestmark = pytest.mark.authority_database
MIGRATION = '20260929162030_rf_annual_document_read_admission.sql'
SIGNATURE = 'documents.list_documents_v1(uuid[],text)'
PDF = b'%PDF-1.7\nSynthetic annual evidence\n'


def query(fixture, store):
    return rf.Rf1086SourceQuery(CompanyId(str(fixture['company'])), IncomeYear(2026), store.actor_id)


def add_document(db, fixture, year=2026, status='attached'):
    identity = uuid4()
    subject = str(fixture['owner'])
    db.execute('set local role documents_executor')
    db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
               (subject, json.dumps({str(fixture['company']): 'owner'})))
    request = {'documentId': str(identity), 'companyId': str(fixture['company']), 'incomeYear': year,
               'documentType': 'accounting_document', 'linkedTo': 'aksjonaerregisteroppgaven',
               'name': 'Annual reference.pdf', 'storageKey': f"{fixture['company']}/{year}/{identity}/annual.pdf",
               'contentType': 'application/pdf', 'declaredByteLength': len(PDF), 'finalStatus': 'attached'}
    db.execute('select * from documents.stage_upload_v1(%s,%s)', (Jsonb(request), subject))
    if status in ('attached', 'removed'):
        db.execute('select * from documents.finalize_upload_v1(%s,%s,%s,%s)',
                   (identity, len(PDF), sha256(PDF).hexdigest(), subject))
    if status == 'removed':
        db.execute('select * from documents.mark_removed_v1(%s,%s,%s)', (identity, 'Synthetic cleanup', subject))
    elif status == 'quarantined':
        db.execute('select documents.quarantine_upload_v1(%s,%s,%s)', (identity, 'Synthetic quarantine', subject))
    db.execute('reset role')
    return identity


def test_complete_active_exact_year_metadata_and_expired_scope(admitted, backend_url, original):
    store = session(admitted, backend_url)
    # Neither a missing current role nor an unrelated cached role may determine
    # the visibility of this complete enumeration.
    store._roles = {str(original['company']): 'owner'}
    with psycopg.connect(backend_url) as db:
        attached = add_document(db, admitted)
        quarantined = add_document(db, admitted, status='quarantined')
        staged = {add_document(db, admitted, status='staged') for _ in range(101)}
        excluded = {add_document(db, admitted, 2025), add_document(db, admitted, status='removed'),
                    original['document'].document_id.value}
    async def run():
        async with store.source_admission(query(admitted, store)) as scope:
            context = await (await scope._connection.execute(
                "select current_setting('talli.authorized_company_roles') as roles")).fetchone()
            assert json.loads(context['roles']) == {str(admitted['company']): 'owner'}
            result = await scope.annual_document_inputs()
            assert result.company_id == CompanyId(str(admitted['company'])) and result.income_year == IncomeYear(2026)
            records = {str(item.document_id): item for item in result.documents}
            assert set(records) == {str(value) for value in {attached, quarantined, *staged}}
            assert not set(records).intersection(map(str, excluded))
            item = records[str(attached)]
            assert item.status == DocumentStatus.ATTACHED and item.linked_to == 'aksjonaerregisteroppgaven'
            assert item.byte_length == len(PDF) and item.content_sha256 == sha256(PDF).hexdigest()
            assert str(item.created_by.subject) == str(admitted['owner'])
            assert item.created_at.tzinfo is not None and item.removed_at is None
            assert records[str(quarantined)].status == DocumentStatus.QUARANTINED
            assert all(records[str(value)].status == DocumentStatus.STAGED for value in staged)
            with psycopg.connect(DATABASE_URL) as observer:
                assert not observer.execute('select pg_try_advisory_xact_lock(hashtextextended(%s,157))',
                                            (str(admitted['company']),)).fetchone()[0]
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.annual_document_inputs()
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert not db.execute("select has_table_privilege('shareholder_register_filing_executor','public.documents','SELECT')").fetchone()[0]
        for role in ('anon', 'authenticated', 'service_role'):
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, SIGNATURE)).fetchone()[0]


def test_complete_empty_current_year_does_not_reuse_prior_metadata(admitted, backend_url):
    store = session(admitted, backend_url)
    with psycopg.connect(backend_url) as db:
        add_document(db, admitted, 2025)
        add_document(db, admitted, status='removed')
    async def run():
        async with store.source_admission(query(admitted, store)) as scope:
            result = await scope.annual_document_inputs()
            assert result.company_id == CompanyId(str(admitted['company'])) and result.income_year == IncomeYear(2026)
            assert result.documents == ()
    asyncio.run(run())


@pytest.mark.parametrize('revoke', [False, True])
def test_wait_observes_committed_document_or_rejects_revoked_owner(admitted, backend_url, revoke):
    store = session(admitted, backend_url)
    store._roles = {str(admitted['company']): 'owner'}
    async def run():
        ready = asyncio.get_running_loop().create_future()
        original_transaction = store._transaction
        @asynccontextmanager
        async def observed(*args, **kwargs):
            async with original_transaction(*args, **kwargs) as db:
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield db
        store._transaction = observed
        async def read():
            async with store.source_admission(query(admitted, store)) as scope:
                return await scope.annual_document_inputs()
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
                task = asyncio.create_task(read())
                await waiting(await asyncio.wait_for(ready, 3))
                if revoke:
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                                    (admitted['company'], admitted['owner']))
                else:
                    identity = add_document(blocker, admitted)
            if revoke:
                with pytest.raises(rf.ShareholderRegisterFilingError):
                    await asyncio.wait_for(task, 3)
            else:
                result = await asyncio.wait_for(task, 3)
                assert tuple(str(item.document_id) for item in result.documents) == (str(identity),)
        finally:
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_restricted_grant_rollback_replay_preserves_owner_definitions_and_authority():
    role = 'rf_annual_documents_migrator_' + uuid4().hex[:8]
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        password = uuid4().hex
        db.execute(sql.SQL('create role {} login createrole password {}').format(sql.Identifier(role), sql.Literal(password)))
        try:
            db.execute(sql.SQL('grant documents_store_owner to {} with admin true,inherit false,set false').format(sql.Identifier(role)))
            def memberships():
                return db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
            def function():
                # Compare complete grants, not ACL array insertion order.
                return db.execute('''select prosrc,proconfig,proowner,
                    (select jsonb_agg(to_jsonb(a) order by grantor,grantee,privilege_type,is_grantable)
                     from aclexplode(proacl) a)
                    from pg_proc where oid=%s::regprocedure''', (SIGNATURE,)).fetchone()
            before, definition = memberships(), function()
            schema = db.execute("select nspowner,nspacl::text from pg_namespace where nspname='documents'").fetchone()
            with psycopg.connect(make_conninfo(DATABASE_URL, user=role, password=password), autocommit=True) as migrator:
                assert migrator.execute("select rolsuper,rolbypassrls,pg_has_role(current_user,'documents_store_owner','SET') from pg_roles where rolname=current_user").fetchone() == (False, False, False)
                for _ in range(2):
                    migrator.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                    assert not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (SIGNATURE,)).fetchone()[0]
                    migrator.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
                    assert memberships() == before
                    assert function() == definition
                    assert db.execute("select nspowner,nspacl::text from pg_namespace where nspname='documents'").fetchone() == schema
        finally:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
