import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(
  new URL(
    "../supabase/migrations/20260827109000_ledger_opening_position_rebuild.sql",
    import.meta.url,
  ),
  "utf8",
);
const contract = readFileSync(
  new URL(
    "../supabase/contract-migrations/20260827101000_ledger_capability_contract.sql",
    import.meta.url,
  ),
  "utf8",
);
const rollback = readFileSync(
  new URL(
    "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
    import.meta.url,
  ),
  "utf8",
);

test("opening rebuild, components, and provenance are immutable forced-RLS records", () => {
  for (const table of [
    "opening_position_rebuilds",
    "opening_position_components",
    "opening_position_component_sources",
  ]) {
    assert.match(migration, new RegExp(`create table if not exists ledger\\.${table}`, "iu"));
    assert.match(migration, new RegExp(`alter table ledger\\.${table} enable row level security`, "iu"));
    assert.match(migration, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.match(migration, new RegExp(`before update or delete on ledger\\.${table}`, "iu"));
  }
  assert.doesNotMatch(
    migration,
    /grant[^;]+opening_position_[^;]+(?:authenticated|ledger_executor|ledger_workflow_executor)/iu,
  );
});

test("the receiver is executor-only and persists one atomic typed opening journal", () => {
  assert.match(migration, /create or replace function ledger\.rebuild_company_year_opening_v1/iu);
  assert.match(migration, /security definer[\s\S]+set search_path = ''/iu);
  assert.match(migration, /ledger\.post_supported_entry_v1\([\s\S]+'OPENING_BALANCE'/iu);
  assert.match(migration, /insert into ledger\.opening_position_rebuilds[\s\S]+insert into ledger\.opening_position_components[\s\S]+insert into ledger\.opening_position_component_sources/iu);
  assert.match(migration, /grant execute on function ledger\.rebuild_company_year_opening_v1[\s\S]+to ledger_executor/iu);
  assert.doesNotMatch(migration, /p_(?:account|debit|credit)/iu);
});

test("bank-loan components are an exact journal-backed payment basis", () => {
  assert.match(migration, /category = 'BANK_LOAN_PAYABLE'/iu);
  assert.match(migration, /ledger:bank-loan:v1:/iu);
  assert.match(migration, /from ledger\.bank_loan_anchors/iu);
  assert.match(migration, /from ledger\.opening_position_components/iu);
  assert.match(migration, /ledger\.bank_loan_principal_basis_v1/iu);
  assert.match(migration, /ledger_bank_loan_principal_exceeded/iu);
});

test("full-state digest includes opening and lifecycle facts", () => {
  for (const key of [
    "openingRebuilds",
    "openingComponents",
    "openingSources",
    "bankLoanAnchors",
    "bankLoanPayments",
    "receivedDividendDecisions",
    "capitalIncreasePhases",
    "capitalReductionPhases",
  ]) assert.match(migration, new RegExp(`'${key}'`, "u"));
});

test("contract requires the receiver and rollback revokes it without deleting facts", () => {
  const signature = /ledger\.rebuild_company_year_opening_v1\(text,uuid,integer,date,text,jsonb,text,text,text,text,jsonb,jsonb\)/iu;
  assert.match(contract, signature);
  assert.match(rollback, /revoke all on function ledger\.rebuild_company_year_opening_v1/iu);
  assert.doesNotMatch(rollback, /drop table(?: if exists)? ledger\.opening_position_/iu);
});
