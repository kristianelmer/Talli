import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actionsSource = readFileSync(
  new URL("../apps/web/app/actions.ts", import.meta.url),
  "utf8",
);
const wizardSource = readFileSync(
  new URL(
    "../apps/web/app/(owner)/actions/_components/ShareholderLoanWizard.tsx",
    import.meta.url,
  ),
  "utf8",
);
const supabaseWorkspaceSource = readFileSync(
  new URL("./supabase_workspace.test.mjs", import.meta.url),
  "utf8",
);

function serverActionSource(name) {
  const start = actionsSource.indexOf(`export async function ${name}`);
  assert.notEqual(start, -1, `${name} must exist`);
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  return actionsSource.slice(start, end < 0 ? undefined : end);
}

test("shareholder-loan intent crosses only the governance generated boundary", () => {
  const action = serverActionSource("recordShareholderLoan");

  assert.match(action, /requiredFormUuid\(formData, "operationId"\)/u);
  assert.match(action, /getCurrentSessionAccessToken\(\)/u);
  assert.match(action, /await recordShareholderLoanThroughApi\(/u);
  assert.match(action, /actionId: operationId/u);
  assert.match(action, /ledgerEntryId: operationId/u);
  assert.match(
    action,
    /recordShareholderLoanThroughApi\([\s\S]*?operationId,[\s\S]*?operationId/u,
  );
  assert.match(action, /corporateGovernanceOutcomeMayBeUnknown\(error\)/u);
  assert.match(action, /shareholderLoanActionErrorMessage\(error\)/u);
  assert.doesNotMatch(
    action,
    /postLedgerShareholderLoan|validateShareholderLoan|shareholderLoanLedgerLines/u,
  );
});

test("active Supabase integration no longer imports or exercises browser-owned loan policy", () => {
  assert.doesNotMatch(
    supabaseWorkspaceSource,
    /lib\/shareholder-loan|validateShareholderLoan|shareholderLoanLedgerLines/u,
  );
  assert.doesNotMatch(supabaseWorkspaceSource, /action_type:\s*"shareholder_loan"/u);
});

test("shareholder-loan wizard submits intent without owning domain or ledger policy", () => {
  assert.doesNotMatch(
    wizardSource,
    /lib\/shareholder-loan|validateShareholderLoan|shareholderLoanLedgerLines/u,
  );
  assert.doesNotMatch(wizardSource, /ActionPreview|LedgerLine|useMemo/u);
  assert.doesNotMatch(wizardSource, /\b(?:1920|2255|1370)\b/u);
  assert.match(wizardSource, /shareholderLoanFormPresentation\(direction, relatedPartySecurity\)/u);
  assert.match(wizardSource, /presentation\.block !== null/u);
  assert.match(wizardSource, /<form action=\{recordShareholderLoan\}/u);
  assert.match(wizardSource, /<Banner variant=\{presentation\.block \? "danger" : "info"\}/u);
});
