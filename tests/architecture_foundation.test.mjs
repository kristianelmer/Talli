import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  checkArchitecture,
  legacyOperationProof,
  validateCompatibilityRegistry,
} from "../scripts/check-architecture.mjs";

const repositoryRoot = new URL("..", import.meta.url);

const compatibilityScope = Object.freeze({
  path: "apps/web/app/actions.ts",
  rule: "direct-web-business-persistence",
  resource: "table:companies",
  operation: "legacyOperation",
});

function legacyFacade({
  id = "compat-company-access",
  capability = "company_access",
  removalIssue = "#138",
  scopes = [compatibilityScope],
} = {}) {
  return {
    id,
    kind: "legacy-facade",
    capability,
    owner: "web:legacy-runtime",
    creationIssue: "#135",
    decisionIssue: "#185",
    removalIssue,
    baselineRevision: "d331ee2717d1eeacef0d81db42b9d4fb5848b408",
    canonicalImplementation: `web:legacy-runtime:${capability}`,
    approvedBy: "Kristian Elmer",
    approvedAt: "2026-08-26T10:56:36Z",
    removalCondition: `Remove the ${capability} facade before ${removalIssue} exits.`,
    scopes,
  };
}

function activeStageDebt({
  id = "compat-company-access-active-stage-debt",
  capability = "company_access",
  creationIssue = "#138",
  removalIssue = "#138",
  successorCapability = "ledger",
  scopes = [compatibilityScope],
  approvedAt = "2026-08-26T10:56:36Z",
  expiresAt = "2026-09-09T10:56:36Z",
} = {}) {
  return {
    id,
    kind: "active-stage-debt",
    capability,
    owner: "backend:company_access",
    creationIssue,
    removalIssue,
    successorCapability,
    scopes,
    approvedBy: "Kristian Elmer",
    approvedAt,
    releaseLimit: "next-stable-customer-ready-release",
    expiresAt,
    residualRisk: "The active migration stage still has one bounded direct persistence seam.",
    rollback: "Remove the record and revert to the last green active-stage implementation.",
    removalCondition: `Remove the ${capability} debt before ${successorCapability} exits.`,
  };
}

function compatibilityFixture({
  records = [legacyFacade()],
  currentCapability = "company_access",
  currentIssue = "#138",
  status = "active",
  exitedCapabilities,
  foundationStatus = "complete",
} = {}) {
  const order = [
    { capability: "company_access", removalIssues: ["#138"] },
    { capability: "ledger", removalIssues: ["#139"] },
    { capability: "banking", removalIssues: ["#140"] },
  ];
  const currentIndex = order.findIndex((stage) => stage.capability === currentCapability);
  const exited = exitedCapabilities ?? order.slice(0, currentIndex).map((stage) => stage.capability);
  return {
    schemaVersion: "2.0",
    baseline: {
      path: "architecture/compatibility-baseline.json",
      digest: "TEST_BASELINE_DIGEST",
    },
    migration: {
      foundationRecovery: {
        issue: "#186",
        status: foundationStatus,
        gates: foundationStatus === "complete"
          ? ["a".repeat(40), "b".repeat(40)].map((revision) => ({
            revision,
            evidencePath: `architecture/evidence/customer-ready-gates/${revision}.json`,
            evidenceDigest: `sha256:${revision}${revision.slice(0, 24)}`,
          }))
          : [],
      },
      order,
      currentCapability,
      currentIssue,
      status,
      exitedCapabilities: exited,
      completedStages: exited.map((capability, index) => ({
        capability,
        removalIssues: order.find((stage) => stage.capability === capability).removalIssues,
        gates: [String(index + 1).repeat(40), String(index + 2).repeat(40)].map((revision) => ({
          revision,
          evidencePath: `architecture/evidence/customer-ready-gates/${revision}.json`,
          evidenceDigest: `sha256:${revision}${revision.slice(0, 24)}`,
        })),
      })),
    },
    records,
  };
}

function compatibilityBaseline(records) {
  return {
    schemaVersion: "1.0",
    decisionIssue: "#185",
    sourceRevision: "d331ee2717d1eeacef0d81db42b9d4fb5848b408",
    records: records.map((record) => ({
      id: record.id,
      kind: "legacy-facade",
      capability: record.capability,
      removalIssue: record.removalIssue,
      canonicalImplementation: record.canonicalImplementation,
      scopes: record.scopes,
    })),
  };
}

function writeCompatibilityFixture(root, registry, baseline) {
  const registryPath = join(root, "compatibility.json");
  const baselinePath = join(root, "compatibility-baseline.json");
  writeFileSync(registryPath, JSON.stringify(registry));
  writeFileSync(baselinePath, JSON.stringify(baseline));
  return { registryPath, baselinePath };
}

function canonicalDigest(value) {
  const stableValue = (candidate) => (
    Array.isArray(candidate)
      ? candidate.map(stableValue)
      : candidate && typeof candidate === "object"
        ? Object.fromEntries(Object.keys(candidate).sort().map((key) => [key, stableValue(candidate[key])]))
        : candidate
  );
  return `sha256:${createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex")}`;
}

function git(root, args, date) {
  return execFileSync("git", ["-C", root, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      ...(date ? { GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date } : {}),
    },
  }).trim();
}

function initializeFixtureRepository(root, date = "2026-07-30T00:00:00Z") {
  git(root, ["init", "--quiet"]);
  git(root, ["config", "user.name", "Architecture Test"]);
  git(root, ["config", "user.email", "architecture@example.invalid"]);
  git(root, ["add", "."]);
  git(root, ["commit", "--quiet", "-m", "fixture baseline"], date);
}

function tagCustomerReadyRelease(root, id, date) {
  git(root, ["tag", "--annotate", id, "--message", `${id} fixture release`], date);
}

test("architecture manifests, scoped documentation, and dependency evidence agree", () => {
  const result = checkArchitecture({ root: repositoryRoot, writeEvidence: false });

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.evidence.modules, [
    "backend-system:system_boundary",
    "backend:company_access",
    "backend:ledger",
    "backend:shareholder_register_filing",
    "web:company-access",
    "web:ledger",
    "web:public-acquisition",
    "web:system-boundary",
  ]);
  assert.deepEqual(result.evidence.edges, [
    {
      from: "backend-system:company-access-administration",
      imports: ["talli_backend.modules.company_access.public"],
      kind: "workflow",
      to: "backend:company_access",
    },
    {
      from: "backend-system:company-access-context",
      imports: ["talli_backend.modules.company_access.public"],
      kind: "workflow",
      to: "backend:company_access",
    },
    {
      from: "backend-system:company-access-onboarding-and-support",
      imports: ["talli_backend.modules.company_access.public"],
      kind: "workflow",
      to: "backend:company_access",
    },
    {
      from: "backend-system:company-year-eligibility-and-admission",
      imports: ["talli_backend.modules.company_access.public"],
      kind: "workflow",
      to: "backend:company_access",
    },
    {
      from: "backend-system:ledger-posting-and-period-control",
      imports: ["talli_backend.modules.ledger.public"],
      kind: "workflow",
      to: "backend:ledger",
    },
    {
      from: "backend-system:new-year-start",
      imports: ["talli_backend.modules.ledger.public"],
      kind: "workflow",
      to: "backend:ledger",
    },
    {
      from: "backend-system:new-year-start",
      imports: ["talli_backend.modules.shareholder_register_filing.public"],
      kind: "workflow",
      to: "backend:shareholder_register_filing",
    },
    {
      from: "backend-system:system-boundary-tracer",
      imports: ["talli_backend.modules.system_boundary.public"],
      kind: "workflow",
      to: "backend-system:system_boundary",
    },
  ]);
  assert.equal(existsSync(new URL("../architecture/module.schema.json", import.meta.url)), true);
  assert.equal(existsSync(new URL("../architecture/backend-system.schema.json", import.meta.url)), true);
  assert.equal(existsSync(new URL("../architecture/release-state.schema.json", import.meta.url)), true);
});

test("architecture evidence is deterministic and committed output is current", () => {
  const generated = checkArchitecture({ root: repositoryRoot, writeEvidence: false });
  const committed = JSON.parse(
    readFileSync(new URL("../architecture/dependency-evidence.json", import.meta.url), "utf8"),
  );

  assert.deepEqual(committed, generated.evidence);
});

test("legacy facades cannot shrink without current-source deletion proof", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-legacy-facade-"));
  const currentBaselineScopes = [
    compatibilityScope,
    { ...compatibilityScope, resource: "table:company_memberships" },
  ];
  const futureBaselineScopes = [
    { ...compatibilityScope, resource: "table:ledger_entries", operation: "postEntry" },
    { ...compatibilityScope, resource: "table:period_locks", operation: "lockPeriod" },
  ];
  const currentFacade = legacyFacade({ scopes: currentBaselineScopes });
  const futureFacade = legacyFacade({
    id: "compat-ledger",
    capability: "ledger",
    removalIssue: "#139",
    scopes: futureBaselineScopes,
  });
  const baselineRecords = [
    legacyFacade({ scopes: currentBaselineScopes }),
    futureFacade,
  ];
  const registry = compatibilityFixture({ records: [currentFacade, futureFacade] });
  const baseline = compatibilityBaseline(baselineRecords);
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, {
      now: new Date("2026-08-26T12:00:00Z"),
      baselinePath,
      expectedBaselineDigest: "TEST_BASELINE_DIGEST",
    }), []);

    futureFacade.scopes.push({
      ...compatibilityScope,
      resource: "table:new_business_state",
      operation: "newBehavior",
    });
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-08-26T12:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-ledger.*scope is outside the frozen baseline/u,
    );

    futureFacade.scopes = [futureBaselineScopes[0]];
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-08-26T12:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-ledger.*removed frozen scope lacks current-source deletion proof/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("resource-owner deletion-only shrink may change only the affected operation", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-legacy-deletion-proof-"));
  const retiredSource = 'export function retiredOperation() { client.from("companies"); }\n';
  const sharedPath = "apps/web/app/ledger.ts";
  const sharedBaselineSource = [
    "export function postEntry() {",
    '  client.from("companies");',
    '  client.from("ledger_entries");',
    "}",
    "",
  ].join("\n");
  const unrelatedPath = "apps/web/app/banking.ts";
  const unrelatedBaselineSource = 'export function importTransactions() { client.from("bank_transactions"); }\n';
  const laterPath = "apps/web/app/banking-context.ts";
  const laterBaselineSource = [
    "export function importWithCompanyContext() {",
    '  client.from("companies");',
    '  client.from("bank_transactions");',
    "}",
    "",
  ].join("\n");
  const retiredScope = {
    ...compatibilityScope,
    operation: "retiredOperation",
  };
  Object.assign(
    retiredScope,
    legacyOperationProof(retiredSource, retiredScope.path, retiredScope),
  );
  const removedSharedScope = {
    ...compatibilityScope,
    path: sharedPath,
    resource: "table:companies",
    operation: "postEntry",
  };
  const retainedSharedScope = {
    ...removedSharedScope,
    resource: "table:ledger_entries",
  };
  Object.assign(
    removedSharedScope,
    legacyOperationProof(sharedBaselineSource, sharedPath, removedSharedScope),
  );
  Object.assign(
    retainedSharedScope,
    legacyOperationProof(sharedBaselineSource, sharedPath, retainedSharedScope),
  );
  const unrelatedScope = {
    ...compatibilityScope,
    path: unrelatedPath,
    resource: "table:bank_transactions",
    operation: "importTransactions",
  };
  Object.assign(
    unrelatedScope,
    legacyOperationProof(unrelatedBaselineSource, unrelatedPath, unrelatedScope),
  );
  const removedLaterScope = {
    ...compatibilityScope,
    path: laterPath,
    resource: "table:companies",
    operation: "importWithCompanyContext",
  };
  const retainedLaterScope = {
    ...removedLaterScope,
    resource: "table:bank_transactions",
  };
  Object.assign(
    removedLaterScope,
    legacyOperationProof(laterBaselineSource, laterPath, removedLaterScope),
  );
  Object.assign(
    retainedLaterScope,
    legacyOperationProof(laterBaselineSource, laterPath, retainedLaterScope),
  );
  const retiredFacade = legacyFacade({ scopes: [retiredScope] });
  const futureFacade = legacyFacade({
    id: "compat-ledger",
    capability: "ledger",
    removalIssue: "#139",
    scopes: [removedSharedScope, retainedSharedScope],
  });
  const unrelatedFacade = legacyFacade({
    id: "compat-banking",
    capability: "banking",
    removalIssue: "#140",
    scopes: [unrelatedScope],
  });
  const laterFacade = legacyFacade({
    id: "compat-banking-resource-owner-shrink",
    capability: "banking",
    removalIssue: "#140",
    scopes: [removedLaterScope, retainedLaterScope],
  });
  const baseline = compatibilityBaseline([
    retiredFacade,
    futureFacade,
    unrelatedFacade,
    laterFacade,
  ]);
  const registry = compatibilityFixture({
    records: [
      legacyFacade({
        id: futureFacade.id,
        capability: futureFacade.capability,
        removalIssue: futureFacade.removalIssue,
        scopes: [retainedSharedScope],
      }),
      unrelatedFacade,
      legacyFacade({
        id: laterFacade.id,
        capability: laterFacade.capability,
        removalIssue: laterFacade.removalIssue,
        scopes: [retainedLaterScope],
      }),
    ],
  });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );
  const workingSources = new Map([
    [compatibilityScope.path, "export const retiredOperation = undefined;\n"],
    [sharedPath, [
      "export function postEntry() {",
      "  callCompanyAccessBackend();",
      '  client.from("ledger_entries");',
      "}",
      "",
    ].join("\n")],
    [unrelatedPath, unrelatedBaselineSource],
    [laterPath, [
      "export function importWithCompanyContext() {",
      '  callCompanyAccessBackend();',
      '  client.from("bank_transactions");',
      "}",
      "",
    ].join("\n")],
  ]);
  const resourceOwners = new Map([
    ["table:companies", "backend:company_access"],
    ["table:ledger_entries", "backend:ledger"],
    ["table:bank_transactions", "backend:banking"],
  ]);
  const completedGateSources = new Map(workingSources);
  const options = {
    baselinePath,
    expectedBaselineDigest: "TEST_BASELINE_DIGEST",
    currentSource: (path) => workingSources.get(path),
    resourceOwner: (resource) => resourceOwners.get(resource),
    sourceAtGateRevision: (_revision, path) => completedGateSources.get(path),
  };

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, options), []);

    const companyAccessMigration = registry.migration;
    registry.migration = compatibilityFixture({
      records: registry.records,
      currentCapability: "ledger",
      currentIssue: "#139",
    }).migration;
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.deepEqual(
      validateCompatibilityRegistry(registryPath, options),
      [],
      "an evidenced company-access deletion must remain authorized after ledger becomes current",
    );
    completedGateSources.set(laterPath, laterBaselineSource);
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-banking-resource-owner-shrink.*was not deleted at completed company_access gate/u,
    );
    completedGateSources.set(laterPath, workingSources.get(laterPath));
    registry.migration = companyAccessMigration;
    writeFileSync(registryPath, JSON.stringify(registry));

    resourceOwners.set("table:companies", "backend:documents");
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-ledger.*future frozen scope resource table:companies is not owned by active or exited capability/u,
    );
    resourceOwners.set("table:companies", "backend:company_access");

    const originalRecords = registry.records;
    const originalOrder = registry.migration.order;
    registry.records = registry.records.filter((record) => record.id !== futureFacade.id);
    registry.migration.order = registry.migration.order.filter(
      (stage) => stage.capability !== futureFacade.capability,
    );
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-ledger.*capability ledger is absent from migration order/u,
    );
    registry.records = originalRecords;
    registry.migration.order = originalOrder;
    writeFileSync(registryPath, JSON.stringify(registry));

    workingSources.set(compatibilityScope.path, retiredSource);
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-company-access.*removed frozen scope still exists/u,
    );

    workingSources.set(compatibilityScope.path, "export const retiredOperation = undefined;\n");
    workingSources.set(
      unrelatedPath,
      'export function importTransactions() { const changed = true; client.from("bank_transactions"); }\n',
    );
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-banking.*legacy operation changed/u,
    );

    workingSources.set(unrelatedPath, unrelatedBaselineSource);
    workingSources.set(sharedPath, [
      "export function postEntry() {",
      "  callCompanyAccessBackend();",
      '  client.from("ledger_entries");',
      '  client.from("ledger_entries");',
      "}",
      "",
    ].join("\n"));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-ledger.*scope has an added writer/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("ledger #139 may relocate only the owner-approved atomic coordinator scopes", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-ledger-coordinator-relocation-"));
  const actionPath = "apps/web/app/actions.ts";
  const scope = (resource, operation) => ({
    path: actionPath,
    rule: "direct-web-business-persistence",
    resource,
    operation,
  });
  const facades = [
    legacyFacade({
      id: "compat-ledger-persistence",
      capability: "ledger",
      removalIssue: "#139",
      scopes: [
        scope("table:ledger_entries", "recordAdminCost"),
        scope("table:ledger_entries", "recordDividendReceived"),
        scope("table:ledger_entries", "recordShareholderLoan"),
        scope("table:ledger_entries", "recordTaxSettlement"),
      ],
    }),
    legacyFacade({
      id: "compat-banking-persistence",
      capability: "banking",
      removalIssue: "#140",
      scopes: [
        scope("table:bank_transactions", "recordAdminCost"),
        scope("table:bank_transactions", "recordDividendReceived"),
        scope("table:bank_transactions", "recordShareholderLoan"),
        scope("table:bank_transactions", "recordTaxSettlement"),
        scope("rpc:accept_bank_transaction_suggestion", "acceptBankTransactionSuggestion"),
        scope("table:bank_transactions", "acceptBankTransactionSuggestion"),
      ],
    }),
    legacyFacade({
      id: "compat-investment-purchase-persistence",
      capability: "investments",
      removalIssue: "#141",
      scopes: [scope("rpc:record_share_purchase_fifo", "recordSharePurchase")],
    }),
    legacyFacade({
      id: "compat-investment-sale-persistence",
      capability: "investments",
      removalIssue: "#142",
      scopes: [
        scope("rpc:record_share_sale_fifo", "recordShareSale"),
        scope("table:investment_lots", "recordShareSale"),
        scope("table:investment_positions", "recordShareSale"),
      ],
    }),
    legacyFacade({
      id: "compat-investment-stage-exit-persistence",
      capability: "investments",
      removalIssue: "#143",
      scopes: [scope("table:holding_actions", "recordDividendReceived")],
    }),
    legacyFacade({
      id: "compat-shareholder-loan-persistence",
      capability: "corporate_governance",
      removalIssue: "#145",
      scopes: [scope("table:holding_actions", "recordShareholderLoan")],
    }),
    legacyFacade({
      id: "compat-tax-settlement-persistence",
      capability: "company_tax_filing",
      removalIssue: "#146",
      scopes: [scope("table:holding_actions", "recordTaxSettlement")],
    }),
    legacyFacade({
      id: "compat-documents-persistence",
      capability: "documents",
      removalIssue: "#147",
      scopes: [
        scope("table:documents", "recordDividendReceived"),
        scope("table:documents", "recordShareholderLoan"),
        scope("table:documents", "recordTaxSettlement"),
      ],
    }),
    legacyFacade({
      id: "compat-audit-persistence",
      capability: "audit",
      removalIssue: "#155",
      scopes: [
        scope("table:audit_events", "recordAdminCost"),
        scope("table:audit_events", "recordDividendReceived"),
        scope("table:audit_events", "recordShareholderLoan"),
        scope("table:audit_events", "recordTaxSettlement"),
      ],
    }),
  ];
  const registry = compatibilityFixture({
    records: [],
    currentCapability: "ledger",
    currentIssue: "#139",
  });
  registry.migration.order = [
    { capability: "company_access", removalIssues: ["#138"] },
    { capability: "ledger", removalIssues: ["#139"] },
    { capability: "banking", removalIssues: ["#140"] },
    { capability: "investments", removalIssues: ["#141", "#142", "#143"] },
    { capability: "documents", removalIssues: ["#147"] },
    { capability: "corporate_governance", removalIssues: ["#144", "#145", "#148"] },
    { capability: "company_tax_filing", removalIssues: ["#146", "#152"] },
    { capability: "audit", removalIssues: ["#155"] },
  ];
  const baseline = compatibilityBaseline(facades);
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );
  const options = {
    baselinePath,
    expectedBaselineDigest: "TEST_BASELINE_DIGEST",
    currentSource: () => "export const atomicCoordinatorRelocated = true;\n",
  };
  const ledgerMigration = structuredClone(registry.migration);

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, options), []);

    registry.records = [{
      ...structuredClone(facades.find((facade) => facade.id === "compat-banking-persistence")),
      scopes: [scope("table:bank_transactions", "recordAdminCost")],
    }];
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /recordAdminCost.*must remove every frozen scope together/u,
    );

    registry.records = [];
    registry.migration.currentCapability = "company_access";
    registry.migration.currentIssue = "#138";
    registry.migration.exitedCapabilities = [];
    registry.migration.completedStages = [];
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /atomic coordinator relocation is authorized only for ledger #139/u,
    );

    registry.migration = structuredClone(ledgerMigration);
    const auditBaseline = baseline.records.find(
      (facade) => facade.id === "compat-audit-persistence",
    );
    auditBaseline.scopes.push(scope("table:unexpected_future_state", "recordAdminCost"));
    writeFileSync(registryPath, JSON.stringify(registry));
    writeFileSync(baselinePath, JSON.stringify(baseline));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /recordAdminCost.*outside the owner-approved scope whitelist/u,
    );

    auditBaseline.scopes.pop();
    auditBaseline.scopes.push({
      ...scope("table:audit_events", "recordAdminCost"),
      rule: "direct-business-fetch",
    });
    writeFileSync(baselinePath, JSON.stringify(baseline));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /recordAdminCost.*outside the owner-approved scope whitelist/u,
    );

    auditBaseline.scopes.pop();
    const bankingBaseline = baseline.records.find(
      (facade) => facade.id === "compat-banking-persistence",
    );
    bankingBaseline.scopes.push(scope("table:bank_transactions", "unapprovedPosting"));
    writeFileSync(baselinePath, JSON.stringify(baseline));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /future frozen scope resource table:bank_transactions is not owned by active or exited capability/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("pending foundation recovery blocks facade and migration changes", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-foundation-recovery-"));
  const current = legacyFacade();
  const future = legacyFacade({
    id: "compat-ledger",
    capability: "ledger",
    removalIssue: "#139",
    scopes: [{ ...compatibilityScope, resource: "table:ledger_entries", operation: "postEntry" }],
  });
  const registry = compatibilityFixture({
    records: [current, future],
    foundationStatus: "pending",
  });
  const baseline = compatibilityBaseline([current, future]);
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );
  const options = { baselinePath, expectedBaselineDigest: "TEST_BASELINE_DIGEST" };

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, options), []);

    current.scopes = [];
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /pending foundation recovery requires the untouched frozen facade inventory/u,
    );

    registry.records = [future, activeStageDebt()];
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /pending foundation recovery blocks active-stage debt/u,
    );

    registry.records = [current, future];
    current.scopes = [compatibilityScope];
    registry.migration.currentCapability = "ledger";
    registry.migration.currentIssue = "#139";
    registry.migration.exitedCapabilities = ["company_access"];
    registry.migration.completedStages = compatibilityFixture({
      currentCapability: "ledger",
      currentIssue: "#139",
    }).migration.completedStages;
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /pending foundation recovery blocks migration-state changes/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("the frozen baseline is traceable to the pre-existing compatibility registry", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-legacy-source-proof-"));
  const facade = legacyFacade();
  const baseline = compatibilityBaseline([facade]);
  const registry = compatibilityFixture({ records: [facade] });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );
  const sourceRegistry = {
    schemaVersion: "1.0",
    exceptions: [{
      id: facade.id,
      removalIssue: facade.removalIssue,
      scopes: structuredClone(facade.scopes),
    }],
  };

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, {
      baselinePath,
      expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      sourceRegistry,
    }), []);

    baseline.records[0].scopes.push({
      ...compatibilityScope,
      resource: "table:not_pre_existing",
      operation: "inventedAfterFreeze",
    });
    writeFileSync(baselinePath, JSON.stringify(baseline));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
        sourceRegistry,
      }).join("\n"),
      /compat-company-access.*frozen scopes do not match source revision/u,
    );

    baseline.sourceRevision = "2222222222222222222222222222222222222222";
    writeFileSync(baselinePath, JSON.stringify(baseline));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
        sourceRegistry,
      }).join("\n"),
      /frozen source revision must remain d331ee2717d1eeacef0d81db42b9d4fb5848b408/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("legacy source proofs reject added writers and changed future operations", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-legacy-operation-proof-"));
  const currentSource = 'export function legacyOperation() { client.from("companies"); }\n';
  const futureSource = 'export function postEntry() { client.from("ledger_entries"); }\n';
  const currentScope = {
    ...compatibilityScope,
    ...legacyOperationProof(currentSource, compatibilityScope.path, compatibilityScope),
  };
  const futureScope = {
    ...compatibilityScope,
    path: "apps/web/app/ledger.ts",
    resource: "table:ledger_entries",
    operation: "postEntry",
  };
  Object.assign(
    futureScope,
    legacyOperationProof(futureSource, futureScope.path, futureScope),
  );
  const currentFacade = legacyFacade({ scopes: [currentScope] });
  const futureFacade = legacyFacade({
    id: "compat-ledger",
    capability: "ledger",
    removalIssue: "#139",
    scopes: [futureScope],
  });
  const registry = compatibilityFixture({ records: [currentFacade, futureFacade] });
  const baseline = compatibilityBaseline([currentFacade, futureFacade]);
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    baseline,
  );
  const frozenSources = new Map([
    [compatibilityScope.path, currentSource],
    [futureScope.path, futureSource],
  ]);
  const workingSources = new Map(frozenSources);
  const sourceRegistry = {
    schemaVersion: "1.0",
    exceptions: baseline.records.map((record) => ({
      id: record.id,
      removalIssue: record.removalIssue,
      scopes: structuredClone(record.scopes),
    })),
  };
  const options = {
    baselinePath,
    expectedBaselineDigest: "TEST_BASELINE_DIGEST",
    sourceRegistry,
    sourceAtRevision: (path) => frozenSources.get(path),
    currentSource: (path) => workingSources.get(path),
  };

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, options), []);

    workingSources.set(
      compatibilityScope.path,
      'export function legacyOperation() { client.from("companies"); client.from("companies"); }\n',
    );
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-company-access.*scope has an added writer/u,
    );

    workingSources.set(compatibilityScope.path, currentSource);
    workingSources.set(
      futureScope.path,
      'export function postEntry() { const changed = true; client.from("ledger_entries"); }\n',
    );
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /compat-ledger.*legacy operation changed/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("legacy facades block stage exit and fail after their capability has exited", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-legacy-stage-exit-"));
  const facade = legacyFacade();
  const baseline = compatibilityBaseline([facade]);
  const exitReview = compatibilityFixture({ records: [facade], status: "exit-review" });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    exitReview,
    baseline,
  );

  try {
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /company_access cannot exit while legacy-facade compat-company-access remains/u,
    );

    const advanced = compatibilityFixture({
      records: [facade],
      currentCapability: "ledger",
      currentIssue: "#139",
      exitedCapabilities: ["company_access"],
    });
    writeFileSync(registryPath, JSON.stringify(advanced));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-company-access.*capability company_access has already exited/u,
    );

    advanced.migration.completedStages = [];
    writeFileSync(registryPath, JSON.stringify(advanced));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /completedStages must exactly evidence every exited capability/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("completed stages require two consecutive complete-gate attestations", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-complete-gate-evidence-"));
  const facade = legacyFacade();
  const registry = compatibilityFixture({
    records: [],
    currentCapability: "ledger",
    currentIssue: "#139",
  });
  const checkNames = [
    "credential-scan",
    "typecheck",
    "architecture",
    "boundary",
    "build-web",
    "build-backend",
    "boundary-smoke",
    "launch-rehearsal",
    "production-dependency-audit",
    "database-isolation",
    "whitespace",
  ];
  const producer = "export const gate = true;\n";
  const revisions = ["1".repeat(40), "2".repeat(40)];
  const transcripts = new Map();
  const evidence = revisions.map((revision, index) => {
    const transcriptPath = `architecture/evidence/customer-ready-gates/${revision}.log`;
    const transcript = `${checkNames.map((name) => `[${name}] exit=0`).join("\n")}\n`;
    transcripts.set(transcriptPath, transcript);
    return {
      schemaVersion: "1.0",
      revision,
      previousPassingRevision: index === 0 ? null : revisions[0],
      workflow: "customer-ready-release-gate",
      executor: "local-script",
      producer: "scripts/run-customer-ready-gate.mjs",
      producerDigest: `sha256:${createHash("sha256").update(producer).digest("hex")}`,
      transcriptPath,
      transcriptDigest: `sha256:${createHash("sha256").update(transcript).digest("hex")}`,
      startedAt: `2026-08-2${index + 6}T11:00:00Z`,
      executedAt: `2026-08-2${index + 6}T12:00:00Z`,
      verdict: "pass",
      checks: checkNames.map((name) => ({
        name,
        command: `run ${name}`,
        exitCode: 0,
        durationMs: 1,
      })),
    };
  });
  registry.migration.completedStages[0].gates = evidence.map((attestation) => ({
    revision: attestation.revision,
    evidencePath: `architecture/evidence/customer-ready-gates/${attestation.revision}.json`,
    evidenceDigest: canonicalDigest(attestation),
  }));
  registry.migration.foundationRecovery = {
    issue: "#186",
    status: "complete",
    gates: structuredClone(registry.migration.completedStages[0].gates),
  };
  const byPath = new Map(registry.migration.completedStages[0].gates.map((gate, index) => (
    [gate.evidencePath, evidence[index]]
  )));
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    compatibilityBaseline([facade]),
  );
  const options = {
    baselinePath,
    expectedBaselineDigest: "TEST_BASELINE_DIGEST",
    reachableRevision: () => true,
    isRevisionAncestor: () => true,
    isImmutableEvidence: () => true,
    loadGateEvidence: (path) => byPath.get(path),
    loadGateTranscript: (path) => transcripts.get(path),
    sourceAtGateRevision: () => producer,
    currentSource: () => "export const retiredFacade = true;\n",
  };

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, options), []);

    evidence[1].previousPassingRevision = null;
    assert.match(
      validateCompatibilityRegistry(registryPath, options).join("\n"),
      /gates are not consecutive passes/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("active-stage debt keeps the fourteen-day, stable-release, and one-successor limits", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-active-stage-debt-"));
  const debt = {
    id: "compat-company-access-cleanup",
    kind: "active-stage-debt",
    capability: "company_access",
    owner: "backend:company_access",
    creationIssue: "#138",
    removalIssue: "#199",
    successorCapability: "ledger",
    scopes: [compatibilityScope],
    approvedBy: "Kristian Elmer",
    approvedAt: "2026-08-26T10:00:00Z",
    releaseLimit: "next-stable-customer-ready-release",
    expiresAt: "2026-09-09T10:00:00Z",
    residualRisk: "One bounded legacy call remains after canonical cutover.",
    rollback: "Disable the canonical route and restore the prior release.",
    removalCondition: "Remove the residual call in #199.",
  };
  const registry = compatibilityFixture({
    records: [debt],
    currentCapability: "ledger",
    currentIssue: "#139",
  });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    compatibilityBaseline([]),
  );

  try {
    assert.deepEqual(validateCompatibilityRegistry(registryPath, {
      now: new Date("2026-08-26T12:00:00Z"),
      baselinePath,
      expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      releaseState: { latestStableCustomerReadyRelease: null },
    }), []);

    registry.migration.status = "exit-review";
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-08-26T12:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /ledger cannot exit while predecessor active-stage-debt compat-company-access-cleanup remains/u,
    );

    registry.migration.status = "active";
    registry.migration.currentCapability = "banking";
    registry.migration.currentIssue = "#140";
    writeFileSync(registryPath, JSON.stringify(registry));
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-08-26T12:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-company-access-cleanup.*may not survive beyond successor capability ledger/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility records cannot suppress authorization or other non-suppressible failures", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-non-suppressible-"));
  const facade = legacyFacade({
    scopes: [{ ...compatibilityScope, rule: "authorization-rls" }],
  });
  const registry = compatibilityFixture({ records: [facade] });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    registry,
    compatibilityBaseline([facade]),
  );

  try {
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /authorization-rls.*is not suppressible/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("active-stage debt requires bounded expiry and a removal condition", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-"));
  const debt = activeStageDebt({ id: "compat-unbounded", expiresAt: "never" });
  debt.removalCondition = "";
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    compatibilityFixture({ records: [debt] }),
    compatibilityBaseline([]),
  );

  try {
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-unbounded.*expiresAt.*RFC 3339/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("active-stage debt must expire strictly after the controlled current time", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-expiry-"));
  const debt = activeStageDebt({
    id: "compat-expired",
    approvedAt: "2026-07-15T00:00:00Z",
    expiresAt: "2026-07-29T00:00:00Z",
  });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    compatibilityFixture({ records: [debt] }),
    compatibilityBaseline([]),
  );
  try {
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-07-30T00:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-expired.*strictly in the future/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("active-stage debt cannot outlive fourteen days or the next stable release", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-expiry-bound-"));
  const debt = activeStageDebt({
    id: "compat-too-distant",
    approvedAt: "2026-07-30T00:00:00Z",
    expiresAt: "2026-08-14T00:00:00Z",
  });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    compatibilityFixture({ records: [debt] }),
    compatibilityBaseline([]),
  );
  try {
    assert.match(
      validateCompatibilityRegistry(registryPath, {
        now: new Date("2026-07-30T00:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      }).join("\n"),
      /compat-too-distant.*fourteen days after approval/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("active-stage debt rejects semantically impossible timestamps", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-invalid-timestamp-"));
  const debt = activeStageDebt({
    id: "compat-invalid-date",
    approvedAt: "2026-99-99T25:99:99Z",
    expiresAt: "2026-99-99T25:99:99Z",
  });
  const { registryPath, baselinePath } = writeCompatibilityFixture(
    temporaryRoot,
    compatibilityFixture({ records: [debt] }),
    compatibilityBaseline([]),
  );
  try {
    const errors = validateCompatibilityRegistry(
      registryPath,
      {
        now: new Date("2026-07-30T00:00:00Z"),
        baselinePath,
        expectedBaselineDigest: "TEST_BASELINE_DIGEST",
      },
    ).join("\n");
    assert.match(errors, /compat-invalid-date.*approvedAt must be a valid RFC 3339 timestamp/u);
    assert.match(errors, /compat-invalid-date.*expiresAt must be a valid RFC 3339 timestamp/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("a fabricated release revision is rejected against the real tag target", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-fabricated-release-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  initializeFixtureRepository(temporaryRoot);
  tagCustomerReadyRelease(temporaryRoot, "customer-ready-v1", "2026-07-30T00:00:00Z");
  const releaseStatePath = join(temporaryRoot, "architecture/release-state.json");
  writeFileSync(releaseStatePath, JSON.stringify({
    schemaVersion: "1.0",
    latestStableCustomerReadyRelease: {
      id: "customer-ready-v1",
      releasedAt: git(temporaryRoot, ["for-each-ref", "--format=%(taggerdate:iso-strict)", "refs/tags/customer-ready-v1"]),
      gitRevision: "1111111111111111111111111111111111111111",
    },
  }));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /release-state\.json: tracked release does not match the latest reachable customer-ready Git tag/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("a lightweight customer-ready tag is rejected as a stable release", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-lightweight-release-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  initializeFixtureRepository(temporaryRoot);
  git(temporaryRoot, ["tag", "customer-ready-v1"]);
  writeFileSync(join(temporaryRoot, "architecture/release-state.json"), JSON.stringify({
    schemaVersion: "1.0",
    latestStableCustomerReadyRelease: {
      id: "customer-ready-v1",
      releasedAt: git(temporaryRoot, ["for-each-ref", "--format=%(creatordate:iso-strict)", "refs/tags/customer-ready-v1"]),
      gitRevision: git(temporaryRoot, ["rev-parse", "customer-ready-v1^{commit}"]),
    },
  }));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /customer-ready Git tag customer-ready-v1 must be an annotated tag object/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("reachable annotated releases with equal tagger timestamps fail closed", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-ambiguous-release-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  initializeFixtureRepository(temporaryRoot);
  const releaseDate = "2026-07-30T00:00:00Z";
  tagCustomerReadyRelease(temporaryRoot, "customer-ready-v1", releaseDate);
  tagCustomerReadyRelease(temporaryRoot, "customer-ready-v2", releaseDate);
  writeFileSync(join(temporaryRoot, "architecture/release-state.json"), JSON.stringify({
    schemaVersion: "1.0",
    latestStableCustomerReadyRelease: {
      id: "customer-ready-v2",
      releasedAt: git(temporaryRoot, ["for-each-ref", "--format=%(taggerdate:iso-strict)", "refs/tags/customer-ready-v2"]),
      gitRevision: git(temporaryRoot, ["rev-parse", "customer-ready-v2^{commit}"]),
    },
  }));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /ambiguous customer-ready Git tags customer-ready-v1, customer-ready-v2 share tagger timestamp/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("a stale release selection is rejected after a later reachable tag", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-stale-release-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  initializeFixtureRepository(temporaryRoot, "2026-07-30T00:00:00Z");
  tagCustomerReadyRelease(temporaryRoot, "customer-ready-v1", "2026-07-30T00:00:00Z");
  const firstRevision = git(temporaryRoot, ["rev-parse", "customer-ready-v1^{commit}"]);
  const firstReleasedAt = git(temporaryRoot, ["for-each-ref", "--format=%(taggerdate:iso-strict)", "refs/tags/customer-ready-v1"]);
  writeFileSync(join(temporaryRoot, "later-release.txt"), "later\n");
  git(temporaryRoot, ["add", "later-release.txt"]);
  git(temporaryRoot, ["commit", "--quiet", "-m", "later release"], "2026-07-31T00:00:00Z");
  tagCustomerReadyRelease(temporaryRoot, "customer-ready-v2", "2026-07-31T00:00:00Z");
  writeFileSync(join(temporaryRoot, "architecture/release-state.json"), JSON.stringify({
    schemaVersion: "1.0",
    latestStableCustomerReadyRelease: {
      id: "customer-ready-v1",
      releasedAt: firstReleasedAt,
      gitRevision: firstRevision,
    },
  }));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /release-state\.json: tracked release does not match the latest reachable customer-ready Git tag customer-ready-v2/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("a real stable customer-ready release after approval revokes active-stage debt", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-stable-release-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  initializeFixtureRepository(temporaryRoot, "2026-07-31T00:00:00Z");
  tagCustomerReadyRelease(
    temporaryRoot,
    "customer-ready-2026-07-31",
    "2026-07-31T00:00:00Z",
  );
  const releaseStatePath = join(temporaryRoot, "architecture/release-state.json");
  writeFileSync(releaseStatePath, JSON.stringify({
    schemaVersion: "1.0",
    latestStableCustomerReadyRelease: {
      id: "customer-ready-2026-07-31",
      releasedAt: git(temporaryRoot, ["for-each-ref", "--format=%(taggerdate:iso-strict)", "refs/tags/customer-ready-2026-07-31"]),
      gitRevision: git(temporaryRoot, ["rev-parse", "customer-ready-2026-07-31^{commit}"]),
    },
  }));
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const debtPath = "apps/web/app/stable-release-debt.ts";
  writeFileSync(join(temporaryRoot, debtPath), `
import { createClient } from "@supabase/supabase-js";
const client = createClient("https://fixture.supabase.co", "fixture-key");
export async function legacyOperation() {
  await client.from("companies").insert({ name: "Fixture" });
}
`);
  compatibility.records.push(activeStageDebt({
    scopes: [{ ...compatibilityScope, path: debtPath }],
    approvedAt: "2026-07-30T00:00:00Z",
    expiresAt: "2026-08-10T00:00:00Z",
  }));
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({
      root: temporaryRoot,
      writeEvidence: false,
      now: new Date("2026-07-31T12:00:00Z"),
    }).errors.join("\n");
    assert.match(errors, /compat-company-access-active-stage-debt.*superseded by stable customer-ready release customer-ready-2026-07-31/u);
    assert.match(errors, /apps\/web\/app\/stable-release-debt\.ts: direct web business persistence is forbidden/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("module test evidence cannot assign one path to multiple ownership categories", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-test-ownership-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const modulePath = join(
    temporaryRoot,
    "apps/backend/src/talli_backend/modules/system_boundary/module.json",
  );
  const module = JSON.parse(readFileSync(modulePath, "utf8"));
  module.tests.unit = module.tests.contract;
  writeFileSync(modulePath, JSON.stringify(module));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /module\.json: test path .*test_system_boundary\.py has multiple ownership categories contract, unit/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("schema constraints and declared public exports are enforced", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-schema-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const backendModulePath = join(temporaryRoot, "apps/backend/src/talli_backend/modules/system_boundary/module.json");
  const backendModule = JSON.parse(readFileSync(backendModulePath, "utf8"));
  backendModule.ports[0].direction = "inbound";
  backendModule.exports.errors.push("UNEXPORTED_ERROR");
  writeFileSync(backendModulePath, JSON.stringify(backendModule));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /module\.json: schema .*ports.*direction/u);
    assert.match(errors, /UNEXPORTED_ERROR.*missing from public package/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("backend workflow routes and public request exports reconcile in both directions", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-public-reconciliation-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const systemPath = join(temporaryRoot, "architecture/backend-system.json");
  const system = JSON.parse(readFileSync(systemPath, "utf8"));
  const workflow = system.workflows.find((candidate) => candidate.name === "company-access-administration");
  workflow.routes = workflow.routes.filter((route) => !route.endsWith("/finalize"));
  writeFileSync(systemPath, JSON.stringify(system));
  const modulePath = join(temporaryRoot, "apps/backend/src/talli_backend/modules/company_access/module.json");
  const module = JSON.parse(readFileSync(modulePath, "utf8"));
  module.exports.commands = module.exports.commands.filter((name) => name !== "FinalizeCompanyDeletionRequest");
  writeFileSync(modulePath, JSON.stringify(module));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /composition route .*finalize.*missing from backend-system\.json/u);
    assert.match(errors, /public request export FinalizeCompanyDeletionRequest missing from module manifest/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("database catalog and declared public import paths are authoritative", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-catalog-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const catalogPath = join(temporaryRoot, "architecture/database-catalog.json");
  const catalog = JSON.parse(readFileSync(catalogPath, "utf8"));
  catalog.tables.push({ name: "public.idempotency_records", kind: "technical" });
  writeFileSync(catalogPath, JSON.stringify(catalog));
  const webModulePath = join(temporaryRoot, "apps/web/features/system-boundary/module.json");
  const webModule = JSON.parse(readFileSync(webModulePath, "utf8"));
  webModule.publicImportPaths = ["@/features/system-boundary"];
  writeFileSync(webModulePath, JSON.stringify(webModule));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /undeclared technical ownership public.idempotency_records/u);
    assert.match(errors, /health\/ready\/route\.ts: undeclared public feature entry point/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("database compatibility resources are globally unambiguous", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-catalog-aliases-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const catalogPath = join(temporaryRoot, "architecture/database-catalog.json");
  const pristine = JSON.parse(readFileSync(catalogPath, "utf8"));
  const errorsFor = (mutate) => {
    const catalog = structuredClone(pristine);
    mutate(catalog.tables);
    writeFileSync(catalogPath, JSON.stringify(catalog));
    return checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
  };

  try {
    assert.match(errorsFor((tables) => {
      tables.find((entry) => entry.name === "ledger.entries")
        .compatibilityResources.push("table:ledger_entries");
    }), /compatibility resource table:ledger_entries is declared more than once by ledger\.entries/u);

    assert.match(errorsFor((tables) => {
      tables.find((entry) => entry.name === "ledger.period_locks")
        .compatibilityResources.push("table:ledger_entries");
    }), /compatibility resource table:ledger_entries is declared by both ledger\.entries and ledger\.period_locks/u);

    assert.match(errorsFor((tables) => {
      tables.find((entry) => entry.name === "ledger.entries")
        .compatibilityResources.push("table:companies");
    }), /compatibility resource table:companies on ledger\.entries collides with catalog table public\.companies/u);

    assert.match(errorsFor((tables) => {
      tables.find((entry) => entry.name === "public.companies")
        .compatibilityResources = ["table:companies"];
    }), /compatibility resource table:companies on public\.companies collides with catalog table public\.companies/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("staged contract table retirement requires an empty-table preflight and rollback", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-contract-table-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const contractPath = join(
    temporaryRoot,
    "supabase/contract-migrations/20260826101000_company_access_onboarding_contract.sql",
  );
  const rollbackPath = join(
    temporaryRoot,
    "supabase/rollback/20260826101000_company_access_onboarding_contract.sql",
  );
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const advancedCompatibility = JSON.parse(
    readFileSync(compatibilityPath, "utf8"),
  );
  const companyAccessCompatibility = structuredClone(advancedCompatibility);
  companyAccessCompatibility.migration.currentCapability = "company_access";
  companyAccessCompatibility.migration.currentIssue = "#138";
  companyAccessCompatibility.migration.status = "exit-review";
  companyAccessCompatibility.migration.exitedCapabilities = [];
  companyAccessCompatibility.migration.completedStages = [];
  writeFileSync(compatibilityPath, JSON.stringify(companyAccessCompatibility));
  const contract = readFileSync(contractPath, "utf8");

  try {
    const completeErrors = checkArchitecture({ root: temporaryRoot, writeEvidence: false })
      .errors.join("\n");
    assert.doesNotMatch(completeErrors, /migration table missing from catalog public\.step_up_events/u);
    assert.doesNotMatch(completeErrors, /staged table drop public\.step_up_events/u);

    writeFileSync(
      contractPath,
      contract.replace(
        "and exists (select 1 from public.step_up_events)",
        "and true",
      ),
    );
    const unguardedErrors = checkArchitecture({ root: temporaryRoot, writeEvidence: false })
      .errors.join("\n");
    assert.match(
      unguardedErrors,
      /staged table drop public\.step_up_events is missing a fail-closed empty-table preflight/u,
    );
    assert.match(unguardedErrors, /migration table missing from catalog public\.step_up_events/u);

    writeFileSync(
      contractPath,
      contract.replace(
        "CONTRACT RELEASE ARTIFACT: #138",
        "CONTRACT RELEASE ARTIFACT: #139",
      ),
    );
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /migration table missing from catalog public\.step_up_events/u,
    );

    writeFileSync(contractPath, contract);
    writeFileSync(compatibilityPath, JSON.stringify(advancedCompatibility));
    assert.doesNotMatch(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /migration table missing from catalog public\.step_up_events/u,
      "a completed stage's validated contract retirement must remain retired",
    );

    rmSync(rollbackPath);
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /staged table drop public\.step_up_events has no matching rollback table restoration/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("multiline web persistence requires an explicit rule-scoped exception", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-persistence-format-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const route = "apps/web/app/documents/[documentId]/download/route.ts";
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  for (const exception of compatibility.records) {
    exception.scopes = exception.scopes.filter((scope) => scope.path !== route);
  }
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const realFormatErrors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(realFormatErrors, new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")}: direct web business persistence is forbidden`, "u"));

    const routePath = join(temporaryRoot, route);
    writeFileSync(
      routePath,
      readFileSync(routePath, "utf8").replace(
        'supabase\n    .from("documents")',
        'supabase /* repository */\n    . /* table */ from("documents")',
      ),
    );
    const commentedFormatErrors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(commentedFormatErrors, new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")}: direct web business persistence is forbidden`, "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("web persistence exceptions match exact path, rule, AST-derived resource, and operation", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-resource-scope-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixture = "apps/web/app/resource-scoped-persistence.ts";
  writeFileSync(join(temporaryRoot, fixture), `
import { createClient } from "@supabase/supabase-js";
const client = createClient("https://example.invalid", "public-key");
export function readCompany() { client.from("companies"); }
export function readDocument() { client.from("documents"); }
`);
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const exactScope = {
    path: fixture,
    rule: "direct-web-business-persistence",
    resource: "table:companies",
    operation: "readCompany",
  };
  compatibility.records[0].scopes.push(exactScope);
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.doesNotMatch(errors, new RegExp(`${fixture}: direct web business persistence is forbidden for table:companies`, "u"));
    assert.match(errors, new RegExp(`${fixture}: direct web business persistence is forbidden for table:documents`, "u"));

    exactScope.resource = "table:*";
    writeFileSync(compatibilityPath, JSON.stringify(compatibility));
    const wildcardErrors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(wildcardErrors, new RegExp(`${fixture}: direct web business persistence is forbidden for table:companies`, "u"));
    assert.match(wildcardErrors, new RegExp(`${fixture}: direct web business persistence is forbidden for table:documents`, "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility operations map to their serialized future tickets", () => {
  const compatibility = JSON.parse(readFileSync(
    new URL("../architecture/compatibility-baseline.json", import.meta.url),
    "utf8",
  ));
  const byRemovalIssue = new Map(
    compatibility.records.map((entry) => [entry.removalIssue, entry]),
  );
  const onboarding = byRemovalIssue.get("#138");
  const ownerOf = (resource, operation, path = "apps/web/app/actions.ts") => compatibility.records.find((entry) => (
    entry.scopes.some((scope) => scope.path === path
      && scope.resource === resource
      && scope.operation === operation)
  ))?.removalIssue;

  assert.equal(ownerOf("rpc:create_company_workspace_with_acceptance", "createWorkspace"), "#138");
  assert.equal(ownerOf("table:companies", "generateRf1086Preview"), "#151");
  assert.equal(ownerOf("table:companies", "approveProductionFiling"), "#151");
  assert.equal(ownerOf("table:companies", "createAnnualCorporateDecisionDraft"), "#148");
  assert.equal(ownerOf("table:companies", "createOwnerDividendDecisionDraft"), "#144");
  assert.equal(ownerOf("table:company_memberships", "queueDeadlineReminders"), "#149");
  assert.equal(ownerOf("table:companies", "recordAnnualAccountsTt02Evidence"), "#153");
  assert.equal(ownerOf("table:companies", "recordCompanyTaxReturnTt02Evidence"), "#152");
  assert.equal(ownerOf(
    "table:companies",
    "searchOperatorSupportDashboard",
    "apps/web/app/lib/supabase/server.ts",
  ), "#150");
  assert.equal(byRemovalIssue.has("#160"), false);
  assert.equal(ownerOf("table:companies", "inviteWorkspaceReviewer"), undefined);
  assert.equal(ownerOf("table:company_memberships", "acceptWorkspaceInvitation"), undefined);
  assert.equal(byRemovalIssue.has("#161"), false);
  assert.equal(ownerOf("table:company_memberships", "requestCompanyCancellation"), undefined);
  assert.equal(ownerOf("table:companies", "completeCompanyDeletionRecord"), undefined);
  assert.equal(ownerOf("table:documents", "requestCompanyCancellation"), undefined);
  assert.equal(ownerOf("table:corporate_document_artifacts", "requestCompanyCancellation"), undefined);
  assert.equal(ownerOf("table:audit_events", "requestCompanyCancellation"), undefined);
  assert.equal(ownerOf("table:audit_events", "completeCompanyDeletionRecord"), undefined);
  assert.equal(ownerOf("table:holding_actions", "recordShareholderLoan"), "#145");
  assert.equal(ownerOf("table:holding_actions", "recordTaxSettlement"), "#146");
  assert.equal(ownerOf("table:authority_test_runs", "recordAnnualAccountsTt02Evidence"), "#153");
  assert.equal(ownerOf("table:investment_lots", "recordShareSale"), "#142");
  assert.equal(ownerOf("table:audit_events", "uploadDocument"), "#155");
  assert.equal(ownerOf(
    "table:audit_events",
    "createInvitationSideEffectStore",
    "apps/web/app/lib/invitation-side-effects.ts",
  ), "#155");
  assert.equal(ownerOf(
    "table:notification_outbox",
    "createInvitationSideEffectStore",
    "apps/web/app/lib/invitation-side-effects.ts",
  ), undefined);
  assert.equal(ownerOf("table:notification_outbox", "queueDeadlineReminders"), "#156");
  assert.deepEqual(
    onboarding.scopes.map(({ resource, operation }) => `${resource}:${operation}`).sort(),
    [
      "rpc:append_company_agreement_acceptance:reacceptCompanyAgreement",
      "rpc:create_company_workspace_with_acceptance:createWorkspace",
      "table:customer_agreement_acceptances:listCustomerAgreementAcceptances",
    ],
  );
});

test("the immutable frozen inventory remains exact while the active registry is a proven subset", () => {
  const registry = JSON.parse(readFileSync(
    new URL("../architecture/compatibility.json", import.meta.url),
    "utf8",
  ));
  const baseline = JSON.parse(readFileSync(
    new URL("../architecture/compatibility-baseline.json", import.meta.url),
    "utf8",
  ));
  const expected = new Map([
    ["compat-company-onboarding-persistence", ["company_access", "#138", 3]],
    ["compat-ledger-persistence", ["ledger", "#139", 25]],
    ["compat-banking-persistence", ["banking", "#140", 10]],
    ["compat-investment-purchase-persistence", ["investments", "#141", 3]],
    ["compat-investment-sale-persistence", ["investments", "#142", 4]],
    ["compat-investment-stage-exit-persistence", ["investments", "#143", 2]],
    ["compat-documents-persistence", ["documents", "#147", 15]],
    ["compat-owner-dividend-persistence", ["corporate_governance", "#144", 2]],
    ["compat-shareholder-loan-persistence", ["corporate_governance", "#145", 1]],
    ["compat-corporate-governance-persistence", ["corporate_governance", "#148", 19]],
    ["compat-billing-persistence", ["billing", "#137", 19]],
    ["compat-authority-connections-persistence", ["authority_connections", "#150", 16]],
    ["compat-rf1086-persistence", ["shareholder_register_filing", "#151", 35]],
    ["compat-tax-settlement-persistence", ["company_tax_filing", "#146", 1]],
    ["compat-company-tax-persistence", ["company_tax_filing", "#152", 2]],
    ["compat-annual-accounts-persistence", ["annual_accounts_filing", "#153", 2]],
    ["compat-annual-compliance-persistence", ["annual_compliance", "#149", 22]],
    ["compat-audit-persistence", ["audit", "#155", 30]],
    ["compat-notification-persistence", ["notifications", "#156", 2]],
    ["compat-company-archive-persistence", ["company_archive", "#157", 24]],
  ]);

  assert.equal(baseline.records.length, 20);
  assert.equal(baseline.records.flatMap((record) => record.scopes).length, 237);
  for (const record of baseline.records) {
    const [capability, removalIssue, scopes] = expected.get(record.id) ?? [];
    assert.equal(record.kind, "legacy-facade", record.id);
    assert.equal(record.capability, capability, record.id);
    assert.equal(record.removalIssue, removalIssue, record.id);
    assert.equal(record.scopes.length, scopes, record.id);
    assert.equal(record.canonicalImplementation, `web:legacy-runtime:${capability}`, record.id);
    assert.equal("expiresAt" in record, false, record.id);
    assert.equal("releaseLimit" in record, false, record.id);
  }
  assert.equal(expected.size, baseline.records.length);

  assert.equal(registry.records.length, 18);
  assert.equal(registry.records.flatMap((record) => record.scopes).length, 188);
  const baselineById = new Map(baseline.records.map((record) => [record.id, record]));
  const scopeKey = (scope) => [scope.path, scope.rule, scope.resource, scope.operation].join("\0");
  for (const record of registry.records) {
    const frozen = baselineById.get(record.id);
    assert.ok(frozen, `${record.id} exists in the immutable baseline`);
    assert.equal(record.kind, "legacy-facade", record.id);
    assert.equal(record.capability, frozen.capability, record.id);
    assert.equal(record.removalIssue, frozen.removalIssue, record.id);
    assert.equal(record.canonicalImplementation, frozen.canonicalImplementation, record.id);
    const frozenScopes = new Set(frozen.scopes.map(scopeKey));
    assert.ok(record.scopes.every((scope) => frozenScopes.has(scopeKey(scope))), record.id);
    assert.equal("expiresAt" in record, false, record.id);
    assert.equal("releaseLimit" in record, false, record.id);
  }
  assert.deepEqual(
    new Set(baseline.records
      .map((record) => record.id)
      .filter((id) => !registry.records.some((record) => record.id === id))),
    new Set([
      "compat-company-onboarding-persistence",
      "compat-owner-dividend-persistence",
    ]),
  );
});

test("company cancellation lifecycle is capability-owned with no direct-web compatibility", () => {
  const catalog = JSON.parse(readFileSync(
    new URL("../architecture/database-catalog.json", import.meta.url),
    "utf8",
  ));
  const backendModule = JSON.parse(readFileSync(new URL(
    "../apps/backend/src/talli_backend/modules/company_access/module.json",
    import.meta.url,
  ), "utf8"));
  const webModule = JSON.parse(readFileSync(new URL(
    "../apps/web/features/company-access/module.json",
    import.meta.url,
  ), "utf8"));
  const byTable = new Map(catalog.tables.map((table) => [table.name, table]));

  for (const table of ["public.company_cancellations", "public.company_deletion_reviews"]) {
    assert.deepEqual(byTable.get(table), {
      name: table,
      kind: "capability-business",
      owner: "backend:company_access",
    });
    assert.ok(backendModule.owns.tables.includes(table));
  }
  for (const operation of [
    "companyAccessListCancellations",
    "companyAccessRequestCancellation",
    "companyAccessResumeCancellation",
    "companyAccessReviewDeletion",
    "companyAccessFinalizeDeletion",
  ]) {
    assert.ok(webModule.apiOperations.includes(operation));
  }
});

test("anonymous object methods fail closed without merging separate call sites", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-anonymous-methods-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixture = "apps/web/app/anonymous-object-methods.ts";
  writeFileSync(join(temporaryRoot, fixture), `
import { createClient } from "@supabase/supabase-js";
const client = createClient("https://example.invalid", "public-key");
function consume(_value) {}
consume({ handler() { client.from("companies"); } });
consume({ handler() { client.from("companies"); } });
`);
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  compatibility.records[0].scopes.push({
    path: fixture,
    rule: "direct-web-business-persistence",
    resource: "table:companies",
    operation: "handler",
  });
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.equal(
      errors.match(new RegExp(`${fixture}: direct web business persistence is forbidden for table:companies in operation:<unscoped>`, "gu"))?.length,
      2,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility scopes match the exact enclosing operation", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-operation-scope-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixture = "apps/web/app/operation-scoped-persistence.ts";
  writeFileSync(join(temporaryRoot, fixture), `
import { createClient } from "@supabase/supabase-js";
const client = createClient("https://example.invalid", "public-key");
export async function onboardCompany() {
  await Promise.resolve().then(() => client.from("companies"));
}
export async function cancelCompany() { client.from("companies"); }
export async function unregisteredCompany() { client.from("companies"); }
Promise.resolve().then(() => client.from("documents"));
`);
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  compatibility.records.push(activeStageDebt({ scopes: [
    {
      path: fixture,
      rule: "direct-web-business-persistence",
      resource: "table:companies",
      operation: "onboardCompany",
    },
    {
      path: fixture,
      rule: "direct-web-business-persistence",
      resource: "table:companies",
      operation: "cancelCompany",
    },
  ] }));
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.doesNotMatch(errors, /operation:onboardCompany/u);
    assert.doesNotMatch(errors, /operation:cancelCompany/u);
    assert.match(errors, new RegExp(`${fixture}.*table:companies.*operation:unregisteredCompany`, "u"));
    assert.match(errors, new RegExp(`${fixture}.*table:documents.*operation:<unscoped>`, "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility scopes cannot overlap across future tickets", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-operation-overlap-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const primary = compatibility.records.find((entry) => entry.removalIssue === "#139");
  const secondary = compatibility.records.find((entry) => entry.removalIssue === "#140");
  const duplicateScope = {
    path: "apps/web/app/actions.ts",
    rule: "direct-web-business-persistence",
    resource: "table:company_memberships",
    operation: "inviteWorkspaceMemberAction",
  };
  primary.scopes.push(duplicateScope);
  secondary.scopes.push(duplicateScope);
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /duplicate compatibility scope.*#139.*#140/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility registry is complete in both directions", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-operation-completeness-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const ledger = compatibility.records.find((entry) => entry.removalIssue === "#139");
  const missingScope = ledger.scopes[0];
  assert.ok(missingScope);
  ledger.scopes = ledger.scopes.filter((scope) => scope !== missingScope);
  ledger.scopes.push({
    path: "apps/web/app/actions.ts",
    rule: "direct-web-business-persistence",
    resource: "table:companies",
    operation: "nonexistentCompanyOperation",
  });
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(
      errors,
      new RegExp(
        `${missingScope.path.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")}: direct web business persistence is forbidden for ${missingScope.resource.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")} in operation:${missingScope.operation}`,
        "u",
      ),
    );
    assert.match(
      errors,
      /registered compatibility scope has no matching finding: .*operation:nonexistentCompanyOperation/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("web boundary detection follows client provenance without flagging ordinary from methods", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-receiver-provenance-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const adversarialPath = "apps/web/app/receiver-bypass.ts";
  const namespaceFactoryPath = "apps/web/app/namespace-factory-bypass.ts";
  const platformAliasPath = "apps/web/app/platform-fetch-bypass.ts";
  const benignPath = "apps/web/app/ordinary-from.ts";
  writeFileSync(
    join(temporaryRoot, adversarialPath),
    `import { createClient as buildDatabase } from "@supabase/supabase-js";
const db = buildDatabase("https://example.invalid", "public-key");
db.from("companies");
const input = { gateway: db };
input.gateway.rpc("post_entry");
globalThis.fetch("/api/v1/companies");
`,
  );
  writeFileSync(
    join(temporaryRoot, namespaceFactoryPath),
    `import * as Supabase from "@supabase/supabase-js";
const namespaceDb = Supabase.createClient("https://example.invalid", "public-key");
namespaceDb.from("companies");
`,
  );
  writeFileSync(
    join(temporaryRoot, platformAliasPath),
    `const platform = globalThis;
platform.fetch("/api/v1/companies");
`,
  );
  writeFileSync(
    join(temporaryRoot, benignPath),
    `const supabase = { from(value: string) { return value; } };
supabase.from("not-persistence");
`,
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    const escapedAdversarialPath = adversarialPath.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
    assert.match(errors, new RegExp(`${escapedAdversarialPath}: direct web business persistence is forbidden`, "u"));
    assert.match(errors, new RegExp(`${escapedAdversarialPath}: direct business fetch is forbidden`, "u"));
    assert.match(errors, new RegExp(`${namespaceFactoryPath}: direct web business persistence is forbidden`, "u"));
    assert.match(errors, new RegExp(`${platformAliasPath}: direct business fetch is forbidden`, "u"));
    assert.doesNotMatch(errors, new RegExp(benignPath.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("web boundary analysis follows compiler bindings, type aliases, and callable aliases", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-binding-provenance-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const violations = {
    "type-alias-client.ts": `import type { SupabaseClient as DatabaseClient } from "@supabase/supabase-js";
type ClientAlias = DatabaseClient;
type NestedAlias = ClientAlias;
function query(client: NestedAlias) { client.from("companies"); }
`,
    "typed-client-property.ts": `import type { SupabaseClient as DatabaseClient } from "@supabase/supabase-js";
type ClientAlias = DatabaseClient;
type Input = { gateway: ClientAlias };
function query(input: Input) { input.gateway.rpc("post_entry"); }
`,
    "namespace-client-type.ts": `import type * as Supabase from "@supabase/supabase-js";
function query(client: Supabase.SupabaseClient) { client.from("companies"); }
`,
    "class-client-property.ts": `import type * as Supabase from "@supabase/supabase-js";
class Repository {
  declare readonly client: Supabase.SupabaseClient;
  query() { this.client.rpc("post_entry"); }
}
`,
    "factory-property-declaration.ts": `import * as Supabase from "@supabase/supabase-js";
const build = Supabase.createClient;
build("https://example.invalid", "public-key").from("companies");
`,
    "factory-property-assignment.ts": `import * as Supabase from "@supabase/supabase-js";
let build;
build = Supabase.createClient;
build("https://example.invalid", "public-key").rpc("post_entry");
`,
    "factory-property-destructure.ts": `import * as Supabase from "@supabase/supabase-js";
const { createClient: build } = Supabase;
build("https://example.invalid", "public-key").from("companies");
`,
    "factory-property-destructure-assignment.ts": `import * as Supabase from "@supabase/supabase-js";
let build;
({ createClient: build } = Supabase);
build("https://example.invalid", "public-key").from("companies");
`,
    "fetch-property-declaration.ts": `const request = globalThis.fetch;
request("/api/v1/companies");
`,
    "fetch-property-assignment.ts": `let request;
request = window.fetch;
request("/api/v1/companies");
`,
    "fetch-property-destructure.ts": `const { fetch: request } = globalThis;
request("/api/v1/companies");
`,
    "fetch-property-destructure-assignment.ts": `let request;
({ fetch: request } = globalThis);
request("/api/v1/companies");
`,
  };
  for (const [name, source] of Object.entries(violations)) {
    writeFileSync(join(temporaryRoot, "apps/web/app", name), source);
  }

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    for (const name of [
      "type-alias-client.ts",
      "typed-client-property.ts",
      "namespace-client-type.ts",
      "class-client-property.ts",
      "factory-property-declaration.ts",
      "factory-property-assignment.ts",
      "factory-property-destructure.ts",
      "factory-property-destructure-assignment.ts",
    ]) {
      assert.match(errors, new RegExp(`${name}: direct web business persistence is forbidden`, "u"));
    }
    for (const name of [
      "fetch-property-declaration.ts",
      "fetch-property-assignment.ts",
      "fetch-property-destructure.ts",
      "fetch-property-destructure-assignment.ts",
    ]) {
      assert.match(errors, new RegExp(`${name}: direct business fetch is forbidden`, "u"));
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("web boundary analysis preserves persistence and fetch provenance across imports and re-exports", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-cross-module-provenance-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixtures = {
    "provenance-source.ts": `import { createClient } from "@supabase/supabase-js";
export const database = createClient("https://example.invalid", "public-key");
export const request = globalThis.fetch;
`,
    "provenance-barrel.ts": `export { database, request } from "./provenance-source";
`,
    "persistence-direct-consumer.ts": `import { database } from "./provenance-source";
database.from("companies");
`,
    "persistence-reexport-consumer.ts": `import { database } from "./provenance-barrel";
database.rpc("post_entry");
`,
    "fetch-direct-consumer.ts": `import { request } from "./provenance-source";
request("/api/v1/companies");
`,
    "fetch-reexport-consumer.ts": `import { request } from "./provenance-barrel";
request("/api/v1/companies");
`,
  };
  for (const [name, source] of Object.entries(fixtures)) {
    writeFileSync(join(temporaryRoot, "apps/web/app", name), source);
  }

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    for (const name of ["persistence-direct-consumer.ts", "persistence-reexport-consumer.ts"]) {
      assert.match(errors, new RegExp(`${name}: direct web business persistence is forbidden`, "u"));
    }
    for (const name of ["fetch-direct-consumer.ts", "fetch-reexport-consumer.ts"]) {
      assert.match(errors, new RegExp(`${name}: direct business fetch is forbidden`, "u"));
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("web boundary analysis permits local fetch bindings and non-import generated-client text", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-binding-false-positives-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const benignPath = "apps/web/app/binding-false-positives.ts";
  writeFileSync(
    join(temporaryRoot, benignPath),
    `function fetch(input: string) { return input; }
fetch("/api/v1/local");
function invoke(fetch: (input: string) => string) { return fetch("/api/v1/parameter"); }
const documentation = "@talli/talli-api-client/src/generated/client.ts";
// import "@talli/talli-api-client/src/generated/comment.ts";
function require(specifier: string) { return specifier; }
require("@talli/talli-api-client/src/generated/locally-shadowed-require.ts");
`,
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.doesNotMatch(errors, new RegExp(benignPath.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("generated-client deep imports are detected from every executable module-specifier form", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-generated-imports-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixtures = {
    "generated-import.ts": 'import "@talli/talli-api-client/src/generated/import.ts";\n',
    "generated-export.ts": 'export * from "@talli/talli-api-client/src/generated/export.ts";\n',
    "generated-require.ts": 'require("@talli/talli-api-client/src/generated/require.ts");\n',
    "generated-require-alias.ts": `const load = require;
load("@talli/talli-api-client/src/generated/require-alias.ts");
`,
    "generated-require-assignment-alias.ts": `let load;
load = require;
load("@talli/talli-api-client/src/generated/require-assignment-alias.ts");
`,
    "generated-dynamic-import.ts": 'void import("@talli/talli-api-client/src/generated/dynamic.ts");\n',
  };
  for (const [name, source] of Object.entries(fixtures)) {
    writeFileSync(join(temporaryRoot, "apps/web/app", name), source);
  }

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    for (const name of Object.keys(fixtures)) {
      assert.match(errors, new RegExp(`${name}: generated-client deep import is forbidden`, "u"));
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("generated-client deep imports reject ambiguous same-ticket exceptions", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-generated-ambiguity-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const fixture = "apps/web/app/generated-ambiguity.ts";
  writeFileSync(
    join(temporaryRoot, fixture),
    'import "@talli/talli-api-client/src/generated/ambiguous.ts";\n',
  );
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const scope = {
    path: fixture,
    rule: "generated-client-deep-import",
    resource: "module:@talli/talli-api-client/*",
    operation: "module",
  };
  compatibility.records.push({
    ...compatibility.records[0],
    id: "compat-billing-persistence-duplicate",
    scopes: [scope],
  });
  compatibility.records[0].scopes.push(scope);
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /duplicate compatibility scope.*#137.*#137/u);
    assert.match(errors, new RegExp(`${fixture}: generated-client deep import has ambiguous compatibility`, "u"));
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("adapter bindings require source registration against the declared port", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-port-registration-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const modulePath = join(
    temporaryRoot,
    "apps/backend/src/talli_backend/modules/system_boundary/module.json",
  );
  const module = JSON.parse(readFileSync(modulePath, "utf8"));
  module.ports[0].adapters = ["talli_backend.main._request_id"];
  writeFileSync(modulePath, JSON.stringify(module));
  const systemPath = join(temporaryRoot, "architecture/backend-system.json");
  const system = JSON.parse(readFileSync(systemPath, "utf8"));
  system.adapterBindings[0].adapter = "talli_backend.main._request_id";
  writeFileSync(systemPath, JSON.stringify(system));

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /adapter is not registered for port SystemBoundaryTransport/u);
    assert.doesNotMatch(errors, /adapter symbol does not exist/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("company access declares and injects its persistence and company-registry adapters", () => {
  const module = JSON.parse(readFileSync(new URL(
    "../apps/backend/src/talli_backend/modules/company_access/module.json",
    import.meta.url,
  ), "utf8"));
  const system = JSON.parse(readFileSync(new URL("../architecture/backend-system.json", import.meta.url), "utf8"));
  const capability = readFileSync(new URL(
    "../apps/backend/src/talli_backend/modules/company_access/public.py",
    import.meta.url,
  ), "utf8");
  const adapterUrl = new URL(
    "../apps/backend/src/talli_backend/adapters/supabase_company_access.py",
    import.meta.url,
  );
  assert.equal(existsSync(adapterUrl), true, "company-access adapter module must exist");
  const adapter = readFileSync(adapterUrl, "utf8");
  const registryAdapterUrl = new URL(
    "../apps/backend/src/talli_backend/adapters/brreg_company_registry.py",
    import.meta.url,
  );
  assert.equal(existsSync(registryAdapterUrl), true, "company-registry adapter module must exist");
  const registryAdapter = readFileSync(registryAdapterUrl, "utf8");
  const composition = readFileSync(new URL(
    "../apps/backend/src/talli_backend/main.py",
    import.meta.url,
  ), "utf8");

  assert.deepEqual(module.ports, [
    {
      name: "CompanyAccessGateway",
      direction: "outbound",
      contract: "talli_backend.modules.company_access.public.CompanyAccessGateway",
      registrationDecorator: "talli_backend.modules.company_access.public.company_access_adapter",
      adapters: ["talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter"],
    },
    {
      name: "CompanyRegistryGateway",
      direction: "outbound",
      contract: "talli_backend.modules.company_access.public.CompanyRegistryGateway",
      registrationDecorator: "talli_backend.modules.company_access.public.company_registry_adapter",
      adapters: ["talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter"],
    },
  ]);
  assert.ok(system.adapterBindings.some((binding) => (
    binding.port === "CompanyAccessGateway"
    && binding.adapter === "talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter"
  )));
  assert.doesNotMatch(capability, /urllib|SupabaseCompanyAccessAdapter|os\.environ/u);
  assert.match(adapter, /@company_access_adapter\(CompanyAccessGateway\)/u);
  assert.match(registryAdapter, /@company_registry_adapter\(CompanyRegistryGateway\)/u);
  assert.match(composition, /else SupabaseCompanyAccessAdapter\.from_environment\(\)/u);
  assert.match(composition, /company_registry_gateway or BrregCompanyRegistryAdapter\.from_environment\(\)/u);
});

test("adapter registration resolves decorator and port bindings to their declared public symbols", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-port-shadowing-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const mainPath = join(temporaryRoot, "apps/backend/src/talli_backend/main.py");
  writeFileSync(
    mainPath,
    readFileSync(mainPath, "utf8").replace(
      "@adapter_for(SystemBoundaryTransport)",
      `def adapter_for(port):
    return lambda adapter: adapter

class SystemBoundaryTransport:
    pass

@adapter_for(SystemBoundaryTransport)`,
    ),
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.match(errors, /adapter is not registered for port SystemBoundaryTransport/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("adapter registration accepts legitimate aliases of the declared public symbols", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-port-aliases-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const mainPath = join(temporaryRoot, "apps/backend/src/talli_backend/main.py");
  writeFileSync(
    mainPath,
    readFileSync(mainPath, "utf8")
      .replace("SystemBoundaryTransport,\n    adapter_for,", "SystemBoundaryTransport as BoundaryPort,\n    adapter_for as bind_adapter,")
      .replace("@adapter_for(SystemBoundaryTransport)", "@bind_adapter(BoundaryPort)"),
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    assert.doesNotMatch(errors, /adapter is not registered for port SystemBoundaryTransport/u);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("adapter registration validates the final effective top-level binding", () => {
  for (const [name, replacement] of [
    ["duplicate", "\ndef create_app():\n    return object()\n"],
    ["assignment", "\ncreate_app = lambda: object()\n"],
  ]) {
    const temporaryRoot = mkdtempSync(join(tmpdir(), `talli-architecture-port-${name}-`));
    for (const directory of ["architecture", "apps", "supabase"]) {
      cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
    }
    const mainPath = join(temporaryRoot, "apps/backend/src/talli_backend/main.py");
    writeFileSync(mainPath, `${readFileSync(mainPath, "utf8")}${replacement}`);

    try {
      const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
      assert.match(errors, /adapter is not registered for port SystemBoundaryTransport/u);
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true });
    }
  }
});

test("backend composition, rule-scoped exceptions, documentation inventories, and shared kernel are enforced", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-deep-enforcement-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const mainPath = join(temporaryRoot, "apps/backend/src/talli_backend/main.py");
  writeFileSync(
    mainPath,
    `${readFileSync(mainPath, "utf8")}
from talli_backend.modules.system_boundary.internal import secret
import fastapi, requests
import collections, talli_backend.modules.system_boundary.internal as private_module
from .modules.system_boundary import internal as relative_private
`,
  );
  const systemPath = join(temporaryRoot, "architecture/backend-system.json");
  const system = JSON.parse(readFileSync(systemPath, "utf8"));
  system.adapterBindings[0].adapter = "talli_backend.main.not_real";
  writeFileSync(systemPath, JSON.stringify(system));
  const actionsPath = join(temporaryRoot, "apps/web/app/actions.ts");
  writeFileSync(
    actionsPath,
    `${readFileSync(actionsPath, "utf8")}
fetch("/api/v1/forbidden");
import "@talli/talli-api-client/src/generated/client.ts";
`,
  );
  const publicPath = join(temporaryRoot, "apps/backend/src/talli_backend/modules/system_boundary/public.py");
  writeFileSync(
    publicPath,
    `${readFileSync(publicPath, "utf8")}
from talli_backend.shared.persistence import SharedRepository
from ..other import internal as other_internal
`,
  );
  const documentationPath = join(temporaryRoot, "apps/web/features/system-boundary/MODULE.md");
  writeFileSync(
    documentationPath,
    `${readFileSync(documentationPath, "utf8")}
<!-- architecture-inventory {"routes":["/invented-route"]} -->
`,
  );
  const backendDocumentationPath = join(temporaryRoot, "architecture/BACKEND-SYSTEM.md");
  writeFileSync(
    backendDocumentationPath,
    readFileSync(backendDocumentationPath, "utf8").replace(
      '"routes":["/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/context","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/system-boundary/tracer"]',
      '"routes":["/invented-system-route"]',
    ),
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    for (const expected of [
      "private backend module dependency",
      "undeclared composition-root dependency requests",
      "forbidden backend deep import talli_backend.modules.other",
      "adapter binding does not match declared port adapter",
      "adapter symbol does not exist",
      "apps/web/app/actions.ts: direct business fetch is forbidden",
      "apps/web/app/actions.ts: generated-client deep import is forbidden",
      "forbidden shared-kernel import",
      "documentation inventory has extra routes",
      "architecture/backend-system.json: documentation inventory is missing routes",
      "architecture/backend-system.json: documentation inventory has extra routes",
    ]) {
      assert.match(errors, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("architecture checker rejects representative forbidden boundary violations", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-rejection-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), {
      recursive: true,
    });
  }
  const webModulePath = join(
    temporaryRoot,
    "apps/web/features/system-boundary/module.json",
  );
  const webModule = JSON.parse(readFileSync(webModulePath, "utf8"));
  webModule.dependencies = [
    { module: "system-boundary", kind: "feature", imports: ["self"] },
  ];
  writeFileSync(webModulePath, JSON.stringify(webModule));
  writeFileSync(
    join(temporaryRoot, "apps/web/features/system-boundary/transport/load-system-boundary.ts"),
    `${readFileSync(join(temporaryRoot, "apps/web/features/system-boundary/transport/load-system-boundary.ts"), "utf8")}
fetch("/api/v1/forbidden");
import { createClient } from "@supabase/supabase-js";
const forbiddenPersistence = createClient("https://example.invalid", "public-key");
forbiddenPersistence.from("forbidden");
import "@talli/talli-api-client/src/generated/client.ts";
`,
  );
  writeFileSync(
    join(temporaryRoot, "apps/web/app/system-boundary/page.tsx"),
    'import { loadSystemBoundary } from "../../features/system-boundary/transport/load-system-boundary.ts";\n',
  );
  const systemPath = join(temporaryRoot, "architecture/backend-system.json");
  const system = JSON.parse(readFileSync(systemPath, "utf8"));
  system.technicalOwnership.tables = ["public.launch_signoffs"];
  writeFileSync(systemPath, JSON.stringify(system));
  writeFileSync(
    join(temporaryRoot, "apps/web/features/system-boundary/MODULE.md"),
    "# Drifted documentation\n",
  );

  try {
    const errors = checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n");
    for (const expected of [
      "direct business fetch is forbidden",
      "direct web business persistence is forbidden",
      "generated-client deep import is forbidden",
      "undeclared public feature entry point",
      "undeclared technical ownership public.notification_outbox",
      "circular module dependency",
      "documentation omits declared @/features/system-boundary",
    ]) {
      assert.match(errors, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});
