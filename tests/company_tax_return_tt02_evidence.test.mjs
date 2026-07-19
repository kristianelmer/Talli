import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const evidenceUrl = new URL(
  "../docs/filing/evidence/company-tax-tt02-2026-07-14.json",
  import.meta.url,
);

test("company-tax TT02 evidence is submitted, receipted, archived, test-only, and secret-free", async () => {
  const raw = await readFile(evidenceUrl, "utf8");
  const evidence = JSON.parse(raw);

  assert.equal(evidence.schemaVersion, 2);
  assert.equal(evidence.status, "submitted_and_receipted");
  assert.equal(evidence.environment, "test");
  assert.equal(evidence.productionEnabled, false);
  assert.equal(evidence.companyOrgNumber, "310279617");
  assert.equal(evidence.incomeYear, 2025);
  assert.equal(
    evidence.scope,
    "skatteetaten:formueinntekt/skattemelding altinn:instances.read altinn:instances.write",
  );
  assert.equal(evidence.systemUserResource, "app_skd_formueinntekt-skattemelding-v2");
  assert.equal(evidence.systemUserExternalRef, null);
  assert.equal(evidence.localSchemaValidation.status, "passed");
  assert.deepEqual(evidence.localSchemaValidation.schemas, [
    "skattemeldingUpersonlig_v5_ekstern.xsd",
    "naeringsspesifikasjon_v6_ekstern.xsd",
    "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
  ]);
  assert.equal(evidence.preflightValidation.result, "validertOK");
  assert.deepEqual(evidence.preflightValidation.failureReasons, []);
  assert.equal(evidence.authorityValidation.result, "validertOK");
  assert.deepEqual(evidence.authorityValidation.failureReasons, []);
  assert.ok(evidence.validationResponseBytes > 0);
  assert.equal(evidence.instance.fileScanResult, "Clean");
  assert.equal(evidence.instance.confirmationPrepared, true);
  assert.match(evidence.instance.id, /^\d+\/[0-9a-f-]{36}$/u);
  assert.equal(evidence.receipt.dataType, "tilbakemelding");
  assert.match(evidence.receipt.contentType, /^(?:application|text)\/xml$/u);
  assert.ok(evidence.receipt.byteLength > 0);
  assert.match(evidence.receipt.contentSha256, /^[0-9a-f]{64}$/u);
  assert.equal(
    evidence.receipt.reference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${evidence.instance.id}/data/${evidence.receipt.dataId}`,
  );
  assert.equal(evidence.submission.submitted, true);
  assert.equal(evidence.submission.archived, true);
  assert.ok(Number.isFinite(Date.parse(evidence.submission.processEndedAt)));
  assert.ok(Number.isFinite(Date.parse(evidence.submission.archivedAt)));
  assert.equal(
    evidence.submission.archiveReference,
    `https://platform.tt02.altinn.no/storage/api/v1/instances/${evidence.instance.id}`,
  );
  assert.equal(evidence.receipt.reference.startsWith(evidence.submission.archiveReference), true);
  assert.equal(evidence.secretsStored, false);
  assert.equal(evidence.error, null);
  for (const hash of Object.values(evidence.payloadHashes)) {
    assert.match(hash, /^[0-9a-f]{64}$/u);
  }
  assert.doesNotMatch(raw, /access_token|PRIVATE KEY|talli-test\.key|opaque-|<\?xml|<skattemelding|<naeringsspesifikasjon/u);
  assert.doesNotMatch(raw, /partsnummer|partyNumber|foedselsnummer|fødselsnummer/iu);
  assert.doesNotMatch(raw, /\/Users\/|\\Users\\/u);
  assert.doesNotMatch(raw, /\b\d{11}\b/u);
});
