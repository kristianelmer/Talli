import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const transport = readFileSync(
  new URL("../apps/web/features/billing/transport.ts", import.meta.url),
  "utf8",
);
const workspaceData = readFileSync(
  new URL("../apps/web/app/lib/workspace-data.ts", import.meta.url),
  "utf8",
);
const annualReadiness = readFileSync(
  new URL("../apps/web/app/lib/annual-readiness.ts", import.meta.url),
  "utf8",
);
const annualWorkspaceServer = readFileSync(
  new URL("../apps/web/app/lib/annual-workspace-server.ts", import.meta.url),
  "utf8",
);
const submissionReview = readFileSync(
  new URL("../apps/web/app/components/annual-workspace/SubmissionReview.tsx", import.meta.url),
  "utf8",
);
const billingAdapter = readFileSync(
  new URL("../apps/backend/src/talli_backend/adapters/supabase_billing.py", import.meta.url),
  "utf8",
);
const billingMigration = readFileSync(
  new URL("../supabase/migrations/20260905010000_billing_capability.sql", import.meta.url),
  "utf8",
);
const companyAccessBillingContract = readFileSync(
  new URL("../supabase/migrations/20260905003000_company_access_billing_owner_subject.sql", import.meta.url),
  "utf8",
);
const companyAccessBillingRollback = readFileSync(
  new URL("../supabase/rollback/20260905003000_company_access_billing_owner_subject.sql", import.meta.url),
  "utf8",
);

test("web billing commands and queries cross only the generated backend client", () => {
  assert.match(transport, /createTalliApiClient/);
  assert.match(transport, /billingReadSnapshot/);
  assert.match(transport, /billingReadEntitlement/);
  assert.match(transport, /billingActivateSubscription/);
  assert.match(transport, /billingRefundFilingPackage/);
  assert.match(transport, /billingManagePilotEntitlement/);

  assert.doesNotMatch(actions, /\.from\(["']billing_/);
  assert.doesNotMatch(actions, /\.from\(["']production_pilot_entitlements/);
  assert.doesNotMatch(workspaceData, /\.from\(["']billing_/);
  assert.doesNotMatch(workspaceData, /\.from\(["']production_pilot_entitlements/);
});

test("the retired TypeScript policy modules stay removed", () => {
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/billing.ts", import.meta.url)),
    false,
  );
  assert.equal(
    existsSync(new URL("../apps/web/app/lib/production-pilot.ts", import.meta.url)),
    false,
  );
  assert.doesNotMatch(annualReadiness, /productionBillingGate|evaluateProductionPilot/);
  assert.match(annualReadiness, /billingDecision\.readinessAllowed/);
});

test("annual submission review renders the backend entitlement without a second policy", () => {
  assert.match(annualWorkspaceServer, /loadBillingEntitlement/);
  assert.match(submissionReview, /billingEntitlement\.allowed/);
  assert.doesNotMatch(submissionReview, /billingAccounts|filing_package_paid|pricing_plan|founder/u);
});

test("billing uses the versioned company-access authorization seam", () => {
  assert.match(billingAdapter, /company_access_is_accepted_owner_subject_v1/);
  assert.doesNotMatch(billingAdapter, /from public\.company_memberships/u);
  assert.doesNotMatch(billingMigration, /create or replace function public\.company_access_/iu);
  assert.doesNotMatch(billingMigration, /from public\.company_memberships/iu);
  assert.doesNotMatch(
    billingMigration,
    /grant select on public\.system_user_requests, public\.company_memberships\s+to billing_store_owner/iu,
  );
  assert.match(companyAccessBillingContract, /company_access_is_active_admin_v1\(\)/iu);
  assert.match(companyAccessBillingContract, /company_access_has_fresh_mfa_v1\(\)/iu);
  assert.match(companyAccessBillingContract, /from public\.company_memberships/iu);
  assert.match(companyAccessBillingRollback, /drop function if exists\s+public\.company_access_/iu);
});

test("predecessor billing audit facts remain on every successor journey", () => {
  for (const action of [
    "billing_account_saved",
    "billing_subscription_activated",
    "billing_subscription_canceled",
    "filing_package_paid",
    "billing_unsupported_no_charge",
    "billing_refund_completed",
  ]) {
    assert.match(actions, new RegExp(`action: "${action}"`, "u"));
  }
  for (const message of [
    /Faktureringskonto lagret med/,
    /Abonnement aktivert via/,
    /Abonnement kansellert via/,
    /Innsendingspakke betalt for/,
    /Innsendingspakke refundert via/,
  ]) {
    assert.match(actions, message);
  }
});
