import assert from "node:assert/strict";
import test from "node:test";

import { buildCompanyTaxReturnEvidencePersistence } from "../app/lib/company-tax-return-submission.ts";

const instanceId = "51549454/60d6fdca-9e11-49d4-b55d-73b8bb5a2108";
const envelopeDataId = "7bbb17d7-5af0-4a17-9ed6-0647bcc845b5";
const receiptDataId = "70beee03-d8c2-4584-b366-8231c6de6584";

function companyTaxEvidence(overrides = {}) {
  const archiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`;
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
    authorityValidation: { result: "validertOK", failureReasons: [] },
    currentDocumentReferenceHash: "e".repeat(64),
    currentDocumentReference: "CURRENT_DOCUMENT_REFERENCE_SENTINEL",
    sourceXml: "<skattemelding>RAW_XML_SENTINEL</skattemelding>",
    partyNumber: "PARTY_NUMBER_SENTINEL",
    accessToken: "ACCESS_TOKEN_SENTINEL",
    privateKeyPem: "PRIVATE_KEY_SENTINEL",
    personalIdentifier: "PERSONAL_IDENTIFIER_SENTINEL",
    instance: {
      id: instanceId,
      envelopeUploaded: true,
      envelopeDataId,
      fileScanResult: "Clean",
      confirmationPrepared: true,
      processTask: "confirmation",
    },
    confirmationUrl: `https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=${instanceId}`,
    validatedAt: "2026-07-14T12:20:00.000Z",
    confirmationPreparedAt: "2026-07-14T12:21:00.000Z",
    receipt: {
      dataId: receiptDataId,
      dataType: "tilbakemelding",
      contentType: "application/xml",
      byteLength: 527,
      contentSha256: "f".repeat(64),
      reference: `${archiveReference}/data/${receiptDataId}`,
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

function project(evidence = companyTaxEvidence(), overrides = {}) {
  return buildCompanyTaxReturnEvidencePersistence({
    companyId: "company-1",
    expectedCompanyOrgNumber: "310279617",
    expectedIncomeYear: 2025,
    evidence,
    evidenceUrl: "https://evidence.example/company-tax-tt02-2026-07-14.json",
    recordedBy: "user-1",
    ...overrides,
  });
}

test("projects completed TT02 evidence as deterministic pending company-tax feedback", () => {
  const evidence = companyTaxEvidence();
  const projected = project(evidence);

  assert.equal(projected.authorityRun.status, "pending");
  assert.equal(projected.submission.mode, "test_authority");
  assert.equal(projected.submission.adapter_mode, "test_authority");
  assert.equal(projected.submission.status, "feedback_ready");
  assert.equal(projected.submission.receipt_id, evidence.receipt.dataId);
  assert.deepEqual(projected.submission.feedback_document_ids, [evidence.receipt.dataId]);
  assert.deepEqual(projected.submission.feedback_items, [{
    severity: "warning",
    code: "COMPANY_TAX_AUTHORITY_OUTCOME_PENDING",
    message: "Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.",
    documentId: evidence.receipt.dataId,
  }]);
  assert.equal(projected.submission.submitted_payload, null);
  assert.match(projected.submission.payload_hash, /^[0-9a-f]{64}$/u);
  assert.match(projected.submission.idempotency_key, /^company-tax:company-1:2025:/u);
  assert.deepEqual(projected.submission.calls.map((call) => ({
    body_hash: call.body_hash,
    status: call.status,
    created_at: call.created_at,
  })), [
    {
      body_hash: evidence.payloadHashes.validationEnvelope,
      status: "validertOK",
      created_at: evidence.validatedAt,
    },
    {
      body_hash: evidence.payloadHashes.submissionEnvelope,
      status: "confirmation_prepared",
      created_at: evidence.confirmationPreparedAt,
    },
    {
      body_hash: evidence.receipt.contentSha256,
      status: "received",
      created_at: evidence.receiptRetrievedAt,
    },
  ]);
  assert.equal(projected.submission.receipt_metadata.archiveReference, evidence.submission.archiveReference);
  assert.equal(projected.submission.receipt_metadata.contentSha256, evidence.receipt.contentSha256);
  assert.equal(projected.submission.submitted_payload_ref.currentDocumentReferenceHash, evidence.currentDocumentReferenceHash);
  assert.equal(projected.submission.submitted_payload_ref.submissionEnvelopeHash, evidence.payloadHashes.submissionEnvelope);
  assert.equal(projected.submission.submitted_payload_ref.companyOrgNumber, evidence.companyOrgNumber);
  assert.equal(projected.submission.submitted_payload_ref.incomeYear, evidence.incomeYear);
  assert.equal(projected.submission.updated_at, evidence.receiptRetrievedAt);
});

test("retries produce the same complete projection without a supplied recorded timestamp", async () => {
  const evidence = companyTaxEvidence();
  const first = project(evidence);
  await new Promise((resolve) => setTimeout(resolve, 10));
  const second = project(structuredClone(evidence));

  assert.deepEqual(second, first);
  assert.equal(first.authorityRun.recorded_at, evidence.receiptRetrievedAt);
});

test("rejects unsafe evidence URLs and normalizes blank evidence URLs to null", () => {
  for (const evidenceUrl of [
    "data:text/plain,secret",
    "https:///missing-host",
    "https://evidence.example",
    "https://user:password@evidence.example/company-tax.json",
    "https://evidence.example:443/company-tax.json",
    "https://evidence.example/company-tax.json?token=secret",
    "https://evidence.example/company-tax.json#secret",
    "https://evidence.example/archive/../company-tax.json",
    "https://evidence.example/archive/%2e%2e/company-tax.json",
    " https://evidence.example/company-tax.json",
    "https://evidence.example/company tax.json",
    "https://evidence.example/company-tax.json\nignored",
    "https://evidence.example/CuRrEnT_DoCuMeNt_ReFeReNcE_SeNtInEl.json",
    `https://evidence.example/${"a".repeat(2048)}`,
  ]) {
    assert.throws(
      () => project(companyTaxEvidence(), { evidenceUrl }),
      /evidenslenke/u,
    );
  }

  assert.equal(
    project(companyTaxEvidence(), { evidenceUrl: "   " }).authorityRun.evidence_url,
    null,
  );
  assert.equal(
    project(companyTaxEvidence(), {
      evidenceUrl: "https://evidence.example/static/company-tax-2025.json",
    }).authorityRun.evidence_url,
    "https://evidence.example/static/company-tax-2025.json",
  );
});

test("rejects a self-consistent non-2025 company-tax evidence projection", () => {
  assert.throws(
    () => project(companyTaxEvidence({ incomeYear: 2024 }), { expectedIncomeYear: 2024 }),
    /2025|inntektsår/u,
  );
});

test("requires strict RFC3339 evidence instants in chronological order", () => {
  for (const evidence of [
    companyTaxEvidence({ validatedAt: "2026-02-30T12:20:00Z" }),
    companyTaxEvidence({ validatedAt: "2026-07-14T12:20:00" }),
    companyTaxEvidence({ validatedAt: "2026-07-14T12:22:00Z" }),
    companyTaxEvidence({
      validatedAt: "2026-07-14T12:20:00.0002Z",
      confirmationPreparedAt: "2026-07-14T12:20:00.0001Z",
    }),
    companyTaxEvidence({
      submission: {
        ...companyTaxEvidence().submission,
        processEndedAt: "2026-07-14T12:31:01Z",
      },
    }),
    companyTaxEvidence({ receiptRetrievedAt: "2026-07-14T12:30:59Z" }),
  ]) {
    assert.throws(
      () => project(evidence),
      /tidspunkt|kronologi/u,
    );
  }
});

test("projection omits raw documents, authority secrets, party data, and personal identifiers", () => {
  const json = JSON.stringify(project());
  for (const sentinel of [
    "CURRENT_DOCUMENT_REFERENCE_SENTINEL",
    "RAW_XML_SENTINEL",
    "PARTY_NUMBER_SENTINEL",
    "ACCESS_TOKEN_SENTINEL",
    "PRIVATE_KEY_SENTINEL",
    "PERSONAL_IDENTIFIER_SENTINEL",
  ]) {
    assert.equal(json.includes(sentinel), false, `projection leaked ${sentinel}`);
  }
});
