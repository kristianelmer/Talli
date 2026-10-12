"""Staged RF public evidence contracts; only a unique owned fixture can call them."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from queue import Queue
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_register_observation_withdrawal_database import (
    staged, connection, observed, withdraw, append, old_correction, wait_for_lock,
    admitted, backend_url, cleanup_owned_fixture, rf_fixture_admin_access,
    DATABASE_URL, ROOT, ASSERT_CURRENT,
)

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009222053_rf1086_observation_evidence_assertions.sql'
GOVERNANCE_SUCCESSOR = '20261009234529_governance_register_evidence_amendments.sql'
GOVERNANCE_APPLICATION = '20261010001936_governance_register_evidence_application.sql'
REPORTING_PROJECTION = '20261010005413_governance_reporting_register_evidence.sql'
RF_SOURCE_V2 = '20261010013307_rf1086_closed_year_source_v2.sql'
GOV_SOURCE_PROOF = '20261010015851_governance_rf_year_source_proof.sql'
CURRENT = 'shareholder_register_filing.assert_current_register_observation_v2(uuid,uuid,integer,integer,text,timestamptz,text)'
RETAINED = 'shareholder_register_filing.read_retained_register_observation_withdrawal_v1(uuid,uuid,integer,uuid,integer,text,text,timestamptz,text)'
UNSET = object()


@pytest.fixture
def evidence(staged):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        # Restore the intentional final-chain consumer grant after staged replay.
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
        db.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
        db.execute((ROOT / 'supabase/migrations' / RF_SOURCE_V2).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOV_SOURCE_PROOF).read_text())
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant execute on function ' + CURRENT + ',' + RETAINED + ' to {}').format(sql.Identifier(staged['role'])))
    try:
        yield staged
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke execute on function ' + CURRENT + ',' + RETAINED + ' from {}').format(sql.Identifier(staged['role'])))


def actor(db):
    return db.execute("select current_setting('talli.verified_actor_id')").fetchone()[0]


def cutoff(db, value):
    return db.execute('select clock_timestamp()').fetchone()[0] if value is UNSET else value


def assert_current(db, original, *, not_after=UNSET, **changes):
    args = dict(id=original.observation_id.value, company=original.command.company_id.value,
                year=original.command.income_year.value, revision=original.version, sha=original.fact_sha256,
                not_after=cutoff(db, not_after), subject=actor(db))
    args.update(changes)
    db.execute('select shareholder_register_filing.assert_current_register_observation_v2(%s,%s,%s,%s,%s,%s,%s)', tuple(args.values()))


def read_retained(db, receipt, *, not_after=UNSET, **changes):
    c = receipt.command
    args = dict(id=receipt.withdrawal_id.value, company=c.company_id.value, year=c.income_year.value,
                observation=c.observation_id.value, revision=c.observation_version, fact_sha=c.observation_fact_sha256,
                withdrawal_sha=receipt.withdrawal_sha256, not_after=cutoff(db, not_after), subject=actor(db))
    args.update(changes)
    return db.execute('select shareholder_register_filing.read_retained_register_observation_withdrawal_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)', tuple(args.values())).fetchone()[0]


def retained(evidence, original):
    encoded = withdraw(evidence, original)
    return encoded, rf.parse_rf1086_register_observation_withdrawal(encoded)


def test_current_identity_accepts_exact_capture_cutoff_and_equivalent_offset(evidence):
    original = observed(evidence)
    for at in (original.confirmed_at, original.confirmed_at.astimezone(timezone(timedelta(hours=-4)))):
        with connection(evidence) as db:
            assert_current(db, original, not_after=at)
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_observation_after_cutoff'):
            assert_current(db, original, not_after=original.confirmed_at - timedelta(microseconds=1))


@pytest.mark.parametrize('bad_cutoff', [None, 'infinity', '-infinity', '0001-01-01 BC', '9999-01-01T00:00:00Z'])
@pytest.mark.parametrize('contract', ['current', 'retained'])
def test_cutoff_must_be_finite_supported_and_not_in_the_future(evidence, contract, bad_cutoff):
    original = observed(evidence)
    receipt = retained(evidence, original)[1] if contract == 'retained' else None
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_observation_cutoff_invalid'):
            if receipt is None:
                assert_current(db, original, not_after=bad_cutoff)
            else:
                read_retained(db, receipt, not_after=bad_cutoff)


@pytest.mark.parametrize('changes', [{'id': str(uuid4())}, {'year': 2025}, {'revision': 2}, {'sha': '0' * 64}])
def test_current_assertion_binds_exact_observation_scope_version_and_digest(evidence, changes):
    original = observed(evidence)
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'):
            assert_current(db, original, **changes)


@pytest.mark.parametrize('terminal', ['superseded', 'withdrawn'])
def test_current_assertion_rejects_terminal_target_but_accepts_independent_root(evidence, terminal):
    original = observed(evidence)
    if terminal == 'withdrawn':
        withdraw(evidence, original)
    else:
        with connection(evidence) as db:
            old_correction(db, evidence, original)
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'):
            assert_current(db, original)
    independent = observed(evidence)
    with connection(evidence) as db:
        assert_current(db, independent)


def test_retained_receipt_returns_original_canonical_bytes_without_requiring_active_target(evidence):
    original = observed(evidence)
    encoded, receipt = retained(evidence, original)
    observed(evidence)
    with connection(evidence) as db:
        assert read_retained(db, receipt, not_after=receipt.withdrawn_at) == encoded
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_observation_after_cutoff'):
            read_retained(db, receipt, not_after=receipt.withdrawn_at - timedelta(microseconds=1))


@pytest.mark.parametrize('changes', [{'id': str(uuid4())}, {'year': 2025}, {'observation': str(uuid4())},
                                   {'revision': 2}, {'fact_sha': '0' * 64}, {'withdrawal_sha': '0' * 64}])
def test_retained_assertion_binds_exact_receipt_target_and_both_digests(evidence, changes):
    receipt = retained(evidence, observed(evidence))[1]
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_withdrawal_evidence_mismatch'):
            read_retained(db, receipt, **changes)


def test_retained_receipt_is_available_to_another_current_owner_but_concealed_from_outsider(evidence):
    encoded, receipt = retained(evidence, observed(evidence))
    with connection(evidence, actor=evidence['seed']['outsider']) as db:
        with pytest.raises(psycopg.Error, match='rf1086_not_found'):
            read_retained(db, receipt)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
                   (evidence['seed']['company'], evidence['seed']['outsider']))
    with connection(evidence, actor=evidence['seed']['outsider']) as db:
        assert read_retained(db, receipt) == encoded
        assert receipt.command.actor_id.subject.value != actor(db)


def test_retained_reader_rejects_canonical_privileged_fixture_receipt_predating_capture(evidence):
    original = observed(evidence)
    with connection(evidence, role='shareholder_register_filing_store_owner') as db:
        at = original.confirmed_at - timedelta(microseconds=1)
        identity = str(uuid4())
        encoded = db.execute('select shareholder_register_filing.withdrawal_receipt_text_internal_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (identity, original.command.company_id.value, original.command.income_year.value,
             actor(db), original.observation_id.value, original.version, original.fact_sha256,
             'Synthetic invalid chronology', at)).fetchone()[0]
        receipt = rf.parse_rf1086_register_observation_withdrawal(encoded)
        # The row codec is valid but its historical relationship is not. Ordinary
        # append refuses this; only this owned fixture bypasses that command.
        db.execute('insert into shareholder_register_filing.register_observation_withdrawals values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (identity, original.command.company_id.value, original.command.income_year.value,
             actor(db), original.observation_id.value, original.version, original.fact_sha256,
             receipt.command.reason, str(uuid4()), receipt.request_sha256, receipt.withdrawal_sha256, at, encoded))
    with connection(evidence) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_withdrawal_storage_invalid'):
            read_retained(db, receipt)


@pytest.mark.parametrize('contract', ['current', 'retained'])
@pytest.mark.parametrize('violation', ['subject', 'company', 'repeatable_read'])
def test_existing_subject_tenant_and_snapshot_guards_are_not_weakened(evidence, contract, violation):
    original = observed(evidence)
    receipt = retained(evidence, original)[1] if contract == 'retained' else None
    changes = {'subject': str(uuid4())} if violation == 'subject' else {'company': str(uuid4())} if violation == 'company' else {}
    with connection(evidence, repeatable_read=violation == 'repeatable_read') as db:
        expected = 'rf1086_forbidden' if violation == 'subject' else 'rf1086_not_found' if violation == 'company' else 'rf1086_guard_requires_read_committed'
        with pytest.raises(psycopg.Error, match=expected):
            if receipt is None:
                assert_current(db, original, **changes)
            else:
                read_retained(db, receipt, **changes)


@pytest.mark.parametrize('winner', ['withdrawal', 'assertion'])
def test_time_bounded_current_assertion_serializes_with_withdrawal_in_both_orders(evidence, winner):
    original = observed(evidence)
    started = Queue()

    def compete():
        with connection(evidence) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return assert_current(db, original) if winner == 'withdrawal' else append(db, original)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(evidence) as db:
            if winner == 'withdrawal':
                append(db, original)
            else:
                assert_current(db, original)
            pending = pool.submit(compete)
            wait_for_lock(started.get(timeout=5))
        if winner == 'withdrawal':
            with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'):
                pending.result(timeout=10)
        else:
            assert pending.result(timeout=10)


@pytest.mark.parametrize('contract', ['current', 'retained'])
def test_current_owner_is_rechecked_after_company_lock_wait(evidence, contract):
    original = observed(evidence)
    receipt = retained(evidence, original)[1] if contract == 'retained' else None
    started = Queue()

    def compete():
        with connection(evidence) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return assert_current(db, original) if receipt is None else read_retained(db, receipt)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (evidence['seed']['company'],))
            pending = pool.submit(compete)
            wait_for_lock(started.get(timeout=5))
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (evidence['seed']['company'],))
        with pytest.raises(psycopg.Error, match='rf1086_forbidden'):
            pending.result(timeout=10)


def test_new_contracts_keep_only_narrow_governance_assertion_grant_and_preserve_v1_and_role_state(evidence):
    try:
        with psycopg.connect(DATABASE_URL) as db:
            old = db.execute('select to_jsonb(p) from pg_proc p where oid=%s::regprocedure', (ASSERT_CURRENT,)).fetchone()
            roles = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            # Verify the predecessor's closed stage before restoring the final chain.
            for role in ('anon','authenticated','service_role','shareholder_register_filing_executor',
                         'corporate_governance_workflow_executor','corporate_governance_store_owner'):
                for identity in (CURRENT, RETAINED):
                    assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role,identity)).fetchone()[0]
            # Restore the intentional final-chain consumer grant after staged replay.
            db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
            db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
            db.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
            db.execute((ROOT / 'supabase/migrations' / RF_SOURCE_V2).read_text())
            db.execute((ROOT / 'supabase/migrations' / GOV_SOURCE_PROOF).read_text())
            assert db.execute('select to_jsonb(p) from pg_proc p where oid=%s::regprocedure', (ASSERT_CURRENT,)).fetchone() == old
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == roles
            for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor',
                         'corporate_governance_workflow_executor', 'corporate_governance_store_owner'):
                for identity in (CURRENT, RETAINED):
                    assert db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, identity)).fetchone()[0] == (role == 'corporate_governance_store_owner')
            assert db.execute("select has_schema_privilege('corporate_governance_store_owner','shareholder_register_filing','USAGE')").fetchone()[0]
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            assert db.execute('select to_jsonb(p) from pg_proc p where oid=%s::regprocedure', (ASSERT_CURRENT,)).fetchone() == old
    finally:
        with psycopg.connect(DATABASE_URL) as restored:
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
            restored.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
            restored.execute((ROOT / 'supabase/migrations' / RF_SOURCE_V2).read_text())
            restored.execute((ROOT / 'supabase/migrations' / GOV_SOURCE_PROOF).read_text())
    original = observed(evidence)
    with connection(evidence, role='shareholder_register_filing_executor') as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            assert_current(db, original)
