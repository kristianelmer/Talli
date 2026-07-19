import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("annual accounts authority rehearsal refuses to run without explicit test-write approval", () => {
  const result = spawnSync(process.execPath, [
    "--experimental-strip-types",
    "scripts/annual-accounts-authority-test.mjs",
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: { PATH: process.env.PATH ?? "" },
  });

  assert.equal(result.status, 1);
  const output = JSON.parse(result.stderr.trim().split("\n").at(-1));
  assert.equal(output.ok, false);
  assert.equal(output.code, "local_configuration_or_payload_error");
  assert.match(output.message, /TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE/);
});
