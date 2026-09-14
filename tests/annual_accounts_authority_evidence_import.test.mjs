import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actions = await readFile(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const workspace = await readFile(
  new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);

test("runtime imports validated RR0002 evidence as pending without enabling production", () => {
  assert.match(actions, /importAnnualAccountsTt02Evidence/u);
  assert.match(actions, /export async function recordAnnualAccountsTt02Evidence/u);
  assert.match(actions, /formData\.get\("evidenceFile"\)/u);
  assert.match(actions, /loadAcceptedMembershipCompany/u);
  assert.match(actions, /annualAccountsEvidenceImportErrorMessage/u);
  const actionBody = actions.match(
    /export async function recordAnnualAccountsTt02Evidence[\s\S]*?\n\}\n/u,
  )?.[0] ?? "";
  assert.match(actionBody, /loadAcceptedMembershipCompany\(companyId\)/u);
  assert.doesNotMatch(actionBody, /\.from\("companies"\)/u);
  assert.doesNotMatch(actionBody, /production_enabled|authority_permissions|\.from\("authority_test_runs"\)/u);
  assert.match(actionBody, /annual_accounts_tt02_evidence_imported/u);
});

test("workspace offers a JSON evidence import and defaults manual evidence to pending", () => {
  assert.match(workspace, /recordAnnualAccountsTt02Evidence/u);
  assert.match(workspace, /action=\{recordAnnualAccountsTt02Evidence\}/u);
  assert.match(workspace, /name="evidenceFile"[^>]*type="file"/u);
  assert.match(workspace, /accept="application\/json,\.json"/u);
  assert.match(workspace, /name="status" defaultValue="pending"/u);
});
