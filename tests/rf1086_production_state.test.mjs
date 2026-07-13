import assert from "node:assert/strict";
import test from "node:test";

import { deriveRf1086ProductionState } from "../app/lib/rf1086-production-state.ts";

const actorId = "12345678-1234-4234-9234-123456789abc";
const companyId = "22345678-1234-4234-9234-123456789abc";
const preview = {
  id: "32345678-1234-4234-9234-123456789abc",
  company_id: companyId,
  setup_id: "42345678-1234-4234-9234-123456789abc",
  income_year: 2025,
  filing: "aksjonærregisteroppgaven",
  status: "ready",
  issues: [],
  preview: "RF-1086 no-activity preview",
  hovedskjema_xml: "<melding />",
  underskjema_xml: { shareholder: "<melding />" },
  source: "python_rf1086_engine",
  created_at: "2026-07-13T18:00:00.000Z",
};

function readyInput(overrides = {}) {
  const company = {
    id: companyId,
    org_number: "310279617",
    name: "LOGISK ØDE TIGER AS",
    entity_type: "AS",
    address: "Klokkargarden 44",
    postal_code: "5200",
    city: "OS",
    status_text: "aktiv",
    source: "brreg",
    created_by: actorId,
    identity_confirmed_at: "2026-07-13T16:00:00.000Z",
    identity_locked_at: "2026-07-13T16:00:00.000Z",
    created_at: "2026-07-13T16:00:00.000Z",
  };
  const authorityPermissions = [{
    company_id: companyId,
    obligation: "aksjonaerregisteroppgaven",
    submitter_user_id: actorId,
    confirmed_by: actorId,
    confirmed_at: "2026-07-13T17:00:00.000Z",
    production_enabled: true,
  }];
  return {
    actorId,
    preview,
    company,
    membership: {
      company_id: companyId,
      user_id: actorId,
      role: "owner",
      accepted_at: "2026-07-13T17:00:00.000Z",
    },
    incomeYear: 2025,
    setups: [{
      id: preview.setup_id,
      company_id: companyId,
      income_year: 2025,
      bank_balance: 1_000_000,
      share_capital: 1_000_000,
      share_count: 500,
      nominal_value: 2_000,
      locked_at: "2026-07-13T17:00:00.000Z",
      created_by: actorId,
    }],
    ledgerEntries: [],
    holdingActions: [],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{
      id: "52345678-1234-4234-9234-123456789abc",
      company_id: companyId,
      income_year: 2025,
      reason: "Annual close",
      locked_by: actorId,
      locked_at: "2026-07-13T17:00:00.000Z",
    }],
    annualData: {
      id: "62345678-1234-4234-9234-123456789abc",
      company_id: companyId,
      income_year: 2025,
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
      confirmations: ["bank_balance_confirmed", "authority_to_submit_confirmed", "no_activity_confirmed"],
      no_activity_confirmed: true,
      annual_full_time_equivalents: 0,
      completed_by: actorId,
      completed_at: "2026-07-13T17:00:00.000Z",
      updated_by: actorId,
      updated_at: "2026-07-13T17:00:00.000Z",
    },
    billingAccount: {
      company_id: companyId,
      pricing_plan: "founder",
      monthly_nok: 29,
      filing_package_nok: 299,
      founder_cohort_number: 1,
      subscription_active: true,
      filing_package_paid: true,
      supported_case: true,
      refund_eligible: false,
      no_charge_reason: null,
    },
    authorityPermissions,
    filingPreviews: [preview],
    filingSubmissions: [],
    authorityTestRuns: [{
      company_id: companyId,
      obligation: "aksjonaerregisteroppgaven",
      status: "accepted",
      receipt_reference: "tt02-receipt",
      archive_reference: "tt02-archive",
      recorded_at: "2026-07-13T17:00:00.000Z",
    }],
    stepUpContext: {
      actorId,
      mfaVerifiedAt: "2026-07-13T17:55:00.000Z",
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
    },
    launchSignoffRows: [{
      key: "rf1086_authority",
      status: "approved",
      reviewer: "Independent reviewer",
      reviewed_at: "2026-07-13T17:30:00.000Z",
      evidence_link: "https://evidence.example/rf1086",
      decision: "Approved supported RF-1086 production scope.",
      recorded_by: actorId,
      updated_at: "2026-07-13T17:30:00.000Z",
    }],
    reviewComments: [],
    confirmations: { authorityConfirmed: true, previewConfirmed: true },
    now: new Date("2026-07-13T18:00:00.000Z"),
    ...overrides,
  };
}

test("derives a production release from current rows and normalizes launch signoffs", () => {
  const state = deriveRf1086ProductionState(readyInput());

  assert.equal(state.preview.id, preview.id);
  assert.equal(state.release.filingReady, true);
  assert.equal(state.release.hardReviewBlockCount, 0);
  assert.equal(state.release.blockingOverrideCount, 0);
  assert.deepEqual(state.release.launchSignoffs, [{
    key: "rf1086_authority",
    status: "approved",
    reviewer: "Independent reviewer",
    reviewedAt: "2026-07-13T17:30:00.000Z",
    evidenceLink: "https://evidence.example/rf1086",
    decision: "Approved supported RF-1086 production scope.",
  }]);
});

test("fresh unmatched bank data disables a release instead of trusting old readiness", () => {
  const input = readyInput();
  input.bankTransactions.push({
    id: "72345678-1234-4234-9234-123456789abc",
    company_id: companyId,
    income_year: 2025,
    transaction_date: "2025-12-31",
    text: "Unmatched",
    amount: 100,
    balance: null,
    source_hash: "source-hash",
    matched_entry_id: null,
    matched_action_id: null,
    accepted_warning: false,
    created_by: actorId,
    created_at: "2026-07-13T17:59:00.000Z",
  });

  const state = deriveRf1086ProductionState(input);

  assert.equal(state.release.filingReady, false);
});

test("open warnings, hard review comments, and blocking overrides remain production blockers", () => {
  const input = readyInput({ locks: [] });
  input.reviewComments.push({ preview_id: preview.id, severity: "hard_block" });
  input.overrides.push({
    id: "82345678-1234-4234-9234-123456789abc",
    preview_id: preview.id,
    company_id: companyId,
    income_year: 2025,
    filing: "aksjonærregisteroppgaven",
    field_target: "rf1086.shareholder",
    old_value: "",
    new_value: "unsupported",
    reason: "manual override",
    risk_level: "block",
    owner_confirmed_by: actorId,
    owner_confirmed_at: "2026-07-13T17:59:00.000Z",
    created_by: actorId,
    created_at: "2026-07-13T17:59:00.000Z",
  });

  const state = deriveRf1086ProductionState(input);

  assert.equal(state.release.filingReady, false);
  assert.equal(state.release.hardReviewBlockCount, 1);
  assert.equal(state.release.blockingOverrideCount, 1);
});
