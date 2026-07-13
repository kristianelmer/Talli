import assert from "node:assert/strict";
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
