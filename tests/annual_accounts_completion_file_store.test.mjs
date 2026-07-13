import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, lstat, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  AnnualAccountsCompletionFileStoreError,
  createAnnualAccountsCompletionFileStore,
} from "../app/lib/annual-accounts-completion-file-store.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const evidence = {
  schemaVersion: 1,
  environment: "test",
  operationId,
  organizationNumber: "310279617",
  incomeYear: 2025,
  instance: {
    ownerPartyId: "500700",
    instanceGuid: "232c5390-9479-4506-a266-9890d7287bfb",
  },
  completedAt: "2026-07-13T12:42:31.123Z",
  mainFormId: "ce8665c1-01c3-49f7-960f-196b250a2266",
  accountsFormId: "0445d618-28b8-4af5-95e0-c8c989487e7a",
  signatureDataElementId: "7b8b2632-5b85-4d31-86cc-0c8766e4e079",
  mainFormHash: "a".repeat(64),
  accountsFormHash: "b".repeat(64),
};
const dialogEvidence = {
  schemaVersion: 1,
  environment: "test",
  operationId,
  organizationNumber: "310279617",
  incomeYear: 2025,
  instance: {
    ownerPartyId: "500700",
    instanceGuid: "232c5390-9479-4506-a266-9890d7287bfb",
  },
  completionEvidenceSha256: createHash("sha256").update(JSON.stringify(evidence), "utf8").digest("hex"),
  dialogId: "0193d51a-ec30-7d58-b727-6ce65964d3d4",
  dialogRevision: "12345678-1234-4234-9234-123456789abd",
  dialogStatus: "Completed",
  dialogCreatedAt: "2026-07-13T12:00:00Z",
  dialogUpdatedAt: "2026-07-13T12:43:00Z",
  serviceResourceId: "app_brg_aarsregnskap",
  serviceOwnerCode: "brg",
  transmissionCount: 1,
  authorizedTransmissionCount: 1,
  authorizedAttachmentCount: 1,
  authorizedApiAttachmentCount: 1,
};

async function fixture() {
  const parent = await mkdtemp(path.join(os.tmpdir(), "annual-completion-store-"));
  const directory = path.join(parent, "private");
  return { parent, directory, store: createAnnualAccountsCompletionFileStore(directory) };
}

test("stores signed-instance evidence privately, immutably, and idempotently", async () => {
  const { directory, store } = await fixture();
  const first = await store.save(evidence);
  const second = await store.save(structuredClone(evidence));
  const loaded = await store.load(operationId);
  const filePath = path.join(directory, `${operationId}.signed.json`);

  assert.match(first.evidenceSha256, /^[0-9a-f]{64}$/u);
  assert.deepEqual(first, { evidenceSha256: second.evidenceSha256, alreadyStored: false });
  assert.deepEqual(second, { evidenceSha256: first.evidenceSha256, alreadyStored: true });
  assert.deepEqual(loaded, evidence);
  assert.equal((await lstat(directory)).mode & 0o777, 0o700);
  assert.equal((await lstat(filePath)).mode & 0o777, 0o600);
  assert.doesNotMatch(await readFile(filePath, "utf8"), /token|assertion|<melding>/iu);
});

test("rejects conflicting evidence for an already recorded operation", async () => {
  const { store } = await fixture();
  await store.save(evidence);

  await assert.rejects(
    store.save({ ...evidence, completedAt: "2026-07-13T12:43:31.123Z" }),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_completion_evidence_changed",
  );
});

test("rejects evidence with unknown secret fields and tampered stored JSON", async () => {
  const { directory, store } = await fixture();
  await assert.rejects(
    store.save({ ...evidence, bearerToken: "must-not-persist" }),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_completion_evidence_invalid",
  );

  await store.save(evidence);
  const filePath = path.join(directory, `${operationId}.signed.json`);
  await writeFile(filePath, JSON.stringify({ ...evidence, providerBody: "must-not-persist" }), { mode: 0o600 });
  await assert.rejects(
    store.load(operationId),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_completion_evidence_invalid",
  );
});

test("rejects permissive evidence directories and symlinked evidence files", async () => {
  const permissive = await fixture();
  await permissive.store.save(evidence);
  await chmod(permissive.directory, 0o755);
  await assert.rejects(
    permissive.store.load(operationId),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_completion_store_directory_insecure",
  );

  const linked = await fixture();
  await linked.store.save(evidence);
  const target = path.join(linked.directory, `${operationId}.signed.json`);
  const moved = path.join(linked.directory, "moved.json");
  await (await import("node:fs/promises")).rename(target, moved);
  await symlink(moved, target);
  await assert.rejects(
    linked.store.load(operationId),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_completion_store_file_invalid",
  );
});

test("stores Dialogporten evidence only after the matching signed-instance evidence", async () => {
  const { directory, store } = await fixture();
  await assert.rejects(
    store.saveDialog(dialogEvidence),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_dialog_completion_missing",
  );

  await store.save(evidence);
  const first = await store.saveDialog(dialogEvidence);
  const second = await store.saveDialog(structuredClone(dialogEvidence));
  const loaded = await store.loadDialog(operationId);
  const filePath = path.join(directory, `${operationId}.dialog.json`);

  assert.deepEqual(first, { evidenceSha256: second.evidenceSha256, alreadyStored: false });
  assert.deepEqual(second, { evidenceSha256: first.evidenceSha256, alreadyStored: true });
  assert.deepEqual(loaded, dialogEvidence);
  assert.equal((await lstat(filePath)).mode & 0o777, 0o600);
  assert.doesNotMatch(await readFile(filePath, "utf8"), /token|assertion|provider receipt|<melding>/iu);
});

test("rejects mismatched, conflicting, and over-specified Dialogporten evidence", async () => {
  const { store } = await fixture();
  await store.save(evidence);
  await assert.rejects(
    store.saveDialog({ ...dialogEvidence, completionEvidenceSha256: "c".repeat(64) }),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_dialog_completion_mismatch",
  );
  await assert.rejects(
    store.saveDialog({ ...dialogEvidence, accessToken: "must-not-persist" }),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_dialog_evidence_invalid",
  );

  await store.saveDialog(dialogEvidence);
  await assert.rejects(
    store.saveDialog({ ...dialogEvidence, dialogRevision: "12345678-1234-4234-9234-123456789abe" }),
    (error) =>
      error instanceof AnnualAccountsCompletionFileStoreError &&
      error.code === "annual_accounts_dialog_evidence_changed",
  );
});
