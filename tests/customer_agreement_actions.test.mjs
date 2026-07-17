import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../app/(owner)/workspace/page.tsx", import.meta.url), "utf8");
const copy = readFileSync(new URL("../app/lib/copy.ts", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../app/lib/customer-onboarding.ts", import.meta.url), "utf8");
const createWorkspaceAction = actions.match(
  /export async function createWorkspace[\s\S]+?\n\}\n\nexport async function/iu,
)?.[0] ?? "";
const companyCreationForm = workspace.match(
  /<form[^>]+action=\{createWorkspace\}[\s\S]+?<\/form>/iu,
)?.[0] ?? "";

test("company creation requires current explicit company assent", () => {
  assert.match(createWorkspaceAction, /onboardCustomer/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "agreementAccepted"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "businessTermsVersion"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "businessTermsSha256"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "dpaVersion"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "dpaSha256"\)/iu);
  assert.match(createWorkspaceAction, /createSupabaseServiceRoleClient\(\)/iu);
  assert.match(createWorkspaceAction, /\.rpc\("create_company_workspace_with_acceptance"/iu);
  assert.match(createWorkspaceAction, /\.rpc\("create_company_workspace_with_acceptance",\s*payload\)/iu);
  assert.doesNotMatch(createWorkspaceAction, /supabase\.rpc\("create_company_workspace_with_acceptance"/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("companies"\)\s*\.insert/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("company_memberships"\)\s*\.insert/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("audit_events"\)\s*\.insert/iu);
  assert.match(createWorkspaceAction, /if \(!result\.ok\) \{\s*failTo\(returnTo, result\.message\);?\s*\}/iu);
});

test("the Server Action owns the server-only atomic RPC dependency", () => {
  assert.match(createWorkspaceAction, /getAuthenticatedUser:\s*async/iu);
  assert.match(createWorkspaceAction, /lookupCompanyIdentity:\s*fetchBrregEntity/iu);
  assert.match(createWorkspaceAction, /assertSupportedCompanyIdentity:\s*assertSupportedBrregIdentity/iu);
  assert.match(createWorkspaceAction, /createCompanyWorkspace:\s*async\s*\(payload\)/iu);
  assert.match(createWorkspaceAction, /const serviceRoleClient = createSupabaseServiceRoleClient\(\)/iu);
  assert.doesNotMatch(createWorkspaceAction, /SUPABASE_SERVICE_ROLE_KEY/iu);
  assert.doesNotMatch(onboarding, /createSupabaseServiceRoleClient|SUPABASE_SERVICE_ROLE_KEY|\.rpc\(/iu);
});

test("workspace creation shows an unchecked authority and agreement control", () => {
  assert.match(companyCreationForm, /name="agreementAccepted"/iu);
  assert.match(companyCreationForm, /id="agreementAccepted"/iu);
  assert.match(companyCreationForm, /type="checkbox"/iu);
  assert.match(companyCreationForm, /value="accepted"/iu);
  assert.match(companyCreationForm, /required/iu);
  assert.match(companyCreationForm, /aria-describedby="agreementAcceptedDescription"/iu);
  assert.match(companyCreationForm, /htmlFor="agreementAccepted"/iu);
  assert.match(companyCreationForm, /id="agreementAcceptedDescription"/iu);
  assert.doesNotMatch(companyCreationForm, /defaultChecked|checked=\{true\}/iu);
  assert.match(companyCreationForm, /href="\/vilkar"/iu);
  assert.match(companyCreationForm, /href="\/databehandleravtale"/iu);
  assert.match(companyCreationForm, /name="businessTermsVersion"/iu);
  assert.match(companyCreationForm, /name="businessTermsSha256"/iu);
  assert.match(companyCreationForm, /value=\{currentCustomerAgreements\.businessTerms\.contentSha256\}/iu);
  assert.match(companyCreationForm, /name="dpaVersion"/iu);
  assert.match(companyCreationForm, /name="dpaSha256"/iu);
  assert.match(companyCreationForm, /value=\{currentCustomerAgreements\.dpa\.contentSha256\}/iu);
  const agreementLabel = companyCreationForm.match(/<label[^>]+htmlFor="agreementAccepted"[\s\S]+?<\/label>/iu)?.[0] ?? "";
  assert.doesNotMatch(agreementLabel, /<Link/iu);
});

test("the exact authority statement is centralized as linked copy fragments", () => {
  assert.match(copy, /authority:\s*"Jeg bekrefter at jeg har fullmakt til å inngå avtale på vegne av selskapet, og godtar Talli"/iu);
  assert.match(copy, /businessTerms:\s*"Brukervilkår for bedriftskunder"/iu);
  assert.match(copy, /conjunction:\s*"og"/iu);
  assert.match(copy, /dpa:\s*"Databehandleravtalen\."/iu);
  assert.match(companyCreationForm, /ownerCopy\.workspace\.agreementAcceptance\.authority/iu);
  assert.match(companyCreationForm, /ownerCopy\.workspace\.agreementAcceptance\.businessTerms/iu);
  assert.match(companyCreationForm, /ownerCopy\.workspace\.agreementAcceptance\.conjunction/iu);
  assert.match(companyCreationForm, /ownerCopy\.workspace\.agreementAcceptance\.dpa/iu);
});
