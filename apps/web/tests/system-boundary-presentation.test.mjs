import assert from "node:assert/strict";
import test from "node:test";

import {
  presentSystemBoundaryFailure,
  presentSystemBoundarySuccess,
} from "../features/system-boundary/view-models/presentation.ts";
import {
  createTalliApiClient,
  TalliApiError,
} from "@talli/talli-api-client";
import {
  BackendConfigurationError,
  backendBaseUrl,
} from "../features/system-boundary/transport/load-system-boundary.ts";
import { GET as liveness } from "../app/health/live/route.ts";
import { GET as readiness } from "../app/health/ready/route.ts";

async function withBackendEnvironment(value, callback) {
  const previous = process.env.TALLI_BACKEND_URL;
  if (value === undefined) {
    delete process.env.TALLI_BACKEND_URL;
  } else {
    process.env.TALLI_BACKEND_URL = value;
  }
  try {
    return await callback();
  } finally {
    if (previous === undefined) {
      delete process.env.TALLI_BACKEND_URL;
    } else {
      process.env.TALLI_BACKEND_URL = previous;
    }
  }
}

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

test("generated client rejects an availability value outside the closed contract", async () => {
  const client = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () =>
      Response.json({
        apiVersion: "v1",
        service: "talli-backend",
        status: "DEGRADED",
      }),
  });

  await assert.rejects(
    client.systemBoundaryGetTracerStatus(),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});

test("missing backend configuration fails closed with a typed error", async () => {
  await withBackendEnvironment(undefined, () => {
    assert.throws(
      () => backendBaseUrl(),
      (error) =>
        error instanceof BackendConfigurationError &&
        error.code === "BACKEND_URL_MISSING",
    );
  });
});

test("web liveness stays process-only while readiness fails invalid configuration", async () => {
  await withBackendEnvironment("not a url", async () => {
    const liveResponse = liveness();
    const readyResponse = await readiness();

    assert.equal(liveResponse.status, 200);
    assert.deepEqual(await liveResponse.json(), { status: "alive" });
    assert.equal(readyResponse.status, 503);
    assert.deepEqual(await readyResponse.json(), { status: "not_ready" });
  });
});

test("web readiness validates local configuration without depending on backend reachability", async () => {
  await withBackendEnvironment("http://127.0.0.1:1", async () => {
    const readyResponse = await readiness();

    assert.equal(readyResponse.status, 200);
    assert.deepEqual(await readyResponse.json(), { status: "ready" });
  });
});
