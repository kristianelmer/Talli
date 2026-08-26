import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  classifyRf1086TransportOutcome,
  transitionProductionSubmission,
} from "../apps/web/app/lib/production-submission.ts";

test("allows only documented production submission transitions", () => {
  assert.equal(transitionProductionSubmission("approved", "sending"), "sending");
  assert.equal(transitionProductionSubmission("sending", "received"), "received");
  assert.equal(transitionProductionSubmission("received", "processing"), "processing");
  assert.equal(
    transitionProductionSubmission("processing", "accepted", { finalAuthorityDecision: true }),
    "accepted",
  );
  assert.throws(() => transitionProductionSubmission("approved", "accepted", { finalAuthorityDecision: true }), /illegal/i);
  assert.throws(() => transitionProductionSubmission("accepted", "sending"), /terminal/i);
});

test("transport acknowledgement cannot become accepted", () => {
  assert.throws(
    () => transitionProductionSubmission("processing", "accepted", { finalAuthorityDecision: false }),
    /final authority decision/i,
  );
  assert.equal(
    classifyRf1086TransportOutcome({
      forsendelseId: "forsendelse-id",
      documents: ["<submitted-document />"],
      finalAuthorityDecision: null,
    }),
    "processing",
  );
});

test("uses explicit authority feedback for terminal outcomes", () => {
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: "id", documents: [], finalAuthorityDecision: "accepted" }), "accepted");
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: "id", documents: [], finalAuthorityDecision: "rejected" }), "rejected");
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: null, documents: [], finalAuthorityDecision: null }), "unknown");
});

const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const ownerPage = readFileSync(new URL("../apps/web/app/(owner)/filing/[obligation]/page.tsx", import.meta.url), "utf8");
const documents = readFileSync(new URL("../apps/web/app/lib/documents.ts", import.meta.url), "utf8");
const feedbackPersistence = readFileSync(
  new URL("../apps/web/app/lib/rf1086-feedback-persistence.ts", import.meta.url),
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

test("reconciliation action rechecks the exact owner, submission, and verified request without POST", () => {
  const start = actions.indexOf("export async function reconcileRf1086ProductionAction");
  const end = actions.indexOf("export async function postManualJournal", start);
  assert.ok(start >= 0 && end > start);
  const action = actions.slice(start, end);
  assert.match(action, /requiredFormUuid/u);
  assert.match(action, /loadAcceptedMembershipCompany\(submission\.company_id\)/u);
  assert.doesNotMatch(action, /\.from\("company_memberships"\)/u);
  assert.match(action, /role.*owner/su);
  assert.match(action, /system_user_requests/u);
  assert.match(action, /preflight_verified_at/u);
  assert.match(action, /claim_production_feedback_reconciliation/u);
  const claimIndex = action.indexOf("claim_production_feedback_reconciliation");
  assert.doesNotMatch(action.slice(0, claimIndex), /!submission\.feedback_forsendelse_id/u);
  assert.match(action.slice(claimIndex), /readClaimedRf1086ForsendelseId/u);
  assert.match(action.slice(claimIndex), /authoritativeForsendelseId/u);
  assert.match(action, /release_production_feedback_reconciliation/u);
  assert.match(action, /reconcileJournaledRf1086Production/u);
  assert.doesNotMatch(action, /executeJournaledRf1086Production|postHovedskjema|postUnderskjema|\.confirm\(/u);
});

test("initial send performs bounded feedback polling only after the journaled confirmation path", () => {
  const start = actions.indexOf("export async function sendApprovedRf1086ProductionFiling");
  const end = actions.indexOf("export async function reconcileRf1086ProductionAction", start);
  const send = actions.slice(start, end);
  assert.ok(send.indexOf("executeJournaledRf1086Production") >= 0);
  assert.ok(send.indexOf("reconcileJournaledRf1086Production") > send.indexOf("executeJournaledRf1086Production"));
  assert.ok(send.indexOf("claimRf1086FeedbackLease") > send.indexOf("executeJournaledRf1086Production"));
  assert.ok(send.indexOf("readClaimedRf1086ForsendelseId") > send.indexOf("claimRf1086FeedbackLease"));
  assert.match(send, /authoritativeForsendelseId !== submitted\.forsendelseId/u);
  assert.match(send, /initialPoll:\s*true/u);
});

test("private artifact persistence verifies receipts and cleans up only after authoritative absence", () => {
  assert.match(documents, /authority-feedback\/\$\{companyId\}\/\$\{submissionId\}\/\$\{sha256\}/u);
  assert.match(actions, /createRf1086FeedbackArtifactRecorder\(service, input\)/u);
  assert.match(feedbackPersistence, /document_type:\s*"authority_feedback"/u);
  assert.match(feedbackPersistence, /record_production_feedback_artifact/u);
  assert.match(feedbackPersistence, /bucket\.remove\(\[storageKey\]\)/u);
  assert.match(feedbackPersistence, /from\("documents"\)\.delete\(\)/u);
  assert.match(feedbackPersistence, /bucket\.download\(storageKey\)/u);
  assert.match(feedbackPersistence, /bytes\.byteLength !== artifact\.byteLength/u);
  assert.match(feedbackPersistence, /hash !== artifact\.sha256/u);
  assert.match(feedbackPersistence, /if \(persisted\.error\)[\s\S]+if \(persisted\.data\)[\s\S]+bucket\.remove/u);
  assert.match(feedbackPersistence, /Rf1086FeedbackArtifactPersistenceError/u);
  assert.match(actions, /createRf1086FeedbackArtifactPersistenceError/u);
  assert.doesNotMatch(actions, /databaseTerminalFailure/u);
  assert.doesNotMatch(feedbackPersistence, /getPublicUrl/u);
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
