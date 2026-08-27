import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(new URL(
  "../supabase/migrations/20260827102000_ledger_supported_patterns.sql",
  import.meta.url,
), "utf8");
const predecessorExpand = readFileSync(new URL(
  "../supabase/migrations/20260827100000_ledger_capability.sql",
  import.meta.url,
), "utf8");
const lifecycle = readFileSync(new URL(
  "./ledger_database_runtime.test.mjs",
  import.meta.url,
), "utf8");

test("supported entries persist immutable event and source provenance", () => {
  for (const table of ["entry_contexts", "entry_sources"]) {
    assert.match(migration, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.match(migration, new RegExp(`create trigger ledger_${table}_immutable`, "iu"));
    assert.doesNotMatch(
      migration,
      new RegExp(`grant[^;]+(?:insert|update|delete)[^;]+ledger\\.${table}[^;]+ledger_executor`, "iu"),
    );
  }
  assert.match(migration, /event_date date not null/iu);
  assert.match(migration, /rule_version text not null/iu);
  assert.match(migration, /fact_sha256 text not null/iu);
  assert.match(migration, /source_revision integer not null/iu);
  assert.match(migration, /ledger_entry_sources_one_primary_uidx/iu);
});

test("SQL keeps accounting policy out and delegates to the canonical writer", () => {
  const wrapper = migration.match(
    /create or replace function ledger\.post_supported_entry_v1\([\s\S]+?\$function\$\s*;/iu,
  )?.[0];
  assert.ok(wrapper);
  assert.match(wrapper, /from ledger\.post_entry\(/iu);
  assert.doesNotMatch(wrapper, /when 'BANK_INTEREST'|when 'GROUP_CONTRIBUTION'/iu);
  assert.doesNotMatch(wrapper, /'1920'|'8050'|'8075'|'2030'/u);
  assert.match(wrapper, /ledger_idempotency_key_reused/iu);
  assert.match(wrapper, /sources_digest = v_sources_digest/iu);
});

test("fresh database lifecycle proves replay, RLS, provenance, and recutover", () => {
  assert.match(lifecycle, /20260827102000_ledger_supported_patterns\.sql/iu);
  assert.match(lifecycle, /post_supported_entry_v1/iu);
  assert.match(lifecycle, /golden:runtime-bank-interest/u);
  assert.match(lifecycle, /ledger_idempotency_key_reused/iu);
  assert.match(lifecycle, /insert into ledger\.entry_sources/iu);
});

test("the predecessor expand remains forward-compatible during recutover", () => {
  for (const entryKind of [
    "BANK_INTEREST",
    "BANK_LOAN",
    "CAPITAL_INCREASE",
    "COMPANY_TAX_ACCRUAL",
    "GROUP_CONTRIBUTION",
  ]) {
    assert.match(predecessorExpand, new RegExp(`'${entryKind}'`, "u"));
  }
  assert.match(lifecycle, /psql\(containerName, \["--file", expandPath\]\);[\s\S]+psql\(containerName, \["--file", supportedPatternsPath\]\);/u);
});
