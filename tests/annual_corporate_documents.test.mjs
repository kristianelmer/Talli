import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

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

test("annual basis helpers were removed from the web authority boundary", () => {
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/annual-corporate-documents.ts", import.meta.url)),
    false,
  );
  assert.doesNotMatch(actionsSource, /buildAnnualCloseBasis|buildAnnualCloseReviewedFacts/u);
  assert.match(actionsSource, /deriveCorporateDecisionFacts/u);
});

test("annual decisions render only inside the Python backend", () => {
  const backendRenderer = readFileSync(
    new URL(
      "../apps/backend/src/talli_backend/modules/corporate_governance/rendering.py",
      import.meta.url,
    ),
    "utf8",
  );
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/corporate-documents.ts", import.meta.url)),
    false,
  );
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
