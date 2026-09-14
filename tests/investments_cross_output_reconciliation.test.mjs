import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { buildPersistedCompanyArchive } from "../apps/web/app/lib/archive.ts";
import { buildCompanyTaxReturnPayload } from "./support/company_tax_public.mjs";
import { renderRf1086SourceFacts } from "./support/rf1086-source-facts.mjs";
import { estimateAnnualTax } from "./support/company_tax_public.mjs";
import { effectiveInvestmentActivity } from "../apps/web/features/investments/presentation.ts";

const companyId = "10000000-0000-4000-8000-000000000190";
const actorId = "20000000-0000-4000-8000-000000000190";
const incomeYear = 2026;
const evidence = JSON.parse(readFileSync(new URL(
  "fixtures/investments-supported-patterns.json",
  import.meta.url,
), "utf8"));

const company = {
  id: companyId,
  org_number: "314259521",
  name: "Avstemt Holding AS",
  entity_type: "AS",
  address: "Storgata 1",
  postal_code: "0155",
  city: "OSLO",
  status_text: "aktiv",
  source: "brreg",
  created_by: actorId,
  identity_confirmed_at: "2026-01-01T00:00:00Z",
  identity_locked_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

const setup = {
  id: "30000000-0000-4000-8000-000000000190",
  company_id: companyId,
  income_year: incomeYear,
  bank_balance: 30000,
  share_capital: 30000,
  share_count: 100,
  nominal_value: 300,
  locked_at: "2026-01-01T00:00:00Z",
  created_by: actorId,
};

const shareholders = [{
  id: "40000000-0000-4000-8000-000000000190",
  setup_id: setup.id,
  company_id: companyId,
  name: "Ola Nordmann",
  shareholder_kind: "norwegian_person",
  national_id: "01017012345",
  org_number: null,
  share_count: 100,
}];

const annualData = {
  id: "50000000-0000-4000-8000-000000000190",
  company_id: companyId,
  income_year: incomeYear,
  answers: {
    shares_owned_at_year_end: true,
    bought_or_sold_shares: false,
    received_dividends: true,
    declared_owner_dividends: false,
    shareholder_loans: false,
    paid_costs: false,
    bank_balance_confirmed: true,
    has_unpaid_items: false,
    general_meeting_approved: true,
    authority_to_submit_confirmed: true,
  },
  confirmations: [
    "bank_balance_confirmed",
    "general_meeting_approved",
    "authority_to_submit_confirmed",
  ],
  no_activity_confirmed: false,
  annual_full_time_equivalents: 0,
  completed_by: actorId,
  completed_at: "2026-12-31T12:00:00Z",
  updated_by: actorId,
  updated_at: "2026-12-31T12:00:00Z",
};

function ledgerEntry(id, sourceRecordId, entryType, lines) {
  return {
    id,
    company_id: companyId,
    setup_id: null,
    income_year: incomeYear,
    entry_type: entryType,
    memo: entryType,
    lines,
    source_capability: "INVESTMENTS",
    source_record_id: sourceRecordId,
    risk_flags: [],
    warning_accepted_by: null,
    warning_accepted_at: null,
    created_by: actorId,
    created_at: "2026-12-31T12:00:00Z",
  };
}

function action(id, actionType, ledgerEntryId, actionDate, payload) {
  return {
    id,
    company_id: companyId,
    income_year: incomeYear,
    action_type: actionType,
    action_date: actionDate,
    payload,
    ledger_entry_id: ledgerEntryId,
    bank_transaction_id: null,
    document_id: null,
    risk_level: "ready",
    blocker_code: null,
    created_by: actorId,
    created_at: `${actionDate}T12:00:00Z`,
  };
}

const activity = [
  action("a0000000-0000-4000-8000-000000000001", "share_purchase", "e0000000-0000-4000-8000-000000000001", "2026-01-02", {
    investment_name: "Norsk Privat AS",
    tax_treatment: "fritaksmetoden",
    calculation_id: "1".repeat(64),
    purchase_amount: 1000,
    transaction_costs: 0,
    capitalized_cost: 1000,
  }),
  action("a0000000-0000-4000-8000-000000000002", "share_purchase", "e0000000-0000-4000-8000-000000000002", "2026-01-03", {
    investment_name: "Norsk Fond",
    tax_treatment: "fritaksmetoden",
    calculation_id: "2".repeat(64),
    purchase_amount: 500,
    transaction_costs: 0,
    capitalized_cost: 500,
  }),
  action("a0000000-0000-4000-8000-000000000003", "share_sale", "e0000000-0000-4000-8000-000000000003", "2026-06-01", {
    investment_name: "Norsk Privat AS",
    tax_treatment: "fritaksmetoden",
    calculation_id: "3".repeat(64),
    proceeds: 600,
    book_gain_or_loss: 100,
    tax_gain_or_loss: 100,
    exempt_gain: 100,
    taxable_gain: 0,
    non_deductible_loss: 0,
    deductible_loss: 0,
  }),
  action("a0000000-0000-4000-8000-000000000004", "dividend_received", "e0000000-0000-4000-8000-000000000004", "2026-07-01", {
    paying_company_name: "Norsk Privat AS",
    tax_treatment: "fritaksmetoden",
    calculation_id: "4".repeat(64),
    gross_amount: 100,
    taxable_add_back: 3,
  }),
  action("a0000000-0000-4000-8000-000000000005", "fund_distribution_received", "e0000000-0000-4000-8000-000000000005", "2026-08-01", {
    fund_name: "Norsk Fond",
    tax_treatment: "fritaksmetoden",
    calculation_id: "5".repeat(64),
    gross_amount: 100,
    dividend_portion: 50,
    interest_portion: 50,
    taxable_add_back: 1.5,
    total_taxable_income: 51.5,
  }),
];

const ledgerEntries = [
  ledgerEntry(activity[0].ledger_entry_id, activity[0].id, "share_purchase", [
    { account: "1300", debit: 1000, credit: 0 },
    { account: "2990", debit: 0, credit: 1000 },
  ]),
  ledgerEntry("e1000000-0000-4000-8000-000000000001", "s0000000-0000-4000-8000-000000000001", "investment_cash_settlement", [
    { account: "2990", debit: 1000, credit: 0 },
    { account: "1920", debit: 0, credit: 1000 },
  ]),
  ledgerEntry(activity[1].ledger_entry_id, activity[1].id, "share_purchase", [
    { account: "1815", debit: 500, credit: 0 },
    { account: "2990", debit: 0, credit: 500 },
  ]),
  ledgerEntry("e1000000-0000-4000-8000-000000000002", "s0000000-0000-4000-8000-000000000002", "investment_cash_settlement", [
    { account: "2990", debit: 500, credit: 0 },
    { account: "1920", debit: 0, credit: 500 },
  ]),
  ledgerEntry(activity[2].ledger_entry_id, activity[2].id, "share_sale", [
    { account: "1570", debit: 600, credit: 0 },
    { account: "1300", debit: 0, credit: 500 },
    { account: "8071", debit: 0, credit: 100 },
  ]),
  ledgerEntry("e1000000-0000-4000-8000-000000000003", "s0000000-0000-4000-8000-000000000003", "investment_cash_settlement", [
    { account: "1920", debit: 600, credit: 0 },
    { account: "1570", debit: 0, credit: 600 },
  ]),
  ledgerEntry(activity[3].ledger_entry_id, activity[3].id, "dividend_received", [
    { account: "1530", debit: 100, credit: 0 },
    { account: "8070", debit: 0, credit: 100 },
  ]),
  ledgerEntry("e1000000-0000-4000-8000-000000000004", "s0000000-0000-4000-8000-000000000004", "investment_cash_settlement", [
    { account: "1920", debit: 100, credit: 0 },
    { account: "1530", debit: 0, credit: 100 },
  ]),
  ledgerEntry(activity[4].ledger_entry_id, activity[4].id, "fund_distribution_received", [
    { account: "1530", debit: 100, credit: 0 },
    { account: "8070", debit: 0, credit: 50 },
    { account: "8050", debit: 0, credit: 50 },
  ]),
  ledgerEntry("e1000000-0000-4000-8000-000000000005", "s0000000-0000-4000-8000-000000000005", "investment_cash_settlement", [
    { account: "1920", debit: 100, credit: 0 },
    { account: "1530", debit: 0, credit: 100 },
  ]),
];

const positions = [
  { id: "p-private", company_id: companyId, share_count: 50, cost_basis: 500, tax_basis: 500 },
  { id: "p-fund", company_id: companyId, share_count: 10, cost_basis: 500, tax_basis: 500 },
];
const lots = [
  { id: "l-private", company_id: companyId, position_id: "p-private", remaining_share_count: 50, remaining_cost_basis: 500, remaining_tax_basis: 500 },
  { id: "l-fund", company_id: companyId, position_id: "p-fund", remaining_share_count: 10, remaining_cost_basis: 500, remaining_tax_basis: 500 },
];

function fieldValue(payload, tag) {
  return payload.fields.find((field) => field.tag === tag)?.value;
}

function archiveInput(overrides = {}) {
  return {
    company,
    incomeYear,
    setups: [setup],
    shareholders,
    ledgerEntries,
    documents: [],
    holdingActions: activity,
    investmentPositions: positions,
    investmentLots: lots,
    effectiveInvestmentActions: activity,
    filingPreviews: [],
    filingSubmissions: [],
    ...overrides,
  };
}

test("positions and FIFU lots reconcile cent-exactly to the canonical ledger", () => {
  const positionBook = positions.reduce((sum, position) => sum + position.cost_basis, 0);
  const lotBook = lots.reduce((sum, lot) => sum + lot.remaining_cost_basis, 0);
  const positionTax = positions.reduce((sum, position) => sum + position.tax_basis, 0);
  const lotTax = lots.reduce((sum, lot) => sum + lot.remaining_tax_basis, 0);
  const investmentAccounts = new Set(["1300", "1310", "1350", "1800", "1810", "1815"]);
  const ledgerBook = ledgerEntries.flatMap((entry) => entry.lines)
    .filter((line) => investmentAccounts.has(line.account))
    .reduce((sum, line) => sum + Number(line.debit ?? 0) - Number(line.credit ?? 0), 0);

  assert.equal(positionBook, 1000);
  assert.equal(positionBook, lotBook);
  assert.equal(positionTax, lotTax);
  assert.equal(positionBook, ledgerBook);
});

test("one effective fact set reconciles tax, annual accounts, SAF-T input, archive, and RF-1086", () => {
  const companyTax = buildCompanyTaxReturnPayload({
    companyOrgNumber: company.org_number,
    incomeYear,
    annualData,
    ledgerEntries,
    holdingActions: activity,
  });
  const annualAccounts = buildAnnualAccountsPayload({ incomeYear, annualData, ledgerEntries });
  const taxEstimate = estimateAnnualTax({ ledgerEntries, holdingActions: activity });
  const archive = buildPersistedCompanyArchive(archiveInput());

  assert.equal(companyTax.derived.dividendIncome, 150);
  assert.equal(companyTax.derived.bookShareSaleGain, 100);
  assert.equal(companyTax.derived.exemptShareSaleGain, 100);
  assert.equal(companyTax.derived.fritaksmetodenAddBack, 4.5);
  assert.equal(companyTax.derived.taxableBasis, 54.5);
  assert.equal(taxEstimate.taxBasis, 54.5);
  assert.equal(fieldValue(annualAccounts, "investeringAksjerAndeler/aarets"), 1000);
  assert.equal(fieldValue(annualAccounts, "sumFinansinntekter/aarets"), 300);

  const saftSourceIds = ledgerEntries
    .filter((entry) => entry.source_capability === "INVESTMENTS")
    .map((entry) => entry.source_record_id)
    .sort();
  assert.deepEqual(saftSourceIds, [
    ...activity.map((item) => item.id),
    ...activity.map((_, index) => `s0000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`),
  ].sort());
  assert.deepEqual(
    archive.effectiveInvestmentActions.map((item) => item.id),
    activity.map((item) => item.id),
  );
  assert.deepEqual(archive.investmentPositions, positions);
  assert.deepEqual(archive.investmentLots, lots);

  const issuerOnlyBefore = renderRf1086SourceFacts(company, setup, shareholders);
  const issuerOnlyAfter = renderRf1086SourceFacts(company, setup, shareholders);
  assert.equal(issuerOnlyAfter.status, "ready");
  assert.equal(issuerOnlyAfter.hovedskjema_xml, issuerOnlyBefore.hovedskjema_xml);
  assert.deepEqual(issuerOnlyAfter.underskjema_xml, issuerOnlyBefore.underskjema_xml);
  for (const investmentAction of activity) {
    assert.doesNotMatch(issuerOnlyAfter.hovedskjema_xml ?? "", new RegExp(investmentAction.id, "u"));
  }
});

test("every approved golden case traces recognition and settlement identities separately", () => {
  for (const pattern of evidence.acceptedPatterns) {
    assert.equal(pattern.reconciliation.investments.economicEventId, pattern.input.eventId);
    assert.equal(pattern.reconciliation.investments.settlementId, pattern.input.settlementId);
    assert.equal(pattern.reconciliation.ledger.recognitionSourceRecordId, pattern.input.eventId);
    assert.equal(pattern.reconciliation.ledger.settlementSourceRecordId, pattern.input.settlementId);
    assert.deepEqual(
      pattern.reconciliation.saft.sourceRecordIds,
      [pattern.input.eventId, pattern.input.settlementId],
    );
    assert.equal(pattern.reconciliation.rf1086.effect, "none");
  }
});

test("a correction retains history while every effective output counts only the replacement", () => {
  const original = action(
    "a0000000-0000-4000-8000-000000000011",
    "dividend_received",
    "e0000000-0000-4000-8000-000000000011",
    "2026-09-01",
    { tax_treatment: "fritaksmetoden", calculation_id: "a".repeat(64), gross_amount: 100, taxable_add_back: 3 },
  );
  const replacement = action(
    "a0000000-0000-4000-8000-000000000012",
    "dividend_received",
    "e0000000-0000-4000-8000-000000000013",
    "2026-09-01",
    { tax_treatment: "fritaksmetoden", calculation_id: "b".repeat(64), gross_amount: 120, taxable_add_back: 3.6 },
  );
  const correction = {
    id: "c0000000-0000-4000-8000-000000000011",
    company_id: companyId,
    income_year: incomeYear,
    target_kind: "economic_event",
    original_record_id: original.id,
    original_activity_kind: "dividend_received",
    reversal_accounting_entry_id: "e0000000-0000-4000-8000-000000000012",
    replacement_record_id: replacement.id,
    replacement_activity_kind: "dividend_received",
    replacement_accounting_entry_id: replacement.ledger_entry_id,
    reason: "Rettet mot utbytteoppgaven.",
    document_facts: [],
    legacy_bank_transaction_id: null,
    legacy_document_id: null,
    legacy_document_status: null,
    legacy: false,
    evidence_mode: "manual_fallback",
    evidence_reference: "correction-evidence",
    evidence_digest: "c".repeat(64),
    owner_attested: true,
    created_by: actorId,
    created_at: "2026-09-02T12:00:00Z",
  };
  const correctedLedger = [
    ledgerEntry(original.ledger_entry_id, original.id, "dividend_received", [
      { account: "1920", debit: 100, credit: 0 },
      { account: "8070", debit: 0, credit: 100 },
    ]),
    ledgerEntry(correction.reversal_accounting_entry_id, `correction-reversal:${original.ledger_entry_id}`, "correction_reversal", [
      { account: "1920", debit: 0, credit: 100 },
      { account: "8070", debit: 100, credit: 0 },
    ]),
    ledgerEntry(replacement.ledger_entry_id, replacement.id, "dividend_received", [
      { account: "1920", debit: 120, credit: 0 },
      { account: "8070", debit: 0, credit: 120 },
    ]),
  ];
  const history = [original, replacement];
  const effective = effectiveInvestmentActivity(history, [correction]);
  const tax = buildCompanyTaxReturnPayload({
    companyOrgNumber: company.org_number,
    incomeYear,
    annualData,
    ledgerEntries: correctedLedger,
    holdingActions: effective,
  });
  const annual = buildAnnualAccountsPayload({ incomeYear, annualData, ledgerEntries: correctedLedger });
  const archive = buildPersistedCompanyArchive(archiveInput({
    ledgerEntries: correctedLedger,
    holdingActions: history,
    investmentCorrections: [correction],
    effectiveInvestmentActions: effective,
  }));

  assert.deepEqual(effective.map((item) => item.id), [replacement.id]);
  assert.equal(tax.derived.dividendIncome, 120);
  assert.equal(tax.derived.fritaksmetodenAddBack, 3.6);
  assert.equal(tax.derived.taxableBasis, 3.6);
  assert.equal(fieldValue(annual, "sumFinansinntekter/aarets"), 120);
  assert.deepEqual(archive.investmentActivityHistory.map((item) => item.id), [original.id, replacement.id]);
  assert.deepEqual(archive.effectiveInvestmentActions.map((item) => item.id), [replacement.id]);
  assert.equal(archive.investmentCorrections[0].original_record_id, original.id);
});
