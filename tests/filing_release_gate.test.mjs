import assert from "node:assert/strict";
import test from "node:test";

import { buildFilingReleaseGates } from "../app/lib/filing-release-gate.ts";

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

const readyLaunchSignoffs = [
  { key: "rf1086_authority", status: "approved", reviewer: "RF reviewer", reviewedAt: "2026-06-17T09:00:00.000Z", evidenceLink: "https://evidence.example/rf1086", decision: "Approved RF-1086 production gate." },
  { key: "tax_return_authority", status: "approved", reviewer: "Tax reviewer", reviewedAt: "2026-06-17T09:00:00.000Z", evidenceLink: "https://evidence.example/tax", decision: "Approved tax return production gate." },
  { key: "annual_accounts_authority", status: "approved", reviewer: "RR reviewer", reviewedAt: "2026-06-17T09:00:00.000Z", evidenceLink: "https://evidence.example/rr", decision: "Approved annual accounts production gate." },
];

const readyAdapterCapabilities = {
  aksjonaerregisteroppgaven: { productionImplemented: true, productionEnabled: true },
  skattemelding: { productionImplemented: true, productionEnabled: true },
  aarsregnskap: { productionImplemented: true, productionEnabled: true },
};

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
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
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
  assert.equal(annual.status, "production_ready");
});

test("marks production ready only when every release gate passes", () => {
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
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
    },
    launchSignoffs: readyLaunchSignoffs,
    adapterCapabilities: readyAdapterCapabilities,
    now: new Date("2026-06-17T10:00:00.000Z"),
  });

  assert.ok(gates.every((gate) => gate.status === "production_ready"));
  assert.ok(gates.every((gate) => gate.disabledReasons.length === 0));
  assert.match(gates[0].publicCopyRestriction, /produksjonsklar/);
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
      securityReviewApproved: true,
      productionCredentialsEnabled: true,
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
