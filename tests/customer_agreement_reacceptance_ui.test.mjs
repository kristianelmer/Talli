import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const layout = readFileSync(new URL("../apps/web/app/(owner)/layout.tsx", import.meta.url), "utf8");
const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const moduleSource = readFileSync(new URL("../apps/web/app/lib/customer-agreement-reacceptance.ts", import.meta.url), "utf8");

test("owner layout replaces children with an accessible reacceptance gate", () => {
  assert.match(layout, /companiesRequiringCurrentCustomerAgreement/iu);
  assert.match(layout, /listCustomerAgreementAcceptances/iu);
  assert.match(layout, /pendingCompanies\.length/iu);
  assert.match(layout, /agreementDataError/iu);
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

test("Server Action maps typed results and alone owns the privileged adapter", () => {
  const action = actions.match(/export async function reacceptCompanyAgreement[\s\S]+?\n\}\n\nexport async function/iu)?.[0] ?? "";
  assert.match(action, /reacceptCustomerAgreement/iu);
  assert.match(action, /createSupabaseServiceRoleClient\(\)/iu);
  assert.match(action, /\.rpc\("append_company_agreement_acceptance",\s*payload\)/iu);
  assert.match(action, /if \(!result\.ok\) \{\s*failTo\(returnTo, result\.message\)/iu);
  assert.match(action, /revalidatePath\("\/", "layout"\)/iu);
  assert.doesNotMatch(moduleSource, /createSupabaseServiceRoleClient|SUPABASE_SERVICE_ROLE_KEY|\.rpc\(/iu);
});
