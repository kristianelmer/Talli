import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createCompanyTaxReturnTt02FileJournal } from "../app/lib/company-tax-return-tt02-journal.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const checkpoint = {
  schemaVersion: 1,
  revision: 1,
  operationId,
  environment: "test",
  operation: "calculation-only",
  customerOrgNumber: "310279617",
  incomeYear: 2025,
  status: "prepared",
  requestHash: "a".repeat(64),
  preparedAt: "2026-07-13T12:00:00.000Z",
  completedAt: null,
  validation: null,
  current: null,
  failureCode: null,
};

async function privateDirectory() {
  const parent = await mkdtemp(path.join(os.tmpdir(), "company-tax-tt02-journal-test-"));
  const directory = path.join(parent, "journal");
  await mkdir(directory, { mode: 0o700 });
  return directory;
}

test("persists bounded company-tax TT02 metadata atomically in a private journal", async () => {
  const directory = await privateDirectory();
  const journal = createCompanyTaxReturnTt02FileJournal(directory);
  await journal.save(checkpoint, null);

  assert.deepEqual(await journal.load(operationId), checkpoint);
  const filePath = path.join(directory, `${operationId}.json`);
  assert.equal((await stat(directory)).mode & 0o777, 0o700);
  assert.equal((await stat(filePath)).mode & 0o777, 0o600);
  assert.deepEqual(JSON.parse(await readFile(filePath, "utf8")), checkpoint);
});

test("rejects revision conflicts without replacing company-tax evidence", async () => {
  const directory = await privateDirectory();
  const journal = createCompanyTaxReturnTt02FileJournal(directory);
  await journal.save(checkpoint, null);

  await assert.rejects(journal.save({ ...checkpoint, revision: 2 }, null), /revision conflict/u);
  assert.deepEqual(await journal.load(operationId), checkpoint);
});

test("rejects permissive directories and symlinked company-tax checkpoints", async () => {
  const parent = await mkdtemp(path.join(os.tmpdir(), "company-tax-tt02-journal-test-"));
  const permissive = path.join(parent, "permissive");
  await mkdir(permissive, { mode: 0o755 });
  await assert.rejects(createCompanyTaxReturnTt02FileJournal(permissive).load(operationId), /private/u);

  const directory = path.join(parent, "private");
  await mkdir(directory, { mode: 0o700 });
  const target = path.join(parent, "target.json");
  await writeFile(target, JSON.stringify(checkpoint), { mode: 0o600 });
  await symlink(target, path.join(directory, `${operationId}.json`));
  await assert.rejects(createCompanyTaxReturnTt02FileJournal(directory).load(operationId), /regular file/u);
});

test("rejects checkpoint data that could retain tokens, assertions, XML, or provider values", async () => {
  const directory = await privateDirectory();
  const journal = createCompanyTaxReturnTt02FileJournal(directory);

  for (const forbidden of [
    { accessToken: "secret-token" },
    { assertion: "secret-assertion" },
    { xml: "<skattemelding />" },
    { receivedValue: "sensitive-provider-value" },
  ]) {
    await assert.rejects(
      journal.save({ ...checkpoint, ...forbidden }, null),
      /invalid|forbidden/u,
    );
  }
});
