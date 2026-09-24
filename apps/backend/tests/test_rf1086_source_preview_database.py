"""Immutable full-year preview storage through actual restricted RF authorization."""
import asyncio
from dataclasses import replace
from uuid import uuid4
import psycopg
import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear, IdempotencyKey
from test_rf1086_year_source_database import (
    session, inputs, capture, query, DATABASE_URL, ROOT, remove_only_owned_source_fixture,
)
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access

pytestmark=pytest.mark.authority_database
MIGRATION='20260923105912_rf1086_source_backed_preview.sql'

@pytest.fixture(autouse=True)
def remove_only_preview_fixture(admitted,backend_url,remove_only_owned_source_fixture):
    yield
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute('alter table shareholder_register_filing.source_previews disable trigger source_preview_immutable')
        db.execute('alter table shareholder_register_filing.source_previews no force row level security')
        db.execute('delete from shareholder_register_filing.source_previews where company_id=%s',(admitted['company'],))
        db.execute('alter table shareholder_register_filing.source_previews force row level security')
        db.execute('alter table shareholder_register_filing.source_previews enable trigger source_preview_immutable')


def generate(s,source):
    return asyncio.run(rf.create_rf1086_preparation_service(s).generate_source_preview(
        rf.GenerateRf1086SourcePreview(source.company_id,source.income_year,source)))


def test_exact_preview_replay_and_history_after_source_correction(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    first=generate(s,source)
    assert generate(s,source)==first
    assert first.source_id==source.source_id and first.source_sha256==source.source_sha256
    assert first.case_sha256==source.case_sha256 and first.hovedskjema_xml
    assert asyncio.run(s.source_preview(first.preview_id))==first
    correction=replace(c,supersedes_source_id=source.source_id,supersedes_source_sha256=source.source_sha256,correction_reason='Review new retained evidence')
    new_source=capture(s,correction,ctx)
    with pytest.raises(rf.Rf1086YearSourceError,match='source_preview_stale'):generate(s,source)
    second=generate(s,new_source)
    assert second.preview_id!=first.preview_id and second.hovedskjema_xml==first.hovedskjema_xml
    assert asyncio.run(s.source_preview(first.preview_id))==first
    assert asyncio.run(s.source_preview(second.preview_id))==second
    async def legacy_count():
        async with s._transaction() as db:
            return (await (await db.execute('select count(*) as n from shareholder_register_filing.filing_previews where company_id=%s',(admitted['company'],))).fetchone())['n']
    assert asyncio.run(legacy_count())==0


def test_concurrent_same_source_returns_one_immutable_preview(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    async def run():
        command=rf.GenerateRf1086SourcePreview(source.company_id,source.income_year,source)
        return await asyncio.gather(*(rf.create_rf1086_preparation_service(session(admitted,backend_url)).generate_source_preview(command) for _ in range(2)))
    left,right=asyncio.run(run());assert left==right
    async def count():
        async with s._transaction() as db:
            return (await (await db.execute('select count(*) as n from shareholder_register_filing.source_previews where company_id=%s',(admitted['company'],))).fetchone())['n']
    assert asyncio.run(count())==1


def test_tenant_concealment_and_missing_preview(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx);preview=generate(s,source)
    other=session(admitted,backend_url,admitted['outsider'])
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(other.source_preview(preview.preview_id))
    with pytest.raises(rf.ShareholderRegisterFilingError):generate(other,source)
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(s.source_preview(rf.PreviewId(str(uuid4()))))


def test_owner_revocation_prevents_identical_replay_but_retains_member_history(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx);preview=generate(s,source)
    with psycopg.connect(DATABASE_URL) as db:db.execute("update public.company_memberships set role='read_only' where company_id=%s",(admitted['company'],))
    with pytest.raises(rf.ShareholderRegisterFilingError):generate(s,source)
    assert asyncio.run(s.source_preview(preview.preview_id))==preview


def test_source_identity_scope_and_rendered_changes_cannot_be_forged(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    with pytest.raises(rf.Rf1086YearSourceError):generate(s,replace(source,source_sha256='f'*64))
    async def wrong_year():
        return await rf.create_rf1086_preparation_service(s).generate_source_preview(
            rf.GenerateRf1086SourcePreview(source.company_id,IncomeYear(2025),source))
    with pytest.raises(rf.Rf1086YearSourceError):asyncio.run(wrong_year())
    class ChangedRenderer:
        async def capture_source_preview(self,command,prepared):
            return await s.capture_source_preview(command,replace(prepared,rendered=replace(prepared.rendered,hovedskjema_xml='<unbound/>')))
    async def changed_xml():return await rf.create_rf1086_preparation_service(ChangedRenderer()).generate_source_preview(rf.GenerateRf1086SourcePreview(source.company_id,source.income_year,source))
    with pytest.raises(rf.Rf1086YearSourceError):asyncio.run(changed_xml())


def test_runtime_cannot_mutate_or_delete_preview_and_browser_has_no_reads(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx);preview=generate(s,source)
    async def mutate():
        async with s._transaction() as db:await db.execute('delete from shareholder_register_filing.source_previews where id=%s::uuid',(str(preview.preview_id),))
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(mutate())
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role'):
            assert not db.execute("select has_table_privilege(%s,'shareholder_register_filing.source_previews','SELECT')",(role,)).fetchone()[0]
        assert db.execute("select relforcerowsecurity from pg_class where oid='shareholder_register_filing.source_previews'::regclass").fetchone()[0]


def test_api_rollback_recutover_preserves_preview_and_exact_role_options(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx);preview=generate(s,source)
    with psycopg.connect(DATABASE_URL) as db:
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==roles
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(s.source_preview(preview.preview_id))
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert generate(s,source)==preview
    assert asyncio.run(s.source_preview(preview.preview_id))==preview


def test_direct_rpc_rejects_superseded_source_even_for_exact_stored_payload(admitted,backend_url):
    import hashlib
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx);preview=generate(s,source)
    capture(s,replace(c,supersedes_source_id=source.source_id,supersedes_source_sha256=source.source_sha256,correction_reason='Superseded original'),ctx)
    encoded=rf.serialize_rf1086_source_preview(preview)
    async def stale_rpc():
        async with s._transaction() as db:
            await db.execute('select shareholder_register_filing.append_source_preview_v1(%s::uuid,%s::uuid,%s,%s::uuid,%s,%s,%s,%s)',
                (str(preview.preview_id),str(preview.company_id),int(preview.income_year),source.source_id.value,
                 source.source_sha256,source.case_sha256,hashlib.sha256(encoded.encode()).hexdigest(),encoded))
    with pytest.raises(rf.Rf1086YearSourceError,match='source_preview_stale'):asyncio.run(stale_rpc())
    assert asyncio.run(s.source_preview(preview.preview_id))==preview


async def wait_for_source_lock():
    for _ in range(30):
        await asyncio.sleep(.015)
        with psycopg.connect(DATABASE_URL) as observer:
            waiting=observer.execute("select exists(select 1 from pg_stat_activity where datname=current_database() and wait_event='advisory' and query like '%lock_year_source_v1%')").fetchone()[0]
        if waiting:return
    raise AssertionError('preview never waited on the current-source advisory lock')


def test_queued_preview_observes_source_correction_committed_under_same_lock(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    async def run():
        async with s._transaction() as blocker:
            await blocker.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',(str(source.company_id),int(source.income_year)))
            task=asyncio.create_task(rf.create_rf1086_preparation_service(session(admitted,backend_url)).generate_source_preview(
                rf.GenerateRf1086SourcePreview(source.company_id,source.income_year,source)))
            await wait_for_source_lock()
            correction=replace(c,supersedes_source_id=source.source_id,supersedes_source_sha256=source.source_sha256,correction_reason='Concurrent correction')
            now=(await (await blocker.execute('select clock_timestamp() as now')).fetchone())['now']
            corrected=rf.prepare_rf1086_year_source(correction,context=ctx,source_id=rf.Rf1086YearSourceId(str(uuid4())),confirmed_at=now,previous=source)
            await s._retain_source_documents(blocker,'rf1086_year_source',corrected.source_id.value,corrected.command.documents)
            await blocker.execute('select shareholder_register_filing.append_year_source_v1(%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s)',
                (corrected.source_id.value,str(corrected.company_id),int(corrected.income_year),corrected.version,
                 corrected.source_sha256,rf.rf1086_year_source_digest(correction),str(uuid4()),source.source_id.value,source.source_sha256,
                 correction.correction_reason,rf.serialize_rf1086_year_source(corrected),now))
        with pytest.raises(rf.Rf1086YearSourceError,match='source_preview_stale'):await task
        return corrected
    corrected=asyncio.run(run())
    assert asyncio.run(s.read_current_year_source(query(c)))==corrected
    assert generate(s,corrected).source_id==corrected.source_id


def test_owner_revocation_while_preview_waits_on_source_lock_fails_closed(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    async def run():
        async with s._transaction() as blocker:
            await blocker.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',(str(source.company_id),int(source.income_year)))
            task=asyncio.create_task(rf.create_rf1086_preparation_service(session(admitted,backend_url)).generate_source_preview(
                rf.GenerateRf1086SourcePreview(source.company_id,source.income_year,source)))
            await wait_for_source_lock()
            with psycopg.connect(DATABASE_URL) as db:db.execute("update public.company_memberships set role='read_only' where company_id=%s",(admitted['company'],))
        with pytest.raises(rf.ShareholderRegisterFilingError):await task
    asyncio.run(run())


def test_new_accepted_owner_can_preview_original_source_without_rewriting_actor(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);source=capture(s,c,ctx)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",(admitted['company'],admitted['outsider']))
    new_owner=session(admitted,backend_url,admitted['outsider'])
    preview=generate(new_owner,source)
    retained=asyncio.run(new_owner.read_year_source(replace(query(c),actor_id=new_owner.actor_id),source.source_id))
    assert retained==source and retained.confirmed_by==s.actor_id
    assert preview.source_id==source.source_id and preview.source_sha256==source.source_sha256
    assert asyncio.run(s.source_preview(preview.preview_id))==preview
