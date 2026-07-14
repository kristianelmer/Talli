import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actions = await readFile(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = await readFile(
  new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);

test("runtime imports completed company-tax TT02 evidence as pending without enabling production", () => {
  assert.match(actions, /buildCompanyTaxReturnAuthorityTestRunFromEvidence/u);
  assert.match(actions, /export async function recordCompanyTaxReturnTt02Evidence/u);
  assert.match(actions, /formData\.get\("evidenceFile"\)/u);
  assert.match(actions, /expectedIncomeYear: Number\(formString\(formData, "incomeYear"\)\)/u);
  assert.match(actions, /\.select\("id, org_number"\)/u);
  assert.match(actions, /expectedCompanyOrgNumber: company\.org_number/u);
  assert.match(actions, /\.from\("authority_test_runs"\)\.insert\(record\)/u);

  const actionBody = actions.match(
    /export async function recordCompanyTaxReturnTt02Evidence[\s\S]*?\n\}\n/u,
  )?.[0] ?? "";
  assert.doesNotMatch(
    actionBody,
    /production_enabled|authority_permissions|launch_signoffs/u,
  );
});

test("workspace offers a company-tax JSON evidence import bound to the active year", () => {
  assert.match(workspace, /recordCompanyTaxReturnTt02Evidence/u);
  assert.match(workspace, /action=\{recordCompanyTaxReturnTt02Evidence\}/u);
  assert.match(workspace, /name="incomeYear" type="hidden" value=\{primaryIncomeYear\}/u);
  assert.match(workspace, /Verifisert skattemelding-evidens fra TT02/u);
  assert.match(workspace, /name="evidenceFile"[^>]*type="file"/u);
  assert.match(workspace, /status pending/u);
});
