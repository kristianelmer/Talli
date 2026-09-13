import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { authorityToolPayload } from "../scripts/authority-tool-payload.mjs";
import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../apps/web/app/lib/annual-accounts-xml.ts";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/authority/${name}.json`, import.meta.url)));

test("annual subprocess uses the unchanged frozen generator and passes feedback", () => {
  const c = fixture("annual-accounts-simple-holding-2025");
  const input = { incomeYear: c.company.incomeYear, annualData: c.annualData, ledgerEntries: c.ledgerEntries,
    companyOrgNumber: c.company.orgNumber, companyName: c.company.name, contactEmail: "synthetic@example.test",
    approvalDate: "2026-06-30", confirmingRepresentative: "Synthetic Person" };
  const payload = buildAnnualAccountsPayload(input);
  assert.deepEqual(authorityToolPayload({ operation: "annual_accounts", input }),
    { ...renderAnnualAccountsXml({ ...input, payload }), feedback: payload.feedback });
});

test("payload subprocess rejects arbitrary module/path dispatch without reflecting input", () => {
  for (const operation of ["../../evil.js", "exec", "https://evil.invalid/", "company_tax", "company_tax_envelope", "company_tax_validation_envelope", "company_tax_validation_summary"]) {
    assert.throws(() => authorityToolPayload({ operation, input: {} }), /payload_operation_invalid/);
  }
  const result = spawnSync(process.execPath, ["--experimental-strip-types", "scripts/authority-tool-payload.mjs"], {
    input: JSON.stringify({ operation: "exec", input: { privateKey: "private-input-marker" } }), encoding: "utf8",
    env: { PATH: process.env.PATH ?? "" },
  });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr, "authority_tool_payload_failed\n");
});
