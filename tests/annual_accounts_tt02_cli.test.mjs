import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("refuses an annual-accounts TT02 step without an explicit journal and execute flag", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "scripts/annual-accounts-tt02.ts",
      "step",
      "--input",
      "/definitely/not/read.json",
      "--customer-org",
      "310279617",
      "--income-year",
      "2025",
      "--client-id",
      "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      "--key-id",
      "2d275f93-10a2-4839-993e-b14da2b84ad8",
      "--private-key",
      "/definitely/not/read.key",
    ],
    { cwd: new URL("..", import.meta.url), encoding: "utf8" },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--journal/u);
  assert.equal(result.stderr.includes("definitely/not/read"), false);
});

test("keeps post-signature verification read-only and rejects the mutation-only lock flag", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "scripts/annual-accounts-tt02.ts",
      "verify-signed",
      "--input",
      "/definitely/not/read.json",
      "--journal",
      "/definitely/not/read-journal",
      "--customer-org",
      "310279617",
      "--income-year",
      "2025",
      "--client-id",
      "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      "--key-id",
      "2d275f93-10a2-4839-993e-b14da2b84ad8",
      "--private-key",
      "/definitely/not/read.key",
      "--execute-test",
      "--lock",
    ],
    { cwd: new URL("..", import.meta.url), encoding: "utf8" },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Usage/u);
  assert.equal(result.stderr.includes("definitely/not/read"), false);
});

test("keeps Dialogporten verification read-only and rejects the mutation-only lock flag", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "scripts/annual-accounts-tt02.ts",
      "verify-dialog",
      "--input",
      "/definitely/not/read.json",
      "--journal",
      "/definitely/not/read-journal",
      "--customer-org",
      "310279617",
      "--income-year",
      "2025",
      "--client-id",
      "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
      "--key-id",
      "2d275f93-10a2-4839-993e-b14da2b84ad8",
      "--private-key",
      "/definitely/not/read.key",
      "--execute-test",
      "--lock",
    ],
    { cwd: new URL("..", import.meta.url), encoding: "utf8" },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Usage/u);
  assert.equal(result.stderr.includes("definitely/not/read"), false);
});
