import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildAnnualCloseBasis,
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

const annualData = {
  id: "33333333-3333-4333-8333-333333333333",
  company_id: "22222222-2222-4222-8222-222222222222",
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

test("annual basis binds exact annual-data and annual-account payload hashes", () => {
  const basis = buildAnnualCloseBasis({ annualData, annualAccountsPayload });
  assert.match(basis.annualDataHash, /^[0-9a-f]{64}$/u);
  assert.match(basis.annualAccountsPayloadHash, /^[0-9a-f]{64}$/u);

  const changedBasis = buildAnnualCloseBasis({
    annualData,
    annualAccountsPayload: {
      ...annualAccountsPayload,
      fields: annualAccountsPayload.fields.map((field) =>
        field.tag === "aarsresultat/aarets" ? { ...field, value: 125_001 } : field),
    },
  });
  assert.notEqual(changedBasis.annualAccountsPayloadHash, basis.annualAccountsPayloadHash);
});

test("annual decisions render only inside the Python backend", () => {
  const webRenderer = readFileSync(
    new URL("../apps/web/app/lib/corporate-documents.ts", import.meta.url),
    "utf8",
  );
  const backendRenderer = readFileSync(
    new URL(
      "../apps/backend/src/talli_backend/modules/corporate_governance/rendering.py",
      import.meta.url,
    ),
    "utf8",
  );
  assert.doesNotMatch(webRenderer, /child_process|holding_cli|renderCorporateDocuments/u);
  assert.match(backendRenderer, /ANNUAL_BOARD_MINUTES/u);
  assert.match(backendRenderer, /ANNUAL_GENERAL_MEETING_MINUTES/u);
});

test("annual readiness is read from the Python governance API", () => {
  const transport = readFileSync(
    new URL("../apps/web/features/corporate-governance/transport.ts", import.meta.url),
    "utf8",
  );
  const service = readFileSync(
    new URL(
      "../apps/backend/src/talli_backend/modules/corporate_governance/service.py",
      import.meta.url,
    ),
    "utf8",
  );
  assert.match(transport, /corporateGovernanceReadDecisionReadiness/u);
  assert.match(service, /def assess_lifecycle/u);
  assert.doesNotMatch(actionsSource, /evaluateCorporateDocumentReadiness|deriveCorporateDecisionState/u);
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
  assert.match(refresh, /readCorporateDecisionReadiness/);
  assert.doesNotMatch(refresh, /corporateDocumentEvents|corporateDecisionFinalizations/);
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
