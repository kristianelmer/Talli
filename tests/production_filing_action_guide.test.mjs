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

function extractSlugs(document, pattern) {
  return [...document.matchAll(pattern)].map((match) => match[1]);
}

function stageSection(document, slug, marker) {
  const stageIndex = requiredStageSlugs.indexOf(slug);
  const start = document.indexOf(marker(slug));
  const nextSlug = requiredStageSlugs[stageIndex + 1];
  const end = nextSlug ? document.indexOf(marker(nextSlug), start) : document.length;

  assert.notEqual(start, -1, `missing stage ${slug}`);
  assert.notEqual(end, -1, `missing stage after ${slug}`);
  return document.slice(start, end);
}

function checklistStage(slug) {
  return stageSection(
    checklist,
    slug,
    (stageSlug) => `production-filing-action-guide.md#${stageSlug}`,
  );
}

function guideStage(slug) {
  return stageSection(guide, slug, (stageSlug) => `id="${stageSlug}"`);
}

function assertStageIncludes(slug, patterns) {
  for (const documentStage of [checklistStage(slug), guideStage(slug)]) {
    for (const pattern of patterns) {
      assert.match(documentStage, pattern, `${slug} must include ${pattern}`);
    }
  }
}

test("checklist and guide keep the exact ordered stage sequence", () => {
  const checklistSlugs = extractSlugs(
    checklist,
    /production-filing-action-guide\.md#([a-z0-9-]+)/g,
  );
  const guideSlugs = extractSlugs(guide, /^<a id="([a-z0-9-]+)"><\/a>$/gm);

  assert.deepEqual(checklistSlugs, requiredStageSlugs);
  assert.deepEqual(guideSlugs, requiredStageSlugs);
});

test("both documents keep runtime signoffs in the signoff stage", () => {
  assertStageIncludes("record-the-required-launch-signoffs", [
    "launch_legal_name_public_copy",
    "legal_policy_pack",
    "security_restore",
    "billing_refund",
    "support_rollback",
    "rf1086_authority",
    "founder_production_go_live",
  ].map((key) => new RegExp(key)));
});

test("both documents keep case-specific gates in their operating stages", () => {
  assertStageIncludes("select-an-eligible-pilot-company", [/rf1086_no_activity_v1/]);
  assertStageIncludes("complete-systembruker-approval-and-preflight", [
    /production authority permission/i,
    /accepted authority-test evidence/i,
  ]);
  assertStageIncludes("create-the-pilot-entitlement-and-billing-path", [
    /exact pilot entitlement/i,
    /billing_exempt=true/,
    /billing\/refund proof|billing or billing exemption/i,
  ]);
  assertStageIncludes("capture-the-owners-final-approval", [
    /fresh AAL2/i,
    /filing readiness/i,
  ]);
  assertStageIncludes("run-the-production-filing-window", [
    /implemented and enabled production adapter/i,
  ]);
});

test("guide preserves switch, evidence, and unknown-outcome stop rules", () => {
  const callbackStage = guideStage("verify-the-production-systemregister-callback");
  const closeoutStage = guideStage("save-the-final-result-and-closeout-evidence");

  assert.match(callbackStage, /TALLI_AUTHORITY_OPS_ENABLED=false/);
  assert.match(callbackStage, /Do not use a real filing as a connection test\./i);
  assert.match(closeoutStage, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
  assert.match(closeoutStage, /Do not send again\./i);
  assert.match(closeoutStage, /transport reference is not final acceptance/i);
  assert.match(guide, /Do not save tokens, private keys, raw personal data, or raw filing XML/i);
});

test("both documents state the narrow scope and forbid adjacent filing scope", () => {
  const forbiddenScope =
    /does not unlock public self-service filing, corrections, expanded RF-1086 profiles, annual accounts, or company tax returns\./i;

  assert.match(checklist, /one controlled RF-1086 production pilot/i);
  assert.match(guide, /one controlled RF-1086 production pilot/i);
  assert.match(checklist, forbiddenScope);
  assert.match(guide, forbiddenScope);
  assert.match(guide, /Use this guide one stage at a time/i);
  assert.match(guide, /Stop here\. Do not enable production filing\./i);
  assert.doesNotMatch(checklist, /production filing is now generally available/i);
  assert.doesNotMatch(guide, /production filing is now generally available/i);
});
