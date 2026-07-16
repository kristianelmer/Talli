import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildFilingReleaseGates } from "../app/lib/filing-release-gate.ts";

const liveReleaseGate = readFileSync(
  new URL("../docs/filing/rf1086-live-release-gate.md", import.meta.url),
  "utf8",
);
const systemregisterEvidence = readFileSync(
  new URL("../docs/launch/evidence/production-systemregister-2026-07-16.md", import.meta.url),
  "utf8",
);

const readyBilling = {
  company_id: "company-id",
  pricing_plan: "founder",
  monthly_nok: 29,
  filing_package_nok: 299,
  founder_cohort_number: 1,
  subscription_active: true,
  filing_package_paid: true,
  supported_case: true,
  refund_eligible: false,
  refund_completed: false,
  no_charge_reason: null,
};

const readyPermissions = [
  { obligation: "aksjonaerregisteroppgaven", confirmed_at: "2026-01-01T00:00:00.000Z", production_enabled: true },
  { obligation: "skattemelding", confirmed_at: "2026-01-01T00:00:00.000Z", production_enabled: true },
  { obligation: "aarsregnskap", confirmed_at: "2026-01-01T00:00:00.000Z", production_enabled: true },
];

const readyAuthorityEvidence = [
  { obligation: "aksjonaerregisteroppgaven", status: "accepted", receipt_reference: "rf1086-receipt", archive_reference: "rf1086-archive", recorded_at: "2026-06-17T09:00:00.000Z" },
  { obligation: "skattemelding", status: "accepted", receipt_reference: "tax-receipt", archive_reference: "tax-archive", recorded_at: "2026-06-17T09:00:00.000Z" },
  { obligation: "aarsregnskap", status: "accepted", receipt_reference: "rr-receipt", archive_reference: "rr-archive", recorded_at: "2026-06-17T09:00:00.000Z" },
];

function approvedSignoff(key, reviewedAt = "2026-06-17T09:00:00.000Z") {
  return {
    key,
    status: "approved",
    reviewer: `${key} reviewer`,
    reviewedAt,
    evidenceLink: `https://evidence.example/${key}`,
    decision: `${key} approved for production gate.`,
  };
}

const commonProductionSignoffKeys = [
  "launch_legal_name_public_copy",
  "legal_policy_pack",
  "security_restore",
  "billing_refund",
  "support_rollback",
  "founder_production_go_live",
];

const readyLaunchSignoffs = [
  ...commonProductionSignoffKeys.map((key) => approvedSignoff(key)),
  approvedSignoff("rf1086_authority"),
  approvedSignoff("tax_return_authority"),
  approvedSignoff("annual_accounts_authority"),
];

const readyAdapterCapabilities = {
  aksjonaerregisteroppgaven: { productionImplemented: true, productionEnabled: true },
  skattemelding: { productionImplemented: true, productionEnabled: true },
  aarsregnskap: { productionImplemented: true, productionEnabled: true },
};

const rfPilotContext = {
  companyId: "company-id",
  userId: "owner",
  incomeYear: 2025,
  obligation: "aksjonaerregisteroppgaven",
  caseProfile: "rf1086_no_activity_v1",
};

const rfPilotEntitlement = {
  id: "rf-pilot",
  company_id: "company-id",
  user_id: "owner",
  income_year: 2025,
  obligation: "aksjonaerregisteroppgaven",
  case_profile: "rf1086_no_activity_v1",
  status: "active",
  billing_exempt: false,
  starts_at: "2026-06-01T00:00:00.000Z",
  expires_at: "2026-07-01T00:00:00.000Z",
};

test("release evidence keeps authority and filing switches off after local browser proof", () => {
  for (const document of [liveReleaseGate, systemregisterEvidence]) {
    assert.match(document, /TALLI_AUTHORITY_OPS_ENABLED=false/);
    assert.match(document, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
    assert.match(document, /callback_already_verified|callback_updated_and_verified/);
  }
  assert.match(liveReleaseGate, /mocked\/local flow/i);
  assert.match(liveReleaseGate, /separately authorize any production filing/i);
  assert.match(liveReleaseGate, /local mock[^\n]*not[^\n]*production callback/i);
  assert.match(
    systemregisterEvidence,
    /did not make a live request, change Systemregister, enable a switch, grant an entitlement, or submit a filing/i,
  );
});

test("keeps all production filing gates disabled without authority, billing, step-up, and human review", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: [],
    authorityTestRuns: [],
    billingAccount: null,
    filingReadyByObligation: {},
    stepUpContext: { actorId: "owner", mfaVerifiedAt: null },
    launchSignoffs: [],
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  assert.equal(gates.length, 3);
  assert.ok(gates.every((gate) => gate.status === "production_disabled"));
  assert.ok(gates.every((gate) => gate.disabledReasons.includes("missing_authority_confirmation")));
  assert.ok(gates.every((gate) => gate.disabledReasons.includes("billing_account_missing")));
  assert.ok(gates.every((gate) => gate.disabledReasons.includes("test_evidence_missing")));
  assert.ok(gates.every((gate) => gate.disabledReasons.some((reason) => reason.endsWith("_signoff_missing"))));
  assert.match(gates[0].publicCopyRestriction, /forhåndsvisning\/simulering/);
});

test("blocks production when authority evidence or filing-specific signoff is missing", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: readyPermissions,
    authorityTestRuns: readyAuthorityEvidence.filter((item) => item.obligation !== "skattemelding"),
    billingAccount: readyBilling,
    filingReadyByObligation: {
      aksjonaerregisteroppgaven: true,
      skattemelding: true,
      aarsregnskap: true,
    },
    stepUpContext: {
      actorId: "owner",
      mfaVerifiedAt: "2026-06-17T09:55:00.000Z",
    },
    launchSignoffs: readyLaunchSignoffs.filter((item) => item.key !== "rf1086_authority"),
    adapterCapabilities: readyAdapterCapabilities,
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  const rf1086 = gates.find((gate) => gate.obligation === "aksjonaerregisteroppgaven");
  const tax = gates.find((gate) => gate.obligation === "skattemelding");
  const annual = gates.find((gate) => gate.obligation === "aarsregnskap");

  assert.equal(rf1086.status, "production_disabled");
  assert.ok(rf1086.disabledReasons.includes("rf1086_authority_signoff_missing"));
  assert.equal(tax.status, "production_disabled");
  assert.ok(tax.disabledReasons.includes("test_evidence_missing"));
  assert.equal(annual.status, "production_disabled");
  assert.ok(annual.disabledReasons.includes("pilot_entitlement_context_missing"));
});

test("marks only the exactly entitled RF obligation production ready when every release gate passes", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: readyPermissions,
    authorityTestRuns: readyAuthorityEvidence,
    billingAccount: readyBilling,
    filingReadyByObligation: {
      aksjonaerregisteroppgaven: true,
      skattemelding: true,
      aarsregnskap: true,
    },
    stepUpContext: {
      actorId: "owner",
      mfaVerifiedAt: "2026-06-17T09:55:00.000Z",
    },
    launchSignoffs: readyLaunchSignoffs,
    adapterCapabilities: readyAdapterCapabilities,
    pilotContext: rfPilotContext,
    pilotEntitlements: [rfPilotEntitlement],
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  const rf1086 = gates.find((gate) => gate.obligation === "aksjonaerregisteroppgaven");
  assert.equal(rf1086.status, "production_ready");
  assert.deepEqual(rf1086.disabledReasons, []);
  assert.match(rf1086.publicCopyRestriction, /produksjonsklar/);
  assert.ok(
    gates.filter((gate) => gate.obligation !== "aksjonaerregisteroppgaven")
      .every((gate) => gate.status === "production_disabled"),
  );
});

test("cannot report production ready when a live adapter is unimplemented or disabled", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: readyPermissions,
    authorityTestRuns: readyAuthorityEvidence,
    billingAccount: readyBilling,
    filingReadyByObligation: {
      aksjonaerregisteroppgaven: true,
      skattemelding: true,
      aarsregnskap: true,
    },
    stepUpContext: {
      actorId: "owner",
      mfaVerifiedAt: "2026-06-17T09:55:00.000Z",
    },
    launchSignoffs: readyLaunchSignoffs,
    adapterCapabilities: {
      ...readyAdapterCapabilities,
      skattemelding: { productionImplemented: false, productionEnabled: false },
    },
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  const tax = gates.find((gate) => gate.obligation === "skattemelding");
  assert.equal(tax.status, "production_disabled");
  assert.ok(tax.disabledReasons.includes("production_adapter_unimplemented"));
});

test("fresh AAL2 and enabled adapters cannot replace final founder confirmation", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: readyPermissions,
    authorityTestRuns: readyAuthorityEvidence,
    billingAccount: readyBilling,
    filingReadyByObligation: {
      aksjonaerregisteroppgaven: true,
      skattemelding: true,
      aarsregnskap: true,
    },
    stepUpContext: {
      actorId: "owner",
      mfaVerifiedAt: "2026-06-17T09:55:00.000Z",
    },
    launchSignoffs: readyLaunchSignoffs.filter((item) => item.key !== "founder_production_go_live"),
    adapterCapabilities: readyAdapterCapabilities,
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  assert.ok(gates.every((gate) => gate.status === "production_disabled"));
  assert.ok(
    gates.every((gate) =>
      gate.disabledReasons.includes("founder_production_go_live_signoff_missing"),
    ),
  );
});

test("a stale restore rehearsal blocks every production filing", () => {
  const gates = buildFilingReleaseGates({
    authorityPermissions: readyPermissions,
    authorityTestRuns: readyAuthorityEvidence,
    billingAccount: readyBilling,
    filingReadyByObligation: {
      aksjonaerregisteroppgaven: true,
      skattemelding: true,
      aarsregnskap: true,
    },
    stepUpContext: {
      actorId: "owner",
      mfaVerifiedAt: "2026-06-17T09:55:00.000Z",
    },
    launchSignoffs: readyLaunchSignoffs.map((item) =>
      item.key === "security_restore"
        ? { ...item, reviewedAt: "2026-04-01T09:00:00.000Z" }
        : item,
    ),
    adapterCapabilities: readyAdapterCapabilities,
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  assert.ok(gates.every((gate) => gate.status === "production_disabled"));
  assert.ok(
    gates.every((gate) => gate.disabledReasons.includes("security_restore_signoff_stale")),
  );
});
