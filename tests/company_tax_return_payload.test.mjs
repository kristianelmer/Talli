import assert from "node:assert/strict";
import test from "node:test";

import { buildPersistedCompanyArchive } from "../apps/web/app/lib/archive.ts";
import { buildCompanyTaxReturnPayload } from "../apps/web/app/lib/company-tax-return.ts";
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
  assert.equal(fields["skattemelding.inntektOgUnderskudd.inntekt.naeringsinntekt.beloepSomHeltall"].value, 1510);
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

test("uses the current-draft party number for both authority documents", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    companyPartyNumber: "9000020078",
    incomeYear: 2025,
    annualData,
    ledgerEntries,
    holdingActions: [dividendAction],
  });
  const fields = Object.fromEntries(payload.fields.map((field) => [field.path, field]));

  assert.equal(fields["skattemelding.partsnummer"].value, "9000020078");
  assert.equal(fields["naeringsspesifikasjon.partsreferanse"].value, "9000020078");
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
  assert.equal(fields["skattemelding.inntektOgUnderskudd.inntekt.naeringsinntekt.beloepSomHeltall"].value, 646);
  assert.equal(fields["resultatregnskap.driftskostnad.annenDriftskostnad.kostnad[0].type.resultatOgBalanseregnskapstype"].value, "6700");
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[1].type.resultatOgBalanseregnskapstype"].value, "8050");
  assert.equal(fields["resultatregnskap.finansinntekt.inntekt[2].type.resultatOgBalanseregnskapstype"].value, "8074");
  assert.equal(fields["resultatregnskap.finanskostnad.kostnad[0].type.resultatOgBalanseregnskapstype"].value, "8174");
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[2].permanentForskjellstype.permanentForskjellstype"].value, "regnskapsmessigGevinstVedRealisasjonAvFinansielleInstrumenter");
  assert.equal(fields["forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[3].permanentForskjellstype.permanentForskjellstype"].value, "regnskapsmessigTapVedRealisasjonAvFinansielleInstrumenter");
  assert.deepEqual(payload.feedback.map((item) => item.code), ["tax_return_share_sale_or_purchase_review"]);
});

test("renders a negative taxable basis as a positive whole-number loss", () => {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData,
    ledgerEntries: [{
      ...ledgerEntries[0],
      lines: [{ account: "7770", debit: 100.5, credit: 0 }],
    }],
    holdingActions: [],
  });
  const loss = payload.fields.find(
    (field) => field.path === "skattemelding.inntektOgUnderskudd.inntektsfradrag.underskudd.beloepSomHeltall",
  );

  assert.equal(payload.derived.taxableBasis, -100.5);
  assert.equal(loss?.value, 101);
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
  const incomeField = payload.fields.find(
    (field) => field.path === "skattemelding.inntektOgUnderskudd.inntekt.naeringsinntekt.beloepSomHeltall",
  );
  assert.equal(incomeField?.value, 0);
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
    companyTaxReadiness: { companyId: "company-id", incomeYear: 2025, issues: [{ level: "block", code: "tax_return_unclear_fritaksmetoden", message: "Kun sikker fritaksmetodebehandling støttes i første skattemelding-løype.", source: "company_tax_return_payload", accepted: false }] },
    setups: [{ id: "setup-id", company_id: "company-id", income_year: 2025, bank_balance: 1, share_capital: 1, share_count: 1, nominal_value: 1, locked_at: "2026-01-01T00:00:00Z", created_by: "owner" }],
    ledgerEntries,
    holdingActions: [{ ...dividendAction, payload: { ...dividendAction.payload, tax_treatment: "needs_accountant" } }],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{ id: "lock-id", company_id: "company-id", income_year: 2025, reason: "locked", locked_by: "owner", locked_at: "2026-01-01T00:00:00Z" }],
    annualData,
    billingEntitlements: readyBillingEntitlements,
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

test("archives pending company-tax TT02 feedback without relabeling it as a simulated receipt", () => {
  const companyTaxReceiptId = "70beee03-d8c2-4584-b366-8231c6de6584";
  const archiveReference = "https://platform.tt02.altinn.no/storage/api/v1/instances/instance-id";
  const feedbackItems = [{
    severity: "warning",
    code: "COMPANY_TAX_AUTHORITY_OUTCOME_PENDING",
    message: "Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.",
    documentId: companyTaxReceiptId,
  }];
  const receiptMetadata = {
    authority: "skatteetaten",
    receiptId: companyTaxReceiptId,
    status: "feedback_ready",
    receivedAt: "2026-07-14T12:32:00.000Z",
    feedbackDocumentIds: [companyTaxReceiptId],
    dataType: "tilbakemelding",
    contentType: "application/xml",
    byteLength: 527,
    contentSha256: "f".repeat(64),
    reference: `${archiveReference}/data/${companyTaxReceiptId}`,
    archiveReference,
    processEndedAt: "2026-07-14T12:30:00.000Z",
    archivedAt: "2026-07-14T12:31:00.000Z",
  };
  const submittedPayloadReference = {
    companyOrgNumber: "310279617",
    incomeYear: 2025,
    envelopeDataId: "7bbb17d7-5af0-4a17-9ed6-0647bcc845b5",
    archiveReference,
    payloadHash: "a".repeat(64),
    skattemeldingHash: "b".repeat(64),
    naeringsspesifikasjonHash: "c".repeat(64),
    validationEnvelopeHash: "d".repeat(64),
    submissionEnvelopeHash: "e".repeat(64),
    currentDocumentReferenceHash: "0".repeat(64),
    storedAt: "2026-07-14T12:32:00.000Z",
  };
  const commonSubmission = {
    preview_id: null,
    authority_test_run_id: null,
    company_id: "company-id",
    income_year: 2025,
    payload_hash: "a".repeat(64),
    idempotency_key: "company-tax:company-id:2025:payload-hash",
    authority_confirmed_at: null,
    preview_confirmed_at: null,
    submitted_by: null,
    created_at: "2026-07-14T12:32:00.000Z",
    updated_at: "2026-07-14T12:32:00.000Z",
  };
  const archive = buildPersistedCompanyArchive({
    company: {
      id: "company-id",
      org_number: "310279617",
      name: "Logisk Øde Tiger AS",
      entity_type: "AS",
      address: "",
      postal_code: "",
      city: "",
      status_text: "aktiv",
      source: "test",
      created_by: "owner",
      identity_confirmed_at: "2026-01-01T00:00:00.000Z",
      identity_locked_at: "2026-01-01T00:00:00.000Z",
      created_at: "2026-01-01T00:00:00.000Z",
    },
    incomeYear: 2025,
    setups: [],
    shareholders: [],
    ledgerEntries: [],
    documents: [],
    authorityTestRuns: [{
      id: "company-tax-authority-run-id",
      company_id: "company-id",
      obligation: "skattemelding",
      environment: "test",
      status: "pending",
      test_reference: "tt02:51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108",
      feedback_summary: "validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.",
      receipt_reference: receiptMetadata.reference,
      archive_reference: archiveReference,
      evidence_url: "https://evidence.example/company-tax-tt02.json",
      payload_hash: `sha256:${"a".repeat(64)}`,
      recorded_by: "owner",
      recorded_at: "2026-07-14T12:32:00.000Z",
    }],
    filingPreviews: [],
    filingSubmissions: [
      {
        ...commonSubmission,
        id: "simulation-id",
        filing: "aksjonærregisteroppgaven",
        mode: "simulation",
        adapter_mode: "simulation",
        status: "receipt_stored",
        calls: [],
        receipt_id: "simulation-receipt-id",
        feedback_document_ids: [],
        feedback_items: [],
        receipt_metadata: null,
        submitted_payload_ref: null,
        submitted_payload: null,
      },
      {
        ...commonSubmission,
        id: "company-tax-submission-id",
        authority_test_run_id: "company-tax-authority-run-id",
        filing: "skattemelding for AS",
        mode: "test_authority",
        adapter_mode: "test_authority",
        status: "feedback_ready",
        calls: [{
          endpoint: "altinn:official-feedback-receipt",
          body_hash: "f".repeat(64),
          idempotency_key: null,
          status: "received",
          created_at: "2026-07-14T12:32:00.000Z",
        }],
        receipt_id: companyTaxReceiptId,
        feedback_document_ids: [companyTaxReceiptId],
        feedback_items: feedbackItems,
        receipt_metadata: receiptMetadata,
        submitted_payload_ref: submittedPayloadReference,
        submitted_payload: null,
      },
    ],
  });

  assert.equal(archive.companyTaxSubmissions.length, 1);
  assert.deepEqual(archive.companyTaxSubmissions[0], {
    id: "company-tax-submission-id",
    authorityTestRunId: "company-tax-authority-run-id",
    incomeYear: 2025,
    mode: "test_authority",
    adapterMode: "test_authority",
    status: "feedback_ready",
    payloadHash: "a".repeat(64),
    idempotencyKey: "company-tax:company-id:2025:payload-hash",
    receiptId: companyTaxReceiptId,
    feedbackDocumentIds: [companyTaxReceiptId],
    feedbackItems,
    receiptMetadata,
    submittedPayloadReference,
    submittedPayload: null,
    calls: [{
      endpoint: "altinn:official-feedback-receipt",
      bodyHash: "f".repeat(64),
      idempotencyKey: null,
      status: "received",
    }],
    submittedBy: null,
    createdAt: "2026-07-14T12:32:00.000Z",
    updatedAt: "2026-07-14T12:32:00.000Z",
  });
  assert.equal(archive.companyTaxSubmissions[0].submittedPayload, null);
  assert.deepEqual(archive.simulatedReceipts.map((receipt) => receipt.receiptId), ["simulation-receipt-id"]);
});
