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
const bankLoanMigrationUrl = new URL(
  "../supabase/migrations/20260827106000_ledger_bank_loan_lifecycle.sql",
  import.meta.url,
);
const bankLoanMigration = existsSync(bankLoanMigrationUrl)
  ? readFileSync(bankLoanMigrationUrl, "utf8")
  : "";
const cashCapitalIncreaseMigrationUrl = new URL(
  "../supabase/migrations/20260827107000_ledger_cash_capital_increase_lifecycle.sql",
  import.meta.url,
);
const cashCapitalIncreaseMigration = existsSync(cashCapitalIncreaseMigrationUrl)
  ? readFileSync(cashCapitalIncreaseMigrationUrl, "utf8")
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

test("bank-loan lifecycle state is immutable, forced-RLS, and executor-only", () => {
  assert.ok(bankLoanMigration, "missing additive bank-loan lifecycle migration");
  for (const table of ["bank_loan_anchors", "bank_loan_payment_allocations"]) {
    assert.match(
      bankLoanMigration,
      new RegExp(`alter table ledger\\.${table} force row level security`, "iu"),
    );
    assert.match(
      bankLoanMigration,
      new RegExp(`create trigger ledger_${table}_immutable`, "iu"),
    );
    assert.doesNotMatch(
      bankLoanMigration,
      new RegExp(`grant[^;]+(?:insert|update|delete)[^;]+ledger\\.${table}[^;]+ledger_executor`, "iu"),
    );
  }
  assert.match(bankLoanMigration, /primary key\s*\(company_id, loan_reference_id\)/iu);
  assert.match(bankLoanMigration, /disbursement_entry_id uuid not null unique/iu);
  assert.match(bankLoanMigration, /payment_entry_id uuid primary key/iu);
  assert.match(bankLoanMigration, /principal_disbursed numeric[^\n]+not null/iu);
  assert.match(bankLoanMigration, /principal_paid numeric[^\n]+not null/iu);
  assert.match(bankLoanMigration, /interest_paid numeric[^\n]+not null/iu);
  assert.match(bankLoanMigration, /fee_paid numeric[^\n]+not null/iu);
});

test("bank-loan wrappers persist derived entries without selecting accounting policy", () => {
  for (const wrapperName of [
    "record_bank_loan_disbursement_v1",
    "record_bank_loan_payment_v1",
  ]) {
    const wrapper = bankLoanMigration.match(
      new RegExp(
        `create or replace function ledger\\.${wrapperName}\\([\\s\\S]+?\\$function\\$\\s*;`,
        "iu",
      ),
    )?.[0];
    assert.ok(wrapper, `missing ${wrapperName}`);
    assert.match(wrapper, /from ledger\.post_supported_entry_v1\(/iu);
    assert.doesNotMatch(wrapper, /'1920'|'2220'|'8150'|'7770'/u);
    assert.doesNotMatch(wrapper, /->>\s*'account'|jsonb_extract_path_text\([^;]+account/iu);
    assert.doesNotMatch(wrapper, /case\s+when[^;]+account|when\s+'\d{4}'/iu);
  }
  assert.match(
    bankLoanMigration,
    /record_bank_loan_disbursement_v1\(\s*p_idempotency_key text,\s*p_company_id uuid,\s*p_income_year integer,\s*p_loan_reference_id text,\s*p_principal numeric/iu,
  );
  assert.match(
    bankLoanMigration,
    /record_bank_loan_payment_v1\(\s*p_idempotency_key text,\s*p_company_id uuid,\s*p_income_year integer,\s*p_loan_reference_id text,\s*p_principal numeric,\s*p_interest numeric,\s*p_fee numeric/iu,
  );
});

test("fresh lifecycle covers bank-loan replay, allocation limits, and cutover", () => {
  assert.match(lifecycle, /20260827106000_ledger_bank_loan_lifecycle\.sql/iu);
  assert.match(lifecycle, /record_bank_loan_disbursement_v1/iu);
  assert.match(lifecycle, /record_bank_loan_payment_v1/iu);
  assert.match(lifecycle, /bank_loan_anchors/iu);
  assert.match(lifecycle, /bank_loan_payment_allocations/iu);
  assert.match(lifecycle, /bank-loan-disbursement-runtime/u);
  assert.match(lifecycle, /ledger_bank_loan_principal_exceeded/iu);
  assert.match(lifecycle, /bank_loan_payment_2029/u);
});

test("cash-capital-increase phases are one immutable forced-RLS lifecycle", () => {
  assert.ok(
    cashCapitalIncreaseMigration,
    "missing additive cash-capital-increase lifecycle migration",
  );
  assert.equal(
    (cashCapitalIncreaseMigration.match(
      /create table if not exists ledger\.cash_capital_increase_phases/giu,
    ) ?? []).length,
    1,
    "cash-capital lifecycle must use one append-only phase table",
  );
  assert.match(
    cashCapitalIncreaseMigration,
    /alter table ledger\.cash_capital_increase_phases force row level security/iu,
  );
  assert.match(
    cashCapitalIncreaseMigration,
    /create trigger ledger_cash_capital_increase_phases_immutable/iu,
  );
  assert.match(
    cashCapitalIncreaseMigration,
    /primary key\s*\(company_id, capital_increase_reference_id, phase\)/iu,
  );
  assert.match(cashCapitalIncreaseMigration, /entry_id uuid not null unique/iu);
  assert.match(
    cashCapitalIncreaseMigration,
    /phase text not null[\s\S]+?'BINDING_SUBSCRIPTION'[\s\S]+?'RESTRICTED_PAYMENT'[\s\S]+?'REGISTERED'/iu,
  );
  assert.match(
    cashCapitalIncreaseMigration,
    /grant select, insert on ledger\.cash_capital_increase_phases\s+to ledger_store_owner/iu,
  );
  assert.doesNotMatch(
    cashCapitalIncreaseMigration,
    /grant[^;]+(?:insert|update|delete)[^;]+ledger\.cash_capital_increase_phases[^;]+(?:ledger_executor|ledger_workflow_executor|authenticated|anon)/iu,
  );
});

test("cash-capital wrappers enforce exact sources without selecting accounting policy", () => {
  const wrappers = new Map([
    [
      "record_cash_capital_increase_subscription_v1",
      ["CORPORATE_GOVERNANCE", "DOCUMENTS"],
    ],
    [
      "record_cash_capital_increase_restricted_payment_v1",
      ["BANKING", "CORPORATE_GOVERNANCE", "DOCUMENTS"],
    ],
    [
      "record_cash_capital_increase_registration_v1",
      [
        "BANKING",
        "CORPORATE_GOVERNANCE",
        "DOCUMENTS",
        "SHAREHOLDER_REGISTER_FILING",
      ],
    ],
  ]);

  for (const [wrapperName, capabilities] of wrappers) {
    const wrapper = cashCapitalIncreaseMigration.match(
      new RegExp(
        `create or replace function ledger\\.${wrapperName}\\([\\s\\S]+?\\$function\\$\\s*;`,
        "iu",
      ),
    )?.[0];
    assert.ok(wrapper, `missing ${wrapperName}`);
    assert.match(wrapper, /from ledger\.post_supported_entry_v1\(/iu);
    assert.match(
      wrapper,
      /p_source_capability is distinct from 'CORPORATE_GOVERNANCE'/iu,
    );
    assert.match(
      wrapper,
      /p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'/iu,
    );
    const capabilityLiteral = capabilities
      .map((capability) => `'${capability}'`)
      .join(",\\s*");
    assert.match(
      wrapper,
      new RegExp(`array\\[\\s*${capabilityLiteral}\\s*\\]::text\\[\\]`, "iu"),
    );
    assert.doesNotMatch(wrapper, /'1500'|'1920'|'1921'|'2000'|'2020'|'2030'/u);
    assert.doesNotMatch(
      wrapper,
      /->>\s*'account'|jsonb_extract_path_text\([^;]+account/iu,
    );
    assert.doesNotMatch(wrapper, /case\s+when[^;]+account|when\s+'\d{4}'/iu);
    assert.match(
      cashCapitalIncreaseMigration,
      new RegExp(
        `grant execute on function ledger\\.${wrapperName}\\([\\s\\S]+?\\)\\s+to ledger_executor`,
        "iu",
      ),
    );
    assert.doesNotMatch(
      cashCapitalIncreaseMigration,
      new RegExp(
        `grant execute on function ledger\\.${wrapperName}\\([\\s\\S]+?\\)\\s+to (?:authenticated|anon|ledger_workflow_executor)`,
        "iu",
      ),
    );
  }

  assert.match(
    cashCapitalIncreaseMigration,
    /pg_advisory_xact_lock[\s\S]+?capital[_:-]increase/iu,
  );
  for (const lifecycleControl of [
    "ledger_cash_capital_increase_phase_invalid",
    "ledger_cash_capital_increase_phase_missing",
    "ledger_cash_capital_increase_amount_mismatch",
    "ledger_cash_capital_increase_phase_already_recorded",
  ]) {
    assert.match(
      cashCapitalIncreaseMigration,
      new RegExp(lifecycleControl, "iu"),
      `missing lifecycle control ${lifecycleControl}`,
    );
  }
});

test("fresh lifecycle covers cash-capital rollback revocation and recutover", () => {
  assert.match(
    lifecycle,
    /20260827107000_ledger_cash_capital_increase_lifecycle\.sql/iu,
  );
  for (const runtimeEvidence of [
    "record_cash_capital_increase_subscription_v1",
    "record_cash_capital_increase_restricted_payment_v1",
    "record_cash_capital_increase_registration_v1",
    "cash_capital_increase_phases",
    "cash-capital-increase-subscription-runtime",
    "cash-capital-increase-restricted-payment-runtime",
    "cash-capital-increase-registration-runtime",
  ]) {
    assert.match(lifecycle, new RegExp(runtimeEvidence, "iu"));
  }
  assert.match(
    lifecycle,
    /psql\(containerName, \["--file", rollbackPath\]\);[\s\S]+record_cash_capital_increase_subscription_v1[\s\S]+record_cash_capital_increase_restricted_payment_v1[\s\S]+record_cash_capital_increase_registration_v1[\s\S]+psql\(containerName, \["--file", cashCapitalIncreasePath\]\)/iu,
  );
});
