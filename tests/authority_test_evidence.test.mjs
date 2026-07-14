import assert from "node:assert/strict";
import test from "node:test";

import {
  authorityTestEvidenceGate,
  buildAnnualAccountsAuthorityTestRunFromEvidence,
  buildAuthorityTestRun,
} from "../app/lib/authority-test-evidence.ts";

const annualInstanceId = "51549454/90560530-005d-4f9e-8d8f-a1b7e8a20f51";
const annualReceiptDataId = "f9b307e1-3534-4adb-9e5b-515c312f16f3";

function annualEvidence(overrides = {}) {
  return {
    schemaVersion: 1,
    status: "submitted_and_archived",
    environment: "test",
    productionEnabled: false,
    companyOrgNumber: "310279617",
    systemUserResource: "app_brg_aarsregnskap-vanlig-202406",
    payloadHashes: {
      mainForm: "a".repeat(64),
      companyAccounts: "b".repeat(64),
    },
    validation: { hasErrors: false, issues: [] },
    instance: { id: annualInstanceId },
    signed: true,
    submitted: true,
    submission: {
      processCompleted: true,
      processEndedAt: "2026-07-14T10:37:41.935543Z",
      signed: true,
      submitted: true,
      archived: true,
      archiveReference: `https://platform.tt02.altinn.no/storage/api/v1/instances/${annualInstanceId}`,
      receipt: {
        dataId: annualReceiptDataId,
        dataType: "ref-data-as-pdf",
        contentType: "application/pdf",
        reference: `https://platform.tt02.altinn.no/storage/api/v1/instances/${annualInstanceId}/data/${annualReceiptDataId}`,
      },
    },
    inbox: {
      status: "til_behandling",
      displayStatus: "Til behandling",
      confirmation: "Innsendingen er bekreftet mottatt.",
    },
    ...overrides,
  };
}

test("builds accepted authority test evidence with receipt and archive refs", () => {
  const run = buildAuthorityTestRun({
    companyId: "company-1",
    obligation: "aksjonaerregisteroppgaven",
    status: "accepted",
    testReference: "altinn-test-123",
    receiptReference: "receipt-123",
    archiveReference: "archive-123",
    payloadHash: "sha256:abc",
    recordedBy: "user-1",
    recordedAt: "2026-01-01T00:00:00Z",
  });

  assert.equal(run.environment, "test");
  assert.equal(run.status, "accepted");
  assert.equal(run.receipt_reference, "receipt-123");
  assert.equal(run.archive_reference, "archive-123");
});

test("imports submitted annual-accounts TT02 evidence as pending runtime evidence", () => {
  const run = buildAnnualAccountsAuthorityTestRunFromEvidence({
    companyId: "company-1",
    expectedCompanyOrgNumber: "310279617",
    evidence: annualEvidence(),
    evidenceUrl: "https://evidence.example/annual-accounts-tt02-2026-07-14.json",
    recordedBy: "user-1",
    recordedAt: "2026-07-14T10:55:00Z",
  });

  assert.equal(run.obligation, "aarsregnskap");
  assert.equal(run.environment, "test");
  assert.equal(run.status, "pending");
  assert.equal(run.test_reference, `tt02:${annualInstanceId}`);
  assert.match(run.feedback_summary, /Til behandling.*bekreftet mottatt/u);
  assert.equal(
    run.receipt_reference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${annualInstanceId}/data/${annualReceiptDataId}`,
  );
  assert.equal(
    run.archive_reference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${annualInstanceId}`,
  );
  assert.match(run.payload_hash, /^sha256:[0-9a-f]{64}$/u);
  assert.equal(run.recorded_at, "2026-07-14T10:55:00Z");
  assert.equal(authorityTestEvidenceGate([run], "aarsregnskap").status, "test_evidence_pending");
});

test("annual-accounts TT02 import fails closed on company, production, and submission mismatches", () => {
  const base = {
    companyId: "company-1",
    expectedCompanyOrgNumber: "310279617",
    evidenceUrl: null,
    recordedBy: "user-1",
  };

  assert.throws(
    () => buildAnnualAccountsAuthorityTestRunFromEvidence({
      ...base,
      expectedCompanyOrgNumber: "930835978",
      evidence: annualEvidence(),
    }),
    /organisasjonsnummer/u,
  );
  assert.throws(
    () => buildAnnualAccountsAuthorityTestRunFromEvidence({
      ...base,
      evidence: annualEvidence({ productionEnabled: true }),
    }),
    /produksjon/u,
  );
  assert.throws(
    () => buildAnnualAccountsAuthorityTestRunFromEvidence({
      ...base,
      evidence: annualEvidence({ submitted: false }),
    }),
    /signert og sendt/u,
  );
  assert.throws(
    () => buildAnnualAccountsAuthorityTestRunFromEvidence({
      ...base,
      evidence: annualEvidence({
        submission: {
          ...annualEvidence().submission,
          archiveReference: "https://example.invalid/archive",
        },
      }),
    }),
    /arkivreferanse/u,
  );
});

test("requires test reference and recorder", () => {
  assert.throws(
    () =>
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "skattemelding",
        status: "pending",
        testReference: "",
        recordedBy: "user-1",
      }),
    /Testreferanse/,
  );
  assert.throws(
    () =>
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "skattemelding",
        status: "pending",
        testReference: "manual-1",
        recordedBy: "",
      }),
    /Recorded by/,
  );
});

test("gate requires accepted evidence with receipt and archive refs", () => {
  const missing = authorityTestEvidenceGate([], "aarsregnskap");
  assert.equal(missing.ready, false);
  assert.equal(missing.status, "test_evidence_missing");

  const acceptedWithoutArchive = authorityTestEvidenceGate(
    [
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "aarsregnskap",
        status: "accepted",
        testReference: "rr-test-1",
        receiptReference: "receipt-1",
        recordedBy: "user-1",
        recordedAt: "2026-01-01T00:00:00Z",
      }),
    ],
    "aarsregnskap",
  );
  assert.equal(acceptedWithoutArchive.ready, false);
  assert.equal(acceptedWithoutArchive.status, "test_evidence_missing");

  const ready = authorityTestEvidenceGate(
    [
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "aarsregnskap",
        status: "accepted",
        testReference: "rr-test-2",
        receiptReference: "receipt-2",
        archiveReference: "archive-2",
        recordedBy: "user-1",
        recordedAt: "2026-01-02T00:00:00Z",
      }),
    ],
    "aarsregnskap",
  );
  assert.equal(ready.ready, true);
  assert.equal(ready.status, "test_evidence_ready");
});

test("gate surfaces latest rejected, blocked, and pending evidence", () => {
  const rejected = authorityTestEvidenceGate(
    [
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "skattemelding",
        status: "accepted",
        testReference: "tax-old",
        receiptReference: "receipt-old",
        archiveReference: "archive-old",
        recordedBy: "user-1",
        recordedAt: "2026-01-01T00:00:00Z",
      }),
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "skattemelding",
        status: "rejected",
        testReference: "tax-new",
        feedbackSummary: "Schema mismatch",
        recordedBy: "user-1",
        recordedAt: "2026-01-02T00:00:00Z",
      }),
    ],
    "skattemelding",
  );
  assert.equal(rejected.ready, false);
  assert.equal(rejected.status, "test_evidence_rejected");

  const blocked = authorityTestEvidenceGate(
    [
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "aksjonaerregisteroppgaven",
        status: "blocked",
        testReference: "rf1086-blocked",
        recordedBy: "user-1",
        recordedAt: "2026-01-03T00:00:00Z",
      }),
    ],
    "aksjonaerregisteroppgaven",
  );
  assert.equal(blocked.status, "test_evidence_blocked");

  const pending = authorityTestEvidenceGate(
    [
      buildAuthorityTestRun({
        companyId: "company-1",
        obligation: "aksjonaerregisteroppgaven",
        status: "pending",
        testReference: "rf1086-pending",
        recordedBy: "user-1",
        recordedAt: "2026-01-04T00:00:00Z",
      }),
    ],
    "aksjonaerregisteroppgaven",
  );
  assert.equal(pending.status, "test_evidence_pending");
});
