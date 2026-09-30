"""Current V2 approval/claim persistence uses guarded real annual owner reads."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from talli_backend.application.shareholder_register_annual_readiness import read_annual_readiness
from talli_backend.application.shareholder_register_source_admission import AdmittedRf1086Source
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_approval_database import approval_fixture, admitted, backend_url, rf_fixture_admin_access
from test_rf1086_source_review_bridge_database import remove_only_bridge_fixture
from test_rf1086_source_preview_database import remove_only_preview_fixture
from test_rf1086_year_source_database import remove_only_owned_source_fixture, DATABASE_URL, ROOT
from test_rf_annual_opening_admission_database import add_opening, remove_only_annual_opening_fixture
from test_rf_annual_ledger_admission_database import ledger_fixture_insert_access, add_lock
from test_annual_interview_company_guard_database import fixture_roles, seed, bind

pytestmark = pytest.mark.authority_database
MIGRATION = '20260929173935_rf1086_annual_approval_binding.sql'
CORRELATION = CorrelationId('annual-approval-database')


def test_historical_source_fixture_restores_current_override_receiver():
    from test_authority_connections_database_runtime import rf193_consequential_topology
    from test_rf1086_source_approval_database import historical_source_command_revision

    def state(db):
        receiver = db.execute("select pg_get_functiondef('backend_system.rf1086_other_overrides_ready_v1(uuid,integer)'::regprocedure)").fetchone()[0]
        roles = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        return receiver, roles, rf193_consequential_topology(db)

    with psycopg.connect(DATABASE_URL) as db:
        before = state(db)
    assert 'annual_accounts_filing.has_blocking_override_v1' in before[0]
    historical = historical_source_command_revision.__wrapped__()
    try:
        next(historical)
        historical.close()
        with psycopg.connect(DATABASE_URL) as db:
            assert state(db) == before, 'Historical fixture replaced the current RF override receiver'
    finally:
        historical.close()
        # A failing regression must not contaminate the remaining database lane.
        with psycopg.connect(DATABASE_URL) as db:
            for migration in before[2]:
                db.execute((ROOT/'supabase/migrations'/migration).read_text())


@pytest.fixture
def annual_fixture(approval_fixture):
    f = approval_fixture
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        db.execute((ROOT/'supabase/migrations/20260930083000_rf1086_override_receiver_cutover.sql').read_text())
        opening, _ = add_opening(db, f['seed'])
        # The old browser-written prerequisite is deliberately false.
        db.execute('update public.filing_readiness_snapshots set ready=false where company_id=%s', (f['seed']['company'],))
    with ledger_fixture_insert_access(DATABASE_URL):
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) values(%s,%s,2026,%s,%s,clock_timestamp())',
                       (opening, f['seed']['company'], Decimal('123.45'), f['seed']['owner']))
            add_lock(db, f['seed'])
    f['interview'] = seed(f['seed'])
    set_answers(f)
    try:
        yield f
    finally:
        # This deliberately unsupported non-RF row tests the retained override
        # gate. Do not leak it into the later global Tax expansion quarantine.
        if f.get('synthetic_non_rf_override') is not None:
            with psycopg.connect(DATABASE_URL) as db:
                db.execute('delete from public.filing_overrides where id=%s and company_id=%s',
                    (f['synthetic_non_rf_override'], f['seed']['company']))


def set_answers(f, **changes):
    answers = {'bank_balance_confirmed': True, 'has_unpaid_items': False, 'authority_to_submit_confirmed': True} | changes
    with psycopg.connect(DATABASE_URL) as db:
        bind(db, f['seed'])
        db.execute('update public.annual_data set answers=%s where id=%s', (Jsonb(answers), f['interview']))


def query(f):
    return rf.Rf1086SourceQuery(f['source'].company_id, f['source'].income_year, f['store'].actor_id)


async def proof(f, scope):
    return await read_annual_readiness(AdmittedRf1086Source(f['source'], f['preview'], (), scope), CORRELATION)


async def approval(f, scope):
    annual = await proof(f, scope)
    review = await scope.read_source_approval_context(f['preview'].preview_id, str(f['entitlement']), annual)
    assert review.can_approve, review.blockers
    manifest = rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        f['source'], f['preview'], scope.actor_id, str(f['entitlement']), review.review_sha256,
        review.warning_codes, annual_readiness=annual))
    result = await scope.append_source_approval(f['preview'], str(f['entitlement']), manifest, review.review_sha256)
    return result, manifest, annual


def test_v2_approval_ignores_stored_ready_binds_annual_facts_and_claims_exactly_once(annual_fixture):
    f = annual_fixture
    async def run():
        async with f['store'].source_admission(query(f)) as scope:
            result, manifest, annual = await approval(f, scope)
            assert annual.readiness_status == 'ready'
            assert manifest.manifest['schemaVersion'] == 'production-source-approval-v2'
            retained = await scope.read_source_claim_approval(rf.ApprovalId(result.record_id))
            assert retained.manifest_text == rf.serialize_rf1086_source_approval_manifest(manifest)
            row = await (await scope._connection.execute('select review_text from shareholder_register_filing.source_approval_bindings where approval_id=%s', (result.record_id,))).fetchone()
            review = json.loads(row['review_text'])
            assert 'storedReleaseReady' not in review
            assert review['otherOverridesReady'] is True
            assert review['annualReadiness'] == dict(manifest.manifest['annualReadiness'])
            claim = await scope.claim_source_submission(rf.ApprovalId(result.record_id), manifest.manifest_sha256, None, annual)
            replay = await scope.claim_source_submission(rf.ApprovalId(result.record_id), manifest.manifest_sha256, None, annual)
            assert claim.newly_claimed and not replay.newly_claimed and claim.claim == replay.claim
            return result, manifest, claim.claim
    result, manifest, claim = asyncio.run(run())
    set_answers(f, has_unpaid_items=True)
    async def recover():
        return await f['store'].read_source_submission_claim(rf.ApprovalId(result.record_id), manifest.manifest_sha256, None)
    assert asyncio.run(recover()) == claim
    archive_query = rf.Rf1086ArchiveQuery(f['source'].company_id,f['source'].income_year,f['store'].actor_id)
    archive = asyncio.run(rf.create_rf1086_preparation_service(f['store']).archive_source(archive_query))
    assert archive.approvals[0].manifest['schemaVersion'] == 'production-source-approval-v2'
    assert archive.source_submission_claims == (claim,)
    encoded = rf.serialize_rf1086_archive(archive, query=archive_query)
    assert rf.parse_rf1086_archive(encoded, query=archive_query) == archive


@pytest.mark.parametrize('change', ['blocked', 'metadata', 'warning'])
def test_current_annual_change_requires_a_new_approval_before_first_claim(annual_fixture, change):
    f = annual_fixture
    async def approve():
        async with f['store'].source_admission(query(f)) as scope:
            return await approval(f, scope)
    result, manifest, old = asyncio.run(approve())
    if change == 'blocked': set_answers(f, has_unpaid_items=True)
    elif change == 'warning': set_answers(f, bank_balance_confirmed=False)
    else:
        # Same booleans and same filing XML; source metadata is still evidence.
        with psycopg.connect(DATABASE_URL) as db:
            bind(db, f['seed'])
            db.execute("update public.annual_data set updated_at=updated_at+interval '1 second' where id=%s", (f['interview'],))
    async def claim():
        async with f['store'].source_admission(query(f)) as scope:
            annual = await proof(f, scope)
            assert annual.proof_sha256 != old.proof_sha256
            await scope.claim_source_submission(rf.ApprovalId(result.record_id), manifest.manifest_sha256, None, annual)
    with pytest.raises((rf.Rf1086ProductionError, rf.ShareholderRegisterFilingError)): asyncio.run(claim())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_submissions where company_id=%s', (f['seed']['company'],)).fetchone()[0] == 0


@pytest.mark.parametrize('field', ['annual', 'permission', 'technical', 'other-override'])
def test_remaining_release_blocks_cannot_be_replaced_by_a_ready_proof(annual_fixture, field):
    f = annual_fixture
    if field == 'annual': set_answers(f, has_unpaid_items=True)
    with psycopg.connect(DATABASE_URL) as db:
        if field == 'permission': db.execute('update shareholder_register_filing.authority_permissions set production_enabled=false where company_id=%s', (f['seed']['company'],))
        if field == 'technical': db.execute("update public.launch_signoffs set status='pending' where key='rf1086_authority'")
        if field == 'other-override':
            f['synthetic_non_rf_override'] = db.execute("insert into public.filing_overrides(company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,created_by,owner_confirmed_by,owner_confirmed_at) values(%s,2026,'other','check','a','b','Synthetic block','block',%s,%s,clock_timestamp()) returning id", (f['seed']['company'], f['seed']['owner'], f['seed']['owner'])).fetchone()[0]
    async def check():
        async with f['store'].source_admission(query(f)) as scope:
            annual = await proof(f, scope)
            review = await scope.read_source_approval_context(f['preview'].preview_id, str(f['entitlement']), annual)
            assert review.blockers and not review.can_approve
            return review
    assert asyncio.run(check())


def test_current_grants_close_v1_and_browser_bypasses(annual_fixture):
    with psycopg.connect(DATABASE_URL) as db:
        old = ['read_source_approval_context_v1(uuid,uuid,text)', 'append_source_approval_v1(uuid,uuid,text,text,text,text)',
               'claim_source_submission_v1(uuid,text,uuid,text)']
        new = ['read_source_approval_context_v2(uuid,uuid,text,text)', 'append_source_approval_v2(uuid,uuid,text,text,text,text)',
               'claim_source_submission_v2(uuid,text,uuid,text,text)']
        for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
            for signature in old + ([] if role == 'shareholder_register_filing_executor' else new):
                assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, 'shareholder_register_filing.'+signature)).fetchone()[0]
        for signature in new:
            assert db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', ('shareholder_register_filing_executor', 'shareholder_register_filing.'+signature)).fetchone()[0]


def test_warning_commitment_changes_review_and_requires_exact_manifest_acknowledgement(annual_fixture):
    f = annual_fixture
    async def review():
        async with f['store'].source_admission(query(f)) as scope:
            annual = await proof(f, scope)
            return await scope.read_source_approval_context(f['preview'].preview_id,str(f['entitlement']),annual)
    before = asyncio.run(review())
    set_answers(f, bank_balance_confirmed=False)
    after = asyncio.run(review())
    assert after.can_approve and after.warning_codes == ('bank_balance_not_confirmed',)
    assert after.review_sha256 != before.review_sha256
    async def run():
        async with f['store'].source_admission(query(f)) as scope:
            result, manifest, annual = await approval(f, scope)
            assert manifest.manifest['review']['acknowledgedWarningCodes'] == after.warning_codes
            return result
    assert asyncio.run(run())


@pytest.mark.parametrize('field', ['subject', 'company', 'year', 'source', 'preview', 'payload', 'version', 'missing'])
def test_sql_binding_rejects_wrong_scope_identity_or_incomplete_proof(annual_fixture, field):
    f = annual_fixture
    async def run():
        async with f['store'].source_admission(query(f)) as scope:
            annual = await proof(f, scope)
            text = rf.serialize_rf1086_annual_readiness(annual,f['source'],f['preview'])
            raw = json.loads(text)
            evidence = raw['proof']['fields']['source']['fields']['evidence']['fields']
            if field == 'company': evidence['company_id']['fields']['value'] = str(uuid4())
            if field == 'year': evidence['income_year']['fields']['value'] = 2025
            if field == 'source': evidence['source_sha256'] = 'f'*64
            if field == 'preview': evidence['preview_id']['fields']['value'] = str(uuid4())
            if field == 'payload': evidence['preview_payload_sha256'] = 'f'*64
            if field == 'version': raw['codec'] = 'unknown'
            if field == 'missing': del raw['proof']['fields']['not_evaluated']
            text = json.dumps(raw,sort_keys=True,separators=(',',':'))
            subject = str(uuid4()) if field == 'subject' else str(scope.actor_id.subject)
            await scope._connection.execute('select shareholder_register_filing.read_source_approval_context_v2(%s,%s,%s,%s)',
                (f['preview'].preview_id.value,f['entitlement'],text,subject))
    with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086ProductionError)): asyncio.run(run())


def test_rollback_retains_history_closes_new_effects_and_replay_restores_exact_authority(annual_fixture):
    f = annual_fixture
    async def approve():
        async with f['store'].source_admission(query(f)) as scope:
            return await approval(f, scope)
    result, manifest, annual = asyncio.run(approve())
    def state(db):
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        schema=db.execute("select nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','shareholder_register_filing') order by nspname").fetchall()
        return roles,schema
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        before=state(db)
        try:
            for _ in range(2):
                db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                assert state(db)==before
                with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(approve())
                # Retained approvals are readable while new effects are suspended.
                retained=asyncio.run(f['store'].read_source_claim_approval(rf.ApprovalId(result.record_id)))
                assert retained.manifest_text==rf.serialize_rf1086_source_approval_manifest(manifest)
                db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
                db.execute((ROOT/'supabase/migrations/20260930083000_rf1086_override_receiver_cutover.sql').read_text())
                assert state(db)==before
                assert asyncio.run(approve()) == (result,manifest,annual)
        finally:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            db.execute((ROOT/'supabase/migrations/20260930083000_rf1086_override_receiver_cutover.sql').read_text())


@pytest.mark.parametrize('revoke_owner', [False, True])
def test_first_claim_wait_observes_committed_annual_change_or_revoked_owner(annual_fixture, revoke_owner):
    from contextlib import asynccontextmanager
    from test_rf1086_source_company_guard_database import waiting
    f = annual_fixture
    async def approve():
        async with f['store'].source_admission(query(f)) as scope:
            return await approval(f, scope)
    result, manifest, old = asyncio.run(approve())
    async def run():
        ready = asyncio.get_running_loop().create_future()
        original = f['store']._transaction
        @asynccontextmanager
        async def observed(*args, **kwargs):
            async with original(*args, **kwargs) as db:
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield db
        f['store']._transaction = observed
        async def claim():
            async with f['store'].source_admission(query(f)) as scope:
                annual = await proof(f, scope)
                assert annual.proof_sha256 != old.proof_sha256
                return await scope.claim_source_submission(rf.ApprovalId(result.record_id),manifest.manifest_sha256,None,annual)
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (f['seed']['company'],))
                task = asyncio.create_task(claim())
                await waiting(await asyncio.wait_for(ready, 3))
                if revoke_owner:
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (f['seed']['company'],f['seed']['owner']))
                else:
                    bind(blocker,f['seed'])
                    blocker.execute("update public.annual_data set updated_at=updated_at+interval '1 second' where id=%s", (f['interview'],))
            with pytest.raises((rf.ShareholderRegisterFilingError,rf.Rf1086ProductionError)):
                await asyncio.wait_for(task, 3)
        finally:
            if task is not None and not task.done(): task.cancel()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            f['store']._transaction = original
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_submissions where company_id=%s', (f['seed']['company'],)).fetchone()[0] == 0
