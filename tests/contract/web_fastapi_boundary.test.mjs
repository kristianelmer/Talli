import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assertCompatible,
  assertContractPackageVersion,
  validateOpenApiDocument,
} from "../../scripts/check-openapi-contract.mjs";

const contractPath = new URL("../../contracts/openapi/talli-v1.json", import.meta.url);
const baselinePath = new URL(
  "../../contracts/openapi/baselines/talli-v1.0.0.json",
  import.meta.url,
);
const generatedClientPath = new URL(
  "../../packages/talli-api-client/src/generated/client.ts",
  import.meta.url,
);
const generatedClientPackagePath = new URL(
  "../../packages/talli-api-client/package.json",
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

test("the tracer contract declares optional request and response correlation headers", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = contract.paths["/api/v1/system-boundary/tracer"].get;
  const requestId = operation.parameters.find(
    (parameter) => parameter.in === "header" && parameter.name === "X-Request-ID",
  );

  assert.equal(requestId.required, false);
  assert.equal(requestId.schema.type, "string");
  for (const status of ["200", "500", "503"]) {
    assert.equal(operation.responses[status].headers["X-Request-ID"].schema.type, "string");
  }
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

test("the OpenAPI document validates and operation IDs are globally unique", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  validateOpenApiDocument(contract);

  const duplicate = structuredClone(contract);
  duplicate.paths["/duplicate"] = {
    get: structuredClone(duplicate.paths["/api/v1/system-boundary/tracer"].get),
  };
  assert.throws(
    () => validateOpenApiDocument(duplicate),
    /duplicate operationId systemBoundaryGetTracerStatus/,
  );
});

test("the current response contract remains compatible with the explicit v1 baseline", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const current = JSON.parse(readFileSync(contractPath, "utf8"));

  assert.doesNotThrow(() => assertCompatible(baseline, current));

  const breaking = structuredClone(current);
  breaking.components.schemas.SystemBoundaryStatus.required =
    breaking.components.schemas.SystemBoundaryStatus.required.filter(
      (property) => property !== "status",
    );
  delete breaking.components.schemas.SystemBoundaryStatus.properties.status;

  assert.throws(
    () => assertCompatible(baseline, breaking),
    /response property SystemBoundaryStatus.status was removed/,
  );

  const changedLiteral = structuredClone(current);
  changedLiteral.components.schemas.SystemBoundaryStatus.properties.status.const =
    "UNAVAILABLE";
  assert.throws(
    () => assertCompatible(baseline, changedLiteral),
    /SystemBoundaryStatus\.status changed const/,
  );
});

test("compatibility rejects newly required parameters and request bodies", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const requiredParameter = JSON.parse(readFileSync(contractPath, "utf8"));
  const operation = requiredParameter.paths["/api/v1/system-boundary/tracer"].get;
  operation.parameters = [
    ...(operation.parameters ?? []),
    { in: "query", name: "requiredFilter", required: true, schema: { type: "string" } },
  ];
  assert.throws(
    () => assertCompatible(baseline, requiredParameter),
    /systemBoundaryGetTracerStatus added required parameter query requiredFilter/,
  );

  const requiredBody = JSON.parse(readFileSync(contractPath, "utf8"));
  requiredBody.paths["/api/v1/system-boundary/tracer"].get.requestBody = {
    required: true,
    content: { "application/json": { schema: { type: "object", properties: {} } } },
  };
  assert.throws(
    () => assertCompatible(baseline, requiredBody),
    /systemBoundaryGetTracerStatus made the request body required/,
  );

  const removedCorrelationHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  removedCorrelationHeader.paths["/api/v1/system-boundary/tracer"].get.parameters = [];
  assert.throws(
    () => assertCompatible(baseline, removedCorrelationHeader),
    /systemBoundaryGetTracerStatus removed parameter header X-Request-ID/,
  );

  const changedCorrelationHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  changedCorrelationHeader.paths[
    "/api/v1/system-boundary/tracer"
  ].get.parameters[0].schema.type = "integer";
  assert.throws(
    () => assertCompatible(baseline, changedCorrelationHeader),
    /systemBoundaryGetTracerStatus parameter header X-Request-ID changed schema/,
  );
});

test("compatibility rejects narrower authentication requirements", () => {
  const publicBaseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const newlyProtected = JSON.parse(readFileSync(contractPath, "utf8"));
  newlyProtected.components.securitySchemes = {
    bearerAuth: { type: "http", scheme: "bearer" },
  };
  newlyProtected.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: [] },
  ];
  assert.throws(
    () => assertCompatible(publicBaseline, newlyProtected),
    /systemBoundaryGetTracerStatus changed authentication requirements incompatibly/,
  );

  const alternativeBaseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  alternativeBaseline.components.securitySchemes = {
    bearerAuth: { type: "http", scheme: "bearer" },
    serviceKey: { type: "apiKey", in: "header", name: "X-Service-Key" },
  };
  alternativeBaseline.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: [] },
    { serviceKey: [] },
  ];
  const narrowed = structuredClone(alternativeBaseline);
  narrowed.paths["/api/v1/system-boundary/tracer"].get.security = [
    { bearerAuth: ["tracer:read"] },
  ];
  assert.throws(
    () => assertCompatible(alternativeBaseline, narrowed),
    /systemBoundaryGetTracerStatus changed authentication requirements incompatibly/,
  );

  const changedScheme = structuredClone(alternativeBaseline);
  changedScheme.components.securitySchemes.bearerAuth = {
    type: "apiKey",
    in: "header",
    name: "Authorization",
  };
  assert.throws(
    () => assertCompatible(alternativeBaseline, changedScheme),
    /security scheme bearerAuth changed incompatibly/,
  );
});

test("compatibility rejects removed or changed response headers", () => {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const removedHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  delete removedHeader.paths["/api/v1/system-boundary/tracer"].get.responses[
    "200"
  ].headers["X-Request-ID"];
  assert.throws(
    () => assertCompatible(baseline, removedHeader),
    /systemBoundaryGetTracerStatus response 200 removed header X-Request-ID/,
  );

  const changedHeader = JSON.parse(readFileSync(contractPath, "utf8"));
  changedHeader.paths["/api/v1/system-boundary/tracer"].get.responses[
    "200"
  ].headers["X-Request-ID"].schema.type = "integer";
  assert.throws(
    () => assertCompatible(baseline, changedHeader),
    /systemBoundaryGetTracerStatus response 200 header X-Request-ID changed schema/,
  );
});

test("the generated package version matches the OpenAPI contract version", () => {
  const contract = JSON.parse(readFileSync(contractPath, "utf8"));
  const packageManifest = JSON.parse(
    readFileSync(generatedClientPackagePath, "utf8"),
  );

  assert.doesNotThrow(() =>
    assertContractPackageVersion(contract, packageManifest),
  );

  const nextMajor = structuredClone(contract);
  nextMajor.info.version = "2.0.0";
  assert.throws(
    () => assertContractPackageVersion(nextMajor, packageManifest),
    /contract version 2\.0\.0 does not match client package version 1\.0\.0/,
  );
});

test("the generated client is committed and carries its provenance marker", () => {
  const generatedClient = readFileSync(generatedClientPath, "utf8");

  assert.match(generatedClient, /Generated from contracts\/openapi\/talli-v1\.json/);
  assert.match(generatedClient, /systemBoundaryGetTracerStatus/);
  assert.match(generatedClient, /requestId\?: string/);
  assert.doesNotMatch(generatedClient, /ECONNREFUSED|Forbindelsen virker/);
});

test("the web tracer uses the generated package through a thin transport wrapper", () => {
  const transport = readFileSync(transportPath, "utf8");

  assert.match(transport, /from "@talli\/talli-api-client"/);
  assert.match(transport, /systemBoundaryGetTracerStatus/);
  assert.doesNotMatch(transport, /X-Request-ID/);
  assert.doesNotMatch(transport, /\bfetch\s*\(/);
  assert.doesNotMatch(transport, /AVAILABLE|Forbindelsen virker/);
});
