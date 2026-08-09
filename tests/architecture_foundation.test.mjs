import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  checkArchitecture,
  validateCompatibilityRegistry,
} from "../scripts/check-architecture.mjs";

const repositoryRoot = new URL("..", import.meta.url);

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
    "web:company-access",
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

test("compatibility exceptions require bounded expiry and a removal condition", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-"));
  const registry = join(temporaryRoot, "compatibility.json");
  writeFileSync(
    registry,
    JSON.stringify({
      schemaVersion: "1.0",
      exceptions: [
        {
          id: "compat-unbounded",
          owner: "backend:system_boundary",
          creationIssue: "#135",
          removalIssue: "#136",
          scopes: [{
            path: "apps/web/app/legacy.ts",
            rule: "direct-web-business-persistence",
            resource: "table:companies",
            operation: "legacyOperation",
          }],
          expiresAt: "never",
          removalCondition: "",
        },
      ],
    }),
  );

  try {
    assert.match(
      validateCompatibilityRegistry(registry).join("\n"),
      /compat-unbounded.*expiresAt.*RFC 3339/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility exceptions must expire strictly after the controlled current time", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-expiry-"));
  const registry = join(temporaryRoot, "compatibility.json");
  writeFileSync(
    registry,
    JSON.stringify({
      schemaVersion: "1.0",
      exceptions: [{
        id: "compat-expired",
        owner: "web:legacy-runtime",
        creationIssue: "#135",
        removalIssue: "#136",
        scopes: [{
          path: "apps/web/app/actions.ts",
          rule: "direct-web-business-persistence",
          resource: "table:companies",
          operation: "legacyOperation",
        }],
        expiresAt: "2026-07-29T00:00:00Z",
        removalCondition: "Remove when #136 owns the authenticated company context.",
      }],
    }),
  );
  try {
    assert.match(
      validateCompatibilityRegistry(registry, { now: new Date("2026-07-30T00:00:00Z") }).join("\n"),
      /compat-expired.*strictly in the future/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility exceptions cannot outlive fourteen days or the next stable release", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-expiry-bound-"));
  const registry = join(temporaryRoot, "compatibility.json");
  writeFileSync(
    registry,
    JSON.stringify({
      schemaVersion: "1.0",
      exceptions: [{
        id: "compat-too-distant",
        owner: "web:legacy-runtime",
        creationIssue: "#135",
        removalIssue: "#136",
        scopes: [{
          path: "apps/web/app/actions.ts",
          rule: "direct-web-business-persistence",
          resource: "table:companies",
          operation: "legacyOperation",
        }],
        approvedBy: "Kristian Elmer",
        approvedAt: "2026-07-30T00:00:00Z",
        releaseLimit: "next-stable-customer-ready-release",
        expiresAt: "2026-08-14T00:00:00Z",
        removalCondition: "Remove when #136 owns the authenticated company context.",
      }],
    }),
  );
  try {
    assert.match(
      validateCompatibilityRegistry(registry, { now: new Date("2026-07-30T00:00:00Z") }).join("\n"),
      /compat-too-distant.*fourteen days after approval/u,
    );
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("compatibility exceptions reject semantically impossible timestamps", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-invalid-timestamp-"));
  const registry = join(temporaryRoot, "compatibility.json");
  writeFileSync(
    registry,
    JSON.stringify({
      schemaVersion: "1.0",
      exceptions: [{
        id: "compat-invalid-date",
        owner: "web:legacy-runtime",
        creationIssue: "#135",
        removalIssue: "#136",
        scopes: [{
          path: "apps/web/app/actions.ts",
          rule: "direct-web-business-persistence",
          resource: "table:companies",
          operation: "legacyOperation",
        }],
        approvedBy: "Kristian Elmer",
        approvedAt: "2026-99-99T25:99:99Z",
        releaseLimit: "next-stable-customer-ready-release",
        expiresAt: "2026-99-99T25:99:99Z",
        removalCondition: "Remove when #136 owns the authenticated company context.",
      }],
    }),
  );
  try {
    const errors = validateCompatibilityRegistry(
      registry,
      { now: new Date("2026-07-30T00:00:00Z") },
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

test("a real stable customer-ready release after approval revokes the compatibility exception", () => {
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

  try {
    const errors = checkArchitecture({
      root: temporaryRoot,
      writeEvidence: false,
      now: new Date("2026-07-31T12:00:00Z"),
    }).errors.join("\n");
    assert.match(errors, /compat-company-onboarding-persistence.*superseded by stable customer-ready release customer-ready-2026-07-31/u);
    assert.match(errors, /apps\/web\/app\/actions\.ts: direct web business persistence is forbidden/u);
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

test("multiline web persistence requires an explicit rule-scoped exception", () => {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-architecture-persistence-format-"));
  for (const directory of ["architecture", "apps", "supabase"]) {
    cpSync(new URL(`../${directory}`, import.meta.url), join(temporaryRoot, directory), { recursive: true });
  }
  const route = "apps/web/app/documents/[documentId]/download/route.ts";
  const compatibilityPath = join(temporaryRoot, "architecture/compatibility.json");
  const compatibility = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  for (const exception of compatibility.exceptions) {
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
  compatibility.exceptions[0].scopes.push(exactScope);
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
    new URL("../architecture/compatibility.json", import.meta.url),
    "utf8",
  ));
  const byRemovalIssue = new Map(
    compatibility.exceptions.map((entry) => [entry.removalIssue, entry]),
  );
  const onboarding = byRemovalIssue.get("#138");
  const ownerOf = (resource, operation, path = "apps/web/app/actions.ts") => compatibility.exceptions.find((entry) => (
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
  assert.match(onboarding.removalCondition, /workspace creation.*#138/u);
  assert.deepEqual(
    onboarding.scopes.map(({ resource, operation }) => `${resource}:${operation}`).sort(),
    [
      "rpc:append_company_agreement_acceptance:reacceptCompanyAgreement",
      "rpc:create_company_workspace_with_acceptance:createWorkspace",
      "table:customer_agreement_acceptances:listCustomerAgreementAcceptances",
    ],
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
  compatibility.exceptions[0].scopes.push({
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
  const onboarding = compatibility.exceptions.find((entry) => entry.removalIssue === "#138");
  const secondary = compatibility.exceptions.find((entry) => entry.removalIssue === "#139");
  onboarding.scopes.push({
    path: fixture,
    rule: "direct-web-business-persistence",
    resource: "table:companies",
    operation: "onboardCompany",
  });
  secondary.scopes.push({
    path: fixture,
    rule: "direct-web-business-persistence",
    resource: "table:companies",
    operation: "cancelCompany",
  });
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
  const onboarding = compatibility.exceptions.find((entry) => entry.removalIssue === "#138");
  const secondary = compatibility.exceptions.find((entry) => entry.removalIssue === "#139");
  const duplicateScope = {
    path: "apps/web/app/actions.ts",
    rule: "direct-web-business-persistence",
    resource: "table:company_memberships",
    operation: "inviteWorkspaceMemberAction",
  };
  onboarding.scopes.push(duplicateScope);
  secondary.scopes.push(duplicateScope);
  writeFileSync(compatibilityPath, JSON.stringify(compatibility));

  try {
    assert.match(
      checkArchitecture({ root: temporaryRoot, writeEvidence: false }).errors.join("\n"),
      /duplicate compatibility scope.*#138.*#139/u,
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
  const onboarding = compatibility.exceptions.find((entry) => entry.removalIssue === "#138");
  const missingScope = onboarding.scopes.find((scope) => (
    scope.path === "apps/web/app/actions.ts"
    && scope.resource === "rpc:create_company_workspace_with_acceptance"
    && scope.operation === "createWorkspace"
  ));
  assert.ok(missingScope);
  onboarding.scopes = onboarding.scopes.filter((scope) => scope !== missingScope);
  onboarding.scopes.push({
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
      /actions\.ts: direct web business persistence is forbidden for rpc:create_company_workspace_with_acceptance in operation:createWorkspace/u,
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
  compatibility.exceptions.push({
    ...compatibility.exceptions[0],
    id: "compat-billing-persistence-duplicate",
    scopes: [scope],
  });
  compatibility.exceptions[0].scopes.push(scope);
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

test("company access declares and injects its Supabase port adapter", () => {
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
  const composition = readFileSync(new URL(
    "../apps/backend/src/talli_backend/main.py",
    import.meta.url,
  ), "utf8");

  assert.deepEqual(module.ports, [{
    name: "CompanyAccessGateway",
    direction: "outbound",
    contract: "talli_backend.modules.company_access.public.CompanyAccessGateway",
    registrationDecorator: "talli_backend.modules.company_access.public.company_access_adapter",
    adapters: ["talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter"],
  }]);
  assert.ok(system.adapterBindings.some((binding) => (
    binding.port === "CompanyAccessGateway"
    && binding.adapter === "talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter"
  )));
  assert.doesNotMatch(capability, /urllib|SupabaseCompanyAccessAdapter|os\.environ/u);
  assert.match(adapter, /@company_access_adapter\(CompanyAccessGateway\)/u);
  assert.match(composition, /else SupabaseCompanyAccessAdapter\.from_environment\(\)/u);
  assert.match(composition, /CompanyAccessService\(gateway\)/u);
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
