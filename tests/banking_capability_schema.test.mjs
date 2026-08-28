import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL(
  "../supabase/migrations/20260828100000_banking_capability.sql",
  import.meta.url,
);

function artifact(path) {
  assert.equal(existsSync(path), true, "missing banking expand artifact");
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

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

test("legacy transaction writes are mirrored during expand without a second policy engine", () => {
  const source = artifact(expandPath);
  assert.match(source, /sync_legacy_bank_transaction_to_banking_v1/iu);
  assert.match(source, /sync_banking_transaction_to_legacy_v1/iu);
  assert.match(source, /sync_legacy_bank_acceptance_to_banking_v1/iu);
  assert.match(source, /pg_trigger_depth\(\)\s*>\s*1/iu);
  assert.doesNotMatch(source, /arsgebyr|bankgebyr|systemabonnement|renteinntekt/iu);
  assert.doesNotMatch(source, /['"](?:1920|6700|7770|8050)['"]/u);
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
