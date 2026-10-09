"""Staged, ungranted withdrawal SQL on the owned disposable database only."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
from time import monotonic, sleep
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import DATABASE_URL, ROOT, session
from test_rf1086_register_observation_database import (
    cleanup_owned_fixture, inputs, capture, correction, query,
)
from test_annual_purchase_basis_runtime import admitted


pytestmark = pytest.mark.authority_database
MIGRATION = "20261009213032_rf1086_observation_withdrawal_foundation.sql"
APPEND = "shareholder_register_filing.append_register_observation_withdrawal_v1(uuid,integer,uuid,integer,text,text,text)"
ASSERT_CURRENT = "shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)"
TABLE = "shareholder_register_filing.register_observation_withdrawals"


@pytest.fixture
def staged(admitted, backend_url, cleanup_owned_fixture):
    """Grant only a unique NOLOGIN fixture role; runtime ACLs remain untouched."""
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    role = "rf_withdrawal_fixture_" + uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / "supabase/migrations" / MIGRATION).read_text())
        principal = db.execute("select current_user").fetchone()[0]
        db.execute(sql.SQL("create role {} nologin noinherit nobypassrls").format(sql.Identifier(role)))
        db.execute(sql.SQL("grant {} to {} with inherit false,set true").format(sql.Identifier(role), sql.Identifier(principal)))
        db.execute(sql.SQL("grant shareholder_register_filing_executor to {} with inherit true,set true").format(sql.Identifier(role)))
        db.execute("set local role shareholder_register_filing_store_owner")
        db.execute(sql.SQL("grant execute on function " + APPEND + "," + ASSERT_CURRENT + " to {}").format(sql.Identifier(role)))
    try:
        yield {"seed": admitted, "backend_url": backend_url, "store": store, "command": command, "context": context, "role": role}
    finally:
        # Dependencies clean observations afterwards. Restore immutable/RLS state
        # atomically before the exact fixture company can be removed.
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("set local role shareholder_register_filing_store_owner")
            db.execute("alter table " + TABLE + " disable trigger observation_withdrawal_immutable")
            db.execute("alter table " + TABLE + " no force row level security")
            db.execute("delete from " + TABLE + " where company_id=%s", (admitted["company"],))
            db.execute("alter table " + TABLE + " force row level security")
            db.execute("alter table " + TABLE + " enable trigger observation_withdrawal_immutable")
            db.execute(sql.SQL("revoke execute on function " + APPEND + "," + ASSERT_CURRENT + " from {}").format(sql.Identifier(role)))
            db.execute("reset role")
            db.execute(sql.SQL("revoke shareholder_register_filing_executor from {}").format(sql.Identifier(role)))
            db.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


@contextmanager
def connection(staged, *, actor=None, role=None, repeatable_read=False):
    store = staged["store"] if actor is None else session(staged["seed"], staged["backend_url"], actor)
    with psycopg.connect(DATABASE_URL) as db:
        if repeatable_read:
            db.execute("set transaction isolation level repeatable read")
        db.execute(sql.SQL("set local role {}").format(sql.Identifier(role or staged["role"])))
        db.execute("set local statement_timeout='8s'")
        db.execute("set local lock_timeout='5s'")
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
                   (str(store.actor_id.subject), store._verified.claims_json, store._verified.claims_json))
        yield db


def observed(staged):
    return capture(staged["store"], staged["command"], staged["context"])


def append(db, observation, *, reason="  Feil original – behold teksten.\n", key=None, **changes):
    args = {"company": observation.command.company_id.value, "year": observation.command.income_year.value,
            "observation": observation.observation_id.value, "version": observation.version,
            "sha": observation.fact_sha256, "reason": reason, "key": key or str(uuid4())}
    args.update(changes)
    return db.execute("select shareholder_register_filing.append_register_observation_withdrawal_v1(%s,%s,%s,%s,%s,%s,%s)",
                      tuple(args.values())).fetchone()[0]


def withdraw(staged, observation, **options):
    with connection(staged) as db:
        return append(db, observation, **options)


def old_correction(db, staged, observation):
    command = correction(staged["command"], observation)
    at = db.execute("select clock_timestamp()").fetchone()[0]
    result = rf.prepare_rf1086_register_observation(command, context=staged["context"],
        observation_id=rf.Rf1086RegisterObservationId(str(uuid4())), confirmed_at=at, previous=observation)
    db.execute("select shareholder_register_filing.append_register_observation_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (result.observation_id.value, command.company_id.value, command.income_year.value, result.version,
         result.fact_sha256, rf.rf1086_register_observation_request_digest(command), str(uuid4()),
         observation.observation_id.value, observation.fact_sha256, command.correction_reason,
         rf.serialize_rf1086_register_observation(result), at))
    return result


@pytest.mark.parametrize("reason", ["ordinary", " ø 😀 a\u030a ", 'quote " slash \\ tab\t newline\n',
                                    "control\x01\x1fend", "\u2028line\u2029", "😀" * 1000])
def test_sql_mints_exact_v1_canonical_receipt_and_replays_without_new_identity(staged, reason):
    original = observed(staged)
    key = str(uuid4())
    encoded = withdraw(staged, original, reason=reason, key=key)
    receipt = rf.parse_rf1086_register_observation_withdrawal(encoded)
    expected = rf.prepare_rf1086_register_observation_withdrawal(receipt.command, observation=original,
        withdrawal_id=receipt.withdrawal_id, withdrawn_at=receipt.withdrawn_at)
    assert receipt == expected
    assert rf.serialize_rf1086_register_observation_withdrawal(expected) == encoded
    assert receipt.command.reason == reason and receipt.command.actor_id == staged["store"].actor_id
    assert receipt.withdrawn_at >= original.confirmed_at
    assert withdraw(staged, original, reason=reason, key=key) == encoded
    with connection(staged) as db:
        assert db.execute("select count(*) from " + TABLE).fetchone()[0] == 1
    assert asyncio.run(staged["store"].read_register_observation(query(staged["command"]), original.observation_id)) == original


def test_new_function_and_helpers_have_no_runtime_execute_or_direct_mutation_grants(staged):
    original = observed(staged)
    with psycopg.connect(DATABASE_URL) as db:
        for role in ("anon", "authenticated", "service_role", "shareholder_register_filing_executor", "corporate_governance_workflow_executor"):
            for function in (
                APPEND,
                "shareholder_register_filing.withdrawal_command_text_internal_v1(uuid,integer,uuid,uuid,integer,text,text)",
                "shareholder_register_filing.withdrawal_receipt_text_internal_v1(uuid,uuid,integer,uuid,uuid,integer,text,text,timestamptz)",
                "shareholder_register_filing.assert_register_observation_active_internal_v1(uuid,uuid,integer,integer,text)",
                "shareholder_register_filing.protect_observation_withdrawal_v1()",
            ):
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, function)).fetchone()[0]
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not db.execute("select has_table_privilege(%s,%s,%s)", (role, TABLE, privilege)).fetchone()[0]
        assert db.execute("select relrowsecurity and relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone()[0]
        assert not db.execute("select rolcanlogin or rolbypassrls from pg_roles where rolname=%s", (staged["role"],)).fetchone()[0]
        args = db.execute("select proargnames from pg_proc where oid=%s::regprocedure", (APPEND,)).fetchone()[0]
        assert args == ["p_company", "p_year", "p_observation", "p_version", "p_fact_sha", "p_reason", "p_key"]
    with connection(staged) as db:
        db.execute("set local role shareholder_register_filing_executor")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            append(db, original)


@pytest.mark.parametrize("changes", [{"version": 2}, {"sha": "0" * 64}, {"year": 2025}, {"company": str(uuid4())}])
def test_wrong_target_scope_version_or_hash_fails_without_receipt(staged, changes):
    with pytest.raises(psycopg.Error):
        withdraw(staged, observed(staged), **changes)
    with connection(staged) as db:
        assert db.execute("select count(*) from " + TABLE).fetchone()[0] == 0


@pytest.mark.parametrize("reason", ["", " \t\r\n", "\x1c\x85\u00a0\u2007\u202f\u3000", "x" * 1001])
def test_sql_reason_validation_matches_pure_bound_and_whitespace(staged, reason):
    with pytest.raises(psycopg.Error, match="rf1086_register_withdrawal_input_invalid"):
        withdraw(staged, observed(staged), reason=reason)


def test_replay_conflict_and_new_key_cannot_create_second_withdrawal(staged):
    original = observed(staged)
    key = str(uuid4())
    encoded = withdraw(staged, original, key=key)
    with pytest.raises(psycopg.Error, match="idempotency_conflict"):
        withdraw(staged, original, key=key, reason="Different reason")
    with pytest.raises(psycopg.Error, match="predecessor_mismatch"):
        withdraw(staged, original)
    assert withdraw(staged, original, key=key) == encoded


def test_owner_revocation_blocks_replay_and_foreign_actor_cannot_probe_key(staged):
    original = observed(staged)
    key = str(uuid4())
    withdraw(staged, original, key=key)
    with connection(staged, actor=staged["seed"]["outsider"]) as db:
        assert db.execute("select count(*) from " + TABLE).fetchone()[0] == 0
        with pytest.raises(psycopg.Error, match="rf1086_not_found"):
            append(db, original, key=key)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("update public.company_memberships set role='read_only' where company_id=%s", (staged["seed"]["company"],))
    with pytest.raises(psycopg.Error, match="rf1086_forbidden"):
        withdraw(staged, original, key=key)
    with connection(staged) as db:
        assert db.execute("select count(*) from " + TABLE).fetchone()[0] == 1


def test_same_key_is_actor_scoped_and_does_not_replay_another_owners_receipt(staged):
    original = observed(staged)
    independent = observed(staged)
    key = str(uuid4())
    first = rf.parse_rf1086_register_observation_withdrawal(withdraw(staged, original, key=key))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
                   (staged["seed"]["company"], staged["seed"]["outsider"]))
    with connection(staged, actor=staged["seed"]["outsider"]) as db:
        with pytest.raises(psycopg.Error, match="predecessor_mismatch"):
            append(db, original, key=key, reason="Different actor cannot discover a key conflict")
    with connection(staged, actor=staged["seed"]["outsider"]) as db:
        second = rf.parse_rf1086_register_observation_withdrawal(append(db, independent, key=key))
    assert second.withdrawal_id != first.withdrawal_id
    assert second.command.actor_id.subject.value == str(staged["seed"]["outsider"])


@pytest.mark.parametrize("field", ["request_sha256", "withdrawal_sha256", "snapshot_text", "reason", "actor_id"])
def test_table_rejects_forged_receipt_commitments_even_through_owner_fixture(staged, field):
    original = observed(staged)
    with connection(staged, role="shareholder_register_filing_store_owner") as db:
        at = db.execute("select clock_timestamp()").fetchone()[0]
        command = rf.WithdrawRf1086RegisterObservation(original.command.company_id, staged["store"].actor_id,
            original.command.income_year, original.observation_id, original.version, original.fact_sha256, "Original")
        receipt = rf.prepare_rf1086_register_observation_withdrawal(command, observation=original,
            withdrawal_id=rf.Rf1086RegisterObservationWithdrawalId(str(uuid4())), withdrawn_at=at)
        values = {"id": receipt.withdrawal_id.value, "company_id": command.company_id.value,
            "income_year": command.income_year.value, "actor_id": command.actor_id.subject.value,
            "observation_id": command.observation_id.value, "observation_version": command.observation_version,
            "observation_fact_sha256": command.observation_fact_sha256, "reason": command.reason,
            "idempotency_key": str(uuid4()), "request_sha256": receipt.request_sha256,
            "withdrawal_sha256": receipt.withdrawal_sha256, "withdrawn_at": at,
            "snapshot_text": rf.serialize_rf1086_register_observation_withdrawal(receipt)}
        values[field] = str(uuid4()) if field == "actor_id" else "forged" if field in ("reason", "snapshot_text") else "0" * 64
        with pytest.raises(psycopg.Error):
            db.execute(sql.SQL("insert into " + TABLE + " ({}) values ({})").format(
                sql.SQL(",").join(map(sql.Identifier, values)), sql.SQL(",").join(sql.Placeholder() for _ in values)), tuple(values.values()))


def test_concurrent_exact_replays_commit_one_original_receipt(staged):
    original = observed(staged)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(withdraw, staged, original, key=key) for _ in range(2)]
        assert futures[0].result(timeout=10) == futures[1].result(timeout=10)
    with connection(staged) as db:
        assert db.execute("select count(*) from " + TABLE).fetchone()[0] == 1


@pytest.mark.parametrize("statement", ["update " + TABLE + " set reason='changed'", "delete from " + TABLE])
def test_no_executor_mutation_and_immutable_trigger_survives_owner_fixture(staged, statement):
    original = observed(staged)
    encoded = withdraw(staged, original)
    with connection(staged) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(statement)
    with connection(staged, role="shareholder_register_filing_store_owner") as db:
        db.execute("alter table " + TABLE + " no force row level security")
        with pytest.raises(psycopg.Error, match="rf1086_register_withdrawal_immutable"):
            db.execute(statement + " where company_id=%s", (staged["seed"]["company"],))
    with connection(staged) as db:
        assert db.execute("select snapshot_text from " + TABLE).fetchone()[0] == encoded
        assert db.execute("select relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone()[0]


def wait_for_lock(pid):
    deadline = monotonic() + 5
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        while monotonic() < deadline:
            if db.execute("select wait_event_type='Lock' from pg_stat_activity where pid=%s", (pid,)).fetchone() == (True,):
                return
            sleep(0.01)
    pytest.fail("owned competing transaction did not wait on the company guard")


def test_owner_is_rechecked_after_the_company_lock_wait(staged):
    original = observed(staged)
    from queue import Queue
    started = Queue()
    def waiting_withdrawal():
        with connection(staged) as db:
            started.put(db.execute("select pg_backend_pid()").fetchone()[0])
            return append(db, original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute("select public.company_archive_lock_company_v1(%s)", (staged["seed"]["company"],))
            pending = pool.submit(waiting_withdrawal)
            wait_for_lock(started.get(timeout=5))
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (staged["seed"]["company"],))
        with pytest.raises(psycopg.Error, match="rf1086_forbidden"):
            pending.result(timeout=10)


@pytest.mark.parametrize("winner", ["withdrawal", "correction"])
def test_old_correction_and_withdrawal_serialize_without_ancestor_reactivation(staged, winner):
    original = observed(staged)
    from queue import Queue
    started = Queue()
    def compete():
        with connection(staged) as db:
            started.put(db.execute("select pg_backend_pid()").fetchone()[0])
            return old_correction(db, staged, original) if winner == "withdrawal" else append(db, original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(staged) as db:
            if winner == "withdrawal": append(db, original)
            else: old_correction(db, staged, original)
            pending = pool.submit(compete)
            wait_for_lock(started.get(timeout=5))
        with pytest.raises(psycopg.Error, match="predecessor_mismatch"):
            pending.result(timeout=10)


def test_old_public_assertion_rejects_withdrawn_head_but_new_independent_capture_survives(staged):
    original = observed(staged)
    withdraw(staged, original)
    with connection(staged) as db:
        with pytest.raises(psycopg.Error, match="predecessor_mismatch"):
            db.execute("select shareholder_register_filing.assert_current_register_observation_v1(%s,%s,%s,%s,%s,%s)",
                (original.observation_id.value, original.command.company_id.value, original.command.income_year.value,
                 original.version, original.fact_sha256, staged["store"].actor_id.subject.value))
    independent = observed(staged)
    assert independent.version == 1 and independent.observation_id != original.observation_id


def test_old_correction_rejects_a_snapshot_taken_before_committed_withdrawal(staged):
    original = observed(staged)
    with connection(staged, repeatable_read=True) as db:
        assert db.execute("select id::text from shareholder_register_filing.register_observations where id=%s",
                          (original.observation_id.value,)).fetchone()[0] == original.observation_id.value
        withdraw(staged, original)
        # The exact old SQL command must refuse a stale transaction snapshot,
        # even though it obtains the company/year lock after withdrawal commits.
        with pytest.raises(psycopg.Error, match="rf1086_guard_requires_read_committed"):
            old_correction(db, staged, original)


def test_migration_replay_preserves_old_oids_acls_and_memberships_and_retained_rollback_refuses(staged):
    original = observed(staged)
    encoded = withdraw(staged, original)
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall()
        routines = db.execute("select oid,proowner,proacl::text from pg_proc where oid in (%s::regprocedure,%s::regprocedure) order by oid",
            (ASSERT_CURRENT, "shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)")).fetchall()
        db.execute((ROOT / "supabase/migrations" / MIGRATION).read_text())
        assert db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall() == before
        assert db.execute("select oid,proowner,proacl::text from pg_proc where oid in (%s::regprocedure,%s::regprocedure) order by oid",
            (ASSERT_CURRENT, "shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)")).fetchall() == routines
    with psycopg.connect(DATABASE_URL) as db:
        with pytest.raises(psycopg.Error, match="retained_withdrawals_block_rollback"):
            db.execute((ROOT / "supabase/rollback" / MIGRATION).read_text())
    with connection(staged) as db:
        assert db.execute("select snapshot_text from " + TABLE).fetchone()[0] == encoded
        assert db.execute("select relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone()[0]


def test_empty_rollback_preserves_inert_storage_guards_and_closed_runtime_grants(staged):
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall()
        db.execute((ROOT / "supabase/rollback" / MIGRATION).read_text())
        assert db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall() == before
        assert db.execute("select relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone()[0]
        assert not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (APPEND,)).fetchone()[0]
        assert "assert_register_observation_active_internal_v1" in db.execute("select pg_get_functiondef(%s::regprocedure)", (ASSERT_CURRENT,)).fetchone()[0]
