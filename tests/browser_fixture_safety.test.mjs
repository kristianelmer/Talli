import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";
import test from "node:test";

import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

test("Supabase browser fixtures only accept loopback URLs", () => {
  for (const value of [
    "http://127.0.0.1:54321",
    "http://localhost:54321",
    "http://[::1]:54321",
  ]) {
    assert.equal(isLoopbackSupabaseUrl(value), true, value);
  }

  for (const value of [
    "https://project.supabase.co",
    "https://localhost.example.com",
    "https://127.0.0.1.example.com",
    "not-a-url",
  ]) {
    assert.equal(isLoopbackSupabaseUrl(value), false, value);
  }
});

test("browser database fixtures only accept loopback PostgreSQL URLs", () => {
  for (const value of [
    "postgres://postgres:postgres@127.0.0.1:54322/postgres",
    "postgresql://postgres:postgres@localhost:54322/postgres",
    "postgresql://postgres:postgres@[::1]:54322/postgres",
  ]) {
    assert.equal(isLoopbackPostgresUrl(value), true, value);
  }

  for (const value of [
    "postgresql://postgres:secret@database.example.com/postgres",
    "postgresql://postgres:secret@localhost.example.com/postgres",
    "https://localhost:54322/postgres",
    "not-a-url",
  ]) {
    assert.equal(isLoopbackPostgresUrl(value), false, value);
  }
});

test("owner browser harness stops before remote fixture creation", () => {
  const harnessPath = fileURLToPath(
    new URL("./browser_owner_annual_loop.mjs", import.meta.url),
  );
  const env = {
    ...process.env,
    DATABASE_URL: "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "remote-test-key",
    NEXT_PUBLIC_SUPABASE_URL: "https://remote.invalid",
    SUPABASE_ANON_KEY: "remote-test-key",
    SUPABASE_SERVICE_ROLE_KEY: "remote-test-service-key",
    SUPABASE_URL: "https://remote.invalid",
  };
  delete env.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [harnessPath], {
    encoding: "utf8",
    env,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Browser fixtures require local Supabase/u);
});

test("owner browser harness rejects a remote database mixed with local Supabase", () => {
  const harnessPath = fileURLToPath(
    new URL("./browser_owner_annual_loop.mjs", import.meta.url),
  );
  const env = {
    ...process.env,
    DATABASE_URL:
      "postgresql://postgres:secret@database.example.invalid/postgres",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "local-test-key",
    NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54321",
    SUPABASE_ANON_KEY: "local-test-key",
    SUPABASE_SERVICE_ROLE_KEY: "local-test-service-key",
    SUPABASE_URL: "http://127.0.0.1:54321",
  };
  delete env.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [harnessPath], {
    encoding: "utf8",
    env,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Browser fixtures require local database/u);
});


test("retained annual browser seeds canonical historical RF/AU facts without replacing the live simulation", async () => {
  const source = readFileSync(new URL("./browser_owner_annual_loop.mjs", import.meta.url), "utf8");
  const seedSource = source.slice(source.indexOf("async function seedAnnualLoop("), source.indexOf("async function establishOwnerAal2("));
  const sql = [];
  const inserts = [];
  const borrowed = [];
  const database = { async query(statement, values) {
    sql.push({ statement, values });
    return { rows: [{ id: "fixture-permission", exact: true, count: 0, absent: true }] };
  } };
  const admin = { from(table) { return { async insert(value) { inserts.push({ table, value }); return { error: null }; } }; } };
  const seed = vm.runInNewContext(`(${seedSource.trim()})`, {
    assert, createHash,
    async assertNoError(query) { assert.ifError((await query).error); },
    async fixtureTableTransaction(actualDatabase, tables, operation) {
      assert.equal(actualDatabase, database);
      borrowed.push(...tables);
      return operation();
    },
  });
  const ids = Object.fromEntries(["companyId", "setupId", "shareholderId", "previewId", "systemUserRequestId", "ownerId", "orgNumber"].map((name, index) => [name, `fixture-${index}`]));
  let created = 0;
  await seed(admin, database, ids, () => { created += 1; });
  assert.equal(created, 1);
  const statements = sql.map(row => row.statement).join("\n");
  assert.match(statements, /insert into authority_connections\.system_user_requests/u);
  assert.doesNotMatch(statements, /insert into public\.system_user_requests/u);
  assert.match(statements, /insert into shareholder_register_filing\.filing_previews/u);
  assert.match(statements, /insert into shareholder_register_filing\.authority_permissions/u);
  assert.match(statements, /insert into ledger\.opening_bank_inputs/u);
  for (const table of ["opening_balance_setups", "opening_shareholders"]) {
    const row = sql.find(row => row.statement.includes(`insert into shareholder_register_filing.${table}`));
    assert.ok(row, `${table} retains its canonical historical source`);
    assert.ok(row.values.includes(table === "opening_shareholders" ? ids.shareholderId : ids.setupId));
    assert.ok(row.values.includes(ids.companyId) && row.values.includes(ids.ownerId));
  }
  assert.doesNotMatch(statements, /insert into public\.opening_(?:balance_setups|shareholders)/u);
  const opening = sql.find(row => row.statement.includes("insert into ledger.entries"));
  assert.doesNotMatch(opening.statement, /setup_id/u);
  assert.ok(opening.values.includes(`opening-setup:${ids.setupId}`));
  assert.ok(borrowed.includes("ledger.entries"));
  assert.ok(borrowed.includes("authority_connections.system_user_requests"));
  assert.ok(borrowed.includes("shareholder_register_filing.filing_previews"));
  assert.doesNotMatch(statements, /insert into public\.(?:filing_previews|authority_permissions)/u);
  for (const family of ["filing_previews", "filing_submissions", "filing_overrides", "filing_review_comments", "authority_permissions", "authority_test_runs"]) {
    assert.ok(sql.some(row => row.statement.includes("to_regclass($1) is null") && row.values[0] === `public.${family}`));
    assert.ok(!borrowed.includes(`public.${family}`));
  }
  const preview = sql.find(row => row.statement.includes("insert into shareholder_register_filing.filing_previews"));
  assert.ok(preview.values.includes(ids.previewId) && preview.values.includes(ids.setupId));
  assert.ok(preview.values.includes("<RF-1086><org>test</org></RF-1086>"));
  assert.equal(JSON.parse(preview.values.find(value => typeof value === "string" && value.startsWith("{")))[ids.shareholderId],
    "<RF-1086U><shareholder>test</shareholder></RF-1086U>");
  assert.ok(!inserts.some(row => row.table === "authority_permissions"));
  const accountsPermission = sql.find(row => row.statement.includes("insert into annual_accounts_filing.authority_permissions"));
  assert.ok(accountsPermission);
  assert.deepEqual(Array.from(accountsPermission.values), [ids.companyId, ids.ownerId]);
  assert.match(accountsPermission.statement, /values\(\$1,'aarsregnskap',\$2,\$2,true\)/u);
  assert.ok(borrowed.includes("annual_accounts_filing.authority_permissions"));
  const taxPermission = sql.find(row => row.statement.includes("insert into company_tax_filing.authority_permissions"));
  assert.ok(taxPermission, "Tax permission must use the contracted owner");
  assert.deepEqual(Array.from(taxPermission.values), [ids.companyId, ids.ownerId]);
  assert.match(taxPermission.statement, /values\(\$1,'skattemelding',\$2,\$2,true\)/u);
  assert.ok(borrowed.includes("company_tax_filing.authority_permissions"));
  assert.doesNotMatch(statements, /insert into (?:public|shareholder_register_filing)\.(?:filing_submissions|filing_approval_snapshots|production_filing_submissions)/u);
  assert.doesNotMatch(statements, /(?:paid|charge)_at|billing_accounts/u);
  assert.match(source, /set local role ledger_executor/u);
  assert.match(source, /backend_system\.read_new_year_opening_snapshots_v1/u);
  assert.doesNotMatch(source, /backend_system\.list_opening_snapshots_legacy_v1/u);
  assert.match(source, /Arkiver simulert kvittering/u);
});
