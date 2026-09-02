import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const migrationPath = new URL(
  "../supabase/migrations/20260828102000_banking_connections.sql",
  import.meta.url,
);
const modulePath = new URL(
  "../apps/backend/src/talli_backend/modules/banking/module.json",
  import.meta.url,
);
const systemPath = new URL("../architecture/backend-system.json", import.meta.url);

function migration() {
  assert.equal(existsSync(migrationPath), true, "missing #189 banking connection migration");
  const source = readFileSync(migrationPath, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

test("#189 owns canonical connection, account, coverage, sync, and source-file state", () => {
  const source = migration();
  for (const table of [
    "connections",
    "accounts",
    "coverage_intervals",
    "sync_attempts",
    "source_files",
  ]) {
    assert.match(source, new RegExp(`create table(?: if not exists)? banking\\.${table}`, "iu"));
    assert.match(source, new RegExp(`alter table banking\\.${table} force row level security`, "iu"));
  }
  assert.match(source, /alter table banking\.transactions[\s\S]+add column if not exists account_id/iu);
  assert.match(source, /source_kind[\s\S]+BANK_SYNC[\s\S]+BANK_CSV[\s\S]+CAMT053/iu);
  assert.match(source, /transaction_state[\s\S]+PENDING[\s\S]+BOOKED[\s\S]+REVERSED/iu);
});

test("provider identifiers, cursors, and original files are encrypted or hashed", () => {
  const source = migration();
  assert.match(source, /adapter_reference_sha256/iu);
  assert.match(source, /next_cursor_ciphertext/iu);
  assert.match(source, /content_ciphertext/iu);
  assert.match(source, /pgp_sym_encrypt/iu);
  assert.match(source, /pgp_sym_decrypt/iu);
  assert.doesNotMatch(source, /access_token|refresh_token|client_secret/iu);
});

test("sync persistence checkpoints each page and keeps accounting outside provider workflows", () => {
  const source = migration();
  assert.match(source, /banking\.prepare_sync_v1/iu);
  assert.match(source, /banking\.apply_sync_page_v1/iu);
  assert.match(source, /banking\.complete_sync_v1/iu);
  assert.match(source, /banking\.fail_sync_v1/iu);
  assert.match(source, /pg_advisory_xact_lock[\s\S]+banking-sync-fact:v1:[\s\S]+sourceHash/iu);
  assert.doesNotMatch(source, /insert into ledger\.|update ledger\.|delete from ledger\./iu);
  assert.doesNotMatch(source, /['"](?:1920|6700|7770|8050)['"]/u);
});

test("runtime roles can call checked functions but cannot mutate canonical tables", () => {
  const source = migration();
  assert.match(source, /create role banking_provider_executor nologin noinherit nobypassrls/iu);
  assert.match(source, /grant execute on function banking\.prepare_sync_v1/iu);
  assert.doesNotMatch(
    source,
    /grant[^;]+(?:insert|update|delete)[^;]+banking\.(?:connections|accounts|coverage_intervals|sync_attempts|source_files|transactions)[^;]+banking_provider_executor/iu,
  );
  assert.match(source, /company_access_is_accepted_owner_v1/iu);
  assert.match(source, /company_access_company_year_allows_consequential_v1/iu);
});

test("migration keeps auth references under the migration principal and drops borrowed authority", () => {
  const source = migration();
  assert.match(
    source,
    /create table banking\.sync_attempts[\s\S]+alter table banking\.connections owner to banking_store_owner[\s\S]+set local role banking_store_owner;[\s\S]+grant usage on schema banking to banking_provider_executor/iu,
  );
  assert.doesNotMatch(source, /grant (?:usage|references)[^;]+auth/iu);
  assert.match(source, /grant execute on function[\s\S]+pgp_sym_encrypt[\s\S]+to banking_store_owner[\s\S]+set local role banking_store_owner/iu);
  assert.match(source, /reset role;[\s\S]+revoke create on schema banking from banking_store_owner/iu);
  assert.match(source, /revoke banking_store_owner, company_access_executor from %I/iu);
});

test("manifests declare every new table and migration", () => {
  const module = JSON.parse(readFileSync(modulePath, "utf8"));
  const system = JSON.parse(readFileSync(systemPath, "utf8"));
  for (const table of [
    "banking.connections",
    "banking.accounts",
    "banking.coverage_intervals",
    "banking.sync_attempts",
    "banking.source_files",
  ]) {
    assert.ok(module.owns.tables.includes(table), table);
  }
  assert.ok(
    system.technicalOwnership.migrations.includes(
      "supabase/migrations/20260828102000_banking_connections.sql",
    ),
  );
});
