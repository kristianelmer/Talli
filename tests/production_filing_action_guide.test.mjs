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
  const link = `production-filing-action-guide.md#${slug}`;
  const matchingRows = (checklist.match(/^\|[^\r\n]*\|$/gm) ?? []).filter((row) =>
    row.includes(link),
  );

  assert.equal(matchingRows.length, 1, `expected one checklist row for ${slug}`);
  const row = matchingRows[0];
  const cells = row.split("|");
  const linkCellIndex = cells.findIndex((cell) => cell.includes(link));

  assert.ok(linkCellIndex > 1, `missing fields before ${slug} link`);
  assert.ok(linkCellIndex < cells.length - 2, `missing fields after ${slug} link`);
  assert.doesNotMatch(row, /[\r\n]/, `multiple checklist rows found for ${slug}`);
  return row;
}

function guideStage(slug) {
  return stageSection(guide, slug, (stageSlug) => `id="${stageSlug}"`);
}

function exactActions(stage) {
  const startMarker = "### Exact actions\n\n";
  const endMarker = "\n### Evidence to retain";
  const start = stage.indexOf(startMarker);
  const end = stage.indexOf(endMarker, start);

  assert.notEqual(start, -1, "missing Exact actions section");
  assert.notEqual(end, -1, "missing Evidence to retain section");
  return stage.slice(start + startMarker.length, end);
}

function assertStageIncludes(slug, patterns) {
  for (const documentStage of [checklistStage(slug), guideStage(slug)]) {
    for (const pattern of patterns) {
      assert.match(documentStage, pattern, `${slug} must include ${pattern}`);
    }
  }
}

function assertStageIncludesExact(slug, sentences) {
  for (const documentStage of [checklistStage(slug), guideStage(slug)]) {
    for (const sentence of sentences) {
      assert.ok(documentStage.includes(sentence), `${slug} must include "${sentence}"`);
    }
  }
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function contradictoryGatePattern(subject) {
  const exactSubject = escapeRegExp(subject);
  const referencedSubject = `(?:an?\\s+|the\\s+)?${exactSubject}`;

  return new RegExp(
    [
      `${referencedSubject}\\s+(?:is|are)\\s+(?:optional|not\\s+(?:required|mandatory))`,
      `${referencedSubject}\\s+(?:isn't|isn’t|aren't|aren’t)\\s+(?:required|mandatory)`,
      `${referencedSubject}\\s+(?:need\\s+not|needn't|needn’t)\\b`,
      `(?:(?:does|do)\\s+not|never)\\s+requires?\\s+${referencedSubject}`,
      `requires?\\s+no\\s+${referencedSubject}`,
      `${referencedSubject}\\s+(?:may|can)\\s+be\\s+bypassed`,
    ].join("|"),
    "i",
  );
}

const mandatoryGates = [
  {
    slug: "complete-systembruker-approval-and-preflight",
    sentence: "Production authority permission is required.",
    subject: "production authority permission",
  },
  {
    slug: "complete-systembruker-approval-and-preflight",
    sentence: "Accepted authority-test evidence is required.",
    subject: "accepted authority-test evidence",
  },
  {
    slug: "create-the-pilot-entitlement-and-billing-path",
    sentence: "An active exact pilot entitlement is required.",
    subject: "active exact pilot entitlement",
  },
  {
    slug: "create-the-pilot-entitlement-and-billing-path",
    sentence: "Billing or an exact billing exemption is required.",
    subject: "billing or an exact billing exemption",
  },
  {
    slug: "capture-the-owners-final-approval",
    sentence: "Fresh AAL2 is required.",
    subject: "fresh AAL2",
  },
  {
    slug: "capture-the-owners-final-approval",
    sentence: "Filing readiness is required.",
    subject: "filing readiness",
  },
  {
    slug: "run-the-production-filing-window",
    sentence: "The production adapter must be implemented and enabled.",
    subject: "production adapter",
  },
];

const concreteOperatorVerbs = new Set([
  "Ask", "Build", "Check", "Choose", "Compare", "Confirm", "Create", "Decide",
  "Defer", "Deploy", "Do", "Enable", "Explain", "Export", "Generate", "Keep",
  "Leave", "Link", "List", "Name", "Open", "Perform", "Poll", "Prepare", "Read",
  "Reconcile", "Record", "Redeploy", "Rehearse", "Repeat", "Require", "Resolve",
  "Restore", "Review", "Run", "Save", "Select", "Set", "Show", "Sign", "Start",
  "Stop", "Test", "Treat", "Try", "Validate", "Verify", "Watch",
]);

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
  assertStageIncludesExact("complete-systembruker-approval-and-preflight", [
    "Production authority permission is required.",
    "Accepted authority-test evidence is required.",
  ]);
  assertStageIncludesExact("create-the-pilot-entitlement-and-billing-path", [
    "An active exact pilot entitlement is required.",
    "Billing or an exact billing exemption is required.",
  ]);
  assertStageIncludes("create-the-pilot-entitlement-and-billing-path", [/billing_exempt=true/]);
  assertStageIncludesExact("capture-the-owners-final-approval", [
    "Fresh AAL2 is required.",
    "Filing readiness is required.",
  ]);
  assertStageIncludesExact("run-the-production-filing-window", [
    "The production adapter must be implemented and enabled.",
  ]);
});

test("mandatory gates stay affirmative without localized contradictions", () => {
  for (const { slug, sentence, subject } of mandatoryGates) {
    for (const documentStage of [checklistStage(slug), guideStage(slug)]) {
      assert.ok(documentStage.includes(sentence), `${slug} must include "${sentence}"`);
      assert.doesNotMatch(
        documentStage,
        contradictoryGatePattern(subject),
        `${slug} contradicts its ${subject} gate`,
      );
    }
  }
});

test("mandatory-gate contradiction matcher rejects bypasses but allows fail-closed language", () => {
  const pattern = contradictoryGatePattern("fresh AAL2");
  const contradictions = [
    "Fresh AAL2 is optional.",
    "Fresh AAL2 is not required.",
    "Fresh AAL2 is not mandatory.",
    "Fresh AAL2 isn't required.",
    "Fresh AAL2 isn’t mandatory.",
    "Fresh AAL2 aren't required.",
    "Fresh AAL2 aren’t mandatory.",
    "Fresh AAL2 need not be current.",
    "Fresh AAL2 needn't be current.",
    "Fresh AAL2 needn’t be current.",
    "This flow does not require fresh AAL2.",
    "This flow never requires fresh AAL2.",
    "The release requires no fresh AAL2.",
    "Fresh AAL2 may be bypassed.",
    "Fresh AAL2 can be bypassed.",
  ];
  const safeLanguage = [
    "Fresh AAL2 is required.",
    "No bypass is allowed.",
    "Never bypass fresh AAL2.",
    "The release requires fresh AAL2.",
  ];

  for (const example of contradictions) assert.match(example, pattern);
  for (const example of safeLanguage) assert.doesNotMatch(example, pattern);
});

test("every guide stage uses only numbered checkbox action entries", () => {
  for (const slug of requiredStageSlugs) {
    const lines = exactActions(guideStage(slug)).split("\n");
    const actionLines = lines.filter((line) => /^\d+\. \[ \] \S/.test(line));
    let hasPrecedingCheckbox = false;

    assert.ok(actionLines.length > 0, `${slug} must include at least one action`);
    for (const line of lines) {
      if (!line.trim()) continue;
      if (/^#### \S/.test(line)) {
        hasPrecedingCheckbox = false;
        continue;
      }
      if (/^\d+\. \[ \] \S/.test(line)) {
        const firstWord = line.match(/^\d+\. \[ \] (\S+)/)?.[1];
        assert.ok(
          concreteOperatorVerbs.has(firstWord),
          `${slug} action must start with a concrete operator verb: ${line}`,
        );
        hasPrecedingCheckbox = true;
        continue;
      }

      assert.match(line, /^\s{2,}\S/, `${slug} has an uncheckable action: ${line}`);
      assert.ok(
        hasPrecedingCheckbox,
        `${slug} has a continuation without a preceding checkbox: ${line}`,
      );
    }
  }
});

test("mandatory gate declarations stay outside exact action checkboxes", () => {
  for (const { slug, sentence } of mandatoryGates) {
    assert.ok(guideStage(slug).includes(sentence), `${slug} must retain "${sentence}"`);
    assert.ok(
      !exactActions(guideStage(slug)).includes(sentence),
      `${slug} must not use a passive gate declaration as an action: ${sentence}`,
    );
  }
});

test("founder go-live approval stays pending until the complete evidence set exists", () => {
  const signoffStage = guideStage("record-the-required-launch-signoffs");
  const filingStage = guideStage("run-the-production-filing-window");

  assert.match(signoffStage, /founder_production_go_live[^\n]*pending/i);
  assert.match(signoffStage, /cannot be approved yet/i);
  assert.match(checklistStage("record-the-required-launch-signoffs"), /pending/i);
  assert.match(
    filingStage,
    /record or reconfirm `founder_production_go_live`[^\n]*complete evidence set/i,
  );
  assert.match(checklistStage("run-the-production-filing-window"), /record or reconfirm/i);
  assert.ok(filingStage.indexOf("founder_production_go_live") < filingStage.indexOf("TALLI_RF1086_PRODUCTION_ENABLED=true"));
});

test("production credential readiness is verified without exposing the key", () => {
  const filingStage = guideStage("run-the-production-filing-window");
  const requiredCredentialEvidence = [
    /Maskinporten client\/key fingerprint/i,
    /rotation owner/i,
    /revocation path/i,
    /secret-store readiness/i,
    /exact scope and permission/i,
    /required production configuration is present/i,
    /Never copy the key\./i,
  ];

  for (const pattern of requiredCredentialEvidence) {
    assert.match(filingStage, pattern);
    assert.match(checklistStage("run-the-production-filing-window"), pattern);
  }
});

test("unknown outcome shutdown precedes read-only reconciliation", () => {
  const actions = exactActions(guideStage("save-the-final-result-and-closeout-evidence"));
  const unknownActions = actions.slice(actions.indexOf("#### If the outcome is unknown"));
  const orderedSentences = [
    "Stop the filing window.",
    "Set both production switches to false.",
    "Do not send again.",
    "Keep the idempotency record and journal.",
    "Redeploy the approved Git SHA.",
    "Verify both deployed values are false.",
    "Reconcile the result through read-only authority calls and support.",
  ];
  let previous = -1;

  for (const sentence of orderedSentences) {
    const index = unknownActions.indexOf(sentence);
    assert.ok(index > previous, `unknown outcome action is missing or reordered: ${sentence}`);
    assert.match(
      unknownActions.slice(
        unknownActions.lastIndexOf("\n", index) + 1,
        unknownActions.indexOf("\n", index),
      ),
      /^\d+\. \[ \] /,
    );
    previous = index;
  }
  assert.equal(unknownActions.match(/Set both production switches to false\./g)?.length, 1);
});

test("legal-pack approval stage says professional approval is pending", () => {
  assert.match(
    guideStage("approve-the-legal-pack"),
    /legal pack is pending professional approval/i,
  );
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
