import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildOwnerDividendAnnualBasis,
  buildOwnerDividendReviewedFacts,
  OwnerDividendDraftBasisError,
} from "../app/lib/owner-dividend.ts";

const ownerDividendSource = readFileSync(
  new URL("../app/lib/owner-dividend.ts", import.meta.url),
  "utf8",
);
const actionsSource = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const wizardSource = readFileSync(
  new URL("../app/(owner)/actions/_components/OwnerDividendWizard.tsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);
const pythonHoldingActionsSource = readFileSync(
  new URL("../holding_core/holding_actions.py", import.meta.url),
  "utf8",
);
const pythonWorkspaceSource = readFileSync(
  new URL("../holding_core/workspace.py", import.meta.url),
  "utf8",
);

test("legacy owner-dividend accounting and placeholder helpers are gone", () => {
  assert.doesNotMatch(ownerDividendSource, /ownerDividendLedgerLines/);
  assert.doesNotMatch(ownerDividendSource, /ownerDividendCorporateDocumentRecords/);
  assert.doesNotMatch(ownerDividendSource, /account:\s*["'](?:1920|2050)["']/);
  assert.doesNotMatch(ownerDividendSource, /\.txt/);
  assert.doesNotMatch(pythonHoldingActionsSource, /build_dividend_to_owner/);
  assert.doesNotMatch(pythonHoldingActionsSource, /Cash dividend paid to shareholders/);
  assert.doesNotMatch(pythonHoldingActionsSource, /Dividend paid from bank/);
  assert.doesNotMatch(pythonWorkspaceSource, /DividendToOwnerInput/);
});

test("dividend basis is recomputed from approved persisted annual facts in integer ore", () => {
  const annualData = {
    id: "10000000-0000-4000-8000-000000000001",
    company_id: "20000000-0000-4000-8000-000000000001",
    income_year: 2025,
    answers: { general_meeting_approved: true, exact_persisted_answer: "bound" },
    confirmations: ["annual_accounts_reviewed"],
    no_activity_confirmed: false,
    annual_full_time_equivalents: 0,
    completed_at: "2026-05-01T10:00:00.000Z",
    updated_at: "2026-05-01T10:00:00.000Z",
  };
  const annualAccountsPayload = {
    fields: [
      { tag: "sumEgenkapital/aarets", value: 250_000.25 },
      { tag: "annenEgenkapital/aarets", value: 125_000.15 },
      { tag: "sumBankinnskuddKontanter/aarets", value: 90_000.05 },
      { tag: "aarsresultat/aarets", value: 20_000.1 },
    ],
    feedback: [],
  };

  const basis = buildOwnerDividendAnnualBasis({ annualData, annualAccountsPayload });
  assert.equal(basis.equityOre, 25_000_025);
  assert.equal(basis.availableDistributionOre, 12_500_015);
  assert.equal(basis.cashOre, 9_000_005);
  assert.equal(basis.resultAfterTaxOre, 2_000_010);
  assert.match(basis.annualDataHash, /^[0-9a-f]{64}$/);
  assert.match(basis.annualAccountsPayloadHash, /^[0-9a-f]{64}$/);

  const facts = buildOwnerDividendReviewedFacts({
    company: {
      id: annualData.company_id,
      organizationNumber: "310279617",
      legalName: "LOGISK ØDE TIGER AS",
    },
    shareholders: [
      { id: "b", name: "B Eier", shareCount: 40, order: 2 },
      { id: "a", name: "A Eier", shareCount: 60, order: 1 },
    ],
    annualBasis: basis,
  });
  assert.deepEqual(facts.shareholders.map(({ shareholderId }) => shareholderId), ["a", "b"]);
  assert.equal(facts.totalCompanyShares, 100);
  assert.equal(facts.availableDistributionOre, basis.availableDistributionOre);
});

test("dividend basis fails closed on unapproved or blocked annual facts", () => {
  const annualData = {
    id: "10000000-0000-4000-8000-000000000001",
    company_id: "20000000-0000-4000-8000-000000000001",
    income_year: 2025,
    answers: { general_meeting_approved: false },
    confirmations: [],
    no_activity_confirmed: false,
    completed_at: "2026-05-01T10:00:00.000Z",
    updated_at: "2026-05-01T10:00:00.000Z",
  };
  const validFields = [
    { tag: "sumEgenkapital/aarets", value: 1 },
    { tag: "annenEgenkapital/aarets", value: 1 },
    { tag: "sumBankinnskuddKontanter/aarets", value: 1 },
    { tag: "aarsresultat/aarets", value: 1 },
  ];

  assert.throws(
    () => buildOwnerDividendAnnualBasis({ annualData, annualAccountsPayload: { fields: validFields, feedback: [] } }),
    (error) => error instanceof OwnerDividendDraftBasisError
      && error.code === "corporate_documents_latest_annual_accounts_required",
  );
  assert.throws(
    () => buildOwnerDividendAnnualBasis({
      annualData: { ...annualData, answers: { general_meeting_approved: true } },
      annualAccountsPayload: {
        fields: validFields,
        feedback: [{ level: "block", code: "annual_accounts_unbalanced", message: "Ubalansert." }],
      },
    }),
    (error) => error instanceof OwnerDividendDraftBasisError && error.code === "annual_accounts_unbalanced",
  );
});

test("server exposes only the draft action and never posts accounting directly", () => {
  assert.match(actionsSource, /export async function createOwnerDividendDecisionDraft\s*\(formData: FormData\)/);
  assert.doesNotMatch(actionsSource, /export async function recordOwnerDividend\s*\(/);

  const start = actionsSource.indexOf("export async function createOwnerDividendDecisionDraft");
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  const action = actionsSource.slice(start, end < 0 ? undefined : end);
  assert.match(action, /TALLI_CORPORATE_DOCUMENTS_ENABLED/);
  assert.match(action, /buildOwnerDividendDecisionInput/);
  assert.match(action, /renderCorporateDocuments|persistCorporateDocumentDraft/);
  assert.match(action, /uploadCorporateArtifacts|persistCorporateDocumentDraft/);
  assert.match(action, /create_corporate_document_draft|persistCorporateDocumentDraft/);
  assert.doesNotMatch(action, /\.from\(["']ledger_entries["']\)\.insert/);
  assert.doesNotMatch(action, /\.from\(["']holding_actions["']\)\.insert/);
  assert.doesNotMatch(action, /\.from\(["']documents["']\)\.insert/);
  assert.doesNotMatch(ownerDividendSource, /dividend_payable_account|bank_account|ledgerLines/i);
});

test("wizard reviews all owners and meeting facts with proportional allocation only", () => {
  for (const field of [
    "dividendAmountOre",
    "paymentDate",
    "boardMeetingDate",
    "boardMeetingTime",
    "boardMeetingPlace",
    "boardTreatmentMethod",
    "generalMeetingDate",
    "generalMeetingTime",
    "generalMeetingPlace",
    "generalMeetingForm",
    "generalMeetingChairName",
    "generalMeetingCoSignerName",
    "oneShareClassConfirmed",
    "fullBoardParticipationConfirmed",
    "unanimousBoardConfirmed",
    "supportedDividendBasisConfirmed",
    "prudentEquityAndLiquidityConfirmed",
  ]) {
    assert.match(wizardSource, new RegExp(`name=["']${field}["']`));
  }
  assert.match(wizardSource, /shareholders\.map/);
  assert.match(wizardSource, /boardParticipants\.map/);
  assert.match(wizardSource, /shareholderVotes/);
  assert.match(wizardSource, /proporsjonal/i);
  assert.match(wizardSource, /utkast/i);
  assert.match(wizardSource, /godkjent for signering/i);
  assert.doesNotMatch(wizardSource, /name=["']allocationAmount["']/);
  assert.doesNotMatch(wizardSource, /name=["']distributableEquity["']/);
  assert.doesNotMatch(wizardSource, /name=["']liquidityAfterPayment["']/);
});

test("workspace no longer embeds the legacy posting form or placeholder copy", () => {
  assert.doesNotMatch(workspaceSource, /recordOwnerDividend(?!Payment)/);
  assert.doesNotMatch(workspaceSource, /Poster eierutbytte/);
  assert.doesNotMatch(workspaceSource, /placeholders/i);
});
