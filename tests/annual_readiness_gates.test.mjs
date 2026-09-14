import assert from "node:assert/strict";
import test from "node:test";

import { evaluateAnnualReadinessGates } from "../apps/web/app/lib/annual-readiness.ts";

const company = {
  id: "company-id",
  org_number: "314259521",
  name: "Demo Holding AS",
  entity_type: "AS",
  address: "Storgata 1",
  postal_code: "0155",
  city: "OSLO",
  status_text: "aktiv",
  source: "brreg",
  created_by: "owner",
  identity_confirmed_at: "2026-01-01T00:00:00Z",
  identity_locked_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

function readyBillingDecision(obligation) {
  return {
    companyId: company.id,
    incomeYear: 2025,
    obligation,
    status: "ready_for_production_filing",
    allowed: true,
    chargeAllowed: false,
    readinessAllowed: true,
    billingExempt: false,
    message: "Billing and filing-package entitlement are ready.",
    pilotEntitlementId: null,
  };
}

function baseInput(overrides = {}) {
  return {
    company,
    incomeYear: 2025,
    setups: [
      {
        id: "setup-id",
        company_id: company.id,
        income_year: 2025,
        bank_balance: 30000,
        share_capital: 30000,
        share_count: 100,
        nominal_value: 300,
        locked_at: "2026-01-01T00:00:00Z",
        created_by: "owner",
      },
    ],
    ledgerEntries: [
      {
        id: "ledger-id",
        company_id: company.id,
        setup_id: "setup-id",
        income_year: 2025,
        entry_type: "opening_balance",
        memo: "Opening",
        lines: [],
        risk_flags: [],
        warning_accepted_by: null,
        warning_accepted_at: null,
        created_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    holdingActions: [
      {
        id: "tax-action-id",
        company_id: company.id,
        income_year: 2025,
        action_type: "tax_settlement",
        action_date: "2026-03-01",
        payload: {},
        ledger_entry_id: "ledger-id",
        bank_transaction_id: null,
        document_id: null,
        risk_level: "ready",
        blocker_code: null,
        created_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{ id: "lock-id", company_id: company.id, income_year: 2025, reason: "Annual close", locked_by: "owner", locked_at: "2026-01-01T00:00:00Z" }],
    annualData: {
      id: "annual-data-id",
      company_id: company.id,
      income_year: 2025,
      answers: {
        shares_owned_at_year_end: true,
        bought_or_sold_shares: false,
        received_dividends: false,
        declared_owner_dividends: false,
        shareholder_loans: false,
        paid_costs: false,
        bank_balance_confirmed: true,
        has_unpaid_items: false,
        general_meeting_approved: true,
        authority_to_submit_confirmed: true,
      },
      confirmations: ["bank_balance_confirmed", "general_meeting_approved", "authority_to_submit_confirmed"],
      no_activity_confirmed: false,
      completed_by: "owner",
      completed_at: "2026-01-01T00:00:00Z",
      updated_by: "owner",
      updated_at: "2026-01-01T00:00:00Z",
    },
    billingEntitlements: Object.fromEntries([
      "aksjonaerregisteroppgaven",
      "skattemelding",
      "aarsregnskap",
    ].map((obligation) => [obligation, readyBillingDecision(obligation)])),
    authorityPermissions: [
      { obligation: "aksjonaerregisteroppgaven", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "skattemelding", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "aarsregnskap", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
    ],
    filingPreviews: [
      {
        id: "preview-id",
        company_id: company.id,
        setup_id: "setup-id",
        income_year: 2025,
        filing: "aksjonærregisteroppgaven",
        status: "ready",
        issues: [],
        preview: "RF-1086",
        hovedskjema_xml: "<RF-1086 />",
        underskjema_xml: {},
        source: "python_rf1086_engine",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    filingSubmissions: [],
    companyTaxReadiness: { companyId: company.id, incomeYear: 2025, issues: [] },
    annualAccountsReadiness: { companyId: company.id, incomeYear: 2025, issues: [] },
    ...overrides,
  };
}

test("evaluates ready state separately for all annual obligations", () => {
  const snapshots = evaluateAnnualReadinessGates(baseInput());

  assert.deepEqual(
    snapshots.map((snapshot) => [snapshot.obligation, snapshot.status, snapshot.ready]),
    [
      ["aksjonaerregisteroppgaven", "ready", true],
      ["skattemelding", "ready", true],
      ["aarsregnskap", "ready", true],
    ],
  );
});

test("returns hard blocks for missing permission and billing", () => {
  const snapshots = evaluateAnnualReadinessGates(baseInput({ billingEntitlements: {}, authorityPermissions: [] }));
  const rf1086 = snapshots.find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven");

  assert.equal(rf1086.status, "blocked");
  assert.equal(rf1086.ready, false);
  assert.ok(rf1086.hard_blocks.some((issue) => issue.code === "missing_authority_confirmation"));
  assert.ok(rf1086.hard_blocks.some((issue) => issue.code === "billing_account_missing"));
});

test("composes a clear owned Tax assessment with no-activity annual data", () => {
  const noActivityAnnualData = {
    ...baseInput().annualData,
    answers: {
      shares_owned_at_year_end: false,
      bought_or_sold_shares: false,
      received_dividends: false,
      declared_owner_dividends: false,
      shareholder_loans: false,
      paid_costs: false,
      bank_balance_confirmed: true,
      has_unpaid_items: false,
      general_meeting_approved: true,
      authority_to_submit_confirmed: true,
    },
    confirmations: ["bank_balance_confirmed", "general_meeting_approved", "authority_to_submit_confirmed", "no_activity_confirmed"],
    no_activity_confirmed: true,
  };
  const tax = evaluateAnnualReadinessGates(baseInput({ annualData: noActivityAnnualData, holdingActions: [] })).find(
    (snapshot) => snapshot.obligation === "skattemelding",
  );

  assert.equal(tax.status, "ready");
  assert.equal(tax.warnings.some((issue) => issue.code === "tax_settlement_missing"), false);
});

test("keeps accepted warnings separate from open warnings", () => {
  const snapshots = evaluateAnnualReadinessGates(
    baseInput({
      documents: [
        {
          id: "doc-id",
          company_id: company.id,
          income_year: 2025,
          document_type: "receipt",
          name: "Missing",
          linked_to: "årsregnskap",
          status: "missing_accepted",
          retention_years: 5,
          storage_key: "missing",
          created_by: "owner",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      overrides: [
        {
          id: "override-id",
          preview_id: null,
          company_id: company.id,
          income_year: 2025,
          filing: "aksjonærregisteroppgaven",
          field_target: "rf1086.note",
          old_value: "",
          new_value: "Forklaring",
          reason: "Owner accepted",
          risk_level: "warning",
          owner_confirmed_by: "owner",
          owner_confirmed_at: "2026-01-01T00:00:00Z",
          created_by: "owner",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    }),
  );

  const rf1086 = snapshots.find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven");
  const annualAccounts = snapshots.find((snapshot) => snapshot.obligation === "aarsregnskap");
  assert.equal(rf1086.status, "ready");
  assert.ok(rf1086.accepted_warnings.some((issue) => issue.code === "accepted_filing_override"));
  assert.equal(annualAccounts.status, "ready");
  assert.ok(annualAccounts.accepted_warnings.some((issue) => issue.code === "missing_documents_accepted"));
});

test("reports open warnings and obligation-specific blocks", () => {
  const snapshots = evaluateAnnualReadinessGates(
    baseInput({
      locks: [],
      companyTaxReadiness: { companyId: company.id, incomeYear: 2025, issues: [{ level: "block", code: "blocking_holding_action", message: "Støttet holdinghandling må ryddes før skattemelding.", source: "holding_actions", accepted: false }] },
      holdingActions: [
        {
          id: "blocked-action-id",
          company_id: company.id,
          income_year: 2025,
          action_type: "shareholder_loan",
          action_date: "2025-06-01",
          payload: {},
          ledger_entry_id: null,
          bank_transaction_id: null,
          document_id: null,
          risk_level: "block",
          blocker_code: "company_to_personal_shareholder",
          created_by: "owner",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    }),
  );

  const rf1086 = snapshots.find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven");
  const tax = snapshots.find((snapshot) => snapshot.obligation === "skattemelding");
  assert.equal(rf1086.status, "warning");
  assert.ok(rf1086.warnings.some((issue) => issue.code === "period_not_locked"));
  assert.equal(tax.status, "blocked");
  assert.ok(tax.hard_blocks.some((issue) => issue.code === "blocking_holding_action"));
});

for (const preview of [undefined, null, { companyId: "other", incomeYear: 2025, issues: [] }, { companyId: company.id, incomeYear: 2024, issues: [] }]) {
  test("Annual cannot turn missing or wrong-scope Tax preview into ready", () => {
    const tax = evaluateAnnualReadinessGates(baseInput({ companyTaxReadiness: preview })).find(item => item.obligation === "skattemelding");
    assert.equal(tax.ready, false);
    assert.ok(tax.hard_blocks.some(item => item.code === "company_tax_source_unavailable"));
  });
}

for (const readiness of [null, { companyId: "foreign", incomeYear: 2025, issues: [] }, { companyId: company.id, incomeYear: 2024, issues: [] }]) {
  test("Accounts readiness is blocked when its owned source is absent or foreign", () => {
    const result = evaluateAnnualReadinessGates(baseInput({ annualAccountsReadiness: readiness })).find(row => row.obligation === "aarsregnskap");
    assert.equal(result.ready, false);
    assert.ok(result.hard_blocks.some(issue => issue.code === "annual_accounts_source_unavailable"));
  });
}

test("Annual composes Accounts Corporate blocks and accepted warnings without recalculating them", () => {
  const issues = [
    { level: "block", code: "corporate_documents_signatures_missing", message: "Signaturer mangler.", source: "corporate_documents", accepted: false },
    { level: "warning", code: "manual_review", message: "Eier har akseptert kontroll.", source: "ledger", accepted: true },
  ];
  const result = evaluateAnnualReadinessGates(baseInput({ annualAccountsReadiness: { companyId: company.id, incomeYear: 2025, issues } })).find(row => row.obligation === "aarsregnskap");
  assert.deepEqual(result.hard_blocks, [issues[0]]);
  assert.deepEqual(result.accepted_warnings, [issues[1]]);
});
