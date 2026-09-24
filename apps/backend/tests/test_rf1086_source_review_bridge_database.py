"""Actual immutable source-to-review projection; production stays fail-closed."""
import asyncio
from dataclasses import replace
import hashlib
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import (
    DATABASE_URL, ROOT, session, inputs, capture, remove_only_owned_source_fixture,
)
from test_rf1086_source_preview_database import generate, remove_only_preview_fixture

pytestmark=pytest.mark.authority_database
MIGRATION='20260924085227_rf1086_source_review_bridge.sql'


@pytest.fixture(autouse=True)
def remove_only_bridge_fixture(admitted,backend_url,remove_only_preview_fixture):
    yield
    # Exact disposable fixture only. Runtime has no UPDATE/DELETE grant.
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute('alter table shareholder_register_filing.source_review_bridges disable trigger source_bridge_immutable')
        db.execute('alter table shareholder_register_filing.source_review_bridges no force row level security')
        db.execute('delete from shareholder_register_filing.source_review_bridges where company_id=%s',(admitted['company'],))
        db.execute('alter table shareholder_register_filing.source_review_bridges force row level security')
        db.execute('alter table shareholder_register_filing.source_review_bridges enable trigger source_bridge_immutable')
        db.execute('alter table shareholder_register_filing.filing_previews disable trigger source_review_projection_immutable')
        db.execute('alter table shareholder_register_filing.filing_previews no force row level security')
        db.execute("delete from shareholder_register_filing.filing_previews where company_id=%s and source='rf1086-full-year-v1'",(admitted['company'],))
        db.execute('alter table shareholder_register_filing.filing_previews force row level security')
        db.execute('alter table shareholder_register_filing.filing_previews enable trigger source_review_projection_immutable')


def prepare(admitted,backend_url):
    store=session(admitted,backend_url);command,context=inputs(admitted,store)
    source=capture(store,command,context)
    return store,command,context,source,generate(store,source)


async def bridge(store,preview,*,sha=None,subject=None):
    payload_sha=hashlib.sha256(rf.serialize_rf1086_source_preview(preview).encode()).hexdigest()
    async with store._transaction() as db:
        return (await (await db.execute('select shareholder_register_filing.bridge_source_preview_v1(%s::uuid,%s,%s) as id',
            (preview.preview_id.value,sha or payload_sha,subject or str(store.actor_id.subject)))).fetchone())['id']


async def records(store,preview):
    async with store._transaction() as db:
        p=await (await db.execute('select * from shareholder_register_filing.filing_previews where id=%s::uuid',(preview.preview_id.value,))).fetchone()
        b=await (await db.execute('select * from shareholder_register_filing.source_review_bridges where preview_id=%s::uuid',(preview.preview_id.value,))).fetchone()
        return p,b


def test_exact_projection_replay_preserves_source_bytes_and_uses_no_opening(admitted,backend_url):
    store,_,_,source,preview=prepare(admitted,backend_url)
    assert str(asyncio.run(bridge(store,preview)))==preview.preview_id.value
    first=asyncio.run(records(store,preview));assert asyncio.run(bridge(store,preview))
    assert asyncio.run(records(store,preview))==first
    p,b=first
    assert p['setup_id'] is None and p['source']=='rf1086-full-year-v1'
    assert p['preview']==preview.preview_text and p['hovedskjema_xml']==preview.hovedskjema_xml
    assert p['status']==preview.readiness_status
    assert p['issues']==[{'level':i.level,'code':i.code,'message':i.message} for i in preview.readiness_issues]
    expected={'source_'+hashlib.sha256(('rf1086-source-shareholder-v1:'+name).encode()).hexdigest():xml
        for name,xml in (preview.underskjema_xml or {}).items()}
    assert p['underskjema_xml']==expected
    assert str(b['source_id'])==source.source_id.value and b['source_sha256']==source.source_sha256
    assert b['payload_sha256']==hashlib.sha256(rf.serialize_rf1086_source_preview(preview).encode()).hexdigest()


def test_concurrent_replay_has_one_bridge_and_one_projection(admitted,backend_url):
    store,_,_,_,preview=prepare(admitted,backend_url)
    async def run():return await asyncio.gather(bridge(store,preview),bridge(store,preview))
    left,right=asyncio.run(run());assert left==right
    assert all(asyncio.run(records(store,preview)))


def test_corrected_source_cannot_rebridge_but_original_review_remains_readable(admitted,backend_url):
    store,command,context,source,preview=prepare(admitted,backend_url)
    asyncio.run(bridge(store,preview));before=asyncio.run(records(store,preview))
    corrected=capture(store,replace(command,supersedes_source_id=source.source_id,
        supersedes_source_sha256=source.source_sha256,correction_reason='New verified annual source'),context)
    with pytest.raises(rf.Rf1086YearSourceError,match='source_preview_stale'):asyncio.run(bridge(store,preview))
    assert asyncio.run(records(store,preview))==before
    next_preview=generate(store,corrected);assert asyncio.run(bridge(store,next_preview))


@pytest.mark.parametrize('kind',['hash','subject','outsider','revoked-owner'])
def test_bridge_rejects_wrong_digest_actor_and_membership(admitted,backend_url,kind):
    store,_,_,_,preview=prepare(admitted,backend_url)
    kwargs={}
    if kind=='hash':kwargs['sha']='f'*64
    if kind=='subject':kwargs['subject']=str(uuid4())
    if kind=='outsider':store=session(admitted,backend_url,admitted['outsider'])
    if kind=='revoked-owner':
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s",(admitted['company'],))
    with pytest.raises((rf.Rf1086YearSourceError,rf.ShareholderRegisterFilingError)):
        asyncio.run(bridge(store,preview,**kwargs))


@pytest.mark.parametrize('mutation',["update shareholder_register_filing.filing_previews set preview='changed' where id=%s",
    'delete from shareholder_register_filing.filing_previews where id=%s',
    'delete from shareholder_register_filing.source_review_bridges where preview_id=%s'])
def test_even_owner_table_writes_cannot_change_retained_projection(admitted,backend_url,mutation):
    store,_,_,_,preview=prepare(admitted,backend_url);asyncio.run(bridge(store,preview))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(store.actor_id.subject),))
        # Owner-only fixture bypasses RLS to exercise the immutable trigger.
        table='source_review_bridges' if 'source_review_bridges' in mutation else 'filing_previews'
        db.execute('alter table shareholder_register_filing.'+table+' no force row level security')
        with pytest.raises(psycopg.Error,match='rf1086_source_preview_immutable'):
            db.execute(mutation,(preview.preview_id.value,))
        db.rollback()


def test_legacy_production_cannot_insert_approval_for_source_preview(admitted,backend_url):
    store,_,_,_,preview=prepare(admitted,backend_url);asyncio.run(bridge(store,preview))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true)",(str(store.actor_id.subject),))
        with pytest.raises(psycopg.Error,match='rf1086_source_production_admission_required'):
            db.execute("""insert into shareholder_register_filing.filing_approval_snapshots
                (entitlement_id,preview_id,company_id,user_id,income_year,obligation,case_profile,
                 adapter_version,payload_hash,manifest_hash,manifest,approved_by)
                values(%s,%s,%s,%s,%s,'aksjonaerregisteroppgaven','rf1086_no_activity_v1',
                       'rf1086-production-v1',%s,%s,'{}'::jsonb,%s)""",
                (uuid4(),preview.preview_id.value,admitted['company'],admitted['owner'],int(preview.income_year),'a'*64,'b'*64,admitted['owner']))
        db.rollback()


def test_safe_rollback_retains_review_and_production_barriers_then_exact_recutover(admitted,backend_url):
    store,_,_,_,preview=prepare(admitted,backend_url);asyncio.run(bridge(store,preview))
    before=asyncio.run(records(store,preview))
    with psycopg.connect(DATABASE_URL) as db:
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==roles
    try:
        assert asyncio.run(records(store,preview))==before
        with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(bridge(store,preview))
    finally:
        with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert asyncio.run(bridge(store,preview)) and asyncio.run(records(store,preview))==before
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.bridge_source_preview_v1(uuid,text,text)','execute')",(role,)).fetchone()[0]
