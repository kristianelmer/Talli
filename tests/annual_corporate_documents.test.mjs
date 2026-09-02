import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildAnnualCloseDecisionInput,
  corporateAnnualSourceHash,
} from "../apps/web/app/lib/corporate-decision-facts.ts";
import { evaluateCorporateDocumentReadiness } from "../apps/web/app/lib/corporate-document-readiness.ts";
import { corporateDecisionHash, renderCorporateDocuments } from "../apps/web/app/lib/corporate-documents.ts";
import {
  buildAnnualCloseBasis,
  buildAnnualCloseReviewedFacts,
} from "../apps/web/app/lib/annual-corporate-documents.ts";

const actionsSource = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const formSource = readFileSync(
  new URL("../apps/web/app/(owner)/year-end/CorporateAnnualDecisionForm.tsx", import.meta.url),
  "utf8",
);
const yearEndSource = readFileSync(new URL("../apps/web/app/(owner)/year-end/page.tsx", import.meta.url), "utf8");
const filingSource = readFileSync(
  new URL("../apps/web/app/(owner)/filing/[obligation]/page.tsx", import.meta.url),
  "utf8",
);
const readinessSource = readFileSync(
  new URL("../apps/web/app/(owner)/filing/_readiness.ts", import.meta.url),
  "utf8",
);

const company = {
  id: "22222222-2222-4222-8222-222222222222",
  organizationNumber: "310279617",
  legalName: "LOGISK ØDE TIGER AS",
};
const shareholders = [
  { id: "owner-1", name: "Viktig Rosin", shareCount: 60, order: 0 },
  { id: "owner-2", name: "Jørgen Østby", shareCount: 40, order: 1 },
];
const annualData = {
  id: "33333333-3333-4333-8333-333333333333",
  company_id: company.id,
  income_year: 2025,
  answers: { general_meeting_approved: true },
  confirmations: ["general_meeting_approved"],
  no_activity_confirmed: false,
  annual_full_time_equivalents: 0,
  completed_at: "2026-05-01T10:00:00.000Z",
  updated_at: "2026-05-01T10:00:00.000Z",
};
const annualAccountsPayload = {
  fields: [
    { tag: "sumEgenkapital/aarets", value: 500_000 },
    { tag: "annenEgenkapital/aarets", value: 300_000 },
    { tag: "sumBankinnskuddKontanter/aarets", value: 400_000 },
    { tag: "aarsresultat/aarets", value: 125_000 },
  ],
  feedback: [],
};

function annualDecisionInput() {
  const basis = buildAnnualCloseBasis({ annualData, annualAccountsPayload });
  const reviewedFacts = buildAnnualCloseReviewedFacts({ company, shareholders, annualBasis: basis });
  return {
    basis,
    decision: buildAnnualCloseDecisionInput({
      company,
      shareholders,
      annualBasis: basis,
      submission: {
        requestId: "11111111-1111-4111-8111-111111111111",
        incomeYear: 2025,
        boardMeeting: {
          meetingDate: "2026-04-15",
          meetingTime: "09:00:00",
          place: "Os",
          treatmentMethod: "physical",
        },
        boardParticipants: [
          { participantId: "board-1", name: "Viktig Rosin", role: "chair", order: 0 },
          { participantId: "board-2", name: "Jørgen Østby", role: "member", order: 1 },
        ],
        generalMeeting: {
          meetingDate: "2026-05-10",
          meetingTime: "10:00:00",
          place: "Os",
          meetingForm: "physical",
          chairName: "Viktig Rosin",
          coSignerName: "Jørgen Østby",
        },
        shareholderVotes: [
          { shareholderId: "owner-1", representedShareCount: 60, vote: "for" },
          { shareholderId: "owner-2", representedShareCount: 40, vote: "for" },
        ],
        oneShareClassConfirmed: true,
        fullBoardParticipationConfirmed: true,
        unanimousBoardConfirmed: true,
        supportedDividendBasisConfirmed: true,
        prudentEquityAndLiquidityConfirmed: true,
        reviewedFacts,
        annualResultAllocationOre: basis.resultAfterTaxOre,
      },
    }),
  };
}

test("annual basis binds exact annual-data and annual-account payload hashes", () => {
  const { basis, decision } = annualDecisionInput();
  assert.equal(decision.decision_kind, "annual_close");
  assert.equal(decision.source_hash, corporateAnnualSourceHash(basis));
  assert.equal(decision.dividend, null);

  const changedBasis = buildAnnualCloseBasis({
    annualData,
    annualAccountsPayload: {
      ...annualAccountsPayload,
      fields: annualAccountsPayload.fields.map((field) =>
        field.tag === "aarsresultat/aarets" ? { ...field, value: 125_001 } : field),
    },
  });
  assert.notEqual(corporateAnnualSourceHash(changedBasis), decision.source_hash);
});

test("annual decision renders exactly the two annual PDF artifacts", async () => {
  const { decision } = annualDecisionInput();
  const rendered = await renderCorporateDocuments(decision);
  assert.equal(rendered.status, "rendered");
  assert.deepEqual(
    rendered.artifacts.map(({ artifactKind }) => artifactKind),
    ["annual_board_minutes", "annual_general_meeting_minutes"],
  );
});

test("annual readiness becomes stale when the persisted source facts change", () => {
  const { basis, decision } = annualDecisionInput();
  const decisionHash = corporateDecisionHash(decision);
  const input = {
    currentDecisionHash: decisionHash,
    currentSourceHash: corporateAnnualSourceHash(basis),
    decision: {
      id: decision.request_id,
      decision_kind: "annual_close",
      decision_hash: decisionHash,
      source_hash: decision.source_hash,
    },
    documentSet: {
      id: "44444444-4444-4444-8444-444444444444",
      decision_id: decision.request_id,
      decision_hash: decisionHash,
    },
    artifacts: [],
    events: [],
    finalizations: [],
  };
  assert.equal(evaluateCorporateDocumentReadiness(input).currentHashMatches, true);
  const stale = evaluateCorporateDocumentReadiness({ ...input, currentSourceHash: "f".repeat(64) });
  assert.equal(stale.currentHashMatches, false);
  assert.ok(stale.blockers.some(({ code }) => code === "corporate_documents_current_hash_mismatch"));
});

test("annual server action uses backend canonicalization and rendered artifacts", () => {
  assert.match(actionsSource, /export async function createAnnualCorporateDecisionDraft\s*\(formData: FormData\)/);
  const start = actionsSource.indexOf("export async function createAnnualCorporateDecisionDraft");
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  const action = actionsSource.slice(start, end < 0 ? undefined : end);
  assert.match(action, /proposeAnnualClose/);
  assert.match(action, /annual_board_minutes/);
  assert.match(action, /annual_general_meeting_minutes/);
  assert.match(action, /renderedArtifacts|persistCorporateDocumentDraft/);
  assert.doesNotMatch(action, /buildAnnualCloseDecisionInput|renderCorporateDocuments/);
  assert.match(action, /create_corporate_document_draft|persistCorporateDocumentDraft/);
  assert.doesNotMatch(action, /\.from\(["']ledger_entries["']\)\.insert/);
  assert.doesNotMatch(action, /\.from\(["']holding_actions["']\)\.insert/);

  const refreshStart = actionsSource.indexOf("export async function refreshAnnualReadinessSnapshots");
  const refreshEnd = actionsSource.indexOf("\nexport async function ", refreshStart + 1);
  const refresh = actionsSource.slice(refreshStart, refreshEnd < 0 ? undefined : refreshEnd);
  assert.match(refresh, /corporateDocuments/);
  assert.match(refresh, /currentAnnualSourceHash/);
  assert.match(refresh, /corporateDecisionFinalizations/);
});

test("year-end and filing UI expose the annual corporate lifecycle honestly", () => {
  for (const field of [
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
  ]) {
    assert.match(formSource, new RegExp(`name=["']${field}["']`));
  }
  assert.match(formSource, /årsregnskapet krever separat.*signatur/is);
  assert.match(formSource, /kildehash/i);
  assert.match(formSource, /malversjon/i);
  assert.match(yearEndSource, /CorporateAnnualDecisionForm/);
  assert.match(`${yearEndSource}\n${formSource}`, /superseded|erstattet/i);
  assert.match(filingSource, /corporate_documents|beslutningsdokument/i);
  assert.match(readinessSource, /corporateDocuments/);
});
