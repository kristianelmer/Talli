import assert from "node:assert/strict";
import test from "node:test";

import { buildAnnualAccountsPayload, assessAnnualAccountsReadiness } from "./support/annual_accounts_public.mjs";
import { evaluateAnnualReadinessGates } from "../apps/web/app/lib/annual-readiness.ts";

const readyBillingEntitlements = Object.fromEntries([
  "aksjonaerregisteroppgaven",
  "skattemelding",
  "aarsregnskap",
].map((obligation) => [obligation, {
  companyId: "company-id",
  incomeYear: 2025,
  obligation,
  status: "ready_for_production_filing",
  allowed: true,
  chargeAllowed: false,
  readinessAllowed: true,
  billingExempt: false,
  message: "Billing and filing-package entitlement are ready.",
  pilotEntitlementId: null,
}]));

const annualData = {
  id: "annual-data-id",
  company_id: "company-id",
  income_year: 2025,
  answers: {
    shares_owned_at_year_end: true,
    bought_or_sold_shares: false,
    received_dividends: true,
    declared_owner_dividends: false,
    shareholder_loans: false,
    paid_costs: true,
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
};

const ledgerEntries = [
  {
    id: "entry-id",
    company_id: "company-id",
    setup_id: "setup-id",
    income_year: 2025,
    entry_type: "annual",
    memo: "Annual",
    lines: [
      { account: "1920", debit: 128510, credit: 0 },
      { account: "8070", debit: 0, credit: 100000 },
      { account: "7770", debit: 1490, credit: 0 },
      { account: "2000", debit: 0, credit: 30000 },
    ],
    risk_flags: [],
    warning_accepted_by: null,
    warning_accepted_at: null,
    created_by: "owner",
    created_at: "2026-01-01T00:00:00Z",
  },
];

test("builds verified RR0002 annual accounts payload fields", () => {
  const payload = buildAnnualAccountsPayload({ incomeYear: 2025, annualData, ledgerEntries });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.tag, field]));

  assert.equal(payload.schemaType, "aarsregnskap-vanlig-202406");
  assert.equal(payload.hovedskjemaDataFormatId, "1266");
  assert.equal(payload.selskapsregnskapDataFormatVersion, "51980");
  assert.equal(fields["valuta"].orid, "34984");
  assert.equal(fields["sumDriftskostnad/aarets"].value, 1490);
  assert.equal(fields["sumFinansinntekter/aarets"].orid, "153");
  assert.equal(fields["sumBankinnskuddKontanter/aarets"].orid, "29042");
  assert.equal(fields["sumEgenkapital/aarets"].orid, "250");
  assert.equal(fields["antallAarsverk"].value, 0);
  assert.deepEqual(payload.feedback, []);
});

test("includes system costs, bank interest, and share-sale losses in annual result", () => {
  const payload = buildAnnualAccountsPayload({
    incomeYear: 2025,
    annualData,
    ledgerEntries: [
      {
        ...ledgerEntries[0],
        lines: [
          { account: "1920", debit: 0, credit: 0 },
          { account: "8070", debit: 0, credit: 20000 },
          { account: "8050", debit: 0, credit: 125.5 },
          { account: "6700", debit: 990, credit: 0 },
          { account: "8090", debit: 5000, credit: 0 },
        ],
      },
    ],
  });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.tag, field]));

  assert.equal(fields["sumDriftskostnad/aarets"].value, 990);
  assert.equal(fields["sumFinansinntekter/aarets"].value, 20125.5);
  assert.equal(fields["sumFinanskostnader/aarets"].value, 5000);
  assert.equal(fields["resultatFoerSkattekostnad/aarets"].value, 14135.5);
  assert.equal(fields["aarsresultat/aarets"].value, 14135.5);
});

test("separates tax expense from result before tax and includes tax payable in debt", () => {
  const payload = buildAnnualAccountsPayload({
    incomeYear: 2025,
    annualData,
    ledgerEntries: [
      {
        ...ledgerEntries[0],
        lines: [
          { account: "1920", debit: 128510, credit: 0 },
          { account: "8070", debit: 0, credit: 100000 },
          { account: "7770", debit: 1490, credit: 0 },
          { account: "8300", debit: 20000, credit: 0 },
          { account: "2500", debit: 0, credit: 20000 },
          { account: "2000", debit: 0, credit: 30000 },
        ],
      },
    ],
  });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.tag, field]));

  assert.equal(fields["resultatFoerSkattekostnad/aarets"].value, 98510);
  assert.equal(fields["skattekostnad/aarets"].orid, "11835");
  assert.equal(fields["skattekostnad/aarets"].value, 20000);
  assert.equal(fields["aarsresultat/aarets"].value, 78510);
  assert.equal(fields["betalbarSkatt/aarets"].orid, "2483");
  assert.equal(fields["betalbarSkatt/aarets"].value, 20000);
  assert.equal(fields["sumKortsiktigGjeld/aarets"].value, 20000);
  assert.equal(fields["sumEgenkapital/aarets"].value, 108510);
  assert.equal(fields["sumEiendeler/aarets"].value, 128510);
});

test("returns annual accounts feedback for missing notes and unsupported cases", () => {
  const payload = buildAnnualAccountsPayload({
    incomeYear: 2025,
    annualData: {
      ...annualData,
      annual_full_time_equivalents: null,
      confirmations: [...annualData.confirmations, "annual_accounts_audit_required"],
    },
    ledgerEntries,
  });

  assert.deepEqual(
    payload.feedback.map((item) => item.code),
    ["annual_accounts_aarsverk_missing", "annual_accounts_audit_required"],
  );
});

test("persists annual accounts payload feedback into readiness gate shape", () => {
  const snapshots = evaluateAnnualReadinessGates({
    company: {
      id: "company-id",
      org_number: "314259521",
      name: "Demo Holding AS",
      entity_type: "AS",
      address: "",
      postal_code: "",
      city: "",
      status_text: "",
      source: "test",
      created_by: "owner",
      identity_confirmed_at: "2026-01-01T00:00:00Z",
      identity_locked_at: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
    },
    incomeYear: 2025,
    setups: [{ id: "setup-id", company_id: "company-id", income_year: 2025, bank_balance: 1, share_capital: 1, share_count: 1, nominal_value: 1, locked_at: "2026-01-01T00:00:00Z", created_by: "owner" }],
    ledgerEntries,
    holdingActions: [],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{ id: "lock-id", company_id: "company-id", income_year: 2025, reason: "locked", locked_by: "owner", locked_at: "2026-01-01T00:00:00Z" }],
    annualData: { ...annualData, annual_full_time_equivalents: null },
    annualAccountsReadiness: assessAnnualAccountsReadiness({companyId: "company-id", incomeYear: 2025,
      annualData: { ...annualData, annual_full_time_equivalents: null }, ledgerEntries}),
    billingEntitlements: readyBillingEntitlements,
    authorityPermissions: [
      { obligation: "aksjonaerregisteroppgaven", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "skattemelding", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "aarsregnskap", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
    ],
    filingPreviews: [{ id: "preview-id", company_id: "company-id", setup_id: "setup-id", income_year: 2025, filing: "aksjonærregisteroppgaven", status: "ready", issues: [], preview: "RF", hovedskjema_xml: "", underskjema_xml: {}, source: "test", created_at: "2026-01-01T00:00:00Z" }],
    filingSubmissions: [],
  });
  const annual = snapshots.find((snapshot) => snapshot.obligation === "aarsregnskap");

  assert.equal(annual.status, "blocked");
  assert.ok(annual.hard_blocks.some((issue) => issue.code === "annual_accounts_aarsverk_missing"));
});
