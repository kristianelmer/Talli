"""Real restricted-role full-year approval; every full-year send stays closed."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from talli_backend.modules.shareholder_register_filing import public as rf
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access, insert, SIGNOFFS
from test_rf1086_year_source_database import DATABASE_URL, ROOT, capture, remove_only_owned_source_fixture
from test_rf1086_source_preview_database import remove_only_preview_fixture
from test_rf1086_source_review_bridge_database import prepare, bridge, remove_only_bridge_fixture

pytestmark=pytest.mark.authority_database
MIGRATION='20260924091015_rf1086_source_approval_foundation.sql'


@pytest.fixture
def approval_fixture(admitted,backend_url,remove_only_bridge_fixture):
    store,command,context,source,preview=prepare(admitted,backend_url)
    claims=json.loads(store._verified.claims_json)
    claims['amr'][0]['timestamp']=int(claims['amr'][0]['timestamp'])
    store._verified=replace(store._verified,claims_json=json.dumps(claims))
    asyncio.run(bridge(store,preview))
    request,entitlement=uuid4(),uuid4(); external='source-approval-'+str(request)
    with psycopg.connect(DATABASE_URL) as db:
        now=db.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        signoffs=db.execute('select to_jsonb(s) from public.launch_signoffs s where key=any(%s)',(list(SIGNOFFS),)).fetchall()
        insert(db,'authority_connections.system_user_requests',dict(id=request,company_id=admitted['company'],
            initiating_owner_user_id=admitted['owner'],external_ref=external,status='accepted',preflight_verified_at=now))
        insert(db,'billing.production_pilot_entitlements',dict(id=entitlement,company_id=admitted['company'],user_id=admitted['owner'],
            income_year=2026,obligation='aksjonaerregisteroppgaven',case_profile='rf1086_full_year_v1',status='active',billing_exempt=True,
            system_user_request_id=request,system_user_external_reference=external,starts_at=now,expires_at=now+timedelta(days=30),
            evidence_reference='local-full-year-approval',approved_by=admitted['owner']))
        insert(db,'shareholder_register_filing.authority_permissions',dict(company_id=admitted['company'],obligation='aksjonaerregisteroppgaven',
            submitter_user_id=admitted['owner'],confirmed_by=admitted['owner'],production_enabled=True))
        insert(db,'public.filing_readiness_snapshots',dict(company_id=admitted['company'],income_year=2026,obligation='aksjonaerregisteroppgaven',
            status='ready',ready=True,created_by=admitted['owner']))
        for key in SIGNOFFS:
            db.execute("insert into public.launch_signoffs(key,status,reviewer,reviewed_at,evidence_link,decision,recorded_by) "
                "values(%s,'approved','Local fixture',%s,'local-full-year-approval','approved',%s) on conflict(key) do update "
                "set status=excluded.status,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,evidence_link=excluded.evidence_link,"
                "decision=excluded.decision,recorded_by=excluded.recorded_by",(key,now,admitted['owner']))
    fixture=dict(seed=admitted,store=store,command=command,context=context,source=source,preview=preview,request=request,entitlement=entitlement)
    try:yield fixture
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('alter table shareholder_register_filing.source_approval_bindings disable trigger source_approval_binding_immutable')
            db.execute('alter table shareholder_register_filing.source_approval_bindings no force row level security')
            db.execute('delete from shareholder_register_filing.source_approval_bindings where company_id=%s',(admitted['company'],))
            db.execute('alter table shareholder_register_filing.source_approval_bindings force row level security')
            db.execute('alter table shareholder_register_filing.source_approval_bindings enable trigger source_approval_binding_immutable')
            db.execute('reset role')
            db.execute('delete from shareholder_register_filing.production_feedback_artifacts where company_id=%s',(admitted['company'],))
            db.execute('delete from shareholder_register_filing.production_filing_submissions where company_id=%s',(admitted['company'],))
            db.execute('delete from shareholder_register_filing.filing_approval_snapshots where company_id=%s',(admitted['company'],))
            db.execute("delete from shareholder_register_filing.filing_previews where company_id=%s and source<>'rf1086-full-year-v1'",(admitted['company'],))
            db.execute('delete from shareholder_register_filing.authority_permissions where company_id=%s',(admitted['company'],))
            db.execute('delete from billing.production_pilot_entitlements where id=%s',(entitlement,))
            db.execute('delete from authority_connections.system_user_requests where id=%s',(request,))
            db.execute('delete from public.filing_readiness_snapshots where company_id=%s',(admitted['company'],))
            db.execute('delete from public.launch_signoffs where key=any(%s)',(list(SIGNOFFS),))
            for row in signoffs:db.execute('insert into public.launch_signoffs select * from jsonb_populate_record(null::public.launch_signoffs,%s::jsonb)',(json.dumps(row[0]),))


async def lock(db,f):
    await db.execute('select shareholder_register_filing.lock_year_source_v1(%s,%s)',(f['seed']['company'],2026))


async def context(db,f):
    return (await (await db.execute('select shareholder_register_filing.read_source_approval_context_v1(%s,%s,%s) as result',
        (f['preview'].preview_id.value,f['entitlement'],str(f['store'].actor_id.subject)))).fetchone())['result']


def manifest(f,review):
    return rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        source=f['source'],preview=f['preview'],actor_id=f['store'].actor_id,entitlement_id=str(f['entitlement']),
        review_sha256=review['reviewSha256'],acknowledged_warning_codes=tuple(review['warningCodes'])))


def canonical(value):
    # The domain returns immutable mappings; its canonical JSON is reconstructed
    # with ordinary containers without changing any bytes, order, or numbers.
    from collections.abc import Mapping
    def plain(v):
        if isinstance(v,Mapping):return {k:plain(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [plain(x) for x in v]
        return v
    return json.dumps(plain(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


async def append(db,f,review,*,change=None,sha=None):
    body=json.loads(canonical(manifest(f,review).manifest))
    if change:change(body)
    text=canonical(body)
    return await (await db.execute('select * from shareholder_register_filing.append_source_approval_v1(%s,%s,%s,%s,%s,%s)',
        (f['preview'].preview_id.value,f['entitlement'],text,sha or hashlib.sha256(text.encode()).hexdigest(),
         review['reviewSha256'],str(f['store'].actor_id.subject)))).fetchone()


def test_exact_approval_replay_retains_original_manifest_review_and_source_bytes(approval_fixture):
    f=approval_fixture
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);review=await context(db,f)
            assert set(review)=={'companyId','incomeYear','previewId','sourceId','sourceSha256','entitlementId','reviewSha256','warningCodes','blockers'}
            assert review['blockers']==[]
            first=await append(db,f,review);assert await append(db,f,review)==first
            binding=await (await db.execute('select * from shareholder_register_filing.source_approval_bindings where approval_id=%s',(first['id'],))).fetchone()
            assert hashlib.sha256(binding['manifest_text'].encode()).hexdigest()==first['manifest_hash']
            assert hashlib.sha256(binding['review_text'].encode()).hexdigest()==review['reviewSha256']
            assert json.loads(binding['manifest_text'])==first['manifest']
            retained=json.loads(binding['review_text'])
            assert retained['scope']['previewId']==f['preview'].preview_id.value
            assert retained['permission']['production_enabled'] is True
            assert first['payload_hash']==hashlib.sha256(rf.serialize_rf1086_source_preview(f['preview']).encode()).hexdigest()
            return first['id']
    assert asyncio.run(run())


@pytest.mark.parametrize('guard',['none','company-only','repeatable-read'])
def test_context_requires_same_connection_company_and_year_guards(approval_fixture,guard):
    f=approval_fixture
    async def run():
        async with f['store']._transaction(snapshot=guard=='repeatable-read') as db:
            if guard=='company-only':await db.execute('select public.company_archive_lock_company_v1(%s)',(f['seed']['company'],))
            if guard=='repeatable-read':
                await db.execute('select pg_advisory_xact_lock(hashtextextended(%s,157)),pg_advisory_xact_lock(hashtextextended(%s,0))',
                    (str(f['seed']['company']),f"rf1086:year-source:{f['seed']['company']}:2026"))
            await context(db,f)
    with pytest.raises(Exception,match='source_approval_guard_required|basis_unavailable'):asyncio.run(run())


@pytest.mark.parametrize('field',['permission','readiness','technical','hard-comment','acknowledged-hard-comment','override'])
def test_review_blockers_are_visible_and_append_is_closed(approval_fixture,field):
    f=approval_fixture
    with psycopg.connect(DATABASE_URL) as db:
        if field=='permission':db.execute('update shareholder_register_filing.authority_permissions set production_enabled=false where company_id=%s',(f['seed']['company'],))
        elif field=='readiness':db.execute('update public.filing_readiness_snapshots set ready=false where company_id=%s',(f['seed']['company'],))
        elif field=='technical':db.execute("update public.launch_signoffs set status='pending' where key='rf1086_authority'")
        else:
            # Exercise the actual RF review APIs and their company guard.
            async def mutate():
                async with f['store']._transaction() as conn:
                    if field in ('hard-comment','acknowledged-hard-comment'):await conn.execute("select shareholder_register_filing.add_review_comment_v1(%s,'hard_block','Review needed')",(f['preview'].preview_id.value,))
                    else:await conn.execute("select shareholder_register_filing.record_override_v1(%s,'preview','old','new','Reason','block',true)",(f['preview'].preview_id.value,))
            asyncio.run(mutate())
            if field=='acknowledged-hard-comment':
                db.execute('set local role shareholder_register_filing_store_owner')
                db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",(str(f['store'].actor_id.subject),f['store']._verified.claims_json))
                db.execute("update shareholder_register_filing.filing_review_comments set acknowledged_by=%s,acknowledged_at=clock_timestamp() where preview_id=%s",(f['seed']['owner'],f['preview'].preview_id.value))
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);review=await context(db,f);assert review['blockers']
            await append(db,f,review)
    with pytest.raises(Exception,match='source_approval_blocked|basis_unavailable'):asyncio.run(run())


@pytest.mark.parametrize('change',[lambda m:m.update(extra='unknown'),lambda m:m['source'].update(sha256='f'*64),
    lambda m:m['review'].update(acknowledgedWarningCodes=['not-in-preview']),lambda m:m['documentHashes'][0].update(sha256='f'*64),
    lambda m:m.update(userId=str(uuid4())),lambda m:m.update(caseProfile='rf1086_no_activity_v1')])
def test_manifest_must_match_every_stored_source_and_review_field(approval_fixture,change):
    f=approval_fixture
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);await append(db,f,await context(db,f),change=change)
    with pytest.raises(Exception,match='source_approval_manifest_invalid|basis_unavailable'):asyncio.run(run())


def test_changed_review_requires_new_digest_and_supersedes_prior_approval(approval_fixture):
    f=approval_fixture
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);old=await context(db,f);first=await append(db,f,old)
        async with f['store']._transaction() as db:
            await db.execute("select shareholder_register_filing.add_review_comment_v1(%s,'advisory','New review note')",(f['preview'].preview_id.value,))
        with pytest.raises(Exception,match='source_review_changed|payload_changed'):
            async with f['store']._transaction() as db:
                await lock(db,f);await append(db,f,old)
        async with f['store']._transaction() as db:
            await lock(db,f);new=await context(db,f);assert new['reviewSha256']!=old['reviewSha256']
            second=await append(db,f,new);assert second['id']!=first['id']
            prior=await (await db.execute('select invalidated_at,invalidation_reason from shareholder_register_filing.filing_approval_snapshots where id=%s',(first['id'],))).fetchone()
            assert prior['invalidated_at'] and prior['invalidation_reason']=='superseded_by_new_approval'
    asyncio.run(run())


def test_source_correction_invalidates_old_preview_admission(approval_fixture):
    f=approval_fixture
    capture(f['store'],replace(f['command'],supersedes_source_id=f['source'].source_id,
        supersedes_source_sha256=f['source'].source_sha256,correction_reason='Corrected source'),f['context'])
    async def run():
        async with f['store']._transaction() as db:await lock(db,f);await context(db,f)
    with pytest.raises(Exception,match='source_preview_stale|payload_changed'):asyncio.run(run())


def test_full_approval_does_not_enable_legacy_approve_or_send(approval_fixture):
    f=approval_fixture
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);approval=await append(db,f,await context(db,f))
        for command,args in [
            ('select shareholder_register_filing.approve_production_filing(%s,%s,%s,%s,%s)',
             (f['preview'].preview_id.value,f['entitlement'],Jsonb({}),'a'*64,'rf1086-production-v1')),
            ('select shareholder_register_filing.begin_production_filing(%s)',(approval['id'],))]:
            with pytest.raises(Exception,match='source_production_admission_required|basis_unavailable'):
                async with f['store']._transaction() as db:await db.execute(command,args)
    asyncio.run(run())


def test_private_binding_and_helpers_have_no_runtime_write_or_browser_access(approval_fixture):
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
            assert not db.execute("select has_table_privilege(%s,'shareholder_register_filing.source_approval_bindings','INSERT,UPDATE,DELETE')",(role,)).fetchone()[0]
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.source_approval_context_internal_v1(uuid,uuid,text)','execute')",(role,)).fetchone()[0]
        for role in ('anon','authenticated','service_role'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text)','execute')",(role,)).fetchone()[0]


def test_rollback_preserves_retained_approval_and_replay_restores_only_authorized_command(approval_fixture):
    f=approval_fixture
    async def approve():
        async with f['store']._transaction() as db:await lock(db,f);return await append(db,f,await context(db,f))
    first=asyncio.run(approve())
    with psycopg.connect(DATABASE_URL) as db:
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
    try:
        with pytest.raises(Exception):asyncio.run(approve())
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==roles
    assert asyncio.run(approve())==first
    # Earlier successor rehearsals validate80249's exact outer guard prefix.
    # Source approval inserts its own rejection after that prefix, so replaying
    # the real wrapper block followed by both successors must preserve identity.
    guard=(ROOT/'supabase/migrations/20260924080249_documents_rf_consequential_company_guards.sql').read_text()
    block=guard[guard.index('do $wrap$'):guard.index('end; $wrap$;')+len('end; $wrap$;')]
    with psycopg.connect(DATABASE_URL) as db:
        identity=db.execute("select oid,proowner,proacl::text,proconfig,prosrc from pg_proc where oid='shareholder_register_filing.approve_production_filing(uuid,uuid,jsonb,text,text)'::regprocedure").fetchone()
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(block)
            db.execute((ROOT/'supabase/migrations/20260924085227_rf1086_source_review_bridge.sql').read_text())
    finally:
        with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute("select oid,proowner,proacl::text,proconfig,prosrc from pg_proc where oid='shareholder_register_filing.approve_production_filing(uuid,uuid,jsonb,text,text)'::regprocedure").fetchone()==identity
    assert asyncio.run(approve())==first


def test_blocked_company_admission_rereads_current_owner(approval_fixture):
    from test_rf1086_source_company_guard_database import waiting
    f=approval_fixture
    async def run():
        ready=asyncio.get_running_loop().create_future()
        async def writer():
            async with f['store']._transaction() as db:
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                await lock(db,f);return await context(db,f)
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(f['seed']['company'],))
            task=asyncio.create_task(writer());await waiting(await ready)
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s",(f['seed']['company'],))
        with pytest.raises(Exception,match='(?i)forbidden|owner|not_found'):await task
    asyncio.run(run())


def test_authority_lock_precedes_billing_and_rechecks_preflight_after_wait(approval_fixture):
    f=approval_fixture
    async def run():
        ready=asyncio.get_running_loop().create_future()
        async def writer():
            async with f['store']._transaction() as db:
                await lock(db,f)
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                return await context(db,f)
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select id from authority_connections.system_user_requests where id=%s for update',(f['request'],))
            task=asyncio.create_task(writer());pid=await ready
            for _ in range(100):
                with psycopg.connect(DATABASE_URL) as observer:
                    waiting=observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event_type='Lock')",(pid,)).fetchone()[0]
                if waiting:break
                await asyncio.sleep(.01)
            else:raise AssertionError('Context did not wait on exact Authority request')
            with psycopg.connect(DATABASE_URL) as observer:
                # NOWAIT proves the later Billing row was not acquired first.
                observer.execute('select id from billing.production_pilot_entitlements where id=%s for update nowait',(f['entitlement'],))
            blocker.execute('update authority_connections.system_user_requests set preflight_verified_at=null where id=%s',(f['request'],))
        with pytest.raises(Exception,match='(?i)pilot_entitlement_required|basis_unavailable|company_year_not_admitted'):await task
    asyncio.run(run())


@pytest.mark.parametrize('state',['valid','unconfirmed','wrong-hash','wrong-scope'])
def test_correction_predecessor_requires_exact_terminal_retained_journal(approval_fixture,state):
    f=approval_fixture;preview,approval,submission=[uuid4() for _ in range(3)];digest='d'*64
    with psycopg.connect(DATABASE_URL) as db:
        insert(db,'shareholder_register_filing.filing_previews',dict(id=preview,company_id=f['seed']['company'],income_year=2026,
            filing='aksjonaerregisteroppgaven',status='ready',preview='Historical fixture',created_by=f['seed']['owner']))
        insert(db,'shareholder_register_filing.filing_approval_snapshots',dict(id=approval,entitlement_id=f['entitlement'],preview_id=preview,
            company_id=f['seed']['company'],user_id=f['seed']['owner'],income_year=2026,obligation='aksjonaerregisteroppgaven',
            case_profile='rf1086_no_activity_v1',adapter_version='rf1086-production-v1',payload_hash='a'*64,manifest_hash='b'*64,
            manifest=Jsonb({}),approved_by=f['seed']['owner']))
        insert(db,'shareholder_register_filing.production_filing_submissions',dict(id=submission,approval_id=approval,entitlement_id=f['entitlement'],
            company_id=f['seed']['company'],user_id=f['seed']['owner'],income_year=2025 if state=='wrong-scope' else 2026,
            obligation='aksjonaerregisteroppgaven',case_profile='rf1086_no_activity_v1',adapter_version='rf1086-production-v1',payload_hash='a'*64,
            environment='production',status='accepted',feedback_state='accepted',feedback_artifact_count=1,submitted_by=f['seed']['owner']))
        insert(db,'shareholder_register_filing.production_feedback_artifacts',dict(company_id=f['seed']['company'],submission_id=submission,
            document_id=f['command'].documents[0].document_id,authority_reference='local-terminal-fixture',content_type='application/pdf',
            byte_length=100,sha256=digest,classification='accepted'))
        if state!='unconfirmed':
            insert(db,'shareholder_register_filing.production_filing_events',dict(submission_id=submission,company_id=f['seed']['company'],
                income_year=2025 if state=='wrong-scope' else 2026,operation_name='reconciliation:fixture',operation_state='succeeded',attempt=1,
                resulting_status='accepted',artifact_hashes=[digest]))
    def change(m):m['predecessor']={'submissionId':str(submission),'manifestSha256':'f'*64 if state=='wrong-hash' else 'b'*64,'reason':'Corrected source'}
    async def run():
        async with f['store']._transaction() as db:
            await lock(db,f);return await append(db,f,await context(db,f),change=change)
    if state=='valid':assert asyncio.run(run())['manifest']['predecessor']['submissionId']==str(submission)
    else:
        with pytest.raises(Exception,match='source_predecessor_mismatch|payload_changed'):asyncio.run(run())


@pytest.mark.parametrize('expired',['pilot','mfa'])
def test_authority_wait_uses_wall_clock_for_expiry(approval_fixture,expired):
    f=approval_fixture
    async def run():
        ready=asyncio.get_running_loop().create_future()
        async def writer():
            async with f['store']._transaction() as db:
                await db.execute("set local lock_timeout='3s'")
                await lock(db,f)
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                return await context(db,f)
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select id from authority_connections.system_user_requests where id=%s for update',(f['request'],))
            if expired=='pilot':
                blocker.execute("update billing.production_pilot_entitlements set expires_at=clock_timestamp()+interval '0.3 seconds' where id=%s",(f['entitlement'],))
            else:
                claims=json.loads(f['store']._verified.claims_json)
                claims['amr'][0]['timestamp']=int(blocker.execute('select extract(epoch from clock_timestamp())').fetchone()[0])-898
                f['store']._verified=replace(f['store']._verified,claims_json=json.dumps(claims))
            task=asyncio.create_task(writer());pid=await ready
            for _ in range(100):
                with psycopg.connect(DATABASE_URL) as observer:
                    blocked=observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event_type='Lock')",(pid,)).fetchone()[0]
                if blocked:break
                await asyncio.sleep(.01)
            else:raise AssertionError('Context did not reach Authority lock wait')
            await asyncio.sleep(.4 if expired=='pilot' else 2.1)
        with pytest.raises(Exception,match='(?i)pilot_entitlement_required|step_up_required|basis_unavailable|company_year_not_admitted'):await task
    asyncio.run(run())
