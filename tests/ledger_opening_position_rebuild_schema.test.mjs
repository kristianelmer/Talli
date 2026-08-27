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
const acceptanceMigration = readFileSync(
  new URL(
    "../supabase/migrations/20260827109100_ledger_opening_position_acceptance.sql",
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
const ledgerCapability = readFileSync(
  new URL(
    "../supabase/migrations/20260827100000_ledger_capability.sql",
    import.meta.url,
  ),
  "utf8",
);
const companyYearClose = readFileSync(
  new URL(
    "../supabase/migrations/20260827104000_ledger_company_year_close.sql",
    import.meta.url,
  ),
  "utf8",
);

test("opening rebuild, components, and provenance are immutable forced-RLS records", () => {
  for (const table of [
    "opening_position_rebuilds",
    "opening_position_components",
    "opening_position_component_sources",
    "opening_received_dividend_settlements",
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
  assert.match(migration, /ledger\.post_supported_entry_storage_v1\([\s\S]+'OPENING_BALANCE'/iu);
  assert.match(
    migration,
    /create or replace function ledger\.post_supported_entry_v1\([\s\S]+upper\(coalesce\(p_entry_kind, ''\)\) = 'OPENING_BALANCE'[\s\S]+raise exception 'ledger_invalid_input'/iu,
  );
  assert.match(
    migration,
    /revoke all on function ledger\.post_supported_entry_storage_v1\([\s\S]+ledger_executor,[\s\S]+ledger_workflow_executor/iu,
  );
  assert.match(migration, /insert into ledger\.opening_position_rebuilds[\s\S]+insert into ledger\.opening_position_components[\s\S]+insert into ledger\.opening_position_component_sources/iu);
  assert.match(migration, /grant execute on function ledger\.rebuild_company_year_opening_v1[\s\S]+to ledger_executor/iu);
  assert.doesNotMatch(migration, /p_(?:account|debit|credit)/iu);
  assert.match(
    ledgerCapability,
    /upper\(coalesce\(p_entry_kind, ''\)\) = 'OPENING_BALANCE'/iu,
  );
  assert.match(
    companyYearClose,
    /upper\(coalesce\(p_entry_kind, ''\)\) = 'OPENING_BALANCE'/iu,
  );
  assert.match(
    migration,
    /grant execute on function ledger\.rebuild_company_year_opening_v1[\s\S]+to ledger_executor, ledger_workflow_executor/iu,
  );
  assert.match(migration, /opening_mode text not null/iu);
  assert.match(migration, /component_kind text not null/iu);
  assert.match(migration, /lifecycle_phase text/iu);
  assert.match(migration, /nominal_increase_nok numeric/iu);
  assert.match(migration, /nominal_reduction_nok numeric/iu);
  assert.match(migration, /record_received_dividend_payment_by_reference_v1/iu);
  assert.match(migration, /cash_capital_increase_phase_basis_v1/iu);
  assert.match(migration, /loss_coverage_capital_reduction_basis_v1/iu);
  assert.match(migration, /account text not null/iu);
  assert.doesNotMatch(migration, /ordinal between 1 and 49/iu);
  assert.doesNotMatch(migration, /jsonb_array_length\(p_components\) not between 2 and 49/iu);
});

test("SQL stores Python accounting decisions without reimplementing them", () => {
  assert.doesNotMatch(migration, /v_expected_primary|v_expected_corroborating/iu);
  assert.doesNotMatch(migration, /case v_component ->> 'category'/iu);
  assert.doesNotMatch(migration, /when v_component ->> 'category' in/iu);
  assert.match(migration, /matched\.line ->> 'account'[\s\S]+item ->> 'account'/iu);
});

test("component and source tenant keys are bound to their parents", () => {
  assert.match(
    migration,
    /foreign key \(opening_entry_id, company_id, income_year\)[\s\S]+references ledger\.opening_position_rebuilds\(\s*opening_entry_id, company_id, income_year\s*\)/iu,
  );
  assert.match(
    migration,
    /foreign key \(\s*opening_entry_id, component_ordinal, company_id, income_year\s*\)[\s\S]+references ledger\.opening_position_components\(\s*opening_entry_id, ordinal, company_id, income_year\s*\)/iu,
  );
});

test("bank-loan components are an exact journal-backed payment basis", () => {
  assert.match(migration, /category in \(\s*'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'\s*\)/iu);
  assert.match(migration, /create unique index(?: if not exists)?[\s\S]+\(company_id, reference_id\)[\s\S]+where category in/iu);
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
    "openingReceivedDividendSettlements",
    "capitalIncreasePhases",
    "capitalReductionPhases",
  ]) assert.match(migration, new RegExp(`'${key}'`, "u"));
});

test("contract requires the receiver and rollback revokes it without deleting facts", () => {
  const signature = /ledger\.rebuild_company_year_opening_v1\(text,uuid,integer,date,text,text,jsonb,text,text,text,text,jsonb,jsonb\)/iu;
  assert.match(contract, signature);
  assert.match(
    contract,
    /ledger\.record_received_dividend_payment_by_reference_v1\(text,uuid,integer,text,text,jsonb,text,text,text,text,date,text,jsonb\)/iu,
  );
  assert.match(rollback, /revoke all on function ledger\.rebuild_company_year_opening_v1/iu);
  assert.doesNotMatch(rollback, /drop table(?: if exists)? ledger\.opening_position_/iu);
  assert.match(
    rollback,
    /rebuild_company_year_opening_v1\([\s\S]+from ledger_executor, ledger_workflow_executor, talli_ledger_backend/iu,
  );
});

test("an already-applied predecessor schema receives the uncapped source upgrade", () => {
  assert.match(
    acceptanceMigration,
    /grant create on schema ledger to %I/iu,
  );
  assert.match(
    acceptanceMigration,
    /revoke create on schema ledger from %I/iu,
  );
  assert.match(
    acceptanceMigration,
    /drop constraint if exists entry_sources_ordinal_check/iu,
  );
  assert.match(
    acceptanceMigration,
    /add constraint entry_sources_ordinal_check check \(ordinal >= 1\)/iu,
  );
  assert.match(
    acceptanceMigration,
    /add constraint entry_sources_source_capability_check[\s\S]+ANNUAL_ACCOUNTS_FILING/iu,
  );
  assert.match(
    acceptanceMigration,
    /create or replace function ledger\.post_supported_entry_storage_v1/iu,
  );
  assert.match(acceptanceMigration, /jsonb_array_length\(p_sources\) < 1/iu);
  assert.doesNotMatch(
    acceptanceMigration,
    /jsonb_array_length\(p_sources\) (?:not )?between 1 and 100/iu,
  );
  assert.match(
    acceptanceMigration,
    /revoke all on function ledger\.post_supported_entry_storage_v1[\s\S]+ledger_workflow_executor/iu,
  );
});
