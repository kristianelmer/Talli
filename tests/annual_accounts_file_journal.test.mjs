import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createAnnualAccountsFileJournal } from "../app/lib/annual-accounts-file-journal.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const checkpoint = {
  schemaVersion: 1,
  revision: 1,
  operationId,
  environment: "test",
  organizationNumber: "310279617",
  incomeYear: 2025,
  payloadHash: "a".repeat(64),
  mainFormHash: "b".repeat(64),
  accountsFormHash: "c".repeat(64),
  status: "in-progress",
  instance: null,
  dataElements: null,
  validation: null,
  signingTask: null,
  calls: [
    {
      operation: "create-draft",
      status: "prepared",
      requestHash: "d".repeat(64),
      preparedAt: "2026-07-13T12:00:00.000Z",
      acceptedAt: null,
      failureCode: null,
    },
  ],
  failureCode: null,
};

async function privateDirectory() {
  const parent = await mkdtemp(path.join(os.tmpdir(), "annual-accounts-journal-test-"));
  const directory = path.join(parent, "journal");
  await mkdir(directory, { mode: 0o700 });
  return directory;
}

test("persists bounded annual-accounts checkpoints atomically with private permissions", async () => {
  const directory = await privateDirectory();
  const journal = createAnnualAccountsFileJournal(directory);
  await journal.save(checkpoint, null);

  assert.deepEqual(await journal.load(operationId), checkpoint);
  const filePath = path.join(directory, `${operationId}.json`);
  assert.equal((await stat(directory)).mode & 0o777, 0o700);
  assert.equal((await stat(filePath)).mode & 0o777, 0o600);
  assert.deepEqual(JSON.parse(await readFile(filePath, "utf8")), checkpoint);
});

test("rejects revision conflicts without replacing annual-accounts evidence", async () => {
  const directory = await privateDirectory();
  const journal = createAnnualAccountsFileJournal(directory);
  await journal.save(checkpoint, null);

  await assert.rejects(journal.save({ ...checkpoint, revision: 2 }, null), /revision conflict/u);
  assert.deepEqual(await journal.load(operationId), checkpoint);
});

test("rejects permissive directories and symlinked annual-accounts checkpoints", async () => {
  const parent = await mkdtemp(path.join(os.tmpdir(), "annual-accounts-journal-test-"));
  const permissive = path.join(parent, "permissive");
  await mkdir(permissive, { mode: 0o755 });
  await assert.rejects(createAnnualAccountsFileJournal(permissive).load(operationId), /private/u);

  const directory = path.join(parent, "private");
  await mkdir(directory, { mode: 0o700 });
  const target = path.join(parent, "target.json");
  await writeFile(target, JSON.stringify(checkpoint), { mode: 0o600 });
  await symlink(target, path.join(directory, `${operationId}.json`));
  await assert.rejects(createAnnualAccountsFileJournal(directory).load(operationId), /regular file/u);
});

test("rejects checkpoints containing tokens, assertions, XML, or provider fields", async () => {
  const directory = await privateDirectory();
  const journal = createAnnualAccountsFileJournal(directory);

  for (const forbidden of [
    { accessToken: "secret-token" },
    { assertion: "secret-assertion" },
    { mainFormXml: "<melding />" },
    { providerField: "sensitive.value" },
  ]) {
    await assert.rejects(journal.save({ ...checkpoint, ...forbidden }, null), /invalid|forbidden/u);
  }
});
