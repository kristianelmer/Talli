import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { buildWorkspaceSubmissionPresentation } from "../apps/web/app/(owner)/workspace/_submission-presentation.ts";

const workspaceSource = await readFile(
  new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);

function submission(overrides = {}) {
  return {
    id: "submission-id",
    authority_test_run_id: null,
    company_id: "company-id",
    income_year: 2025,
    mode: "simulation",
    status: "receipt_stored",
    calls: [],
    receipt_id: "simulated-receipt-id",
    feedback_items: [],
    submitted_payload_ref: { payloadHash: "f".repeat(64) },
    preview_confirmed_at: "2026-07-14T12:00:00Z",
    ...overrides,
  };
}

test("workspace keeps simulation and TT02 test-authority submissions in truthful separate presentations", () => {
  const simulation = submission({ id: "simulation" });
  const testAuthority = submission({
    id: "test-authority",
    authority_test_run_id: "authority-run-id",
    mode: "test_authority",
    status: "feedback_ready",
    receipt_id: "feedback-data-id",
    submitted_payload_ref: {
      payloadHash: "a".repeat(64),
      archiveReference: "https://unsafe.example/never-render-this",
    },
    preview_confirmed_at: null,
  });
  const archiveReference = "https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108";

  const presentation = buildWorkspaceSubmissionPresentation({
    submissions: [testAuthority, simulation],
    authorityTestRuns: [{
      id: "authority-run-id",
      status: "pending",
      archive_reference: archiveReference,
    }],
  });

  assert.deepEqual(presentation.simulations.map((item) => item.submission.id), ["simulation"]);
  assert.deepEqual(presentation.testAuthority.map((item) => item.submission.id), ["test-authority"]);
  assert.equal(presentation.testAuthority[0].statusLabel, "Venter på klassifisering");
  assert.equal(presentation.testAuthority[0].archiveReference, archiveReference);
  assert.notEqual(
    presentation.testAuthority[0].archiveReference,
    testAuthority.submitted_payload_ref.payloadHash.slice(0, 12),
  );
});

test("workspace rejects unsafe authority archive references from owner presentation", () => {
  const presentation = buildWorkspaceSubmissionPresentation({
    submissions: [submission({
      id: "test-authority",
      authority_test_run_id: "authority-run-id",
      mode: "test_authority",
    })],
    authorityTestRuns: [{
      id: "authority-run-id",
      status: "pending",
      archive_reference: "https://attacker.example/archive?token=secret",
    }],
  });

  assert.equal(presentation.testAuthority[0].archiveReference, null);
});

test("workspace owner copy does not expose pending or authority gate enum values", () => {
  assert.doesNotMatch(workspaceSource, /status pending/u);
  assert.doesNotMatch(workspaceSource, /\{latestRun\.status\}/u);
  assert.doesNotMatch(workspaceSource, /\{evidenceGate\.status\}/u);
  assert.doesNotMatch(workspaceSource, /\{gate\.status\}/u);
  assert.match(workspaceSource, /Venter på klassifisering/u);
});
