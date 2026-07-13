import assert from "node:assert/strict";
import test from "node:test";

import { buildCompanyTaxReturnPayload } from "../app/lib/company-tax-return.ts";
import { evaluateAnnualReadinessGates } from "../app/lib/annual-readiness.ts";

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
  annual_full_time_equivalents: 0,
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
      { account: "2050", debit: 0, credit: 97020 },
    ],
    risk_flags: [],
    warning_accepted_by: null,
    warning_accepted_at: null,
    created_by: "owner",
    created_at: "2026-01-01T00:00:00Z",
  },
];

const dividendAction = {
  id: "action-id",
  company_id: "company-id",
  income_year: 2025,
  action_type: "dividend_received",
  action_date: "2025-06-15",
  payload: {
    gross_amount: 100000,
    taxable_add_back: 3000,
    tax_treatment: "fritaksmetoden",
  },
  ledger_entry_id: "entry-id",
  bank_transaction_id: null,
  document_id: "document-id",
  risk_level: "info",
  blocker_code: null,
  created_by: "owner",
  created_at: "2026-01-01T00:00:00Z",
};

test("builds 2025 schema-backed company tax return payload candidate", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData,
    ledgerEntries,
    holdingActions: [dividendAction],
  });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.path, field]));

  assert.equal(payload.schema.skattemeldingUpersonlig.xsd, "skattemeldingUpersonlig_v5_ekstern.xsd");
  assert.equal(payload.schema.naeringsspesifikasjon.xsd, "naeringsspesifikasjon_v6_ekstern.xsd");
  assert.equal(fields["skattemelding.partsnummer"].value, "314259521");
  assert.equal(fields["skattemelding.spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret[0].id"].value, "action-id");
  assert.equal(fields["skattemelding.spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret[0].utbytte.beloepSomHeltall"].value, 100000);
  assert.equal(fields["skattemelding.spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret[0].erOmfattetAvFritaksmetoden.boolsk"].value, true);
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[0].type.resultatOgBalanseregnskapstype"].value, "8090");
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[0].beloep.beloep.beloep"].value, 100000);
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[1].permanentForskjellstype.permanentForskjellstype"].value, "skattepliktigDelAvUtbytterOgUtdelinger");
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[1].beloep.beloep.beloep"].value, 3000);
  assert.equal(payload.derived.accountingResultBeforeTax, 98510);
  assert.equal(payload.derived.taxableBasis, 1510);
  assert.equal(payload.derived.estimatedTax, 332.2);
  assert.deepEqual(payload.feedback.map((item) => item.code), ["tax_return_payload_candidate_ready"]);
});

test("reconciles interest, costs, exempt gains, and non-deductible losses", () => {
  const shareGainAction = {
    ...dividendAction,
    id: "sale-gain",
    action_type: "share_sale",
    payload: { gain_or_loss: 20000, tax_treatment: "fritaksmetoden" },
  };
  const shareLossAction = {
    ...dividendAction,
    id: "sale-loss",
    action_type: "share_sale",
    payload: { gain_or_loss: -5000, tax_treatment: "fritaksmetoden" },
  };
  const entries = [
    {
      ...ledgerEntries[0],
      lines: [
        { account: "1920", debit: 0, credit: 0 },
        { account: "8070", debit: 0, credit: 120000 },
        { account: "8050", debit: 0, credit: 125.5 },
        { account: "7770", debit: 1490, credit: 0 },
        { account: "6700", debit: 990, credit: 0 },
        { account: "8090", debit: 5000, credit: 0 },
      ],
    },
  ];
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData,
    ledgerEntries: entries,
    holdingActions: [dividendAction, shareGainAction, shareLossAction],
  });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.path, field]));

  assert.equal(payload.derived.adminCosts, 2480);
  assert.equal(payload.derived.interestIncome, 125.5);
  assert.equal(payload.derived.exemptShareSaleGain, 20000);
  assert.equal(payload.derived.nonDeductibleShareSaleLoss, 5000);
  assert.equal(payload.derived.accountingResultBeforeTax, 112645.5);
  assert.equal(payload.derived.taxableBasis, 645.5);
  assert.equal(payload.derived.estimatedTax, 142.01);
  assert.equal(fields["resultatregnskap.driftskostnad.annenDriftskostnad.kostnad[0].type.resultatOgBalanseregnskapstype"].value, "6700");
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[1].type.resultatOgBalanseregnskapstype"].value, "8050");
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[2].type.resultatOgBalanseregnskapstype"].value, "8074");
  assert.equal(fields["resultatregnskap.finanskostnad.kostnad[0].type.resultatOgBalanseregnskapstype"].value, "8174");
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[2].permanentForskjellstype.permanentForskjellstype"].value, "regnskapsmessigGevinstVedRealisasjonAvFinansielleInstrumenter");
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[3].permanentForskjellstype.permanentForskjellstype"].value, "regnskapsmessigTapVedRealisasjonAvFinansielleInstrumenter");
  assert.deepEqual(payload.feedback.map((item) => item.code), ["tax_return_share_sale_or_purchase_review"]);
});

test("blocks unsupported tax treatment and shareholder loans", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData: { ...annualData, answers: { ...annualData.answers, shareholder_loans: true } },
    ledgerEntries,
    holdingActions: [
      {
        ...dividendAction,
        payload: { ...dividendAction.payload, tax_treatment: "outside_fritaksmetoden" },
      },
    ],
  });

  assert.deepEqual(payload.feedback.map((item) => item.code), [
    "tax_return_shareholder_loan_review_required",
    "tax_return_unclear_fritaksmetoden",
  ]);
});

test("builds no-activity payload candidate without activity warnings", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData: {
      ...annualData,
      answers: {
        ...annualData.answers,
        shares_owned_at_year_end: false,
        received_dividends: false,
        paid_costs: false,
      },
      no_activity_confirmed: true,
    },
    ledgerEntries: [{ ...ledgerEntries[0], entry_type: "opening_balance", lines: [] }],
    holdingActions: [],
  });

  assert.equal(payload.derived.noActivity, true);
  assert.equal(payload.derived.taxableBasis, 0);
  assert.deepEqual(payload.feedback.map((item) => item.code), ["tax_return_payload_candidate_ready"]);
});

test("blocks unsupported owner dividend and blocking actions", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData: { ...annualData, answers: { ...annualData.answers, declared_owner_dividends: true } },
    ledgerEntries,
    holdingActions: [{ ...dividendAction, risk_level: "block" }],
  });

  assert.deepEqual(payload.feedback.map((item) => item.code), [
    "tax_return_owner_dividend_review_required",
    "tax_return_blocking_holding_action",
  ]);
});

test("persists tax return payload feedback into skattemelding readiness", () => {
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
    holdingActions: [{ ...dividendAction, payload: { ...dividendAction.payload, tax_treatment: "needs_accountant" } }],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{ id: "lock-id", company_id: "company-id", income_year: 2025, reason: "locked", locked_by: "owner", locked_at: "2026-01-01T00:00:00Z" }],
    annualData,
    billingAccount: { company_id: "company-id", pricing_plan: "founder", monthly_nok: 29, filing_package_nok: 299, founder_cohort_number: 1, subscription_active: true, filing_package_paid: true, supported_case: true, refund_eligible: false, no_charge_reason: null },
    authorityPermissions: [
      { obligation: "aksjonaerregisteroppgaven", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "skattemelding", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
      { obligation: "aarsregnskap", confirmed_at: "2026-01-01T00:00:00Z", production_enabled: true },
    ],
    filingPreviews: [{ id: "preview-id", company_id: "company-id", setup_id: "setup-id", income_year: 2025, filing: "aksjonærregisteroppgaven", status: "ready", issues: [], preview: "RF", hovedskjema_xml: "", underskjema_xml: {}, source: "test", created_at: "2026-01-01T00:00:00Z" }],
    filingSubmissions: [],
  });
  const tax = snapshots.find((snapshot) => snapshot.obligation === "skattemelding");

  assert.equal(tax.status, "blocked");
  assert.ok(tax.hard_blocks.some((issue) => issue.code === "tax_return_unclear_fritaksmetoden"));
});
