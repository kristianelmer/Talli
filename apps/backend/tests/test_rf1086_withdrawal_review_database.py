"""Current SQL review reads reject withdrawal without changing historical replay."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import json

import psycopg
from psycopg import sql
import pytest

from test_rf1086_withdrawal_admission_database import (
    downstream, annual_fixture, approval_fixture, staged, admitted, backend_url,
    cleanup_owned_fixture, rf_fixture_admin_access, remove_only_bridge_fixture,
    remove_only_preview_fixture, remove_only_owned_source_fixture,
    remove_only_annual_opening_fixture, fixture_roles, connection, withdraw,
    observed, append_withdrawal, wait_for_lock, prepare_stage, state, locked,
    DATABASE_URL, ROOT, STAGES,
)

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009221151_rf1086_withdrawal_review_read_guards.sql'


@pytest.fixture
def guarded_review(downstream):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
    return downstream


@pytest.fixture
def reference_free_review(annual_fixture, staged):
    f = dict(annual_fixture)
    f['staged'] = dict(staged, store=f['store'])
    identity = 'shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text)'
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations/20261009215302_rf1086_withdrawal_source_admission_guards.sql').read_text())
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant execute on function ' + identity + ' to {}').format(sql.Identifier(staged['role'])))
    try:
        yield f
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke execute on function ' + identity + ' from {}').format(sql.Identifier(staged['role'])))


def review(db, f, *, subject=None):
    locked(db, f)
    args = [f['preview'].preview_id.value, f['entitlement']]
    if f['version'] == 2:
        args.append(f['annual_text'])
    args.append(subject or str(f['store'].actor_id.subject))
    return db.execute('select shareholder_register_filing.read_source_approval_context_v'
        + str(f['version']) + '(' + ','.join('%s' for _ in args) + ')', args).fetchone()[0]


@pytest.mark.parametrize('version', [1, 2])
def test_current_review_preserves_exact_projection_then_rejects_withdrawn_reference(guarded_review, version):
    f = guarded_review
    prepare_stage(f, f'approval_v{version}')
    before = state(f)
    with connection(f['staged']) as db:
        first = review(db, f)
        assert first['blockers'] == [] and first['reviewSha256'] == f['review_sha']
        assert 'reviewText' not in first
    assert state(f) == before
    withdraw(f['staged'], f['observation'])
    with connection(f['staged']) as db:
        with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
            review(db, f)
    assert state(f) == before


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('winner', ['withdrawal', 'review'])
def test_current_review_and_withdrawal_obey_both_company_lock_orders(guarded_review, version, winner):
    f = guarded_review
    prepare_stage(f, f'approval_v{version}')
    started = Queue()
    before = state(f)
    def compete():
        with connection(f['staged']) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return review(db, f) if winner == 'withdrawal' else append_withdrawal(db, f['observation'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(f['staged']) as db:
            if winner == 'withdrawal':
                append_withdrawal(db, f['observation'])
            else:
                assert review(db, f)['reviewSha256'] == f['review_sha']
            pending = pool.submit(compete)
            wait_for_lock(started.get(timeout=5))
        if winner == 'withdrawal':
            with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
                pending.result(timeout=10)
        else:
            assert pending.result(timeout=10)
    assert state(f) == before


@pytest.mark.parametrize('version', [1, 2])
def test_review_of_an_independent_active_root_survives_unrelated_withdrawal(guarded_review, version):
    f = guarded_review
    prepare_stage(f, f'approval_v{version}')
    unrelated = observed(f['staged'])
    withdraw(f['staged'], unrelated)
    with connection(f['staged']) as db:
        assert review(db, f)['reviewSha256'] == f['review_sha']


@pytest.mark.parametrize('version', [1, 2])
def test_reference_free_current_review_remains_usable(reference_free_review, version):
    f = reference_free_review
    prepare_stage(f, f'approval_v{version}')
    unrelated = observed(f['staged'])
    withdraw(f['staged'], unrelated)
    with connection(f['staged']) as db:
        assert review(db, f)['reviewSha256'] == f['review_sha']


@pytest.mark.parametrize('version', [1, 2])
def test_existing_fresh_mfa_requirement_precedes_current_evidence(guarded_review, version):
    f = guarded_review
    prepare_stage(f, f'approval_v{version}')
    withdraw(f['staged'], f['observation'])
    claims = json.loads(f['store']._verified.claims_json)
    for amr in claims['amr']:
        amr['timestamp'] = 1
    with connection(f['staged']) as db:
        db.execute("select set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
                   (json.dumps(claims), json.dumps(claims)))
        with pytest.raises(psycopg.Error, match='production_filing_fresh_owner_step_up_required'):
            review(db, f)


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('violation', ['actor', 'missing_guards', 'repeatable_read'])
def test_existing_actor_and_transaction_guards_still_precede_current_evidence(guarded_review, version, violation):
    f = guarded_review
    prepare_stage(f, f'approval_v{version}')
    withdraw(f['staged'], f['observation'])
    with connection(f['staged'], repeatable_read=violation == 'repeatable_read') as db:
        with pytest.raises(psycopg.Error, match='rf1086_forbidden' if violation == 'actor' else 'rf1086_source_approval_guard_required'):
            if violation == 'missing_guards':
                args = [f['preview'].preview_id.value, f['entitlement']]
                if version == 2:
                    args.append(f['annual_text'])
                args.append(str(f['store'].actor_id.subject))
                db.execute('select shareholder_register_filing.read_source_approval_context_v'
                    + str(version) + '(' + ','.join('%s' for _ in args) + ')', args)
            else:
                review(db, f, subject=str(f['seed']['outsider']) if violation == 'actor' else None)


@pytest.mark.parametrize('stage', tuple(s for s in STAGES if s != 'source'))
def test_adding_read_guards_preserves_committed_approval_claim_and_intent_replay(guarded_review, stage):
    f = guarded_review
    operation = prepare_stage(f, stage)
    with connection(f['staged']) as db:
        first = operation(db)
    before = state(f)
    withdraw(f['staged'], f['observation'])
    with connection(f['staged']) as db:
        replay = operation(db)
    if stage.startswith(('intent_', 'retry_')):
        assert replay['operation'] == first['operation'] and replay['newlyPrepared'] is False
    elif stage.startswith('claim_'):
        assert replay['claim'] == first['claim'] and replay['newlyClaimed'] is False
    else:
        assert replay == first
    assert state(f) == before


def test_review_migration_preserves_private_internals_catalog_grants_and_rollback_barrier(guarded_review):
    f = guarded_review
    catalog = "select to_jsonb(p) from pg_proc p where pronamespace='shareholder_register_filing'::regnamespace order by oid"
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute(catalog).fetchall()
        roles = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        assert db.execute(catalog).fetchall() == before
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == roles
        for version, signature in ((1, 'uuid,uuid,text'), (2, 'uuid,uuid,text,text')):
            identity = f'shareholder_register_filing.read_source_approval_context_v{version}({signature})'
            for role in ('anon', 'authenticated', 'service_role', 'corporate_governance_workflow_executor'):
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, identity)).fetchone()[0]
            assert db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (identity,)).fetchone()[0] is (version == 2)
        db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
        assert db.execute(catalog).fetchall() == before
    withdraw(f['staged'], f['observation'])
    with psycopg.connect(DATABASE_URL) as db:
        with pytest.raises(psycopg.Error, match='rf1086_retained_withdrawals_block_rollback'):
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
