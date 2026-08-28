import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL(
  "../supabase/migrations/20260828100000_banking_capability.sql",
  import.meta.url,
);
const workflowPath = new URL(
  "../supabase/migrations/20260828100500_banking_workflows.sql",
  import.meta.url,
);
const overlapPolicyPath = new URL(
  "../supabase/migrations/20260828100600_banking_overlap_trigger_policy.sql",
  import.meta.url,
);
const contractPath = new URL(
  "../supabase/contract-migrations/20260828101000_banking_capability_contract.sql",
  import.meta.url,
);
const rollbackPath = new URL(
  "../supabase/rollback/20260828101000_banking_capability_contract.sql",
  import.meta.url,
);
const localGatePath = new URL(
  "../scripts/test-supabase-local.sh",
  import.meta.url,
);

function artifact(path) {
  assert.equal(existsSync(path), true, "missing banking expand artifact");
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

function workflowArtifact() {
  assert.equal(existsSync(workflowPath), true, "missing banking workflow artifact");
  const source = readFileSync(workflowPath, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

function releaseArtifact(path, phase) {
  assert.equal(existsSync(path), true, `missing banking ${phase} artifact`);
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

test("the complete local database gate includes banking contract and rollback", () => {
  const source = readFileSync(localGatePath, "utf8");
  assert.match(source, /npm run test:banking-database-lifecycle/iu);
});

test("banking expand is overlap-safe and preserves stable source identities", () => {
  const source = artifact(expandPath);
  assert.match(source, /EXPAND\/MIGRATE.*banking/iu);
  assert.match(source, /create schema if not exists banking/iu);
  assert.match(source, /create table if not exists banking\.transactions/iu);
  assert.match(source, /create table if not exists banking\.suggestion_acceptances/iu);
  assert.match(source, /insert into banking\.transactions[\s\S]+select[\s\S]+bank_row\.id/iu);
  assert.match(source, /insert into banking\.suggestion_acceptances[\s\S]+select[\s\S]+acceptance\.id/iu);
  assert.doesNotMatch(source, /drop table (?:if exists )?public\.bank_/iu);
  assert.doesNotMatch(source, /alter table public\.bank_(?:transactions|suggestion_acceptances) set schema/iu);
});

test("migration evidence proves exact count and canonical hash reconciliation", () => {
  const source = artifact(expandPath);
  for (const table of [
    "banking_migration_runs",
    "banking_migration_source_rows",
    "banking_migration_reconciliations",
  ]) {
    assert.match(source, new RegExp(`backend_system\\.${table}`, "iu"));
  }
  assert.match(source, /source_row_count\s*=\s*target_row_count/iu);
  assert.match(source, /source_sha256\s*=\s*target_sha256/iu);
  assert.match(source, /banking_migration_evidence_is_immutable/iu);
});

test("banking migrations borrow and revoke backend-system schema authority", () => {
  for (const source of [artifact(expandPath), workflowArtifact()]) {
    assert.match(source, /grant ledger_store_owner,[^;]+to %I/iu);
    assert.match(source, /set local role ledger_store_owner/iu);
    assert.match(
      source,
      /grant usage, create on schema backend_system to %I/iu,
    );
    assert.match(
      source,
      /revoke create on schema backend_system from %I/iu,
    );
    assert.match(source, /revoke ledger_store_owner,[^;]+from %I/iu);
  }
});

test("legacy transaction writes are mirrored during expand without a second policy engine", () => {
  const source = artifact(expandPath);
  const overlapPolicy = releaseArtifact(overlapPolicyPath, "overlap policy");
  assert.match(source, /sync_legacy_bank_transaction_to_banking_v1/iu);
  assert.match(source, /sync_banking_transaction_to_legacy_v1/iu);
  assert.match(source, /sync_legacy_bank_acceptance_to_banking_v1/iu);
  assert.match(source, /pg_trigger_depth\(\)\s*>\s*1/iu);
  assert.doesNotMatch(source, /arsgebyr|bankgebyr|systemabonnement|renteinntekt/iu);
  assert.doesNotMatch(source, /['"](?:1920|6700|7770|8050)['"]/u);
  assert.match(overlapPolicy, /pg_trigger_depth\(\)\s*>\s*0/iu);
  assert.match(overlapPolicy, /company_access_is_accepted_owner_v1\(company_id\)/iu);
  assert.match(overlapPolicy, /banking overlap mirrors legacy acceptances/iu);
  assert.match(overlapPolicy, /accepted_by\s*=\s*public\.company_access_auth_uid_v1\(\)/iu);
  assert.match(overlapPolicy, /banking overlap mirrors canonical transactions/iu);
  assert.match(overlapPolicy, /sync_banking_acceptance_to_legacy_v1/iu);
  assert.match(overlapPolicy, /banking overlap mirrors canonical acceptances/iu);
  assert.match(
    overlapPolicy,
    /grant select, insert, update, delete on public\.bank_transactions[\s\S]+to banking_store_owner/iu,
  );
  assert.match(overlapPolicy, /banking workflow appends audit events/iu);
  assert.match(overlapPolicy, /actor_id\s*=\s*public\.company_access_auth_uid_v1\(\)/iu);
  assert.match(overlapPolicy, /grant insert on public\.audit_events to banking_store_owner/iu);
  assert.match(overlapPolicy, /grant usage on schema ledger to banking_store_owner/iu);
  assert.doesNotMatch(overlapPolicy, /company_year_allows_consequential/iu);
  assert.match(overlapPolicy, /grant banking_store_owner to %I/iu);
  assert.match(overlapPolicy, /grant ledger_store_owner to %I/iu);
  assert.match(overlapPolicy, /set local role banking_store_owner/iu);
  assert.match(overlapPolicy, /revoke banking_store_owner from %I/iu);
  assert.match(overlapPolicy, /revoke ledger_store_owner from %I/iu);
});

test("canonical banking data is forced-RLS and runtime roles cannot write tables directly", () => {
  const source = artifact(expandPath);
  assert.match(source, /alter table banking\.transactions enable row level security/iu);
  assert.match(source, /alter table banking\.transactions force row level security/iu);
  assert.match(source, /alter table banking\.suggestion_acceptances force row level security/iu);
  assert.match(source, /create role banking_executor nologin noinherit nobypassrls/iu);
  assert.match(source, /create role banking_store_owner nologin noinherit nobypassrls/iu);
  assert.doesNotMatch(
    source,
    /grant[^;]+(?:insert|update|delete)[^;]+banking\.(?:transactions|suggestion_acceptances)[^;]+banking_executor/iu,
  );
});

test("canonical acceptances store source decisions, not ledger policy copies", () => {
  const source = artifact(expandPath);
  const table = source.match(
    /create table if not exists banking\.suggestion_acceptances\s*\([\s\S]+?\n\);/iu,
  )?.[0];
  assert.ok(table);
  assert.doesNotMatch(table, /\blines\b|\baccount\b|\bmemo\b/iu);
  assert.match(table, /accounting_entry_id uuid/iu);
  assert.match(table, /suggestion_kind text/iu);
});

test("banking workflow locks source facts and delegates the only posting to ledger", () => {
  const source = workflowArtifact();
  assert.match(source, /banking\.prepare_suggestion_acceptance_v1/iu);
  assert.match(source, /from banking\.transactions bank_row[\s\S]+for update/iu);
  assert.match(source, /banking\.complete_suggestion_acceptance_v1/iu);
  assert.match(source, /grant execute on function[\s\S]+ledger\.post_entry[\s\S]+to banking_workflow_executor/iu);
  assert.doesNotMatch(source, /insert into ledger\.entries|insert into public\.ledger_entries/iu);
  assert.doesNotMatch(source, /arsgebyr|bankgebyr|systemabonnement|renteinntekt/iu);
  assert.doesNotMatch(source, /['"](?:1920|6700|7770|8050)['"]/u);
});

test("statement import is durable-idempotent and provider data cannot select accounting", () => {
  const source = workflowArtifact();
  assert.match(source, /backend_system\.banking_command_receipts/iu);
  assert.match(source, /banking\.import_statement_v1/iu);
  assert.match(source, /on conflict \(company_id, income_year, source_hash\) do nothing/iu);
  assert.match(source, /banking_idempotency_key_reused/iu);
  assert.doesNotMatch(source, /p_request\s*->>?\s*['"](?:account|lines|memo)/iu);
});

test("banking reads are tenant-scoped deterministic cursor pages", () => {
  const source = workflowArtifact();
  assert.match(source, /banking\.list_records_v1/iu);
  assert.match(source, /company_id\s*=\s*any\(p_company_ids\)/iu);
  assert.match(source, /company_access_is_accepted_member_v1/iu);
  assert.match(source, /order by sort_at desc, id desc/iu);
  assert.match(source, /p_limit \+ 1/iu);
  assert.match(source, /banking_invalid_cursor/iu);
});

test("banking contract removes legacy storage only after live exact reconciliation", () => {
  const source = releaseArtifact(contractPath, "contract");
  assert.match(source, /CONTRACT RELEASE ARTIFACT:.*#140/iu);
  assert.match(source, /pg_advisory_xact_lock[\s\S]+banking:capability-cutover:v1/iu);
  assert.match(source, /lock table public\.bank_transactions[\s\S]+public\.bank_suggestion_acceptances/iu);
  assert.match(source, /banking_contract_transaction_reconciliation_failed/iu);
  assert.match(source, /banking_contract_acceptance_reconciliation_failed/iu);
  assert.match(source, /source_row_count\s*(?:<>|!=)\s*target_row_count/iu);
  assert.match(source, /source_sha256\s*(?:<>|!=)\s*target_sha256/iu);
  assert.match(source, /drop table if exists public\.bank_suggestion_acceptances/iu);
  assert.match(source, /drop table if exists public\.bank_transactions/iu);
  assert.match(source, /create view public\.bank_transactions/iu);
  assert.match(source, /create view public\.bank_suggestion_acceptances/iu);
});

test("banking contract leaves one canonical writer and no SQL suggestion-policy copy", () => {
  const source = releaseArtifact(contractPath, "contract");
  assert.match(source, /drop policy if exists "banking overlap mirrors legacy transactions"/iu);
  assert.match(source, /drop policy if exists "banking overlap mirrors legacy acceptances"/iu);
  assert.match(source, /drop policy if exists "banking overlap mirrors canonical transactions"/iu);
  assert.match(source, /drop function public\.accept_bank_transaction_suggestion\(uuid, text, text\)/iu);
  assert.match(source, /drop function backend_system\.prepare_bank_transaction_suggestion_v1\(jsonb, text\)/iu);
  assert.match(source, /drop function backend_system\.complete_bank_transaction_suggestion_v1\(jsonb, uuid, jsonb, text\)/iu);
  assert.match(source, /drop function backend_system\.sync_legacy_bank_transaction_to_banking_v1\(\)/iu);
  assert.match(source, /drop function backend_system\.sync_banking_transaction_to_legacy_v1\(\)/iu);
  assert.match(source, /drop function backend_system\.sync_legacy_bank_acceptance_to_banking_v1\(\)/iu);
  assert.match(source, /drop function backend_system\.sync_banking_acceptance_to_legacy_v1\(\)/iu);
  assert.doesNotMatch(source, /arsgebyr|bankgebyr|systemabonnement|renteinntekt/iu);
  assert.doesNotMatch(source, /['"](?:1920|6700|7770|8050)['"]/u);
  assert.doesNotMatch(source, /grant[^;]+(?:insert|delete)[^;]+public\.bank_/iu);
  assert.doesNotMatch(source, /grant[^;]+(?:insert|update|delete)[^;]+public\.bank_[^;]+authenticated/iu);
});

test("banking contract preserves only bounded future seams and archive freshness", () => {
  const source = releaseArtifact(contractPath, "contract");
  assert.match(
    source,
    /holding_actions_bank_transaction_id_fkey[\s\S]+references banking\.transactions\(id\)/iu,
  );
  assert.match(
    source,
    /create trigger company_archive_track_bank_suggestion_acceptances[\s\S]+on banking\.suggestion_acceptances/iu,
  );
  assert.match(source, /lower\(acceptance\.suggestion_kind\)\s+as rule_id/iu);
  assert.match(source, /entry\.lines/iu);
  assert.match(source, /company_archive_can_read_banking_acceptance_v1\([\s\S]+acceptance\.company_id/iu);
  assert.match(source, /select public\.company_access_is_accepted_member_v1\(p_company_id\)/iu);
  assert.match(source, /revoke all on public\.bank_transactions[\s\S]+from public, anon, authenticated, service_role/iu);
  assert.match(source, /grant select on public\.bank_suggestion_acceptances to authenticated/iu);
});

test("banking rollback restores the predecessor and supports deterministic recutover", () => {
  const source = releaseArtifact(rollbackPath, "rollback");
  assert.match(source, /target writer is disabled first/iu);
  assert.match(source, /create table if not exists public\.bank_transactions/iu);
  assert.match(source, /create table if not exists public\.bank_suggestion_acceptances/iu);
  assert.match(source, /insert into public\.bank_transactions[\s\S]+from banking\.transactions/iu);
  assert.match(source, /insert into public\.bank_suggestion_acceptances[\s\S]+from banking\.suggestion_acceptances/iu);
  assert.match(source, /create or replace function public\.accept_bank_transaction_suggestion/iu);
  assert.match(source, /bank_transactions_sync_to_banking/iu);
  assert.match(source, /banking_transactions_sync_to_legacy/iu);
  assert.match(source, /bank_acceptances_sync_to_banking/iu);
  assert.match(source, /banking_acceptances_sync_to_legacy/iu);
  assert.match(source, /create policy "banking overlap mirrors legacy transactions"/iu);
  assert.match(source, /create policy "banking overlap mirrors legacy acceptances"/iu);
  assert.match(source, /create policy "banking overlap mirrors canonical transactions"/iu);
  assert.match(source, /create policy "banking overlap mirrors canonical acceptances"/iu);
  assert.doesNotMatch(source, /drop table[^;]+banking\./iu);
});
