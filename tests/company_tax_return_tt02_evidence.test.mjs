import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const evidenceUrl = new URL(
  "../docs/filing/evidence/company-tax-tt02-2026-07-14.json",
  import.meta.url,
);

test("company-tax TT02 evidence is validated, schema-backed, test-only, and secret-free", async () => {
  const raw = await readFile(evidenceUrl, "utf8");
  const evidence = JSON.parse(raw);

  assert.equal(evidence.status, "validated");
  assert.equal(evidence.environment, "test");
  assert.equal(evidence.productionEnabled, false);
  assert.equal(evidence.companyOrgNumber, "310279617");
  assert.equal(evidence.incomeYear, 2025);
  assert.equal(evidence.scope, "skatteetaten:formueinntekt/skattemelding");
  assert.equal(evidence.localSchemaValidation.status, "passed");
  assert.deepEqual(evidence.localSchemaValidation.schemas, [
    "skattemeldingUpersonlig_v5_ekstern.xsd",
    "naeringsspesifikasjon_v6_ekstern.xsd",
    "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
  ]);
  assert.equal(evidence.authorityValidation.result, "validertOK");
  assert.deepEqual(evidence.authorityValidation.failureReasons, []);
  assert.ok(evidence.responseBytes > 0);
  assert.equal(evidence.secretsStored, false);
  for (const hash of Object.values(evidence.payloadHashes)) {
    assert.match(hash, /^[0-9a-f]{64}$/u);
  }
  assert.doesNotMatch(raw, /access_token|PRIVATE KEY|talli-test\.key|opaque-/u);
  assert.doesNotMatch(raw, /\/Users\/|\\Users\\/u);
  assert.doesNotMatch(raw, /\b\d{11}\b/u);
});
