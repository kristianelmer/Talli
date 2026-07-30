import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actions = await readFile(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const workspace = await readFile(
  new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);

test("runtime imports validated RR0002 evidence as pending without enabling production", () => {
  assert.match(actions, /buildAnnualAccountsAuthorityTestRunFromEvidence/u);
  assert.match(actions, /export async function recordAnnualAccountsTt02Evidence/u);
  assert.match(actions, /formData\.get\("evidenceFile"\)/u);
  assert.match(actions, /\.select\("id, org_number"\)/u);
  assert.match(actions, /expectedCompanyOrgNumber: company\.org_number/u);
  assert.match(actions, /\.from\("authority_test_runs"\)\.insert\(record\)/u);
  assert.doesNotMatch(
    actions.match(/export async function recordAnnualAccountsTt02Evidence[\s\S]*?\n\}\n/u)?.[0] ?? "",
    /production_enabled|authority_permissions/u,
  );
});

test("workspace offers a JSON evidence import and defaults manual evidence to pending", () => {
  assert.match(workspace, /recordAnnualAccountsTt02Evidence/u);
  assert.match(workspace, /action=\{recordAnnualAccountsTt02Evidence\}/u);
  assert.match(workspace, /name="evidenceFile"[^>]*type="file"/u);
  assert.match(workspace, /accept="application\/json,\.json"/u);
  assert.match(workspace, /name="status" defaultValue="pending"/u);
});
