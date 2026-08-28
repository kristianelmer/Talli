import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const controlPlane = readFileSync(
  new URL("../docs/architecture/mass-market-execution-control-plane.md", import.meta.url),
  "utf8",
);
const issue188Requirements = JSON.parse(readFileSync(
  new URL("../architecture/evidence/issues/188/requirements.json", import.meta.url),
  "utf8",
));
const issue140Requirements = JSON.parse(readFileSync(
  new URL("../architecture/evidence/issues/140/requirements.json", import.meta.url),
  "utf8",
));

const route = [
  188, 140, 189, 141, 142, 143, 190, 147, 144, 145, 148, 191, 137, 192, 150,
  151, 146, 152, 153, 193, 149, 194, 155, 156, 157, 195, 199, 154,
];
const parallelAndClearance = [196, 197, 198];
const signoffs = [
  "architecture_migration_release",
  "seller_terms_pricing",
  "privacy_dpa_subprocessors",
  "accounting_system_saf_t_archive",
  "supported_boundary_validation",
  "rf1086_authority",
  "company_tax_authority",
  "annual_accounts_authority",
  "security_restore_incident_capacity",
  "accessibility_ux_support",
  "bank_aisp",
  "billing_refund",
  "claims_marketing",
  "founder_unrestricted_go_live",
];

test("the live execution control plane pins the complete route and sole clearance", () => {
  assert.match(
    controlPlane,
    new RegExp(`\`${route.map((issue) => `#${issue}`).join(" → ")}\``),
  );
  for (const issue of [...route, ...parallelAndClearance]) {
    assert.equal(
      controlPlane.split("\n").filter((line) => (
        line.startsWith(`| #${issue} |`) && line.split("|").length === 6
      )).length,
      1,
      `issue #${issue} must have exactly one boundary row`,
    );
  }
  assert.match(controlPlane, /#198 is blocked by both #154 and #197/u);
  assert.match(controlPlane, /only ticket that may record\s+unrestricted launch clearance/u);
  assert.match(controlPlane, /Actual canonical producer\/calculator agreement is mandatory at #199/u);
  assert.match(controlPlane, /archive\/SAF-T and final zero-difference acceptance after #199/u);
});

test("all #179 lanes, signoffs, freshness, and independent controls are explicit", () => {
  for (let lane = 1; lane <= 12; lane += 1) {
    assert.match(controlPlane, new RegExp(`^\\| ${lane} [^|]+\\|`, "mu"));
  }
  for (const signoff of signoffs) {
    assert.match(controlPlane, new RegExp(`\`${signoff}\``));
  }
  assert.match(controlPlane, /Any missing, expired,\s+rejected or conditionally out-of-scope item makes its lane red/u);
  assert.match(controlPlane, /independent controls; none may infer approval from another/u);
  assert.match(controlPlane, /day 21–30 target/u);
  assert.match(controlPlane, /day 60 target/u);
});

test("#188 has a complete executable planned criterion ledger before claim", () => {
  assert.equal(issue188Requirements.issue, "#188");
  assert.equal(issue188Requirements.criteria.length, 7);
  assert.equal(issue188Requirements.entryBlockers[0].observedState, "CLOSED");
  assert.deepEqual(
    issue188Requirements.criteria.map(({ id }) => id),
    Array.from({ length: 7 }, (_, index) => `GH-188-A${index + 1}`),
  );
  for (const criterion of issue188Requirements.criteria) {
    assert.ok(criterion.requirement.length > 0, `${criterion.id} has no requirement`);
    assert.ok(criterion.expectedResult.length > 0, `${criterion.id} has no expected result`);
    assert.ok(criterion.sources.length > 0, `${criterion.id} has no source/version`);
    assert.ok(
      criterion.sources.every((source) => source.version && (source.url || source.path || source.status)),
      `${criterion.id} has an unpinned source descriptor`,
    );
    assert.ok(criterion.plannedEvidence.length > 0, `${criterion.id} has no planned evidence`);
    assert.ok(
      criterion.plannedEvidence.every((evidence) => evidence.path && evidence.command),
      `${criterion.id} has an incomplete evidence mapping`,
    );
  }
  const gateCommands = issue188Requirements.criteria.at(-1).plannedEvidence
    .filter(({ command }) => command.startsWith("npm run gate:customer-ready"))
    .map(({ command }) => command);
  assert.deepEqual(gateCommands, [
    "npm run gate:customer-ready",
    "npm run gate:customer-ready -- --previous <R1>",
  ]);
});

test("#140 has a complete executable planned criterion ledger before product edits", () => {
  assert.equal(issue140Requirements.issue, "#140");
  assert.equal(issue140Requirements.criteria.length, 6);
  assert.deepEqual(
    issue140Requirements.entryBlockers.map(({ issue, observedState }) => [issue, observedState]),
    [["#188", "CLOSED"], ["#139", "CLOSED"]],
  );
  assert.deepEqual(
    issue140Requirements.criteria.map(({ id }) => id),
    Array.from({ length: 6 }, (_, index) => `GH-140-A${index + 1}`),
  );
  for (const criterion of issue140Requirements.criteria) {
    assert.ok(criterion.requirement.length > 0, `${criterion.id} has no requirement`);
    assert.ok(criterion.expectedResult.length > 0, `${criterion.id} has no expected result`);
    assert.ok(criterion.sources.length > 0, `${criterion.id} has no source/version`);
    assert.ok(
      criterion.sources.every((source) => source.version && (source.url || source.path)),
      `${criterion.id} has an unpinned source descriptor`,
    );
    assert.ok(criterion.plannedEvidence.length > 0, `${criterion.id} has no planned evidence`);
    assert.ok(
      criterion.plannedEvidence.every((evidence) => evidence.path && evidence.command),
      `${criterion.id} has an incomplete evidence mapping`,
    );
  }
});

test("the control plane blocks premature banking, validation, spend, and external effects", () => {
  assert.match(controlPlane, /open #188 route-blocks any #140 claim or banking migration/u);
  assert.match(controlPlane, /#197[^\n]+Claim only after #196 closes/u);
  assert.match(controlPlane, /provider, best estimate, one-time\/recurring\/usage basis\s+and a free\/cheaper alternative/u);
  assert.match(controlPlane, /Unknown payment, filing or provider effects are reconciled/u);
  assert.match(controlPlane, /seven\s+consecutive-day observation window/u);
});
