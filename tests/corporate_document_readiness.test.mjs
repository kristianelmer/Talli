import assert from "node:assert/strict";
import test from "node:test";

import { evaluateObligationReadiness } from "../apps/web/app/lib/annual-readiness.ts";
import {
  deriveCorporateDecisionState,
  evaluateCorporateDocumentReadiness,
} from "../apps/web/app/lib/corporate-document-readiness.ts";

const hash = "a".repeat(64);
const decision = { id: "decision-1", decision_kind: "annual_close", decision_hash: hash };
const documentSet = { id: "set-1", decision_id: decision.id, decision_hash: hash };
const unsignedArtifacts = [
  { id: "artifact-1", set_id: documentSet.id, artifact_kind: "annual_board_minutes", variant: "unsigned" },
  { id: "artifact-2", set_id: documentSet.id, artifact_kind: "annual_general_meeting_minutes", variant: "unsigned" },
];
const signedArtifacts = [
  { id: "artifact-3", set_id: documentSet.id, artifact_kind: "annual_board_minutes", variant: "signed_owner_attested" },
  { id: "artifact-4", set_id: documentSet.id, artifact_kind: "annual_general_meeting_minutes", variant: "signed_owner_attested" },
];
const approvedEvent = {
  id: "event-1",
  decision_id: decision.id,
  set_id: documentSet.id,
  event_kind: "facts_approved",
  decision_hash: hash,
};
const finalization = { id: "final-1", decision_id: decision.id, decision_hash: hash };

function lifecycle(overrides = {}) {
  return {
    decision,
    documentSet,
    artifacts: [...unsignedArtifacts, ...signedArtifacts],
    events: [approvedEvent],
    finalizations: [finalization],
    ...overrides,
  };
}

test("state is derived only from current immutable artifacts, events, and finalization", () => {
  assert.equal(deriveCorporateDecisionState(lifecycle({ documentSet: null, artifacts: [], events: [], finalizations: [] })), "draft");
  assert.equal(deriveCorporateDecisionState(lifecycle({ artifacts: unsignedArtifacts, events: [], finalizations: [] })), "rendered");
  assert.equal(deriveCorporateDecisionState(lifecycle({ artifacts: unsignedArtifacts, finalizations: [] })), "facts_approved");
  assert.equal(deriveCorporateDecisionState(lifecycle({ finalizations: [] })), "signed_owner_attested");
  assert.equal(deriveCorporateDecisionState(lifecycle()), "finalized");
  assert.equal(
    deriveCorporateDecisionState(lifecycle({
      finalizations: [],
      events: [...lifecycle().events, { ...approvedEvent, id: "event-2", event_kind: "superseded" }],
    })),
    "superseded",
  );
  assert.equal(
    deriveCorporateDecisionState(lifecycle({
      finalizations: [],
      events: [...lifecycle().events, { ...approvedEvent, id: "event-3", event_kind: "rejected" }],
    })),
    "rejected",
  );
});

test("readiness fails closed for stale hashes, unsigned documents, and terminal decisions", () => {
  const ready = evaluateCorporateDocumentReadiness({ ...lifecycle(), currentDecisionHash: hash });
  assert.equal(ready.state, "finalized");
  assert.equal(ready.annualSubmissionReady, true);
  assert.deepEqual(ready.blockers, []);

  const stale = evaluateCorporateDocumentReadiness({ ...lifecycle(), currentDecisionHash: "b".repeat(64) });
  assert.equal(stale.annualSubmissionReady, false);
  assert.ok(stale.blockers.some((blocker) => blocker.code === "corporate_documents_current_hash_mismatch"));

  const unsigned = evaluateCorporateDocumentReadiness({
    ...lifecycle({ artifacts: unsignedArtifacts, finalizations: [] }),
    currentDecisionHash: hash,
  });
  assert.ok(unsigned.blockers.some((blocker) => blocker.code === "corporate_documents_missing_signed_artifacts"));

  const rejected = evaluateCorporateDocumentReadiness({
    ...lifecycle({
      finalizations: [],
      events: [...lifecycle().events, { ...approvedEvent, id: "event-3", event_kind: "rejected" }],
    }),
    currentDecisionHash: hash,
  });
  assert.equal(rejected.state, "rejected");
  assert.ok(rejected.blockers.some((blocker) => blocker.code === "corporate_documents_terminal_decision"));
});

function annualReadinessInput(corporateDocuments) {
  const company = { id: "company-1", entity_type: "AS" };
  return {
    company,
    incomeYear: 2025,
    setups: [{ company_id: company.id, income_year: 2025 }],
    ledgerEntries: [{
      company_id: company.id,
      income_year: 2025,
      lines: [],
      risk_flags: [],
      warning_accepted_at: null,
    }],
    holdingActions: [{
      company_id: company.id,
      income_year: 2025,
      action_type: "tax_settlement",
      risk_level: "ready",
    }],
    bankTransactions: [],
    documents: [],
    overrides: [],
    locks: [{ company_id: company.id, income_year: 2025 }],
    annualData: {
      no_activity_confirmed: false,
      annual_full_time_equivalents: 0,
      confirmations: [],
      answers: {
        bank_balance_confirmed: true,
        has_unpaid_items: false,
        authority_to_submit_confirmed: true,
        general_meeting_approved: true,
      },
    },
    billingAccount: {
      subscription_active: true,
      filing_package_paid: true,
      supported_case: true,
      refund_eligible: false,
    },
    authorityPermissions: [{
      obligation: "aarsregnskap",
      confirmed_at: "2026-01-01T00:00:00Z",
      production_enabled: true,
    }],
    filingPreviews: [],
    filingSubmissions: [],
    corporateDocuments,
  };
}

test("annual filing gate requires the current annual decision hash and finalization when enabled", () => {
  const staleSnapshot = evaluateObligationReadiness(
    annualReadinessInput({ enabled: true, lifecycle: { ...lifecycle(), currentDecisionHash: "b".repeat(64) } }),
    "aarsregnskap",
  );
  assert.ok(staleSnapshot.hard_blocks.some(
    (blocker) => blocker.code === "corporate_documents_current_hash_mismatch",
  ));

  const readySnapshot = evaluateObligationReadiness(
    annualReadinessInput({ enabled: true, lifecycle: { ...lifecycle(), currentDecisionHash: hash } }),
    "aarsregnskap",
  );
  assert.equal(
    readySnapshot.hard_blocks.some((blocker) => blocker.source === "corporate_documents"),
    false,
  );

  const rolloutDisabled = evaluateObligationReadiness(
    annualReadinessInput({ enabled: false, lifecycle: { ...lifecycle(), currentDecisionHash: "b".repeat(64) } }),
    "aarsregnskap",
  );
  assert.equal(
    rolloutDisabled.hard_blocks.some((blocker) => blocker.source === "corporate_documents"),
    false,
  );
});
