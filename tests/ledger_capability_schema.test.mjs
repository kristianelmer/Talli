import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL("../supabase/migrations/20260827100000_ledger_capability.sql", import.meta.url);
const coordinatorPath = new URL("../supabase/migrations/20260827100500_ledger_writer_coordinators.sql", import.meta.url);
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

function statementPosition(source, pattern, label) {
  const position = source.search(pattern);
  assert.notEqual(position, -1, `missing ${label}`);
  return position;
}

function assertNoRuntimeMigrationAuthority(source) {
  const runtimeRoles = "(?:public|anon|authenticated|service_role|ledger_executor|ledger_workflow_executor|talli_ledger_backend)";
  assert.doesNotMatch(
    source,
    new RegExp(
      `grant\\s+(?:ledger_store_owner|ledger_workflow_store_owner)\\s+to\\s+${runtimeRoles}`,
      "iu",
    ),
  );
  assert.doesNotMatch(
    source,
    new RegExp(
      `grant\\s+(?:usage\\s*,\\s*)?create\\s+on\\s+schema\\s+(?:ledger|backend_system)(?:\\s*,\\s*(?:ledger|backend_system))*\\s+to\\s+${runtimeRoles}`,
      "iu",
    ),
  );
}

test("ledger cutover is an atomic expand, contract, and recutover-safe rollback", () => {
  const expand = artifact(expandPath, "expand");
  const coordinators = artifact(coordinatorPath, "writer coordinator expand");
  const contract = artifact(contractPath, "contract");
  const rollback = artifact(rollbackPath, "rollback");
  assert.match(expand, /EXPAND\/MIGRATE.*ledger/iu);
  assert.match(coordinators, /EXPAND\/MIGRATE.*nine remaining ledger writers/iu);
  assert.match(contract, /CONTRACT.*ledger/iu);
  assert.match(rollback, /target writer is disabled first/iu);
  assert.doesNotMatch(rollback, /drop table[^;]+(?:ledger|receipt|reconciliation)/iu);
});

test("expand reacquires locked-schema authority for recutover and revokes it atomically", () => {
  const source = artifact(expandPath, "expand");
  const begin = statementPosition(source, /\bbegin\s*;/iu, "expand transaction");
  const rolesCreated = statementPosition(source, /\$ledger_roles\$\s*;/iu, "ledger role creation");
  const memberships = statementPosition(
    source,
    /grant\s+ledger_store_owner\s*,\s*ledger_workflow_store_owner\s*,\s*company_access_executor\s+to\s+%I['"],\s*current_user/iu,
    "temporary migration-owner memberships",
  );
  const migratorCreate = statementPosition(
    source,
    /grant\s+create\s+on\s+schema\s+ledger\s*,\s*backend_system\s+to\s+%I['"],\s*current_user/iu,
    "temporary migrator CREATE",
  );
  const ledgerOwnerCreate = statementPosition(
    source,
    /grant\s+usage\s*,\s*create\s+on\s+schema\s+ledger\s*,\s*backend_system\s+to\s+ledger_store_owner/iu,
    "temporary ledger owner CREATE",
  );
  const workflowOwnerCreate = statementPosition(
    source,
    /grant\s+create\s+on\s+schema\s+backend_system\s+to\s+ledger_workflow_store_owner/iu,
    "temporary workflow owner CREATE",
  );
  const firstLockedSchemaObject = statementPosition(
    source,
    /create\s+table\s+if\s+not\s+exists\s+backend_system\.ledger_migration_runs/iu,
    "first locked-schema object",
  );
  const migratorCreateRevoke = statementPosition(
    source,
    /revoke\s+create\s+on\s+schema\s+ledger\s*,\s*backend_system\s+from\s+%I['"],\s*current_user/iu,
    "migrator CREATE revocation",
  );
  const ledgerOwnerCreateRevoke = statementPosition(
    source,
    /revoke\s+create\s+on\s+schema\s+ledger\s*,\s*backend_system\s+from\s+ledger_store_owner/iu,
    "ledger owner CREATE revocation",
  );
  const workflowOwnerCreateRevoke = statementPosition(
    source,
    /revoke\s+create\s+on\s+schema\s+backend_system\s+from\s+ledger_workflow_store_owner/iu,
    "workflow owner CREATE revocation",
  );
  const membershipsRevoke = statementPosition(
    source,
    /revoke\s+ledger_store_owner\s*,\s*ledger_workflow_store_owner\s*,\s*company_access_executor\s+from\s+%I['"],\s*current_user/iu,
    "migration-owner membership revocations",
  );
  const commit = statementPosition(source, /\bcommit\s*;\s*$/iu, "expand commit");

  assert.ok(begin < rolesCreated);
  assert.ok(rolesCreated < memberships, "recutover authority must follow role creation immediately");
  assert.ok(memberships < migratorCreate);
  assert.ok(migratorCreate < ledgerOwnerCreate);
  assert.ok(ledgerOwnerCreate < workflowOwnerCreate);
  assert.ok(workflowOwnerCreate < firstLockedSchemaObject);
  for (const revoke of [
    migratorCreateRevoke,
    ledgerOwnerCreateRevoke,
    workflowOwnerCreateRevoke,
    membershipsRevoke,
  ]) {
    assert.ok(firstLockedSchemaObject < revoke && revoke < commit);
  }
  assertNoRuntimeMigrationAuthority(source);
});

test("contract borrows only ledger ownership and returns it before commit", () => {
  const source = artifact(contractPath, "contract");
  const begin = statementPosition(source, /\bbegin\s*;/iu, "contract transaction");
  const membership = statementPosition(
    source,
    /grant\s+ledger_store_owner\s+to\s+%I['"],\s*current_user/iu,
    "temporary contract ledger ownership",
  );
  const firstOwnedMutation = statementPosition(
    source,
    /revoke\s+all\s+on\s+ledger\.entries\s*,\s*ledger\.period_locks/iu,
    "first contract owner mutation",
  );
  const lastOwnedMutation = statementPosition(
    source,
    /alter\s+table\s+ledger\.entries\s+drop\s+column\s+setup_id/iu,
    "last contract owner mutation",
  );
  const membershipRevoke = statementPosition(
    source,
    /revoke\s+ledger_store_owner\s+from\s+%I['"],\s*current_user/iu,
    "contract ledger ownership revocation",
  );
  const commit = statementPosition(source, /\bcommit\s*;\s*$/iu, "contract commit");

  assert.ok(begin < membership);
  assert.ok(membership < firstOwnedMutation);
  assert.ok(firstOwnedMutation < lastOwnedMutation);
  assert.ok(lastOwnedMutation < membershipRevoke);
  assert.ok(membershipRevoke < commit);
  assert.doesNotMatch(source, /grant\s+ledger_workflow_store_owner\s+to\s+%I/iu);
  assert.doesNotMatch(source, /grant\s+(?:usage\s*,\s*)?create\s+on\s+schema\s+(?:ledger|backend_system)/iu);
  assertNoRuntimeMigrationAuthority(source);
});

test("rollback borrows only the ownership and schema authority its reversal needs", () => {
  const source = artifact(rollbackPath, "rollback");
  const begin = statementPosition(source, /\bbegin\s*;/iu, "rollback transaction");
  const memberships = statementPosition(
    source,
    /grant\s+ledger_store_owner\s*,\s*ledger_workflow_store_owner\s*,\s*company_archive_projection_executor\s+to\s+%I['"],\s*current_user/iu,
    "temporary rollback owner memberships",
  );
  const migratorCreate = statementPosition(
    source,
    /grant\s+create\s+on\s+schema\s+ledger\s+to\s+%I['"],\s*current_user/iu,
    "temporary rollback migrator CREATE",
  );
  const legacyOwnerCreate = statementPosition(
    source,
    /grant\s+create\s+on\s+schema\s+public\s+to\s+ledger_store_owner/iu,
    "temporary rollback legacy-owner CREATE",
  );
  const firstOwnedMutation = statementPosition(
    source,
    /revoke\s+all\s+on\s+function[\s\S]+?backend_system\.prepare_administrative_cost_v1/iu,
    "first rollback owner mutation",
  );
  const lastOwnedMutation = statementPosition(
    source,
    /grant\s+execute\s+on\s+function\s+public\.record_owner_dividend_payment/iu,
    "last rollback owner mutation",
  );
  const membershipsRevoke = statementPosition(
    source,
    /revoke\s+ledger_store_owner\s*,\s*ledger_workflow_store_owner\s*,\s*company_archive_projection_executor\s+from\s+%I['"],\s*current_user/iu,
    "rollback owner membership revocations",
  );
  const migratorCreateRevoke = statementPosition(
    source,
    /revoke\s+create\s+on\s+schema\s+ledger\s+from\s+%I['"],\s*current_user/iu,
    "rollback migrator CREATE revocation",
  );
  const legacyOwnerCreateRevoke = statementPosition(
    source,
    /revoke\s+create\s+on\s+schema\s+public\s+from\s+ledger_store_owner/iu,
    "rollback legacy-owner CREATE revocation",
  );
  const commit = statementPosition(source, /\bcommit\s*;\s*$/iu, "rollback commit");

  assert.ok(begin < memberships);
  assert.ok(memberships < migratorCreate);
  assert.ok(migratorCreate < legacyOwnerCreate);
  assert.ok(legacyOwnerCreate < firstOwnedMutation);
  assert.ok(firstOwnedMutation < lastOwnedMutation);
  assert.ok(lastOwnedMutation < migratorCreateRevoke);
  assert.ok(migratorCreateRevoke < legacyOwnerCreateRevoke);
  assert.ok(legacyOwnerCreateRevoke < membershipsRevoke);
  assert.ok(membershipsRevoke < commit);
  assert.doesNotMatch(source, /grant\s+(?:usage\s*,\s*)?create\s+on\s+schema\s+backend_system/iu);
  assertNoRuntimeMigrationAuthority(source);
});

test("nine exact writer coordinators are executor-only and never accept ledger lines", () => {
  const source = artifact(coordinatorPath, "writer coordinator expand");
  const operations = [
    "administrative_cost",
    "investment_dividend",
    "shareholder_loan",
    "tax_settlement",
    "bank_transaction_suggestion",
    "investment_purchase_fifo",
    "investment_sale_fifo",
    "corporate_decision_finalization",
    "owner_dividend_payment",
  ];
  for (const operation of operations) {
    const prepare = functionBody(source, "backend_system", `prepare_${operation}_v1`);
    const complete = functionBody(source, "backend_system", `complete_${operation}_v1`);
    assert.match(prepare, /p_verified_subject/iu);
    assert.match(prepare, /claim_ledger_writer_v1/iu);
    assert.doesNotMatch(prepare, /insert into ledger\.entries|insert into public\.ledger_entries/iu);
    assert.match(complete, /p_verified_subject/iu);
    assert.doesNotMatch(complete, /insert into ledger\.entries|insert into public\.ledger_entries/iu);
    assert.match(
      source,
      new RegExp(`grant execute on function[\\s\\S]+backend_system\\.prepare_${operation}_v1\\(jsonb, text\\)[\\s\\S]+to ledger_workflow_executor`, "iu"),
    );
    assert.match(
      source,
      new RegExp(`grant execute on function[\\s\\S]+backend_system\\.complete_${operation}_v1\\(jsonb, uuid, jsonb, text\\)[\\s\\S]+to ledger_workflow_executor`, "iu"),
    );
  }
  assert.match(source, /ledger\.post_entry_with_id_v1/iu);
  assert.match(source, /from public, anon, authenticated, service_role, ledger_executor/iu);
});

test("audit placement preserves active continuations and future atomic audits", () => {
  const source = artifact(coordinatorPath, "writer coordinator expand");
  for (const operation of [
    "administrative_cost",
    "investment_dividend",
    "shareholder_loan",
    "tax_settlement",
  ]) {
    const complete = functionBody(source, "backend_system", `complete_${operation}_v1`);
    assert.doesNotMatch(complete, /insert into public\.audit_events/iu);
    assert.match(complete, /'auditRequired', true/iu);
  }
  for (const operation of [
    "bank_transaction_suggestion",
    "investment_purchase_fifo",
    "investment_sale_fifo",
    "corporate_decision_finalization",
    "owner_dividend_payment",
  ]) {
    const complete = functionBody(source, "backend_system", `complete_${operation}_v1`);
    assert.match(complete, /insert into public\.audit_events/iu);
    assert.match(complete, /'auditRequired', false/iu);
  }
  const annual = functionBody(
    source,
    "backend_system",
    "complete_corporate_decision_finalization_v1",
  );
  assert.match(annual, /p_entry_id is null/iu);
  assert.match(annual, /annual_close_adopted/iu);
  assert.doesNotMatch(annual, /ledger\.post_entry/iu);
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

test("entry queries retain canonical source identity for archive reconstruction", () => {
  const source = artifact(expandPath, "expand");
  const listEntries = functionBody(source, "ledger", "list_entries");
  assert.match(listEntries, /'sourceCapability',\s*entry\.source_capability/iu);
  assert.match(listEntries, /'sourceRecordId',\s*entry\.source_record_id/iu);
  assert.match(listEntries, /'createdAt',\s*entry\.created_at/iu);
});

test("opening-snapshot compatibility query is bounded, member-scoped, and read-only", () => {
  const source = artifact(expandPath, "expand");
  const query = functionBody(
    source,
    "backend_system",
    "list_opening_snapshots_legacy_v1",
  );
  assert.match(query, /stable/iu);
  assert.match(query, /security definer/iu);
  assert.match(query, /set search_path = ''/iu);
  assert.match(query, /p_verified_subject/iu);
  assert.match(query, /company_access_auth_uid_v1\(\)/iu);
  assert.match(query, /cardinality\(p_company_ids\) = 0/iu);
  assert.match(query, /cardinality\(p_company_ids\) > 100/iu);
  assert.match(query, /p_limit < 1 or p_limit > 100/iu);
  assert.match(query, /length\(p_cursor\) > 4096/iu);
  assert.match(query, /count\(distinct company_id\)/iu);
  assert.match(query, /'opening_snapshots'/iu);
  assert.match(query, /ledger\.cursor_secret_v1/iu);
  assert.match(query, /limit p_limit \+ 1/iu);
  assert.match(query, /limit p_limit/iu);
  assert.match(query, /offset 100 limit 1/iu);
  assert.match(query, /bank_balance <> pg_catalog\.round\(page_setup\.bank_balance, 2\)/iu);
  assert.match(query, /share_capital <> pg_catalog\.round\(page_setup\.share_capital, 2\)/iu);
  assert.match(query, /nominal_value <> pg_catalog\.round\(page_setup\.nominal_value, 2\)/iu);
  assert.match(query, /'bankBalance',\s*setup\.bank_balance::text/iu);
  assert.match(query, /'shareCapital',\s*setup\.share_capital::text/iu);
  assert.match(query, /'nominalValue',\s*setup\.nominal_value::text/iu);
  assert.match(query, /company_access_is_accepted_member_v1/iu);
  assert.match(query, /order by snapshot\.created_at desc, snapshot\.id desc/iu);
  assert.match(query, /order by shareholder\.id/iu);
  assert.doesNotMatch(query, /\b(?:insert|update|delete)\b/iu);
  assert.match(
    source,
    /create policy "ledger workflow reads opening setups"[\s\S]+company_access_is_accepted_member_v1/iu,
  );
  assert.match(
    source,
    /create policy "ledger workflow reads opening shareholders"[\s\S]+company_access_is_accepted_member_v1/iu,
  );
  assert.match(
    source,
    /grant execute on function\s+backend_system\.list_opening_snapshots_legacy_v1\(uuid\[\], text, integer, text\)\s+to ledger_executor/iu,
  );
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
  assert.match(trigger, /to_jsonb\(new\)\s*->>\s*'setup_id'/iu);
  assert.match(trigger, /opening-setup:/iu);
  assert.doesNotMatch(trigger, /new\.setup_id/iu);
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
  assert.match(source, /ledger_contract_unsupported_legacy_setup_reference/u);
  assert.doesNotMatch(
    source,
    /drop trigger if exists company_archive_track_ledger_entries/iu,
  );
  assert.match(
    source,
    /company_archive_track_source_write_v1\(\)[\s\S]+count\(\*\)[\s\S]+ledger\.entries/iu,
  );
  assert.match(source, /company_archive_track_ledger_entries/u);
  assert.match(source, /tgenabled in \('O', 'A'\)/u);
  assert.match(source, /tgtype = 31/u);
  assert.match(source, /tgnargs = 2/u);
  assert.match(source, /7965617200636f6d70616e795f696400/u);
  assert.match(source, /ledger_archive_freshness_function_missing/u);
});

test("rollback disables target before restoring the frozen legacy writer", () => {
  const source = artifact(rollbackPath, "rollback");
  const disableAt = source.search(/revoke all on function ledger\.post_entry/iu);
  const restoreAt = source.search(/alter table ledger\.ledger_entries set schema public/iu);
  assert.ok(disableAt >= 0 && restoreAt > disableAt);
  assert.doesNotMatch(source, /revoke ledger_executor from talli_ledger_backend/iu);
  assert.doesNotMatch(
    source,
    /revoke all on function backend_system\.list_opening_snapshots_legacy_v1/iu,
  );
  assert.match(source, /revoke ledger_workflow_executor from talli_ledger_backend/iu);
  assert.match(source, /rename column entry_kind to entry_type/iu);
  assert.match(source, /grant select, insert on public\.ledger_entries to authenticated/iu);
  assert.match(source, /grant execute on function public\.accept_bank_transaction_suggestion/iu);
  assert.match(
    source,
    /drop trigger if exists company_archive_track_ledger_entries\s+on public\.ledger_entries;[\s\S]+create trigger company_archive_track_ledger_entries/iu,
  );
  assert.match(source, /ledger_archive_freshness_function_missing/u);
  assert.match(source, /opening-setup:[\s\S]+new\.setup_id/iu);
});
