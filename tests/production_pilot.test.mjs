import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateProductionPilotEntitlement,
  isBillingExemptProductionPilot,
} from "../apps/web/app/lib/production-pilot.ts";
import { buildFilingReleaseGates } from "../apps/web/app/lib/filing-release-gate.ts";

const context = {
  companyId: "company-id",
  userId: "owner-id",
  incomeYear: 2025,
  obligation: "aksjonaerregisteroppgaven",
  caseProfile: "rf1086_no_activity_v1",
};

const entitlement = {
  id: "entitlement-id",
  company_id: "company-id",
  user_id: "owner-id",
  income_year: 2025,
  obligation: "aksjonaerregisteroppgaven",
  case_profile: "rf1086_no_activity_v1",
  status: "active",
  billing_exempt: true,
  starts_at: "2026-07-01T00:00:00.000Z",
  expires_at: "2026-08-01T00:00:00.000Z",
};

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
  billingAccount: null,
  filingReadyByObligation: { aksjonaerregisteroppgaven: true },
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
  pilotContext: context,
  pilotEntitlements: [entitlement],
  now: new Date("2026-07-15T12:00:00.000Z"),
};

test("requires an exact active company/user/year/obligation/profile entitlement", () => {
  const mismatchCases = [
    [{ ...entitlement, company_id: "another-company" }, "pilot_entitlement_company_mismatch"],
    [{ ...entitlement, user_id: "another-owner" }, "pilot_entitlement_user_mismatch"],
    [{ ...entitlement, income_year: 2024 }, "pilot_entitlement_year_mismatch"],
    [{ ...entitlement, obligation: "skattemelding" }, "pilot_entitlement_obligation_mismatch"],
    [{ ...entitlement, case_profile: "another-profile" }, "pilot_entitlement_profile_mismatch"],
    [{ ...entitlement, status: "suspended" }, "pilot_entitlement_suspended"],
  ];

  for (const [candidate, reason] of mismatchCases) {
    assert.deepEqual(
      evaluateProductionPilotEntitlement(context, candidate, new Date("2026-07-15T12:00:00Z")),
      { allowed: false, reason },
    );
  }
  assert.deepEqual(
    evaluateProductionPilotEntitlement(context, entitlement, new Date("2026-07-15T12:00:00Z")),
    { allowed: true, reason: "pilot_entitlement_active" },
  );
});

test("rejects absent, future, and expired entitlements", () => {
  assert.deepEqual(
    evaluateProductionPilotEntitlement(context, null, new Date("2026-07-15T12:00:00Z")),
    { allowed: false, reason: "pilot_entitlement_missing" },
  );
  assert.equal(
    evaluateProductionPilotEntitlement(context, entitlement, new Date("2026-06-30T23:59:59Z")).reason,
    "pilot_entitlement_inactive_interval",
  );
  assert.equal(
    evaluateProductionPilotEntitlement(context, entitlement, new Date("2026-08-01T00:00:00Z")).reason,
    "pilot_entitlement_inactive_interval",
  );
});

test("bypasses billing only for an exact billing-exempt pilot", () => {
  const gate = buildFilingReleaseGates(readyGateInput)
    .find((item) => item.obligation === "aksjonaerregisteroppgaven");

  assert.equal(gate.status, "production_ready");
  assert.ok(!gate.disabledReasons.includes("billing_account_missing"));
  assert.ok(!gate.disabledReasons.some((reason) => reason.startsWith("billing_refund_signoff_")));
  assert.equal(isBillingExemptProductionPilot(entitlement), true);
});

test("never applies the billing exemption to an inexact or non-exempt entitlement", () => {
  const mismatched = buildFilingReleaseGates({
    ...readyGateInput,
    pilotEntitlements: [{ ...entitlement, user_id: "another-owner" }],
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");
  assert.equal(mismatched.status, "production_disabled");
  assert.ok(mismatched.disabledReasons.includes("pilot_entitlement_missing"));
  assert.ok(mismatched.disabledReasons.includes("billing_account_missing"));

  const nonExempt = buildFilingReleaseGates({
    ...readyGateInput,
    pilotEntitlements: [{ ...entitlement, billing_exempt: false }],
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");
  assert.equal(nonExempt.status, "production_disabled");
  assert.ok(nonExempt.disabledReasons.includes("billing_account_missing"));
  assert.ok(nonExempt.disabledReasons.includes("billing_refund_signoff_missing"));
});
