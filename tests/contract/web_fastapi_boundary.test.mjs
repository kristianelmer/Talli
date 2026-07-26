import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

const contractPath = new URL("../../contracts/openapi/talli-v1.json", import.meta.url);
const generatedClientPath = new URL(
  "../../packages/talli-api-client/src/generated/client.ts",
  import.meta.url,
);
const transportPath = new URL(
  "../../apps/web/features/system-boundary/transport/load-system-boundary.ts",
  import.meta.url,
);

test("the committed contract exposes one stable capability-prefixed tracer operation", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/system-boundary/tracer"].get;

  assert.equal(contract.openapi.startsWith("3.1."), true);
  assert.equal(contract.info.version, "1.0.0");
  assert.equal(operation.operationId, "systemBoundaryGetTracerStatus");
});

test("OpenAPI and generated TypeScript artifacts are byte-clean", () => {
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      "apps/backend",
      "python",
      "apps/backend/scripts/generate_openapi.py",
      "--check",
    ],
    { stdio: "pipe" },
  );
  execFileSync("node", ["scripts/generate-api-client.mjs", "--check"], {
    stdio: "pipe",
  });
});

test("the generated client is committed and carries its provenance marker", () => {
  const generatedClient = readFileSync(generatedClientPath, "utf8");

  assert.match(generatedClient, /Generated from contracts\/openapi\/talli-v1\.json/);
  assert.match(generatedClient, /systemBoundaryGetTracerStatus/);
  assert.doesNotMatch(generatedClient, /ECONNREFUSED|Forbindelsen virker/);
});

test("the web tracer uses the generated package through a thin transport wrapper", () => {
  const transport = readFileSync(transportPath, "utf8");

  assert.match(transport, /from "@talli\/talli-api-client"/);
  assert.match(transport, /systemBoundaryGetTracerStatus/);
  assert.doesNotMatch(transport, /\bfetch\s*\(/);
  assert.doesNotMatch(transport, /AVAILABLE|Forbindelsen virker/);
});
