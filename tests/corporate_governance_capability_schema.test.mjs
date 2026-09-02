import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL(
  "../supabase/migrations/20260902040000_corporate_governance_owner_dividend.sql",
  import.meta.url,
);
const rollbackPath = new URL(
  "../supabase/rollback/20260902040000_corporate_governance_owner_dividend.sql",
  import.meta.url,
);

function artifact(path, phase) {
  assert.equal(existsSync(path), true, `missing governance ${phase} artifact`);
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  assert.doesNotMatch(source, /\btruncate\b/iu);
  return source;
}

test("owner-dividend expand owns an isolated forced-RLS store", () => {
  const source = artifact(expandPath, "expand");
  assert.match(source, /create role corporate_governance_store_owner\s+nologin noinherit nobypassrls/iu);
  assert.match(source, /create role corporate_governance_workflow_executor\s+nologin noinherit nobypassrls/iu);
  assert.match(source, /create schema if not exists corporate_governance\s+authorization corporate_governance_store_owner/iu);

  for (const table of [
    "owner_dividend_decisions",
    "owner_dividend_artifacts",
    "owner_dividend_events",
    "owner_dividend_finalizations",
    "owner_dividend_payments",
  ]) {
    assert.match(source, new RegExp(`create table corporate_governance\\.${table}`, "iu"));
    assert.match(source, new RegExp(`alter table corporate_governance\\.${table}\\s+enable row level security`, "iu"));
    assert.match(source, new RegExp(`alter table corporate_governance\\.${table}\\s+force row level security`, "iu"));
    assert.match(source, new RegExp(`alter table corporate_governance\\.${table}\\s+owner to corporate_governance_store_owner`, "iu"));
    assert.match(source, new RegExp(`revoke all on corporate_governance\\.${table}[\\s\\S]+corporate_governance_workflow_executor`, "iu"));
  }
  assert.doesNotMatch(
    source,
    /grant (?:select|insert|update|delete|all)[\s\S]+to (?:public|anon|authenticated|service_role)/iu,
  );
});

test("owner-dividend lifecycle is available only through exact restricted routines", () => {
  const source = artifact(expandPath, "expand");
  const routines = [
    "actor_company_role_v1",
    "propose_owner_dividend_v1",
    "register_owner_dividend_documents_v1",
    "approve_owner_dividend_v1",
    "prepare_owner_dividend_finalization_v1",
    "complete_owner_dividend_finalization_v1",
    "prepare_owner_dividend_payment_v1",
    "complete_owner_dividend_payment_v1",
  ];
  for (const routine of routines) {
    assert.match(source, new RegExp(`function\\s+corporate_governance\\.${routine}`, "iu"));
  }
  assert.match(source, /function ledger\.post_corporate_governance_entry_v1/iu);
  assert.match(source, /function banking\.claim_owner_dividend_transaction_v1/iu);
  assert.match(source, /grant execute on function[\s\S]+to corporate_governance_workflow_executor/iu);
  assert.doesNotMatch(source, /grant execute on function[\s\S]+to (?:public|anon|authenticated|service_role)/iu);
  assert.doesNotMatch(source, /\b(?:2050|2920|1920|no-holding-v1)\b/u);
});

test("owner-dividend persistence is exact-replay, append-only, and reversible", () => {
  const source = artifact(expandPath, "expand");
  const rollback = artifact(rollbackPath, "rollback");
  assert.match(source, /corporate_governance_idempotency_conflict/iu);
  assert.match(source, /prevent_corporate_governance_mutation/iu);
  assert.match(source, /before update or delete/iu);
  assert.match(source, /for update/iu);
  assert.match(source, /company_access_is_accepted_owner_v1/iu);
  assert.match(source, /company_access_company_year_allows_consequential_v1/iu);
  assert.match(source, /talli\.verified_actor_id/iu);
  assert.match(source, /company_access_company_year_allows_consequential_v1/iu);

  for (const table of [
    "owner_dividend_payments",
    "owner_dividend_finalizations",
    "owner_dividend_events",
    "owner_dividend_artifacts",
    "owner_dividend_decisions",
  ]) {
    assert.match(rollback, new RegExp(`drop table corporate_governance\\.${table}`, "iu"));
  }
  assert.match(rollback, /drop function ledger\.post_corporate_governance_entry_v1/iu);
  assert.match(rollback, /drop function banking\.claim_owner_dividend_transaction_v1/iu);
  assert.match(rollback, /drop schema corporate_governance/iu);
});
