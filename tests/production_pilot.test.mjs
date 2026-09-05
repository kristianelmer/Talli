import assert from "node:assert/strict";
import test from "node:test";

import { buildFilingReleaseGates } from "../apps/web/app/lib/filing-release-gate.ts";

function signoff(key) {
  return {
    key,
    status: "approved",
    reviewer: "reviewer",
    reviewedAt: "2026-07-15T10:00:00.000Z",
    evidenceLink: `https://evidence.example/${key}`,
    decision: "approved",
  };
}

const pilotDecision = {
  companyId: "company-id",
  incomeYear: 2025,
  obligation: "aksjonaerregisteroppgaven",
  status: "pilot_entitlement_active",
  allowed: true,
  chargeAllowed: false,
  readinessAllowed: true,
  billingExempt: true,
  message: "An exact active validation entitlement exempts billing.",
  pilotEntitlementId: "4da89eb7-cf0f-4baf-91ce-e496ff482d79",
};

const readyGateInput = {
  authorityPermissions: [{
    obligation: "aksjonaerregisteroppgaven",
    confirmed_at: "2026-07-15T10:00:00.000Z",
    production_enabled: true,
  }],
  authorityTestRuns: [{
    obligation: "aksjonaerregisteroppgaven",
    status: "accepted",
    receipt_reference: "receipt",
    archive_reference: "archive",
    recorded_at: "2026-07-15T10:00:00.000Z",
  }],
  billingEntitlements: { aksjonaerregisteroppgaven: pilotDecision },
  stepUpContext: { actorId: "owner-id", mfaVerifiedAt: "2026-07-15T11:55:00.000Z" },
  launchSignoffs: [
    "launch_legal_name_public_copy",
    "legal_policy_pack",
    "security_restore",
    "support_rollback",
    "founder_production_go_live",
    "rf1086_authority",
  ].map(signoff),
  adapterCapabilities: {
    aksjonaerregisteroppgaven: { productionImplemented: true, productionEnabled: true },
    skattemelding: { productionImplemented: false, productionEnabled: false },
    aarsregnskap: { productionImplemented: false, productionEnabled: false },
  },
  now: new Date("2026-07-15T12:00:00.000Z"),
};

test("uses the backend's exact pilot decision without duplicating entitlement matching in the web app", () => {
  const gate = buildFilingReleaseGates(readyGateInput)
    .find((item) => item.obligation === "aksjonaerregisteroppgaven");

  assert.equal(gate.status, "production_ready");
  assert.ok(!gate.disabledReasons.includes("billing_account_missing"));
  assert.ok(!gate.disabledReasons.some((reason) => reason.startsWith("billing_refund_signoff_")));
});

test("fails closed when the backend does not return a pilot or billing decision", () => {
  const gate = buildFilingReleaseGates({
    ...readyGateInput,
    billingEntitlements: {},
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");

  assert.equal(gate.status, "production_disabled");
  assert.ok(gate.disabledReasons.includes("billing_account_missing"));
});

test("a non-exempt backend decision cannot skip the billing-refund signoff", () => {
  const gate = buildFilingReleaseGates({
    ...readyGateInput,
    billingEntitlements: {
      aksjonaerregisteroppgaven: { ...pilotDecision, billingExempt: false },
    },
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");

  assert.equal(gate.status, "production_disabled");
  assert.ok(gate.disabledReasons.includes("billing_refund_signoff_missing"));
});
