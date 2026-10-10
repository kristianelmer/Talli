"""Real closed claim SQL/owners with synthetic verified claims and local original bytes.

Auth refresh is the existing explicit fixture. No provider operations, hosted
runtime, genuine data, object or independent recovery is exercised here.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json

import psycopg
import pytest

from talli_backend.application.shareholder_register_source_claim_v3 import ShareholderRegisterSourceClaimV3
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_approval_v3_database import (
    state, admitted, closed_source_role, withdrawal_fixture_role, approval_login, backend_url,
    fixture_roles, approved_release, approval_seed_access, rf_fixture_admin_access, documents_authority,
    amendment_fixture_authority, capture_login, prepare_state, review, approve, retained_rows,
    answers, DATABASE_URL, ROOT,
)
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering

pytestmark = pytest.mark.authority_database
MIGRATION = '20261010212500_rf1086_closed_source_claim_v3.sql'
CONTRACTS = ('shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)',
    'shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text)')


@pytest.fixture
def claim_access(approval_login):
    added = []
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute('select oid,proacl::text from pg_proc where oid=any(%s::regprocedure[]) order by oid', (list(CONTRACTS),)).fetchall()
        for contract in CONTRACTS:
            if not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (contract,)).fetchone()[0]:
                db.execute('set local role shareholder_register_filing_store_owner')
                db.execute('grant execute on function '+contract+' to shareholder_register_filing_executor')
                db.execute('reset role')
                added.append(contract)
    try:
        yield approval_login
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            for contract in added:
                db.execute('revoke all on function '+contract+' from shareholder_register_filing_executor')
            db.execute('reset role')
            assert db.execute('select oid,proacl::text from pg_proc where oid=any(%s::regprocedure[]) order by oid', (list(CONTRACTS),)).fetchall() == before


def prepare_claim(state):
    result = approve(state, review(state))
    state.claim_workflow = ShareholderRegisterSourceClaimV3(state.workflow._sessions,state.workflow._documents)
    retained = next(row for row in retained_rows(state) if str(row[0]) == result.record_id)
    state.claim_arguments = dict(approval_id=rf.ApprovalId(result.record_id), manifest_sha256=retained[1],
        correlation_id=state.arguments['correlation_id'])
    return state


def claim(state, **changes):
    return asyncio.run(state.claim_workflow.claim('synthetic-token', **dict(state.claim_arguments, **changes)))


def rows(state):
    with psycopg.connect(DATABASE_URL) as db:
        # The owner role is a privileged fixture observer, never runtime authority.
        db.execute('set local role shareholder_register_filing_store_owner')
        claims = state.store._verified.claims_json
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
            (str(state.store.actor_id.subject),claims,claims))
        bindings = db.execute('select * from shareholder_register_filing.source_submission_bindings where company_id=%s order by submission_id', (str(state.source.company_id),)).fetchall()
        submissions = db.execute('select * from shareholder_register_filing.production_filing_submissions where company_id=%s order by id', (str(state.source.company_id),)).fetchall()
        heads = db.execute('select * from shareholder_register_filing.submission_heads where company_id=%s order by income_year', (str(state.source.company_id),)).fetchall()
        return bindings, submissions, heads


@pytest.mark.parametrize('kind', ['cash_issue','loss_covering_reduction'])
@pytest.mark.parametrize('depth', [0,1,2])
def test_actual_v3_claim_commits_once_with_current_complete_owner_proof(admitted, closed_source_role,
        withdrawal_fixture_role, claim_access, backend_url, fixture_roles, approved_release, kind, depth, monkeypatch):
    state = prepare_claim(prepare_state(admitted,closed_source_role,withdrawal_fixture_role,claim_access,
        backend_url,kind,depth))
    close_fresh_rendering(monkeypatch)
    source = rf.serialize_rf1086_year_source_v2(state.source)
    before = retained_rows(state)
    result = claim(state)
    saved = rows(state)
    assert result.newly_claimed and all(len(value)==1 for value in saved)
    assert result.claim.approval_id == state.claim_arguments['approval_id']
    state.byte_reads.clear()
    assert claim(state) == rf.Rf1086SourceSubmissionClaimResult(result.claim,False)
    assert not state.byte_reads and rows(state)==saved and retained_rows(state)==before
    assert rf.serialize_rf1086_year_source_v2(state.source)==source


@pytest.mark.parametrize('change', ['annual','mfa','pilot','invalidated'])
def test_actual_committed_recovery_precedes_current_evidence(state, claim_access, change):
    prepare_claim(state)
    first = claim(state); saved = rows(state)
    if change == 'annual': answers(state,has_unpaid_items=True)
    elif change == 'mfa':
        claims=json.loads(state.store._verified.claims_json);claims['amr'][0]['timestamp']=1
        state.store._verified=replace(state.store._verified,claims_json=json.dumps(claims))
    else:
        with psycopg.connect(DATABASE_URL) as db:
            if change=='pilot':db.execute("update billing.production_pilot_entitlements set expires_at=clock_timestamp()-interval '1 second' where id=%s",(state.entitlement,))
            else:db.execute('update shareholder_register_filing.filing_approval_snapshots set invalidated_at=clock_timestamp() where id=%s',(first.claim.approval_id.value,))
    state.byte_reads.clear()
    assert claim(state)==rf.Rf1086SourceSubmissionClaimResult(first.claim,False)
    assert rows(state)==saved and not state.byte_reads


@pytest.mark.parametrize('change', ['annual','mfa','invalidated'])
def test_actual_missing_claim_still_requires_live_first_effect(state,claim_access,change):
    prepare_claim(state)
    if change=='annual':answers(state,has_unpaid_items=True)
    elif change=='mfa':
        claims=json.loads(state.store._verified.claims_json);claims['amr'][0]['timestamp']=1
        state.store._verified=replace(state.store._verified,claims_json=json.dumps(claims))
    else:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('update shareholder_register_filing.filing_approval_snapshots set invalidated_at=clock_timestamp() where id=%s',(state.claim_arguments['approval_id'].value,))
    # This fixture replaces production _transaction error mapping with a raw
    # psycopg transport. Pin the published SQL diagnostic, not a broad denial.
    if change=='mfa':
        with pytest.raises(psycopg.errors.RaiseException) as denied:claim(state)
        assert denied.value.sqlstate=='P0001' and denied.value.diag.message_primary=='company_access_forbidden'
    else:
        with pytest.raises(rf.Rf1086ProductionError) as denied:claim(state)
        assert denied.value.code==('basis_unavailable' if change=='annual' else 'payload_changed')
    assert rows(state)==([],[],[])


@pytest.mark.parametrize('change', ['read_only','banned'])
def test_actual_revoked_or_unavailable_original_actor_cannot_recover(state,claim_access,change):
    prepare_claim(state);claim(state)
    with psycopg.connect(DATABASE_URL) as db:
        if change=='read_only':db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",(state.item['seed']['company'],state.item['seed']['owner']))
        else:db.execute("update auth.users set banned_until='infinity' where id=%s",(state.item['seed']['owner'],))
    if change=='read_only':
        with pytest.raises(psycopg.errors.RaiseException) as denied:claim(state)
        assert denied.value.sqlstate=='P0001' and denied.value.diag.message_primary=='rf1086_source_claim_mismatch'
    else:
        with pytest.raises(rf.ShareholderRegisterFilingError) as denied:claim(state)
        assert denied.value.code==rf.ShareholderRegisterFilingErrorCode.FORBIDDEN


def test_actual_commit_during_documents_denial_recovers_exact_claim(state,claim_access):
    prepare_claim(state)
    admission=state.claim_workflow._admission.prepare_preview
    expected=None
    # Avoid recursive use of the injected preflight on the competing request.
    other=ShareholderRegisterSourceClaimV3(state.workflow._sessions,state.workflow._documents)
    async def denied(*args,**kwargs):
        nonlocal expected
        await admission(*args,**kwargs)
        expected=await other.claim('synthetic-token',**state.claim_arguments)
        raise DocumentsError.forbidden()
    state.claim_workflow._admission.prepare_preview=denied
    assert claim(state)==rf.Rf1086SourceSubmissionClaimResult(expected.claim,False)
    assert all(len(value)==1 for value in rows(state))


def test_actual_company_wait_recovers_uncommitted_competing_claim_after_mfa_expires(state,claim_access):
    prepare_claim(state)
    async def run():
        task=None
        original=state.store._verified
        claims=json.loads(original.claims_json)
        with psycopg.connect(DATABASE_URL) as db:
            claims['amr'][0]['timestamp']=int(db.execute('select extract(epoch from clock_timestamp())').fetchone()[0])-897
        state.store._verified=replace(original,claims_json=json.dumps(claims))
        try:
            async with state.workflow.admit('synthetic-token',**state.arguments) as admitted:
                first=await admitted.transaction.claim_source_submission_v3(state.claim_arguments['approval_id'],
                    state.claim_arguments['manifest_sha256'],None,state.arguments['correlation_id'])
                assert first.newly_claimed
                baseline=len(state.traces)
                task=asyncio.create_task(state.claim_workflow.claim('synthetic-token',**state.claim_arguments))
                for _ in range(150):
                    if len(state.traces)>baseline:
                        pid=state.traces[-1]['pid']
                        with psycopg.connect(DATABASE_URL) as db:
                            if db.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')",(pid,)).fetchone()[0]:break
                    await asyncio.sleep(.02)
                else:raise AssertionError('Actual competing V3 claim did not wait on company guard')
                await asyncio.sleep(3.2)
            result=await asyncio.wait_for(task,8)
            assert result==rf.Rf1086SourceSubmissionClaimResult(first.claim,False)
        finally:
            state.store._verified=original
            if task is not None and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())
    assert all(len(value)==1 for value in rows(state))


def test_closed_acl_and_retentive_populated_rollback_preserve_legacy_and_history(state,claim_access):
    prepare_claim(state);first=claim(state);saved=rows(state)
    old=('shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text)',
        'shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)')
    with psycopg.connect(DATABASE_URL) as db:
        def catalog(ids):return db.execute('select oid,prosrc,proowner,proacl::text,proconfig,prosecdef,provolatile,proparallel from pg_proc where oid=any(%s::regprocedure[]) order by oid',(list(ids),)).fetchall()
        before=catalog(old);new=db.execute('select oid,prosrc from pg_proc where oid=any(%s::regprocedure[]) order by oid',(list(CONTRACTS),)).fetchall()
        for directory in ('rollback','migrations'):
            db.execute((ROOT/'supabase'/directory/MIGRATION).read_text())
            assert catalog(old)==before
            assert db.execute('select oid,prosrc from pg_proc where oid=any(%s::regprocedure[]) order by oid',(list(CONTRACTS),)).fetchall()==new
            for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
                assert all(not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,contract)).fetchone()[0] for contract in CONTRACTS)
        # Restore exactly the temporary fixture grants for its teardown oracle.
        db.execute('set local role shareholder_register_filing_store_owner')
        for contract in CONTRACTS:db.execute('grant execute on function '+contract+' to shareholder_register_filing_executor')
    assert rows(state)==saved and claim(state)==rf.Rf1086SourceSubmissionClaimResult(first.claim,False)


@pytest.mark.parametrize('kind',['cancellation','late_application_failure'])
def test_actual_claim_write_rolls_back_when_application_fails_before_scope_exit(state,claim_access,kind):
    """Inject after actual SQL; this is not a real transport/commit failure."""
    prepare_claim(state)
    before=retained_rows(state),rf.serialize_rf1086_year_source_v2(state.source),rows(state)
    assert before[2]==([],[],[])
    failure=asyncio.CancelledError('owned cancellation after claim SQL') if kind=='cancellation' else RuntimeError('controlled application failure after claim SQL')
    recovery=state.store.source_claim_recovery_v3
    scopes=[];writes=[]
    @asynccontextmanager
    async def failing_recovery(*args):
        async with recovery(*args) as retained:
            scopes.append(retained)
            fresh=retained.fresh_admission_v3
            @asynccontextmanager
            async def failing_fresh():
                async with fresh() as transaction:
                    scopes.append(transaction)
                    write=transaction.claim_source_submission_v3
                    async def fail_after_write(*args):
                        result=await write(*args)
                        assert result.newly_claimed
                        proof=await (await transaction._connection.execute(
                            "select to_regclass('pg_temp.rf1086_year_source_governance_proofs') as proof")).fetchone()
                        assert proof['proof'] is not None
                        writes.append(result)
                        raise failure
                    transaction.claim_source_submission_v3=fail_after_write
                    yield transaction
            retained.fresh_admission_v3=failing_fresh
            yield retained
    state.store.source_claim_recovery_v3=failing_recovery
    with pytest.raises(type(failure)) as caught:claim(state)
    assert caught.value is failure and len(writes)==1
    assert len(scopes)==2 and all(not scope._active and scope._connection.closed for scope in scopes)
    assert not state.held
    assert (retained_rows(state),rf.serialize_rf1086_year_source_v2(state.source),rows(state))==before
    async def no_residue():
        async with state.store._transaction(snapshot=True) as db:
            row=await (await db.execute("select to_regclass('pg_temp.rf1086_year_source_governance_proofs') as proof")).fetchone()
            assert row['proof'] is None
    asyncio.run(no_residue())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_events where company_id=%s',
            (str(state.source.company_id),)).fetchone()[0]==0
