import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const ownerPage = readFileSync(new URL("../apps/web/app/(owner)/filing/[obligation]/page.tsx", import.meta.url), "utf8");
const documents = readFileSync(new URL("../apps/web/app/lib/documents.ts", import.meta.url), "utf8");
const feedbackPersistence = readFileSync(
  new URL("../apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py", import.meta.url),
  "utf8",
);
let reconciliationControl = "";
try {
  reconciliationControl = readFileSync(
    new URL("../apps/web/app/(owner)/filing/_submission-presentation.ts", import.meta.url),
    "utf8",
  );
} catch {
  // RED until Task 6 creates the bounded client reconciliation control.
}

test("recovery presentation carries the recorded identity through the generated backend contract", () => {
  const start = actions.indexOf("export async function reconcileRf1086ProductionAction");
  const action = actions.slice(start, actions.indexOf("export async function postManualJournal", start));
  assert.match(action, /requiredFormUuid\(formData, "submissionId"\)/u);
  assert.match(action, /reconcileRf1086ThroughApi\(accessToken, submissionId\)/u);
  assert.match(action, /buildRf1086OwnerReconciliationActionState\(result.state/u);
  assert.doesNotMatch(action, /\.from\(|\.rpc\(|requestMaskinportenToken|postHovedskjema/u);
});

test("RF producer preserves the public Documents lifecycle and original filing linkage", () => {
  assert.match(documents, /rf1086FeedbackFileName/u);
  assert.match(feedbackPersistence, /BeginDocumentUploadCommand/u);
  assert.match(feedbackPersistence, /"authority_feedback"/u);
  assert.match(feedbackPersistence, /production_filing_submission:/u);
  assert.match(feedbackPersistence, /record_production_feedback_artifact/u);
  assert.match(feedbackPersistence, /producer_rollback/u);
  assert.doesNotMatch(feedbackPersistence, /insert into documents\.|update documents\.|getPublicUrl/u);
});

test("filing page auto-resumes pending reconciliation and always exposes manual retry", () => {
  assert.match(ownerPage, /Rf1086ReconciliationControl/u);
  assert.match(ownerPage, /productionFeedbackArtifacts/u);
  assert.match(ownerPage, /\/documents\/\$\{artifact\.documentId\}\/download/u);
  assert.match(reconciliationControl, /"use client"/u);
  assert.match(reconciliationControl, /useActionState/u);
  assert.match(reconciliationControl, /setTimeout/u);
  assert.match(reconciliationControl, /state\.shouldPoll/u);
  assert.doesNotMatch(
    reconciliationControl,
    /"(?:sent|processing|unknown|accepted|rejected|action_required)"/u,
  );
  assert.match(ownerPage, /initialState=\{buildRf1086OwnerReconciliationActionState/u);
  assert.match(reconciliationControl, /ownerCopy\.filing\.production/u);
  assert.match(reconciliationControl, /copy\.reconciliation\.checkCta/u);
});
