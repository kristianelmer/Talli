import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const actionsSource = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const governanceServiceSource = readFileSync(
  new URL("../apps/backend/src/talli_backend/modules/corporate_governance/service.py", import.meta.url),
  "utf8",
);
const governanceTransportSource = readFileSync(
  new URL("../apps/web/features/corporate-governance/transport.ts", import.meta.url),
  "utf8",
);
const wizardSource = readFileSync(
  new URL("../apps/web/app/(owner)/actions/_components/OwnerDividendWizard.tsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url),
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
  assert.equal(existsSync(new URL("../apps/web/app/lib/owner-dividend.ts", import.meta.url)), false);
  assert.equal(existsSync(new URL("../apps/web/app/lib/corporate-decision-facts.ts", import.meta.url)), false);
  assert.equal(existsSync(new URL("../apps/web/app/lib/corporate-documents.ts", import.meta.url)), false);
  assert.doesNotMatch(pythonHoldingActionsSource, /build_dividend_to_owner/);
  assert.doesNotMatch(pythonHoldingActionsSource, /Cash dividend paid to shareholders/);
  assert.doesNotMatch(pythonHoldingActionsSource, /Dividend paid from bank/);
  assert.doesNotMatch(pythonWorkspaceSource, /DividendToOwnerInput/);
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/dividend-allocation.ts", import.meta.url)),
    false,
  );
});

test("dividend basis and fact hashes are owned by the Python governance capability", () => {
  assert.match(governanceServiceSource, /def derive_decision_facts\(/);
  assert.match(governanceServiceSource, /annual_data_sha256/);
  assert.match(governanceServiceSource, /annual_accounts_payload_sha256/);
  assert.match(governanceTransportSource, /corporateGovernanceDeriveDecisionFacts/);
  assert.doesNotMatch(actionsSource, /buildOwnerDividendAnnualBasis|persistedFactHash/);
});

test("server sends owner-dividend intent to governance without duplicating policy", () => {
  assert.match(actionsSource, /export async function createOwnerDividendDecisionDraft\s*\(formData: FormData\)/);
  assert.doesNotMatch(actionsSource, /export async function recordOwnerDividend\s*\(/);

  const start = actionsSource.indexOf("export async function createOwnerDividendDecisionDraft");
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  const action = actionsSource.slice(start, end < 0 ? undefined : end);
  assert.match(action, /TALLI_CORPORATE_DOCUMENTS_ENABLED/);
  assert.match(action, /await proposeOwnerDividend\(/);
  assert.match(action, /decision\s*=\s*proposed\.decision/);
  assert.match(action, /deriveCorporateDecisionFacts/);
  assert.doesNotMatch(action, /buildOwnerDividendDecisionInput/);
  assert.match(action, /renderCorporateDocuments|persistCorporateDocumentDraft/);
  assert.doesNotMatch(action, /renderCorporateDocuments|holding_cli/);
  assert.match(action, /uploadCorporateArtifacts|persistCorporateDocumentDraft/);
  assert.match(action, /create_corporate_document_draft|persistCorporateDocumentDraft/);
  assert.doesNotMatch(action, /\.from\(["']ledger_entries["']\)\.insert/);
  assert.doesNotMatch(action, /\.from\(["']holding_actions["']\)\.insert/);
  assert.doesNotMatch(action, /\.from\(["']documents["']\)\.insert/);
  assert.doesNotMatch(action, /loadAcceptedMembershipCompany/);
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
