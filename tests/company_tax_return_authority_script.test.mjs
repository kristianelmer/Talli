import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";

const scriptPath = "scripts/company-tax-return-authority-test.mjs";
const source = await readFile(new URL(`../${scriptPath}`, import.meta.url), "utf8");

test("company tax rehearsal refuses to run without explicit TT02 write approval", () => {
  const result = spawnSync(process.execPath, ["--experimental-strip-types", scriptPath], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: { PATH: process.env.PATH ?? "" },
  });

  assert.equal(result.status, 1);
  const output = JSON.parse(result.stderr.trim().split("\n").at(-1));
  assert.equal(output.ok, false);
  assert.equal(output.code, "local_configuration_or_payload_error");
  assert.match(output.message, /TALLI_COMPANY_TAX_APPROVED_TEST_WRITE/u);
});

test("company tax rehearsal is resumable, company-bound, and keeps final submission human-controlled", () => {
  assert.match(source, /TALLI_COMPANY_TAX_REHEARSAL_MODE/u);
  assert.match(source, /mode === "prepare"/u);
  assert.match(source, /mode === "resume"/u);
  assert.match(source, /skatteetaten:formueinntekt\/skattemelding/u);
  assert.match(source, /altinn:instances\.read/u);
  assert.match(source, /altinn:instances\.write/u);
  assert.match(source, /exchangeMaskinportenForAltinnToken/u);
  assert.match(source, /renderCompanyTaxReturnEnvelope/u);
  assert.match(source, /advanceToConfirmation/u);
  assert.equal(source.match(/advanceToConfirmation/gu)?.length, 2);
  assert.match(source, /waitForCompanyTaxReturnFeedback/u);
  assert.match(source, /assertSamePreparedCase/u);
  assert.match(source, /existingEvidence/u);
  assert.match(source, /writeJsonAtomic/u);
  assert.match(source, /companyOrgNumber !== systemUserOrgNumber/u);
  assert.doesNotMatch(source, /submitCompanyTax|finalProcessTransition|advanceToFeedback/u);
});
