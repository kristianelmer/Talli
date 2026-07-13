import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createRf1086FileJournal } from "../app/lib/rf1086-file-journal.ts";

const previewId = "12345678-1234-4234-9234-123456789abc";
const checkpoint = {
  schemaVersion: 1,
  revision: 1,
  previewId,
  companyId: "company-id",
  incomeYear: 2025,
  environment: "test",
  payloadHash: "a".repeat(64),
  status: "submitting",
  hovedskjemaId: null,
  confirmation: null,
  calls: [],
  failureCode: null,
  failureMessage: null,
};

async function privateDirectory() {
  const parent = await mkdtemp(path.join(os.tmpdir(), "rf1086-journal-test-"));
  const directory = path.join(parent, "journal");
  await mkdir(directory, { mode: 0o700 });
  return directory;
}

test("persists checkpoints atomically in a private journal", async () => {
  const directory = await privateDirectory();
  const journal = createRf1086FileJournal(directory);
  await journal.save(checkpoint, null);

  assert.deepEqual(await journal.load(previewId), checkpoint);
  const filePath = path.join(directory, `${previewId}.json`);
  assert.equal((await stat(directory)).mode & 0o777, 0o700);
  assert.equal((await stat(filePath)).mode & 0o777, 0o600);
  assert.deepEqual(JSON.parse(await readFile(filePath, "utf8")), checkpoint);
});

test("rejects revision conflicts without replacing the checkpoint", async () => {
  const directory = await privateDirectory();
  const journal = createRf1086FileJournal(directory);
  await journal.save(checkpoint, null);

  await assert.rejects(journal.save({ ...checkpoint, revision: 2 }, null), /revision conflict/u);
  assert.deepEqual(await journal.load(previewId), checkpoint);
});

test("rejects permissive directories and symlinked checkpoint files", async () => {
  const parent = await mkdtemp(path.join(os.tmpdir(), "rf1086-journal-test-"));
  const permissive = path.join(parent, "permissive");
  await mkdir(permissive, { mode: 0o755 });
  const permissiveJournal = createRf1086FileJournal(permissive);
  await assert.rejects(permissiveJournal.load(previewId), /private/u);

  const directory = path.join(parent, "private");
  await mkdir(directory, { mode: 0o700 });
  const target = path.join(parent, "target.json");
  await writeFile(target, JSON.stringify(checkpoint), { mode: 0o600 });
  await symlink(target, path.join(directory, `${previewId}.json`));
  await assert.rejects(createRf1086FileJournal(directory).load(previewId), /regular file/u);
});
