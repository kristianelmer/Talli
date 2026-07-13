import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("refuses a TT02 company-tax operation without an explicit private journal directory", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "scripts/company-tax-return-tt02.ts",
      "inspect-current",
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
    ],
    { cwd: new URL("..", import.meta.url), encoding: "utf8" },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--journal/u);
  assert.equal(result.stderr.includes("definitely/not/read.key"), false);
});
