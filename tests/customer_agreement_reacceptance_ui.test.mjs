import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const layout = readFileSync(new URL("../apps/web/app/(owner)/layout.tsx", import.meta.url), "utf8");
const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");

test("owner layout replaces children with an accessible reacceptance gate", () => {
  assert.match(layout, /listCompanyAccessContexts\(\)/iu);
  assert.match(layout, /companies\.filter\(\(\{ currentAgreementAccepted \}\) => !currentAgreementAccepted\)/iu);
  assert.match(layout, /pendingCompanies\.length/iu);
  assert.match(layout, /companiesError/iu);
  assert.match(layout, /Kunne ikke kontrollere gjeldende avtaleaksept/iu);
  assert.match(layout, /action=\{reacceptCompanyAgreement\}/iu);
  assert.match(layout, /name="companyId"/iu);
  assert.match(layout, /name="agreementAccepted"/iu);
  assert.match(layout, /required/iu);
  assert.doesNotMatch(layout, /defaultChecked|checked=\{true\}/iu);
  assert.match(layout, /htmlFor="reacceptAgreementAccepted"/iu);
  assert.match(layout, /aria-describedby="reacceptAgreementDescription"/iu);
  assert.match(layout, /href="\/vilkar"/iu);
  assert.match(layout, /href="\/databehandleravtale"/iu);
});

test("Server Action reaccepts through the authenticated generated-client boundary", () => {
  const action = actions.match(/export async function reacceptCompanyAgreement[\s\S]+?\n\}\n\nexport async function/iu)?.[0] ?? "";
  assert.match(action, /getCurrentSessionAccessToken\(\)/iu);
  assert.match(action, /currentAgreementCommand\(formData, returnTo\)/iu);
  assert.match(action, /await reacceptCompanyAgreementThroughApi\(accessToken, \{/iu);
  assert.match(action, /companyAccessActionErrorMessage\(error\)/iu);
  assert.match(action, /revalidatePath\("\/", "layout"\)/iu);
  assert.doesNotMatch(action, /createSupabaseServiceRoleClient|SUPABASE_SERVICE_ROLE_KEY|\.rpc\(|\.from\(/iu);
  assert.doesNotMatch(actions, /\.\/lib\/customer-agreement-reacceptance/iu);
});
