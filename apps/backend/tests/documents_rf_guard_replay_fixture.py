"""Replay the frozen Documents guards without overwriting RF's later withdrawal guard."""
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PREDECESSOR = "20260924080249_documents_rf_consequential_company_guards.sql"
WITHDRAWAL = "20261009213032_rf1086_observation_withdrawal_foundation.sql"
PREDECESSOR_SHA = "9c7f8d5f338487fca0c32171812805cc706986de4784c9d65cbee48f98c6c7e7"
WITHDRAWAL_SHA = "bbe6cb7fff945785ae31f66c71d8aa353399e7f2bf4121bba15339e628b1f77d"
IDENTITY = "shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)"
START = "create or replace function shareholder_register_filing.assert_current_register_observation_v1("
END = "end; $fn$;"
ANCHOR = "perform shareholder_register_filing.lock_company_write_v1(p_company,false);"
GUARD = "perform shareholder_register_filing.assert_register_observation_active_internal_v1(p_id,p_company,p_year,p_revision,p_sha);"
OMISSION = "-- Test replay preserves the installed RF withdrawal assertion."


def _replay_sql(predecessor_bytes: bytes, withdrawal_bytes: bytes) -> tuple[str, str]:
    if sha256(predecessor_bytes).hexdigest() != PREDECESSOR_SHA:
        raise AssertionError("documents_guard_replay_predecessor_drift")
    if sha256(withdrawal_bytes).hexdigest() != WITHDRAWAL_SHA:
        raise AssertionError("documents_guard_replay_withdrawal_drift")
    predecessor = predecessor_bytes.decode("utf-8")
    withdrawal = withdrawal_bytes.decode("utf-8")
    assert predecessor.count(START) == 1
    start = predecessor.index(START)
    end = predecessor.index(END, start) + len(END)
    statement = predecessor[start:end]
    assert statement.count("$fn$") == 2 and statement.count(ANCHOR) == 1
    assert GUARD not in statement and GUARD in withdrawal
    body = statement.split("$fn$")[1]
    installed_body = body.replace(ANCHOR, ANCHOR + "\n " + GUARD)
    return predecessor[:start] + OMISSION + predecessor[end:], installed_body


def _snapshot(db):
    return db.execute(
        "select p.oid,p.proowner::regrole::text,p.prosrc,p.proacl::text,p.proconfig,"
        "p.prosecdef,p.provolatile,p.proparallel,l.lanname,p.prorettype::regtype::text,"
        "pg_catalog.pg_get_functiondef(p.oid) "
        "from pg_catalog.pg_proc p join pg_catalog.pg_language l on l.oid=p.prolang "
        "where p.oid=pg_catalog.to_regprocedure(%s)",
        (IDENTITY,),
    ).fetchone()


def replay_documents_guards_preserving_rf_withdrawal(db) -> None:
    migration_dir = ROOT / "supabase/migrations"
    sql, expected_body = _replay_sql(
        (migration_dir / PREDECESSOR).read_bytes(),
        (migration_dir / WITHDRAWAL).read_bytes(),
    )
    before = _snapshot(db)
    if before is None or (
        before[1] != "shareholder_register_filing_store_owner"
        or before[2] != expected_body
        or before[4] != ['search_path=""']
        or before[5:10] != (True, "v", "u", "plpgsql", "void")
    ):
        raise AssertionError("documents_guard_replay_installed_rf_assertion_drift")
    # All Documents definitions, wrappers, grants and role restoration still run.
    # Omit only the exact predecessor CREATE that would erase the later RF guard.
    db.execute(sql)
    if _snapshot(db) != before:
        raise AssertionError("documents_guard_replay_rf_catalog_drift")
