import assert from "node:assert/strict";
import test from "node:test";

import {
  authorityTestEvidenceGate,
  buildAnnualAccountsAuthorityTestRunFromEvidence,
  buildAuthorityTestRun,
  buildCompanyTaxReturnAuthorityTestRunFromEvidence,
} from "../apps/web/app/lib/authority-test-evidence.ts";

const annualInstanceId = "51549454/90560530-005d-4f9e-8d8f-a1b7e8a20f51";
const annualReceiptDataId = "f9b307e1-3534-4adb-9e5b-515c312f16f3";
const companyTaxInstanceId = "51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108";
const companyTaxEnvelopeDataId = "7bbb17d7-5af0-4a17-9ed6-0647bcc845b5";
const companyTaxReceiptDataId = "70beee03-d8c2-4584-b366-8231c6de6584";

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

function companyTaxEvidence(overrides = {}) {
  const archiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${companyTaxInstanceId}`;
  return {
    schemaVersion: 2,
    status: "submitted_and_receipted",
    environment: "test",
    productionEnabled: false,
    companyOrgNumber: "310279617",
    incomeYear: 2025,
    scope: "skatteetaten:formueinntekt/skattemelding altinn:instances.read altinn:instances.write",
    systemUserResource: "app_skd_formueinntekt-skattemelding-v2",
    payloadHashes: {
      skattemelding: "a".repeat(64),
      naeringsspesifikasjon: "b".repeat(64),
      validationEnvelope: "c".repeat(64),
      submissionEnvelope: "d".repeat(64),
    },
    localSchemaValidation: {
      status: "passed",
      schemas: [
        "skattemeldingUpersonlig_v5_ekstern.xsd",
        "naeringsspesifikasjon_v6_ekstern.xsd",
        "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
      ],
    },
    authorityValidation: {
      result: "validertOK",
      failureReasons: [],
    },
    validatedAt: "2026-07-14T12:20:00.000Z",
    currentDocumentReferenceHash: "e".repeat(64),
    instance: {
      id: companyTaxInstanceId,
      envelopeUploaded: true,
      envelopeDataId: companyTaxEnvelopeDataId,
      fileScanResult: "Clean",
      confirmationPrepared: true,
      processTask: "confirmation",
    },
    confirmationUrl: `https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=${companyTaxInstanceId}`,
    confirmationPreparedAt: "2026-07-14T12:21:00.000Z",
    receipt: {
      dataId: companyTaxReceiptDataId,
      dataType: "tilbakemelding",
      contentType: "application/xml",
      byteLength: 527,
      contentSha256: "f".repeat(64),
      reference: `${archiveReference}/data/${companyTaxReceiptDataId}`,
    },
    submission: {
      submitted: true,
      processTask: null,
      processEndedAt: "2026-07-14T12:30:00.000Z",
      archived: true,
      archivedAt: "2026-07-14T12:31:00.000Z",
      archiveReference,
    },
    receiptRetrievedAt: "2026-07-14T12:32:00.000Z",
    secretsStored: false,
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

test("imports completed company-tax TT02 evidence as company- and year-bound pending evidence", () => {
  const run = buildCompanyTaxReturnAuthorityTestRunFromEvidence({
    companyId: "company-1",
    expectedCompanyOrgNumber: "310279617",
    expectedIncomeYear: 2025,
    evidence: companyTaxEvidence(),
    evidenceUrl: "https://evidence.example/company-tax-tt02-2026-07-14.json",
    recordedBy: "user-1",
    recordedAt: "2026-07-14T12:40:00Z",
  });

  assert.equal(run.obligation, "skattemelding");
  assert.equal(run.environment, "test");
  assert.equal(run.status, "pending");
  assert.equal(run.test_reference, `tt02:${companyTaxInstanceId}`);
  assert.match(run.feedback_summary, /validertOK.*personbekreftelse.*tilbakemelding/u);
  assert.equal(
    run.receipt_reference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${companyTaxInstanceId}/data/${companyTaxReceiptDataId}`,
  );
  assert.equal(
    run.archive_reference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${companyTaxInstanceId}`,
  );
  assert.match(run.payload_hash, /^sha256:[0-9a-f]{64}$/u);
  assert.equal(run.recorded_at, "2026-07-14T12:40:00Z");
  assert.equal(authorityTestEvidenceGate([run], "skattemelding").status, "test_evidence_pending");
});

test("company-tax TT02 import fails closed on identity, authority, handoff, receipt, or archive mismatches", () => {
  const base = {
    companyId: "company-1",
    expectedCompanyOrgNumber: "310279617",
    expectedIncomeYear: 2025,
    evidenceUrl: null,
    recordedBy: "user-1",
  };

  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      expectedCompanyOrgNumber: "930835978",
      evidence: companyTaxEvidence(),
    }),
    /organisasjonsnummer/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      expectedIncomeYear: 2024,
      evidence: companyTaxEvidence(),
    }),
    /inntektsår/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      expectedIncomeYear: 2024,
      evidence: companyTaxEvidence({ incomeYear: 2024 }),
    }),
    /2025|inntektsår/u,
  );
  const uppercaseInstanceId = companyTaxInstanceId.toUpperCase();
  const uppercaseEnvelopeDataId = companyTaxEnvelopeDataId.toUpperCase();
  const uppercaseReceiptDataId = companyTaxReceiptDataId.toUpperCase();
  const uppercaseArchiveReference =
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${uppercaseInstanceId}`;
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({
        instance: {
          ...companyTaxEvidence().instance,
          id: uppercaseInstanceId,
          envelopeDataId: uppercaseEnvelopeDataId,
        },
        confirmationUrl:
          "https://skatt-test.sits.no/web/skattemelding-visning/altinn"
          + `?appId=skd/formueinntekt-skattemelding-v2&instansId=${uppercaseInstanceId}`,
        receipt: {
          ...companyTaxEvidence().receipt,
          dataId: uppercaseReceiptDataId,
          reference: `${uppercaseArchiveReference}/data/${uppercaseReceiptDataId}`,
        },
        submission: {
          ...companyTaxEvidence().submission,
          archiveReference: uppercaseArchiveReference,
        },
      }),
    }),
    /instans- eller konvoluttdata-id/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({ productionEnabled: true }),
    }),
    /produksjon/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({ scope: "skatteetaten:formueinntekt/skattemelding" }),
    }),
    /scope/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({
        authorityValidation: { result: "validertMedAvvik", failureReasons: ["avvik"] },
      }),
    }),
    /validertOK/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({ receiptRetrievedAt: "not-a-timestamp" }),
    }),
    /Tilbakemeldingshentetidspunkt/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({
        instance: { ...companyTaxEvidence().instance, confirmationPrepared: false },
      }),
    }),
    /personbekreftelse/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({
        receipt: { ...companyTaxEvidence().receipt, reference: "https://example.invalid/receipt" },
      }),
    }),
    /kvitteringsreferanse/u,
  );
  assert.throws(
    () => buildCompanyTaxReturnAuthorityTestRunFromEvidence({
      ...base,
      evidence: companyTaxEvidence({
        submission: { ...companyTaxEvidence().submission, archived: false },
      }),
    }),
    /arkiv/u,
  );
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
