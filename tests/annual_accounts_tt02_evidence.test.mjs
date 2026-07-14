import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const evidenceUrl = new URL(
  "../docs/filing/evidence/annual-accounts-tt02-2026-07-14.json",
  import.meta.url,
);

test("annual-accounts TT02 evidence is submitted, archived, test-only, and secret-free", async () => {
  const raw = await readFile(evidenceUrl, "utf8");
  const evidence = JSON.parse(raw);

  assert.equal(evidence.status, "submitted_and_archived");
  assert.equal(evidence.environment, "test");
  assert.equal(evidence.productionEnabled, false);
  assert.equal(evidence.companyOrgNumber, "310279617");
  assert.equal(evidence.incomeYear, 2025);
  assert.equal(evidence.scope, "altinn:instances.read altinn:instances.write");
  assert.equal(evidence.systemUserResource, "app_brg_aarsregnskap-vanlig-202406");
  assert.equal(evidence.localXmlValidation.status, "well_formed");
  assert.equal(evidence.validation.hasErrors, false);
  assert.deepEqual(evidence.validation.issues, []);
  assert.match(evidence.instance.id, /^\d+\/[0-9a-f-]{36}$/u);
  assert.equal(evidence.instance.mainFormUploaded, true);
  assert.equal(evidence.instance.companyAccountsUploaded, true);
  assert.equal(evidence.instance.locked, true);
  assert.equal(evidence.instance.lockedProcessTask, "signing");
  assert.equal(evidence.signed, true);
  assert.equal(evidence.submitted, true);
  assert.equal(evidence.submission.processCompleted, true);
  assert.equal(evidence.submission.endEvent, "EndEvent_1");
  assert.equal(evidence.submission.signed, true);
  assert.match(evidence.submission.signatureDataId, /^[0-9a-f-]{36}$/u);
  assert.equal(evidence.submission.submitted, true);
  assert.equal(evidence.submission.archived, true);
  assert.equal(evidence.submission.archivedAt, evidence.submission.processEndedAt);
  assert.equal(
    evidence.submission.archiveReference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${evidence.instance.id}`,
  );
  assert.match(evidence.submission.receipt.dataId, /^[0-9a-f-]{36}$/u);
  assert.equal(evidence.submission.receipt.dataType, "ref-data-as-pdf");
  assert.equal(evidence.submission.receipt.contentType, "application/pdf");
  assert.ok(evidence.submission.receipt.sizeBytes > 0);
  assert.equal(
    evidence.submission.receipt.reference,
    `${evidence.submission.archiveReference}/data/${evidence.submission.receipt.dataId}`,
  );
  assert.equal(evidence.uiReceiptReference, "a1b7e8a20f51");
  assert.equal(evidence.downloadVerification.receiptPdf.exactApiMatch, true);
  assert.equal(evidence.downloadVerification.receiptPdf.sizeBytes, evidence.submission.receipt.sizeBytes);
  assert.equal(
    evidence.downloadVerification.receiptPdf.sha256,
    "efcc42bafd11ef2960ed755534f47e6ed00e77d4a2aba812d2cdaae83987febc",
  );
  assert.equal(
    evidence.downloadVerification.mainFormJson.dataId,
    evidence.instance.dataIds.mainForm,
  );
  assert.equal(
    evidence.downloadVerification.companyAccountsJson.dataId,
    evidence.instance.dataIds.companyAccounts,
  );
  for (const artifact of Object.values(evidence.downloadVerification)) {
    assert.match(artifact.sha256, /^[0-9a-f]{64}$/u);
  }
  assert.equal(evidence.secretsStored, false);
  assert.equal(evidence.evidenceFile, "annual-accounts-tt02-2026-07-14.json");
  assert.equal(
    evidence.signingUrl,
    `https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406/#/instance/${evidence.instance.id}`,
  );
  for (const hash of Object.values(evidence.payloadHashes)) {
    assert.match(hash, /^[0-9a-f]{64}$/u);
  }
  assert.match(evidence.codeCommit, /^[0-9a-f]{40}$/u);
  assert.doesNotMatch(raw, /access_token|PRIVATE KEY|talli-test\.key|opaque-/u);
  assert.doesNotMatch(raw, /\/Users\/|\\Users\\/u);
  assert.doesNotMatch(raw, /\b\d{11}\b/u);
});
