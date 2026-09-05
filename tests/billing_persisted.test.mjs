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
