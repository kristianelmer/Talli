import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL("../supabase/migrations/20260827100000_ledger_capability.sql", import.meta.url);
const contractPath = new URL("../supabase/contract-migrations/20260827101000_ledger_capability_contract.sql", import.meta.url);
const rollbackPath = new URL("../supabase/rollback/20260827101000_ledger_capability_contract.sql", import.meta.url);

function artifact(path, phase) {
  assert.equal(existsSync(path), true, `missing ${phase} artifact`);
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

function functionBody(source, schema, name) {
  const match = source.match(new RegExp(
    `create\\s+or\\s+replace\\s+function\\s+${schema}\\.${name}\\s*\\([\\s\\S]+?\\$function\\$\\s*;`,
    "iu",
  ));
  assert.ok(match, `missing ${schema}.${name}`);
  return match[0];
}

test("ledger cutover is an atomic expand, contract, and recutover-safe rollback", () => {
  const expand = artifact(expandPath, "expand");
  const contract = artifact(contractPath, "contract");
  const rollback = artifact(rollbackPath, "rollback");
  assert.match(expand, /EXPAND\/MIGRATE.*ledger/iu);
  assert.match(contract, /CONTRACT.*ledger/iu);
  assert.match(rollback, /target writer is disabled first/iu);
  assert.doesNotMatch(rollback, /drop table[^;]+(?:ledger|receipt|reconciliation)/iu);
});

test("one physical ledger store has a non-bypass owner and execute-only runtime", () => {
  const source = artifact(expandPath, "expand");
  assert.match(source, /create role ledger_store_owner nologin noinherit nobypassrls/iu);
  assert.match(source, /create role ledger_executor nologin noinherit nobypassrls/iu);
  assert.match(source, /alter table public\.ledger_entries set schema ledger/iu);
  assert.match(source, /alter table ledger\.ledger_entries rename to entries/iu);
  assert.match(source, /alter table public\.period_locks set schema ledger/iu);
  assert.match(source, /alter table ledger\.entries owner to ledger_store_owner/iu);
  assert.match(source, /alter table ledger\.period_locks owner to ledger_store_owner/iu);
  assert.match(source, /alter table ledger\.entries force row level security/iu);
  assert.match(source, /alter table ledger\.period_locks force row level security/iu);
  assert.doesNotMatch(source, /grant[^;]+(?:insert|update|delete)[^;]+ledger\.(?:entries|period_locks)[^;]+ledger_executor/iu);
  assert.match(source, /grant execute on function\s+ledger\.post_entry[\s\S]+to ledger_executor/iu);
  assert.doesNotMatch(source, /grant execute[^;]+cursor_secret_v1[^;]+ledger_executor/iu);
});

test("commands bind verified identity, closed admission, and permanent idempotency", () => {
  const source = artifact(expandPath, "expand");
  const post = functionBody(source, "ledger", "post_entry");
  const lock = functionBody(source, "ledger", "lock_period");
  for (const body of [post, lock]) {
    assert.match(body, /p_verified_subject/iu);
    assert.match(body, /company_access_auth_uid_v1\(\)/iu);
    assert.match(body, /pg_try_advisory_xact_lock/iu);
    assert.match(body, /ledger_idempotency_in_progress/iu);
    assert.match(body, /ledger_idempotency_key_reused/iu);
    assert.match(body, /company_access_company_year_allows_consequential_v1/iu);
    assert.match(body, /ledger_company_year_not_admitted/iu);
    assert.match(body, /backend_system\.ledger_command_receipts/iu);
    assert.doesNotMatch(body, /p_request_fingerprint/iu);
  }
  assert.match(source, /unique\s*\(\s*api_major\s*,\s*actor_id\s*,\s*company_id\s*,\s*operation_name\s*,\s*idempotency_key\s*\)/iu);
  assert.match(source, /idempotency_key\s*~\s*'\^\[A-Za-z0-9\._:-\]\{16,255\}\$'/u);
});

test("new-year coordination is atomic, replayable, and keeps posting policy in ledger", () => {
  const source = artifact(expandPath, "expand");
  const claim = functionBody(source, "backend_system", "claim_ledger_workflow_v1");
  const opening = functionBody(source, "backend_system", "record_opening_snapshot_legacy_v1");
  const complete = functionBody(source, "backend_system", "complete_ledger_workflow_v1");
  assert.match(source, /create role ledger_workflow_store_owner nologin noinherit nobypassrls/iu);
  assert.match(source, /create role ledger_workflow_executor nologin noinherit nobypassrls/iu);
  assert.match(source, /backend_system\.ledger_workflow_receipts/iu);
  assert.match(source, /ledger_workflow_receipts_immutable/iu);
  assert.match(claim, /pg_try_advisory_xact_lock/iu);
  assert.match(claim, /digest\(p_request::text, 'sha256'\)/iu);
  assert.doesNotMatch(claim, /p_request_fingerprint/iu);
  assert.match(opening, /company_access_auth_jwt_v1\(\)[\s\S]+aal/iu);
  assert.match(opening, /company_access_company_year_allows_consequential_v1/iu);
  const companyYearLockAt = opening.search(/ledger\.lock_company_year_v1/iu);
  const admissionLockAt = opening.search(
    /company_access_company_year_allows_consequential_v1/iu,
  );
  assert.ok(companyYearLockAt >= 0 && admissionLockAt > companyYearLockAt);
  assert.match(opening, /insert into public\.opening_balance_setups/iu);
  assert.match(opening, /insert into public\.opening_shareholders/iu);
  assert.doesNotMatch(opening, /'(?:1920|2000|2050)'/u);
  assert.match(complete, /insert into backend_system\.ledger_workflow_receipts/iu);
  assert.doesNotMatch(source, /grant[^;]+(?:insert|update|delete)[^;]+opening_balance_setups[^;]+ledger_workflow_executor/iu);
  assert.match(source, /grant execute on function[\s\S]+ledger\.post_entry[\s\S]+to ledger_workflow_executor/iu);
});

test("consequential admission serializes with recheck and requires AAL2 plus current agreement", () => {
  const source = artifact(expandPath, "expand");
  const admission = functionBody(
    source,
    "public",
    "company_access_company_year_allows_consequential_v1",
  );
  assert.match(admission, /company_access_auth_jwt_v1\(\)[\s\S]+aal[\s\S]+aal2/iu);
  assert.match(admission, /company_access_has_current_agreement_v1/iu);
  assert.match(admission, /eligibility-recheck\|/iu);
  assert.match(admission, /pg_advisory_xact_lock/iu);
});

test("persistence enforces canonical balanced two-decimal NOK entries", () => {
  const source = artifact(expandPath, "expand");
  const validator = functionBody(source, "ledger", "entry_lines_are_valid_v1");
  const post = functionBody(source, "ledger", "post_entry");
  assert.match(validator, /jsonb_array_length\(p_lines\) < 2/iu);
  assert.match(validator, /currency[\s\S]+NOK/iu);
  assert.match(validator, /round\(v_debit, 2\)/iu);
  assert.match(validator, /round\(v_credit, 2\)/iu);
  assert.match(validator, /v_debit_total[\s\S]+v_credit_total/iu);
  assert.match(post, /insert into ledger\.entries/iu);
  assert.match(source, /unique index[^;]+company_id[^;]+source_capability[^;]+source_record_id/iu);
  assert.match(source, /unique index[^;]+company_id[^;]+income_year[^;]+OPENING_BALANCE/iu);
});

test("serialization and signed cursors are bounded and owner-only", () => {
  const source = artifact(expandPath, "expand");
  for (const name of ["post_entry", "lock_period"]) {
    assert.match(functionBody(source, "ledger", name), /ledger\.lock_company_year_v1/iu);
  }
  assert.match(source, /pg_advisory_xact_lock/iu);
  assert.match(source, /gen_random_bytes\(32\)/iu);
  assert.match(source, /'kid'/iu);
  assert.match(source, /'issuedAt'/iu);
  assert.match(source, /interval '7 days'/iu);
  assert.match(source, /length\(p_cursor\) > 4096/iu);
  assert.match(source, /cardinality\(p_company_ids\) > 100/iu);
});

test("migration evidence is pre-transform, reconciled, and immutable", () => {
  const source = artifact(expandPath, "expand");
  const snapshotAt = source.search(/insert into backend_system\.ledger_migration_source_rows/iu);
  const moveAt = source.search(/alter table public\.ledger_entries set schema ledger/iu);
  assert.ok(snapshotAt >= 0 && moveAt > snapshotAt);
  assert.match(source, /backend_system\.ledger_migration_reconciliations/iu);
  assert.match(source, /source_row_count\s*=\s*accepted_row_count\s*\+\s*quarantined_row_count/iu);
  assert.match(source, /unique\s*\(\s*run_id\s*,\s*source_table\s*,\s*source_id\s*\)/iu);
  assert.match(source, /quarantine\.run_id\s*=\s*pg_catalog\.current_setting\([\s\S]*?'talli\.ledger_migration_run_id'[\s\S]*?\)::uuid/iu);
  for (const trigger of ["ledger_command_receipts_immutable", "ledger_workflow_receipts_immutable", "ledger_migration_source_rows_immutable", "ledger_migration_quarantine_immutable", "ledger_migration_reconciliations_immutable"]) {
    assert.match(source, new RegExp(trigger, "iu"));
  }
});

test("the frozen overlap trigger can invoke private normalization helpers", () => {
  const source = artifact(expandPath, "expand");
  const trigger = functionBody(source, "ledger", "enforce_entry_v1");
  assert.match(trigger, /security definer/iu);
  assert.match(source, /alter function ledger\.enforce_entry_v1\(\)\s+owner to ledger_store_owner/iu);
});

test("contract removes legacy writers, facades, and cross-capability FKs", () => {
  const source = artifact(contractPath, "contract");
  for (const routine of ["accept_bank_transaction_suggestion", "record_share_purchase_fifo", "record_share_sale_fifo", "finalize_corporate_decision", "record_owner_dividend_payment"]) {
    assert.match(source, new RegExp(`revoke\\s+execute\\s+on\\s+function\\s+public\\.${routine}`, "iu"));
  }
  assert.match(source, /drop view public\.ledger_entries/iu);
  assert.match(source, /drop view public\.period_locks/iu);
  assert.match(source, /revoke all on ledger\.entries, ledger\.period_locks[\s\S]+authenticated/iu);
  for (const constraint of ["bank_transactions_matched_entry_id_fkey", "holding_actions_ledger_entry_id_fkey", "bank_suggestion_acceptances_ledger_entry_id_fkey", "corporate_decision_finalizations_ledger_entry_id_fkey", "ledger_entries_setup_id_fkey"]) {
    assert.match(source, new RegExp(`drop constraint if exists ${constraint}`, "iu"));
  }
});

test("rollback disables target before restoring the frozen legacy writer", () => {
  const source = artifact(rollbackPath, "rollback");
  const disableAt = source.search(/revoke all on function ledger\.post_entry/iu);
  const restoreAt = source.search(/alter table ledger\.ledger_entries set schema public/iu);
  assert.ok(disableAt >= 0 && restoreAt > disableAt);
  assert.match(source, /revoke ledger_executor from talli_ledger_backend/iu);
  assert.match(source, /revoke ledger_workflow_executor from talli_ledger_backend/iu);
  assert.match(source, /rename column entry_kind to entry_type/iu);
  assert.match(source, /grant select, insert on public\.ledger_entries to authenticated/iu);
  assert.match(source, /grant execute on function public\.accept_bank_transaction_suggestion/iu);
});
