import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const evidenceUrl = new URL(
  "../docs/filing/evidence/rf1086-tt02-2026-07-14.json",
  import.meta.url,
);

test("RF-1086 TT02 evidence is accepted, complete, and secret-free", async () => {
  const raw = await readFile(evidenceUrl, "utf8");
  const evidence = JSON.parse(raw);

  assert.equal(evidence.status, "accepted");
  assert.equal(evidence.company.organizationNumber, "310279617");
  assert.equal(evidence.incomeYear, 2025);
  assert.equal(evidence.scope, "skatteetaten:innrapporteringaksjonaerregisteroppgave");
  assert.equal(evidence.systemUserToken.issued, true);
  assert.equal(evidence.systemUserToken.tokenStored, false);
  assert.equal(evidence.productionEnabled, false);
  assert.deepEqual(evidence.calls.map((call) => call.status), ["accepted", "accepted", "accepted", "accepted"]);
  assert.deepEqual(evidence.calls.slice(0, 3).map((call) => Boolean(call.idempotencyKey)), [true, true, true]);
  assert.equal(evidence.calls[3].idempotencyKey, null);
  assert.match(evidence.authorityReferences.hovedskjemaId, /^[0-9a-f-]{36}$/u);
  assert.match(evidence.authorityReferences.dialogId, /^[0-9a-f-]{36}$/u);
  assert.equal(evidence.archive.reference, evidence.authorityReferences.forsendelseId);
  assert.equal(evidence.archive.documentCount, 2);
  assert.deepEqual(
    evidence.archive.documentHashes,
    [evidence.payloadHashes.hovedskjema, ...evidence.payloadHashes.underskjema],
  );
  assert.doesNotMatch(raw, /access_token|PRIVATE KEY|talli-test\.key/u);
  assert.doesNotMatch(raw, /\b\d{11}\b/u);
});
