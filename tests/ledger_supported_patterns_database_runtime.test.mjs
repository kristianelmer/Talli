import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(new URL(
  "../supabase/migrations/20260827102000_ledger_supported_patterns.sql",
  import.meta.url,
), "utf8");
const predecessorExpand = readFileSync(new URL(
  "../supabase/migrations/20260827100000_ledger_capability.sql",
  import.meta.url,
), "utf8");
const receivedDividendMigrationUrl = new URL(
  "../supabase/migrations/20260827105000_ledger_received_dividend_lifecycle.sql",
  import.meta.url,
);
const receivedDividendMigration = existsSync(receivedDividendMigrationUrl)
  ? readFileSync(receivedDividendMigrationUrl, "utf8")
  : "";
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
    "CAPITAL_REDUCTION",
    "COMPANY_TAX_ACCRUAL",
    "GROUP_CONTRIBUTION",
    "INTERCOMPANY_LOAN",
    "CORRECTION_REVERSAL",
  ]) {
    assert.match(predecessorExpand, new RegExp(`'${entryKind}'`, "u"));
  }
  assert.match(lifecycle, /psql\(containerName, \["--file", expandPath\]\);[\s\S]+psql\(containerName, \["--file", supportedPatternsPath\]\);/u);
});

test("received-dividend lifecycle state is immutable, forced-RLS, and executor-only", () => {
  assert.ok(
    receivedDividendMigration,
    "missing additive received-dividend lifecycle migration",
  );
  for (const table of ["received_dividend_decisions", "received_dividend_settlements"]) {
    assert.match(
      receivedDividendMigration,
      new RegExp(`alter table ledger\\.${table} force row level security`, "iu"),
    );
    assert.match(
      receivedDividendMigration,
      new RegExp(`create trigger ledger_${table}_immutable`, "iu"),
    );
    assert.doesNotMatch(
      receivedDividendMigration,
      new RegExp(`grant[^;]+(?:insert|update|delete)[^;]+ledger\\.${table}[^;]+ledger_executor`, "iu"),
    );
  }
  assert.match(receivedDividendMigration, /decision_entry_id uuid primary key/iu);
  assert.match(receivedDividendMigration, /payment_entry_id uuid/iu);
  assert.match(receivedDividendMigration, /payment_entry_id uuid not null unique/iu);
});

test("received-dividend wrappers coordinate lifecycle around the canonical posting seam", () => {
  for (const wrapperName of [
    "record_received_dividend_decision_v1",
    "record_received_dividend_payment_v1",
  ]) {
    const wrapper = receivedDividendMigration.match(
      new RegExp(
        `create or replace function ledger\\.${wrapperName}\\([\\s\\S]+?\\$function\\$\\s*;`,
        "iu",
      ),
    )?.[0];
    assert.ok(wrapper, `missing ${wrapperName}`);
    assert.match(wrapper, /from ledger\.post_supported_entry_v1\(/iu);
    assert.doesNotMatch(wrapper, /'1530'|'8070'|'1920'/u);
    assert.doesNotMatch(wrapper, /case\s+when[^;]+account|when\s+'\d{4}'/iu);
  }
  assert.match(
    receivedDividendMigration,
    /record_received_dividend_payment_v1\(\s*p_idempotency_key text,\s*p_company_id uuid,\s*p_income_year integer,\s*p_decision_entry_id uuid/iu,
  );
});

test("fresh lifecycle covers received-dividend replay, failure atomicity, and cutover", () => {
  assert.match(
    lifecycle,
    /20260827105000_ledger_received_dividend_lifecycle\.sql/iu,
  );
  assert.match(lifecycle, /record_received_dividend_decision_v1/iu);
  assert.match(lifecycle, /record_received_dividend_payment_v1/iu);
  assert.match(lifecycle, /received_dividend_decisions/iu);
  assert.match(lifecycle, /received_dividend_settlements/iu);
  assert.match(lifecycle, /received-dividend-decision-runtime/u);
  assert.match(lifecycle, /received-dividend-payment-runtime/u);
});
