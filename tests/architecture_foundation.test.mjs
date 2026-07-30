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
createClient();
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
