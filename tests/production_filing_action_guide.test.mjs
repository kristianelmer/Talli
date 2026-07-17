import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const checklist = readFileSync(
  new URL("../docs/launch/production-filing-checklist.md", import.meta.url),
  "utf8",
);
const guide = readFileSync(
  new URL("../docs/launch/production-filing-action-guide.md", import.meta.url),
  "utf8",
);

const requiredStageSlugs = [
  "approve-the-legal-pack",
  "verify-hosted-tenant-isolation-and-private-storage",
  "complete-a-fresh-production-backup-and-restore-rehearsal",
  "verify-monitoring-incident-response-and-rollback",
  "select-an-eligible-pilot-company",
  "capture-business-terms-and-dpa-acceptance",
  "compare-talli-and-fiken",
  "verify-the-production-systemregister-callback",
  "complete-systembruker-approval-and-preflight",
  "record-the-required-launch-signoffs",
  "create-the-pilot-entitlement-and-billing-path",
  "capture-the-owners-final-approval",
  "run-the-production-filing-window",
  "save-the-final-result-and-closeout-evidence",
  "make-the-post-pilot-decision",
];

test("checklist links to every ordered action-guide stage", () => {
  for (const slug of requiredStageSlugs) {
    assert.match(checklist, new RegExp(`production-filing-action-guide\\.md#${slug}`));
    assert.match(guide, new RegExp(`id=\\"${slug}\\"`));
  }
});

test("guide keeps every runtime signoff and case-specific release gate", () => {
  for (const key of [
    "launch_legal_name_public_copy",
    "legal_policy_pack",
    "security_restore",
    "billing_refund",
    "support_rollback",
    "rf1086_authority",
    "founder_production_go_live",
    "rf1086_no_activity_v1",
    "billing_exempt=true",
  ]) {
    assert.match(guide, new RegExp(key));
  }
});

test("guide preserves switch, evidence, and unknown-outcome stop rules", () => {
  assert.match(guide, /TALLI_AUTHORITY_OPS_ENABLED=false/);
  assert.match(guide, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
  assert.match(guide, /Do not use a real filing as a connection test\./i);
  assert.match(guide, /Do not send again\./i);
  assert.match(guide, /transport reference is not final acceptance/i);
  assert.match(guide, /Do not save tokens, private keys, raw personal data, or raw filing XML/i);
});

test("guide states its narrow scope and plain-language purpose", () => {
  assert.match(guide, /one controlled RF-1086 production pilot/i);
  assert.match(guide, /Use this guide one stage at a time/i);
  assert.match(guide, /Stop here\. Do not enable production filing\./i);
  assert.doesNotMatch(guide, /production filing is now generally available/i);
});
