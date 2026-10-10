"""Closed retained approval on real restricted owner schemas.

Verified claims and Auth-state refresh are explicit fixtures. SQL authorization,
annual owners, Documents/Governance proof, locks and writes are real. Original
object bytes come from local retained fixture storage, not independent recovery.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
import pytest

from talli_backend.application.shareholder_register_source_approval_v3 import ShareholderRegisterSourceApprovalV3
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_year_source_v2_database_fixture import (
    admitted, amendment_fixture_authority, closed_source_role, withdrawal_fixture_role,
    withdrawal, amend, DATABASE_URL, ROOT,
)
from test_rf1086_guarded_source_capture_v2_database import capture_login, complete_inputs, restricted_capture_session, GOV_READER
from test_rf1086_source_admission_v2_database import fixture, monitor_guard
from test_documents_historical_original_integrity_database import backend_url, documents_authority
from test_rf1086_database_runtime import rf_fixture_admin_access, SIGNOFFS, insert
from test_rf_annual_opening_admission_database import add_opening
from test_rf_annual_ledger_admission_database import ledger_fixture_insert_access, add_lock
from test_annual_interview_company_guard_database import fixture_roles, seed, bind
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering


pytestmark = pytest.mark.authority_database
MIGRATION = '20261010150223_rf1086_closed_retained_approval_v3.sql'
READ = 'shareholder_register_filing.read_source_approval_context_v3(uuid,uuid,text,text)'
APPEND = 'shareholder_register_filing.append_source_approval_v3(uuid,uuid,text,text,text,text)'
CONTRACTS = (
    'shareholder_register_filing.assert_retained_annual_readiness_v2_shape_internal_v1(text)',
    'shareholder_register_filing.source_annual_binding_internal_v2(uuid,text)',
    'shareholder_register_filing.source_approval_context_internal_v3(uuid,uuid,text,text)',
    READ, APPEND,
)


@pytest.fixture(scope='module', autouse=True)
def approval_seed_access(rf_fixture_admin_access):
    """Borrow seed/observer ACLs only for the disposable BYPASSRLS admin.

    The Documents-only login does not supply Authority/Billing fixture access.
    Runtime roles, FORCE RLS and closed RF contracts remain unchanged.
    """
    tables = (('authority_connections', 'system_user_requests', 'authority_connections_store_owner'),
        ('billing', 'production_pilot_entitlements', 'billing_store_owner'))
    borrowed = []
    edges = []
    with psycopg.connect(DATABASE_URL) as db:
        principal, bypass = db.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass, 'Approval seeding requires the designated disposable database admin'
        role_edges = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members '
            'where roleid=any(%s::regrole[]) and member=current_user::regrole order by roleid,grantor',
            ([owner for _, _, owner in tables],)).fetchall()
        for schema, table, owner in tables:
            if not db.execute("select pg_has_role(current_user,%s,'SET')", (owner,)).fetchone()[0]:
                prior = db.execute('select admin_option,inherit_option,set_option from pg_auth_members '
                    'where roleid=%s::regrole and member=current_user::regrole and grantor=member', (owner,)).fetchone()
                options = prior if prior is not None else (False, False, False)
                db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set true granted by {}').format(
                    sql.Identifier(owner), sql.Identifier(principal),
                    *(sql.SQL(str(value).lower()) for value in options[:2]), sql.Identifier(principal)))
                edges.append((owner, prior))
            schema_acl = db.execute('select nspacl::text from pg_namespace where nspname=%s', (schema,)).fetchone()[0]
            table_oid, *attributes = db.execute('select c.oid,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity '
                'from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s',
                (schema, table)).fetchone()
            table_acl = tuple(attributes)
            assert table_acl[0] is not None, 'Approval seed tables require their published explicit ACLs'
            usage = not db.execute("select has_schema_privilege(current_user,%s,'USAGE')", (schema,)).fetchone()[0]
            missing = tuple(privilege for privilege in ('SELECT', 'INSERT', 'UPDATE')
                if not db.execute('select has_table_privilege(current_user,%s::oid,%s)', (table_oid, privilege)).fetchone()[0])
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
            if usage:
                db.execute(sql.SQL('grant usage on schema {} to {}').format(sql.Identifier(schema), sql.Identifier(principal)))
            if missing:
                db.execute(sql.SQL('grant {} on {} to {}').format(sql.SQL(',').join(map(sql.SQL, missing)),
                    sql.Identifier(schema, table), sql.Identifier(principal)))
            db.execute('reset role')
            borrowed.append((schema, table, table_oid, owner, schema_acl, table_acl, usage, missing))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for schema, table, table_oid, owner, schema_acl, table_acl, usage, missing in reversed(borrowed):
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
                if missing:
                    db.execute(sql.SQL('revoke {} on {} from {}').format(sql.SQL(',').join(map(sql.SQL, missing)),
                        sql.Identifier(schema, table), sql.Identifier(principal)))
                if usage:
                    db.execute(sql.SQL('revoke usage on schema {} from {}').format(sql.Identifier(schema), sql.Identifier(principal)))
                db.execute('reset role')
                assert db.execute('select relacl::text,relrowsecurity,relforcerowsecurity from pg_class where oid=%s::oid',
                    (table_oid,)).fetchone() == table_acl
                assert db.execute('select nspacl::text from pg_namespace where nspname=%s', (schema,)).fetchone()[0] == schema_acl
            for owner, prior in reversed(edges):
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(
                    sql.Identifier(owner), sql.Identifier(principal), sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(
                        sql.Identifier(owner), sql.Identifier(principal),
                        *(sql.SQL(str(value).lower()) for value in prior), sql.Identifier(principal)))
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members '
                'where roleid=any(%s::regrole[]) and member=current_user::regrole order by roleid,grantor',
                ([owner for _, _, owner in tables],)).fetchall() == role_edges


@pytest.fixture
def approval_login(capture_login):
    """Borrow the frozen backend role, restoring exact ACLs and SET edge.

    Billing/Authority contracts check the active RF executor role. Grants exist
    only in this disposable fixture; the separate closure test observes none.
    """
    name = conninfo_to_dict(capture_login)['user']
    from rf1086_year_source_v2_database_fixture import PRODUCER
    grants = (('shareholder_register_filing_store_owner', READ),
        ('shareholder_register_filing_store_owner', APPEND),
        ('corporate_governance_store_owner', GOV_READER),
        ('corporate_governance_store_owner', PRODUCER))
    added = []
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute('select oid,proacl::text from pg_proc where oid=any(%s::regprocedure[]) order by oid', ([contract for _, contract in grants],)).fetchall()
        edge_before = db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members "
            "where roleid='shareholder_register_filing_executor'::regrole and member=%s::regrole order by grantor", (name,)).fetchall()
        db.execute(sql.SQL('grant shareholder_register_filing_executor to {} with inherit true,set true').format(sql.Identifier(name)))
        for owner, contract in grants:
            if not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (contract,)).fetchone()[0]:
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
                db.execute('grant execute on function '+contract+' to shareholder_register_filing_executor')
                db.execute('reset role')
                added.append((owner, contract))
    try:
        yield capture_login
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for owner, contract in added:
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
                db.execute('revoke all on function '+contract+' from shareholder_register_filing_executor')
                db.execute('reset role')
            db.execute(sql.SQL('grant shareholder_register_filing_executor to {} with inherit true,set false').format(sql.Identifier(name)))
            assert db.execute('select oid,proacl::text from pg_proc where oid=any(%s::regprocedure[]) order by oid', ([contract for _, contract in grants],)).fetchall() == before
            assert db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members "
                "where roleid='shareholder_register_filing_executor'::regrole and member=%s::regrole order by grantor", (name,)).fetchall() == edge_before


def use_approval_backend_role(state):
    transaction = state.store._transaction
    @asynccontextmanager
    async def backend_role(**options):
        async with transaction(**options) as db:
            await db.execute('set local role shareholder_register_filing_executor')
            assert (await (await db.execute('select current_user as role')).fetchone())['role'] == 'shareholder_register_filing_executor'
            yield db
    state.store._transaction = backend_role


@pytest.fixture
def approved_release(admitted):
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute('select to_jsonb(s) from public.launch_signoffs s where key=any(%s)', (list(SIGNOFFS),)).fetchall()
        now = db.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        for key in SIGNOFFS:
            db.execute("insert into public.launch_signoffs(key,status,reviewer,reviewed_at,evidence_link,decision,recorded_by) "
                "values(%s,'approved','Closed local fixture',%s,'local-retained-v3-approval','approved',%s) "
                "on conflict(key) do update set status=excluded.status,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,"
                "evidence_link=excluded.evidence_link,decision=excluded.decision,recorded_by=excluded.recorded_by",
                (key, now, admitted['owner']))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('delete from public.launch_signoffs where key=any(%s)', (list(SIGNOFFS),))
            for (row,) in before:
                db.execute('insert into public.launch_signoffs select * from jsonb_populate_record(null::public.launch_signoffs,%s::jsonb)', (json.dumps(row),))


def prepare_state(admitted, source_role, withdrawal_role, login, documents_url, kind='loss_covering_reduction', depth=0):
    item, command, originals = complete_inputs(admitted, source_role, withdrawal_role, kind, depth)
    state = fixture(item, command, originals, login, documents_url)
    use_approval_backend_role(state)
    state.request, state.entitlement = uuid4(), uuid4()
    state.external = base64.urlsafe_b64encode(sha256(str(state.request).encode()).digest()).decode().rstrip('=')
    with psycopg.connect(DATABASE_URL) as db:
        now = db.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        insert(db, 'authority_connections.system_user_requests', dict(id=state.request,
            company_id=admitted['company'], initiating_owner_user_id=admitted['owner'],
            external_ref=state.external, status='accepted', preflight_verified_at=now))
        insert(db, 'billing.production_pilot_entitlements', dict(id=state.entitlement,
            company_id=admitted['company'], user_id=admitted['owner'], income_year=2026,
            obligation='aksjonaerregisteroppgaven', case_profile='rf1086_full_year_v1', status='active',
            billing_exempt=True, system_user_request_id=state.request,
            system_user_external_reference=state.external, starts_at=now, expires_at=now+timedelta(days=30),
            evidence_reference='local-retained-v3-approval', approved_by=admitted['owner']))
        insert(db, 'shareholder_register_filing.authority_permissions', dict(company_id=admitted['company'],
            obligation='aksjonaerregisteroppgaven', submitter_user_id=admitted['owner'],
            confirmed_by=admitted['owner'], production_enabled=True))
        opening, _ = add_opening(db, admitted)
    with ledger_fixture_insert_access(DATABASE_URL):
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) '
                'values(%s,%s,2026,%s,%s,clock_timestamp())', (opening, admitted['company'], Decimal('123.45'), admitted['owner']))
            add_lock(db, admitted)
    state.interview = seed(admitted)
    answers(state, bank_balance_confirmed=True)
    state.approval_workflow = ShareholderRegisterSourceApprovalV3(state.workflow._sessions, state.workflow._documents)
    state.approval_arguments = dict(**state.arguments, entitlement_id=str(state.entitlement))
    return state


@pytest.fixture
def state(admitted, closed_source_role, withdrawal_fixture_role, approval_login, backend_url, fixture_roles, approved_release):
    return prepare_state(admitted, closed_source_role, withdrawal_fixture_role, approval_login, backend_url)


def answers(state, **changes):
    values = dict(bank_balance_confirmed=True, has_unpaid_items=False, authority_to_submit_confirmed=True)
    values.update(changes)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db, state.item['seed'])
        db.execute('update public.annual_data set answers=%s where id=%s', (Jsonb(values), state.interview))


def review(state):
    return asyncio.run(state.approval_workflow.read_review('synthetic-token', **state.approval_arguments))


def approve(state, context, **changes):
    arguments = dict(**state.approval_arguments, review_sha256=context.review.review_sha256,
        acknowledged_warning_codes=context.review.warning_codes, real_filing_confirmed=True)
    arguments.update(changes)
    return asyncio.run(state.approval_workflow.approve('synthetic-token', **arguments))


def retained_rows(state):
    with psycopg.connect(DATABASE_URL) as db:
        return db.execute('select a.id,a.manifest_hash,b.manifest_text,b.review_text,b.approved_by '
            'from shareholder_register_filing.filing_approval_snapshots a join shareholder_register_filing.source_approval_bindings b '
            'on b.approval_id=a.id where a.company_id=%s order by a.id', (str(state.source.company_id),)).fetchall()


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('depth', [0, 1, 2])
def test_actual_v3_approval_and_replay_bind_current_owners_and_exact_capture(admitted, closed_source_role,
        withdrawal_fixture_role, approval_login, backend_url, fixture_roles, approved_release, kind, depth, monkeypatch):
    state = prepare_state(admitted, closed_source_role, withdrawal_fixture_role, approval_login, backend_url, kind, depth)
    before = rf.serialize_rf1086_year_source_v2(state.source), rf.serialize_rf1086_source_preview(state.preview)
    close_fresh_rendering(monkeypatch)
    context = review(state)
    assert context.annual_readiness.readiness_status == 'ready' and context.review.can_approve
    result = approve(state, context)
    rows = retained_rows(state)
    assert len(rows) == 1 and str(rows[0][0]) == result.record_id
    assert sha256(rows[0][2].encode()).hexdigest() == rows[0][1]
    assert json.loads(rows[0][2])['schemaVersion'] == 'production-source-approval-v3'
    captured_review = json.loads(rows[0][3])
    assert captured_review['version'] == 'rf1086-source-review-v3'
    assert captured_review['annualReadiness']['schemaVersion'] == 'rf1086-annual-readiness-binding-v2'
    assert approve(state, context) == result and retained_rows(state) == rows
    assert before == (rf.serialize_rf1086_year_source_v2(state.source), rf.serialize_rf1086_source_preview(state.preview))
    assert not state.held


@pytest.mark.parametrize('status', ['ready', 'warning', 'blocked'])
def test_real_annual_owner_evidence_controls_review_and_warning_acceptance(state, status, monkeypatch):
    answers(state, bank_balance_confirmed=status != 'warning', has_unpaid_items=status == 'blocked')
    close_fresh_rendering(monkeypatch)
    context = review(state)
    assert context.annual_readiness.readiness_status == status
    assert context.review.can_approve is (status != 'blocked')
    if status == 'blocked':
        with pytest.raises(rf.Rf1086ProductionError): approve(state, context)
        assert not retained_rows(state)
    else:
        if status == 'warning':
            assert context.review.warning_codes
            with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
                approve(state, context, acknowledged_warning_codes=())
        approve(state, context)


@pytest.mark.parametrize('change', ['withdrawal', 'amendment', 'revoked_owner', 'annual'])
def test_existing_approval_replay_rechecks_all_current_evidence(state, withdrawal_fixture_role, change):
    context = review(state)
    approve(state, context)
    before = retained_rows(state)
    if change == 'withdrawal': withdrawal(state.item['seed'], withdrawal_fixture_role, state.item['replacement'])
    elif change == 'amendment': amend(state.item)
    elif change == 'annual': answers(state, has_unpaid_items=True)
    else:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (state.item['seed']['company'], state.item['seed']['owner']))
    from talli_backend.modules.documents.public import DocumentsError, DocumentErrorCode
    if change == 'revoked_owner':
        with pytest.raises(DocumentsError) as denied: approve(state, context)
        assert denied.value.code == DocumentErrorCode.FORBIDDEN
    elif change == 'annual':
        with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'): approve(state, context)
    else:
        code = 'rf1086_source_independent_register_unavailable' if change == 'withdrawal' else 'rf1086_source_register_original_changed'
        with pytest.raises(rf.Rf1086YearSourceError, match='^'+code+'$'): approve(state, context)
    assert retained_rows(state) == before


@pytest.mark.parametrize('change', ['permission', 'technical', 'hard_comment', 'override', 'pilot_expired', 'request_unverified'])
def test_current_sql_authority_and_review_changes_cannot_reuse_old_digest(state, change):
    context = review(state)
    with psycopg.connect(DATABASE_URL) as db:
        if change == 'permission':
            db.execute('update shareholder_register_filing.authority_permissions set production_enabled=false where company_id=%s', (state.item['seed']['company'],))
        elif change == 'technical': db.execute("update public.launch_signoffs set status='pending' where key='rf1086_authority'")
        elif change == 'pilot_expired': db.execute("update billing.production_pilot_entitlements set expires_at=clock_timestamp()-interval '1 second' where id=%s", (state.entitlement,))
        elif change == 'request_unverified': db.execute("update authority_connections.system_user_requests set status='verification_failed',preflight_verified_at=null where id=%s", (state.request,))
        else:
            async def mutate():
                async with state.store._transaction() as connection:
                    if change == 'hard_comment':
                        await connection.execute("select shareholder_register_filing.add_review_comment_v1(%s,'hard_block','Fixture review needed')", (state.preview.preview_id.value,))
                    else:
                        await connection.execute("select shareholder_register_filing.record_override_v1(%s,'preview','old','new','Fixture reason','block',true)", (state.preview.preview_id.value,))
            asyncio.run(mutate())
    if change in ('pilot_expired', 'request_unverified'):
        with pytest.raises(psycopg.errors.RaiseException) as denied: approve(state, context)
        assert denied.value.diag.message_primary == 'production_pilot_entitlement_required'
    else:
        expected = {'permission': 'filing_permission_required', 'technical': 'technical_release_not_ready',
            'hard_comment': 'hard_review_comment', 'override': 'blocking_override'}[change]
        assert review(state).review.blockers == (expected,)
        with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'): approve(state, context)
    assert not retained_rows(state)


@pytest.mark.parametrize('cancel', [False, True])
def test_failure_after_real_append_rolls_back_approval_and_closed_proof(state, cancel):
    context = review(state)
    admission = state.store.source_admission
    error = asyncio.CancelledError() if cancel else RuntimeError('owned post-approval abort')
    @asynccontextmanager
    async def failing(query):
        async with admission(query) as scope:
            append = scope.append_source_approval_v3
            async def append_then_fail(*args):
                result = await append(*args)
                row = await (await scope._connection.execute('select manifest_hash from shareholder_register_filing.filing_approval_snapshots where id=%s', (result.record_id,))).fetchone()
                assert row['manifest_hash'] == args[2].manifest_sha256
                proof = await (await scope._connection.execute("select to_regclass('pg_temp.rf1086_year_source_governance_proofs') as proof")).fetchone()
                assert proof['proof'] is not None
                raise error
            scope.append_source_approval_v3 = append_then_fail
            yield scope
    state.store.source_admission = failing
    with pytest.raises(type(error)) as result: approve(state, context)
    assert result.value is error and not retained_rows(state) and not state.held


def test_closed_contracts_deny_all_ordinary_runtime_roles():
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
            for contract in CONTRACTS:
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, contract)).fetchone()[0]


@pytest.mark.parametrize('expired', ['pilot', 'mfa'])
def test_actual_authority_wait_precedes_billing_lock_and_rechecks_expiry(state, expired):
    async def run():
        ready = asyncio.get_running_loop().create_future()
        admission = state.store.source_admission
        @asynccontextmanager
        async def observed(query):
            async with admission(query) as scope:
                ready.set_result((await (await scope._connection.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield scope
        state.store.source_admission = observed
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select id from authority_connections.system_user_requests where id=%s for update', (state.request,))
            if expired == 'pilot':
                blocker.execute("update billing.production_pilot_entitlements set expires_at=clock_timestamp()+interval '0.3 seconds' where id=%s", (state.entitlement,))
            else:
                claims = json.loads(state.store._verified.claims_json)
                claims['amr'][0]['timestamp'] = int(blocker.execute('select extract(epoch from clock_timestamp())').fetchone()[0])-898
                state.store._verified = replace(state.store._verified, claims_json=json.dumps(claims))
            task = asyncio.create_task(state.approval_workflow.read_review('synthetic-token', **state.approval_arguments))
            try:
                pid = await asyncio.wait_for(ready, 5)
                for _ in range(100):
                    with psycopg.connect(DATABASE_URL) as observer:
                        blocked = observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event_type='Lock')", (pid,)).fetchone()[0]
                        if blocked:
                            assert not observer.execute("select exists(select 1 from pg_locks where pid=%s and relation='billing.production_pilot_entitlements'::regclass and mode='RowShareLock' and granted)", (pid,)).fetchone()[0]
                            break
                    await asyncio.sleep(.01)
                else: raise AssertionError('Actual v3 context did not wait on Authority request')
                await asyncio.sleep(.4 if expired == 'pilot' else 2.1)
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
        with pytest.raises(psycopg.errors.RaiseException) as denied:
            await asyncio.wait_for(task, 8)
        assert denied.value.diag.message_primary == ('production_pilot_entitlement_required' if expired == 'pilot'
            else 'production_filing_fresh_owner_step_up_required')
    asyncio.run(run())
    assert not retained_rows(state) and not state.held


def test_actual_held_append_rejects_self_consistent_annual_forgery(state, monkeypatch):
    close_fresh_rendering(monkeypatch)
    async def run():
        async with state.workflow.admit('synthetic-token', **state.arguments) as admitted_source:
            scope = admitted_source.transaction
            observed = await scope.read_source_approval_context_v3(state.preview.preview_id,
                str(state.entitlement), state.arguments['correlation_id'])
            forged_inputs = replace(observed.annual_readiness.annual_inputs, period_lock_ids=(str(uuid4()),))
            forged_annual = rf.build_rf1086_retained_annual_readiness_v2(state.source, admitted_source.retained_preview, forged_inputs)
            assert forged_annual.readiness_status == 'ready' and forged_annual.proof_sha256 != observed.annual_readiness.proof_sha256
            basis = rf.Rf1086SourceApprovalManifestBasisV3(state.source, state.preview, forged_annual,
                scope.actor_id, str(state.entitlement), observed.review.review_sha256, observed.review.warning_codes)
            manifest = rf.build_rf1086_retained_source_approval_manifest_v3(basis, admitted_source.retained_preview)
            await scope.append_source_approval_v3(state.preview.preview_id, str(state.entitlement), manifest,
                observed.review.review_sha256, state.arguments['correlation_id'])
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): asyncio.run(run())
    assert not retained_rows(state) and not state.held


@pytest.mark.parametrize('change', ['source-key', 'input-key', 'bool-string', 'bool-count',
    'float-count', 'exponent-count', 'issue-container', 'mapping-value', 'wrapper-extra'])
def test_actual_closed_sql_rejects_malformed_annual_wire_before_review_or_write(state, change):
    async def run():
        async with state.workflow.admit('synthetic-token', **state.arguments) as admitted_source:
            scope = admitted_source.transaction
            context = await scope.read_source_approval_context_v3(state.preview.preview_id,
                str(state.entitlement), state.arguments['correlation_id'])
            text = rf.serialize_rf1086_retained_annual_readiness_v2(context.annual_readiness,
                state.source, admitted_source.retained_preview)
            raw = json.loads(text)
            fields = raw['proof']['fields']
            inputs, source = fields['annual_inputs']['fields'], fields['source']['fields']
            if change == 'source-key': source['arbitrary'] = source.pop('issues')
            elif change == 'input-key': inputs['arbitrary'] = inputs.pop('bank_balance_confirmed')
            elif change == 'bool-string': inputs['bank_balance_confirmed'] = 'true'
            elif change == 'bool-count': inputs['bank_transaction_count'] = True
            elif change == 'float-count': inputs['bank_transaction_count'] = 1.0
            elif change == 'issue-container': source['issues'] = {}
            elif change == 'mapping-value': inputs['evidence_sha256'] = {'mapping': {'banking': True}}
            elif change == 'wrapper-extra': raw['proof']['ignored'] = True
            text = json.dumps(raw)
            if change == 'exponent-count':
                text = re.sub(r'("bank_transaction_count"\s*:\s*)[-0-9.eE+]+', r'\g<1>1e0', text, count=1)
            await scope._connection.execute('select shareholder_register_filing.read_source_approval_context_v3(%s,%s,%s,%s)',
                (state.preview.preview_id.value, state.entitlement, text, str(scope.actor_id.subject)))
    with pytest.raises(psycopg.errors.RaiseException) as denied: asyncio.run(run())
    assert denied.value.diag.message_primary == 'rf1086_source_annual_evidence_invalid'
    assert not retained_rows(state) and not state.held


def test_new_current_owner_uses_fresh_authority_without_rewriting_historical_capture(state, approval_login, monkeypatch):
    old = approve(state, review(state))
    old_rows = retained_rows(state)
    original_actor = state.source.confirmed_by
    seed = state.item['seed']
    request, entitlement = uuid4(), uuid4()
    external = base64.urlsafe_b64encode(sha256(str(request).encode()).digest()).decode().rstrip('=')
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (seed['company'], seed['outsider']))
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (seed['company'], seed['owner']))
        assert db.execute("update auth.users set banned_until='infinity' where id=%s", (seed['owner'],)).rowcount == 1
        # Terminal fixture status ends the single live company request. Its
        # retained row/old entitlement remain; a new actor gets a fresh binding.
        db.execute("update authority_connections.system_user_requests set status='denied',preflight_verified_at=null where id=%s", (state.request,))
        now = db.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        insert(db, 'authority_connections.system_user_requests', dict(id=request,
            company_id=seed['company'], initiating_owner_user_id=seed['outsider'], external_ref=external,
            status='accepted', preflight_verified_at=now))
        insert(db, 'billing.production_pilot_entitlements', dict(id=entitlement,
            company_id=seed['company'], user_id=seed['outsider'], income_year=2026,
            obligation='aksjonaerregisteroppgaven', case_profile='rf1086_full_year_v1', status='active',
            billing_exempt=True, system_user_request_id=request, system_user_external_reference=external,
            starts_at=now, expires_at=now+timedelta(days=30), evidence_reference='local-new-current-owner',
            approved_by=seed['outsider']))
        db.execute('update shareholder_register_filing.authority_permissions set submitter_user_id=%s,confirmed_by=%s where company_id=%s', (seed['outsider'], seed['outsider'], seed['company']))
    with pytest.raises(rf.ShareholderRegisterFilingError): review(state)
    state.store, state.traces = restricted_capture_session(state.item, approval_login, actor=seed['outsider'])
    monitor_guard(state)
    use_approval_backend_role(state)
    state.request, state.entitlement = request, entitlement
    state.approval_arguments['entitlement_id'] = str(entitlement)
    close_fresh_rendering(monkeypatch)
    current = approve(state, review(state))
    rows = retained_rows(state)
    assert current != old and len(rows) == 2 and all(row in rows for row in old_rows)
    assert state.source.confirmed_by == original_actor and state.store.actor_id != original_actor
    row = next(row for row in rows if str(row[0]) == current.record_id)
    assert row[4] == seed['outsider'] and json.loads(row[2])['userId'] == str(seed['outsider'])


def test_populated_retentive_rollback_and_reapply_preserve_history_legacy_catalog_and_roles(state):
    approve(state, review(state))
    rows = retained_rows(state)
    legacy = ('shareholder_register_filing.source_annual_binding_internal_v1(uuid,text)',
        'shareholder_register_filing.source_approval_context_internal_v2(uuid,uuid,text,text)',
        'shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text)')
    def catalog(db):
        return db.execute('select oid,proowner,prosrc,proacl,proconfig,prosecdef,provolatile,proparallel '
            'from pg_proc where oid=any(%s::regprocedure[]) order by oid', (list(legacy),)).fetchall()
    with psycopg.connect(DATABASE_URL) as db:
        before = catalog(db)
        role_edges = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        new = db.execute('select oid,prosrc from pg_proc where oid=any(%s::regprocedure[]) order by oid', (list(CONTRACTS),)).fetchall()
        for directory in ('rollback', 'migrations'):
            db.execute((ROOT/'supabase'/directory/MIGRATION).read_text())
            assert catalog(db) == before
            assert db.execute('select oid,prosrc from pg_proc where oid=any(%s::regprocedure[]) order by oid', (list(CONTRACTS),)).fetchall() == new
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == role_edges
            for contract in CONTRACTS:
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (conninfo_to_dict(state.store._configuration.database_url)['user'], contract)).fetchone()[0]
    assert retained_rows(state) == rows
