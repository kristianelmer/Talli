import assert from "node:assert/strict";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  checkArchitecture,
  validateCompatibilityRegistry,
} from "../scripts/check-architecture.mjs";

const repositoryRoot = new URL("..", import.meta.url);

test("architecture manifests, scoped documentation, and dependency evidence agree", () => {
  const result = checkArchitecture({ root: repositoryRoot, writeEvidence: false });

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.evidence.modules, ["backend:system_boundary", "web:system-boundary"]);
  assert.deepEqual(result.evidence.edges, [
    {
      from: "backend-system:system-boundary-tracer",
      imports: ["talli_backend.modules.system_boundary.public"],
      kind: "workflow",
      to: "backend:system_boundary",
    },
  ]);
  assert.equal(existsSync(new URL("../architecture/module.schema.json", import.meta.url)), true);
  assert.equal(existsSync(new URL("../architecture/backend-system.schema.json", import.meta.url)), true);
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
          paths: ["apps/backend/src/talli_backend/legacy.py"],
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
        paths: ["apps/web/app/actions.ts"],
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
    exception.paths = exception.paths.filter((path) => path !== route);
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
      '"routes":["/api/v1/system-boundary/tracer"]',
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
const forbiddenPersistence = createSupabaseBoundaryClient();
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
