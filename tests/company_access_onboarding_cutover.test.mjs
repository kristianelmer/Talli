import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("..", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const json = (path) => JSON.parse(read(path));

test("company onboarding and agreement operations are generated-client boundaries", () => {
  const contract = json("contracts/openapi/talli-v1.json");
  const operations = [
    [
      "/api/v1/company-access/onboarding",
      "post",
      "companyAccessOnboardCompany",
    ],
    [
      "/api/v1/company-access/agreements/reaccept",
      "post",
      "companyAccessReacceptAgreement",
    ],
    [
      "/api/v1/company-access/companies/{company_id}",
      "get",
      "companyAccessGetCompanyRecord",
    ],
    [
      "/api/v1/company-access/operator-context",
      "get",
      "companyAccessGetOperatorContext",
    ],
    [
      "/api/v1/company-access/operator-companies",
      "get",
      "companyAccessSearchOperatorCompanies",
    ],
  ];

  for (const [path, method, operationId] of operations) {
    const operation = contract.paths[path]?.[method];
    assert.equal(operation?.operationId, operationId);
    assert.deepEqual(operation?.security, [{ bearerAuth: [] }]);
    assert.ok(operation?.responses["401"]?.content["application/problem+json"]);
  }

  const companyContext = contract.components.schemas.CompanyContext;
  assert.ok(companyContext.required.includes("currentAgreementAccepted"));
  assert.equal(
    companyContext.properties.currentAgreementAccepted.type,
    "boolean",
  );

  const generatedClient = read(
    "packages/talli-api-client/src/generated/client.ts",
  );
  for (const operationId of operations.map(([, , operation]) => operation)) {
    assert.match(generatedClient, new RegExp(`async ${operationId}\\(`, "u"));
  }

  const featureManifest = json("apps/web/features/company-access/module.json");
  for (const operationId of operations.map(([, , operation]) => operation)) {
    assert.ok(featureManifest.apiOperations.includes(operationId));
  }
});

test("the web onboarding slice has no legacy business-policy or persistence path", () => {
  const actions = read("apps/web/app/actions.ts");
  const supabaseServer = read("apps/web/app/lib/supabase/server.ts");
  const onboardingAction =
    actions.match(
      /export async function createWorkspace[\s\S]+?\n\}\n\nexport async function/iu,
    )?.[0] ?? "";
  const reacceptanceAction =
    actions.match(
      /export async function reacceptCompanyAgreement[\s\S]+?\n\}\n\nexport async function/iu,
    )?.[0] ?? "";

  assert.match(actions, /from "\.\.\/features\/company-access"/u);
  assert.match(onboardingAction, /onboardCompanyThroughApi/u);
  assert.match(reacceptanceAction, /reacceptCompanyAgreementThroughApi/u);
  assert.doesNotMatch(
    actions,
    /\.\/lib\/(?:brreg|customer-onboarding|customer-agreement-reacceptance)/u,
  );
  assert.doesNotMatch(
    `${onboardingAction}\n${reacceptanceAction}`,
    /createSupabaseServiceRoleClient|\.rpc\(/u,
  );
  assert.doesNotMatch(
    supabaseServer,
    /listCustomerAgreementAcceptances|\.from\("customer_agreement_acceptances"\)/u,
  );
});

test("the complete Stage 1 web boundary is Supabase-auth-only", () => {
  const files = ["apps/web/app", "apps/web/features"].flatMap((directory) =>
    readdirSync(new URL(directory, root), { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile() && /\.(?:ts|tsx)$/u.test(entry.name))
      .map((entry) => `${entry.parentPath}/${entry.name}`),
  );
  const directTablePattern =
    /\.from\("(?:companies|company_memberships|company_invitations|customer_agreement_acceptances|company_cancellations|step_up_events|support_operators)"\)/u;
  const directRpcPattern =
    /\.rpc\("(?:create_company_workspace_with_acceptance|append_company_agreement_acceptance|company_access_[^"]+)"/u;
  const violations = files.filter((file) => {
    const source = readFileSync(file, "utf8");
    return directTablePattern.test(source) || directRpcPattern.test(source);
  });

  assert.deepEqual(violations, []);
});

test("company access owns agreement evidence and the #138 facade has exited", () => {
  const backendManifest = json(
    "apps/backend/src/talli_backend/modules/company_access/module.json",
  );
  const catalog = json("architecture/database-catalog.json");
  const compatibility = json("architecture/compatibility.json");

  assert.ok(
    backendManifest.owns.tables.includes(
      "public.customer_agreement_acceptances",
    ),
  );
  assert.ok(backendManifest.owns.tables.includes("public.support_operators"));
  assert.deepEqual(
    catalog.tables.find(
      ({ name }) => name === "public.customer_agreement_acceptances",
    ),
    {
      name: "public.customer_agreement_acceptances",
      kind: "capability-business",
      owner: "backend:company_access",
    },
  );
  assert.equal(
    compatibility.records.some(({ removalIssue }) => removalIssue === "#138"),
    false,
  );
  assert.deepEqual(
    catalog.tables.find(({ name }) => name === "public.support_operators"),
    {
      name: "public.support_operators",
      kind: "capability-business",
      owner: "backend:company_access",
    },
  );
  assert.equal(
    catalog.tables.some(({ name }) => name === "public.step_up_events"),
    false,
  );
});

test("the onboarding overlap and destructive contract are separate release artifacts", () => {
  const expand = read(
    "supabase/migrations/20260826100000_company_access_onboarding.sql",
  );
  const contract = read(
    "supabase/contract-migrations/20260826101000_company_access_onboarding_contract.sql",
  );
  const automaticMigrations = readdirSync(
    new URL("supabase/migrations", root),
  );

  assert.match(expand, /company_access_onboard_company/u);
  assert.match(expand, /company_access_reaccept_agreement/u);
  assert.doesNotMatch(
    automaticMigrations.join("\n"),
    /company_access_onboarding_contract/u,
  );
  assert.match(contract, /drop function if exists public\.create_company_workspace_with_acceptance/iu);
  assert.match(contract, /drop function if exists public\.append_company_agreement_acceptance/iu);
  assert.match(contract, /drop table if exists public\.step_up_events/iu);
  assert.match(
    contract,
    /create or replace function company_access_policy\.authenticated_can_append_audit_v1/iu,
  );
  assert.doesNotMatch(
    contract,
    /create or replace function public\.company_access_authenticated_can_append_audit_v1/iu,
  );
  assert.match(
    contract,
    /revoke all on function public\.company_access_auth_uid_v1\(\),[\s\S]*public\.company_access_auth_jwt_v1\(\),[\s\S]*public\.company_access_is_accepted_owner_v1\(uuid\)[\s\S]*from public, anon, authenticated, service_role/iu,
  );
});
