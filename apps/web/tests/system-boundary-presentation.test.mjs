import assert from "node:assert/strict";
import test from "node:test";

import {
  presentSystemBoundaryFailure,
  presentSystemBoundarySuccess,
} from "../features/system-boundary/view-models/presentation.ts";
import {
  createTalliApiClient,
  TalliApiError,
} from "../../../packages/talli-api-client/src/generated/client.ts";

test("presents the generated tracer response as a safe Norwegian success", () => {
  assert.deepEqual(
    presentSystemBoundarySuccess({
      apiVersion: "v1",
      service: "talli-backend",
      status: "AVAILABLE",
    }),
    {
      heading: "Forbindelsen virker",
      message: "Talli-nettsiden har kontakt med backend-tjenesten.",
      tone: "success",
    },
  );
});

test("presents transport failures without leaking exception details", () => {
  assert.deepEqual(
    presentSystemBoundaryFailure(
      new Error("connect ECONNREFUSED 127.0.0.1:8000"),
      "request-134",
    ),
    {
      heading: "Tjenesten er midlertidig utilgjengelig",
      message:
        "Prøv igjen om litt. Oppgi referansen request-134 hvis problemet fortsetter.",
      tone: "failure",
    },
  );
});

test("generated client accepts the declared success shape", async () => {
  const client = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () =>
      Response.json({
        apiVersion: "v1",
        service: "talli-backend",
        status: "AVAILABLE",
      }),
  });

  assert.equal(
    (await client.systemBoundaryGetTracerStatus()).status,
    "AVAILABLE",
  );
});

test("generated client fails closed on an undeclared success shape", async () => {
  const client = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json({ status: "AVAILABLE" }),
  });

  await assert.rejects(
    client.systemBoundaryGetTracerStatus(),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});
