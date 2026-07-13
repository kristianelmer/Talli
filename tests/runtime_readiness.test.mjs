import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { evaluateRuntimeReadiness } from "../app/lib/runtime-readiness.ts";

async function withRuntimeFixture(run) {
  const root = await mkdtemp(path.join(os.tmpdir(), "talli-runtime-"));
  const pythonBin = path.join(root, "python");
  const schemaRoot = path.join(root, "docs", "filing");
  await mkdir(schemaRoot, { recursive: true });
  await writeFile(pythonBin, "#!/bin/sh\nexit 0\n", "utf8");
  await chmod(pythonBin, 0o700);
  await Promise.all([
    writeFile(path.join(schemaRoot, "aksjonaerregisteroppgaveHovedskjema.xsd"), "<schema />", "utf8"),
    writeFile(path.join(schemaRoot, "aksjonaerregisteroppgaveUnderskjema.xsd"), "<schema />", "utf8"),
  ]);
  try {
    await run({ root, pythonBin });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("runtime is ready only when configuration and filing dependencies are present", async () => {
  await withRuntimeFixture(async ({ root, pythonBin }) => {
    const readiness = await evaluateRuntimeReadiness({
      root,
      env: {
        SUPABASE_URL: "https://example.supabase.co",
        SUPABASE_ANON_KEY: "publishable-key",
        TALLI_PYTHON_BIN: pythonBin,
      },
    });

    assert.deepEqual(readiness, {
      status: "ready",
      checks: {
        configuration: { status: "ok" },
        python: { status: "ok" },
        schemas: { status: "ok" },
      },
    });
  });
});

test("runtime readiness fails closed and exposes only stable reason codes", async () => {
  const readiness = await evaluateRuntimeReadiness({ env: {}, root: "/missing/talli" });

  assert.equal(readiness.status, "not_ready");
  assert.deepEqual(readiness.checks, {
    configuration: { status: "failed", reason: "missing_supabase_configuration" },
    python: { status: "failed", reason: "python_runtime_unavailable" },
    schemas: { status: "failed", reason: "rf1086_schemas_unavailable" },
  });
});
