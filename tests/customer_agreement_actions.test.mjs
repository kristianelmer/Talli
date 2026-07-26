import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url), "utf8");
const companyLookup = readFileSync(new URL("../apps/web/app/(owner)/onboarding/CompanyLookupForm.tsx", import.meta.url), "utf8");
const agreementFields = readFileSync(new URL("../apps/web/app/components/CustomerAgreementAcceptanceFields.tsx", import.meta.url), "utf8");
const copy = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../apps/web/app/lib/customer-onboarding.ts", import.meta.url), "utf8");
const createWorkspaceAction = actions.match(
  /export async function createWorkspace[\s\S]+?\n\}\n\nexport async function/iu,
)?.[0] ?? "";
const companyCreationForm = workspace.match(
  /<form[^>]+action=\{createWorkspace\}[\s\S]+?<\/form>/iu,
)?.[0] ?? "";
const companyLookupForm = companyLookup.match(
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
  assert.match(companyCreationForm, /<CustomerAgreementAcceptanceFields \/>/u);
  assert.match(agreementFields, /name="agreementAccepted"/iu);
  assert.match(agreementFields, /id="agreementAccepted"/iu);
  assert.match(agreementFields, /type="checkbox"/iu);
  assert.match(agreementFields, /value="accepted"/iu);
  assert.match(agreementFields, /required/iu);
  assert.match(agreementFields, /aria-describedby="agreementAcceptedDescription"/iu);
  assert.match(agreementFields, /htmlFor="agreementAccepted"/iu);
  assert.match(agreementFields, /id="agreementAcceptedDescription"/iu);
  assert.doesNotMatch(agreementFields, /defaultChecked|checked=\{true\}/iu);
  assert.match(agreementFields, /href="\/vilkar"/iu);
  assert.match(agreementFields, /href="\/databehandleravtale"/iu);
  assert.match(agreementFields, /name="businessTermsVersion"/iu);
  assert.match(agreementFields, /name="businessTermsSha256"/iu);
  assert.match(agreementFields, /value=\{currentCustomerAgreements\.businessTerms\.version\}/iu);
  assert.match(agreementFields, /value=\{currentCustomerAgreements\.businessTerms\.contentSha256\}/iu);
  assert.match(agreementFields, /name="dpaVersion"/iu);
  assert.match(agreementFields, /name="dpaSha256"/iu);
  assert.match(agreementFields, /value=\{currentCustomerAgreements\.dpa\.version\}/iu);
  assert.match(agreementFields, /value=\{currentCustomerAgreements\.dpa\.contentSha256\}/iu);
  const agreementLabel = agreementFields.match(/<label[^>]+htmlFor="agreementAccepted"[\s\S]+?<\/label>/iu)?.[0] ?? "";
  assert.doesNotMatch(agreementLabel, /<Link/iu);
});

test("company lookup submits the current authority and agreement evidence", () => {
  assert.match(companyLookupForm, /<CustomerAgreementAcceptanceFields \/>/u);
});

test("the exact authority statement is centralized as linked copy fragments", () => {
  assert.match(copy, /authority:\s*"Jeg bekrefter at jeg har fullmakt til å inngå avtale på vegne av selskapet, og godtar Talli"/iu);
  assert.match(copy, /businessTerms:\s*"Brukervilkår for bedriftskunder"/iu);
  assert.match(copy, /conjunction:\s*"og"/iu);
  assert.match(copy, /dpa:\s*"Databehandleravtalen\."/iu);
  assert.match(agreementFields, /ownerCopy\.workspace\.agreementAcceptance\.authority/iu);
  assert.match(agreementFields, /ownerCopy\.workspace\.agreementAcceptance\.businessTerms/iu);
  assert.match(agreementFields, /ownerCopy\.workspace\.agreementAcceptance\.conjunction/iu);
  assert.match(agreementFields, /ownerCopy\.workspace\.agreementAcceptance\.dpa/iu);
});
