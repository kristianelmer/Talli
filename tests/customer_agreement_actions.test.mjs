import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../app/(owner)/workspace/page.tsx", import.meta.url), "utf8");
const createWorkspaceAction = actions.match(
  /export async function createWorkspace[\s\S]+?\n\}\n\nexport async function/iu,
)?.[0] ?? "";
const companyCreationForm = workspace.match(
  /<form[^>]+action=\{createWorkspace\}[\s\S]+?<\/form>/iu,
)?.[0] ?? "";

test("company creation requires current explicit company assent", () => {
  assert.match(createWorkspaceAction, /assertCurrentCustomerAgreementForm/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "agreementAccepted"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "businessTermsVersion"\)/iu);
  assert.match(createWorkspaceAction, /formString\(formData, "dpaVersion"\)/iu);
  assert.match(createWorkspaceAction, /createSupabaseServiceRoleClient\(\)/iu);
  assert.match(createWorkspaceAction, /\.rpc\("create_company_workspace_with_acceptance"/iu);
  assert.match(createWorkspaceAction, /p_actor_id:\s*user\.id/iu);
  assert.doesNotMatch(createWorkspaceAction, /supabase\.rpc\("create_company_workspace_with_acceptance"/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("companies"\)\s*\.insert/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("company_memberships"\)\s*\.insert/iu);
  assert.doesNotMatch(createWorkspaceAction, /\.from\("audit_events"\)\s*\.insert/iu);
});

test("authenticated validation and registry values precede the service-role RPC", () => {
  const authentication = createWorkspaceAction.indexOf("supabase.auth.getUser()");
  const validation = createWorkspaceAction.indexOf("assertCurrentCustomerAgreementForm");
  const brregLookup = createWorkspaceAction.indexOf("fetchBrregEntity(orgNumber)");
  const supportedAsCheck = createWorkspaceAction.indexOf("assertSupportedBrregIdentity(identity)");
  const serviceRoleClient = createWorkspaceAction.indexOf("createSupabaseServiceRoleClient()");
  const privilegedRpc = createWorkspaceAction.indexOf('.rpc("create_company_workspace_with_acceptance"');

  assert.ok(authentication >= 0 && authentication < validation);
  assert.ok(validation < brregLookup);
  assert.ok(brregLookup < supportedAsCheck);
  assert.ok(supportedAsCheck < serviceRoleClient);
  assert.ok(serviceRoleClient < privilegedRpc);
  assert.match(createWorkspaceAction, /p_business_terms_version:\s*currentCustomerAgreements\.businessTerms\.version/iu);
  assert.match(createWorkspaceAction, /p_dpa_version:\s*currentCustomerAgreements\.dpa\.version/iu);
  assert.match(createWorkspaceAction, /p_authority_statement_version:\s*customerAgreementAuthorityStatementVersion/iu);
  assert.match(createWorkspaceAction, /p_acceptance_method:\s*"in_app_clickwrap"/iu);
});

test("workspace creation shows an unchecked authority and agreement control", () => {
  assert.match(companyCreationForm, /name="agreementAccepted"/iu);
  assert.match(companyCreationForm, /type="checkbox"/iu);
  assert.match(companyCreationForm, /value="accepted"/iu);
  assert.match(companyCreationForm, /required/iu);
  assert.doesNotMatch(companyCreationForm, /defaultChecked|checked=\{true\}/iu);
  assert.match(companyCreationForm, /href="\/vilkar"/iu);
  assert.match(companyCreationForm, /href="\/databehandleravtale"/iu);
  assert.match(companyCreationForm, /name="businessTermsVersion"/iu);
  assert.match(companyCreationForm, /name="dpaVersion"/iu);
});
