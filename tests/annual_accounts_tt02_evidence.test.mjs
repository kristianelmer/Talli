import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const evidenceUrl = new URL(
  "../docs/filing/evidence/annual-accounts-tt02-2026-07-14.json",
  import.meta.url,
);

test("annual-accounts TT02 evidence is validated, locked, test-only, and secret-free", async () => {
  const raw = await readFile(evidenceUrl, "utf8");
  const evidence = JSON.parse(raw);

  assert.equal(evidence.status, "locked_for_person_signing");
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
  assert.equal(evidence.signed, false);
  assert.equal(evidence.submitted, false);
  assert.equal(evidence.secretsStored, false);
  assert.equal(evidence.evidenceFile, "annual-accounts-tt02-2026-07-14.json");
  assert.equal(
    evidence.signingUrl,
    `https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406/#/instance/${evidence.instance.id}`,
  );
  for (const hash of Object.values(evidence.payloadHashes)) {
    assert.match(hash, /^[0-9a-f]{64}$/u);
  }
  assert.doesNotMatch(raw, /access_token|PRIVATE KEY|talli-test\.key|opaque-/u);
  assert.doesNotMatch(raw, /\/Users\/|\\Users\\/u);
  assert.doesNotMatch(raw, /\b\d{11}\b/u);
});
