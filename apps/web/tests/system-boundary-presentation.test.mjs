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

test("generated client maps the typed correlation option to the declared header", async () => {
  let capturedRequest;
  const client = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async (_url, request) => {
      capturedRequest = request;
      return Response.json(
        { apiVersion: "v1", service: "talli-backend", status: "AVAILABLE" },
        { headers: { "X-Request-ID": "request-134" } },
      );
    },
  });

  await client.systemBoundaryGetTracerStatus({ requestId: "request-134" });

  assert.equal(new Headers(capturedRequest.headers).get("X-Request-ID"), "request-134");
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




import { createReadinessProbe } from "../features/system-boundary/transport/readiness.ts";
import { createServer } from "node:http";
import { once } from "node:events";

const settings = { external: { email: true }, disable_signup: false };
const healthConfig = () => ({ backend: "https://backend.example", auth: "https://auth.example", key: "actual-anon" });
const goodResponse = (url) => Response.json(url.endsWith("/settings") ? settings : { status: "ready" });

test("readiness probes backend health and actual Auth settings/key concurrently, caching success and failure", async () => {
  for (const available of [true, false]) {
    const calls = [];
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    const probe = createReadinessProbe({ configuration: healthConfig, cacheMs: 15, fetch: async (url, options) => {
      calls.push(url);
      assert.equal(options.cache, "no-store");
      assert.equal(options.redirect, "error");
      if (url.endsWith("/settings")) assert.equal(options.headers.apikey, "actual-anon");
      await gate;
      return available ? goodResponse(url) : new Response("secret upstream detail", { status: 503 });
    } });
    const batch = [probe(), probe(), probe()];
    assert.equal(calls.length, 2);
    release();
    assert.deepEqual(await Promise.all(batch), [available, available, available]);
    assert.equal(await probe(), available);
    assert.equal(calls.length, 2);
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(await probe(), available);
    assert.equal(calls.length, 4);
  }
});

for (const failure of ["dns", "backend503", "invalid-key", "malformed", "oversized", "redirect", "wrong-shape", "wrong-content-type"]) {
  test(`readiness rejects ${failure} without diagnostics`, async () => {
    const probe = createReadinessProbe({ configuration: healthConfig, fetch: async (url) => {
      if (failure === "dns") throw new Error("secret.example DNS failed");
      if (failure === "backend503" && url.endsWith("/ready")) return new Response("secret", { status: 503 });
      if (!url.endsWith("/settings")) return goodResponse(url);
      if (failure === "invalid-key") return new Response("Invalid API key secret", { status: 401 });
      if (failure === "malformed") return new Response("{", { headers: { "Content-Type": "application/json" } });
      if (failure === "oversized") return new Response(JSON.stringify(settings) + " ".repeat(16_384), { headers: { "Content-Type": "application/json" } });
      if (failure === "redirect") return new Response(null, { status: 302, headers: { Location: "https://elsewhere.example" } });
      if (failure === "wrong-shape") return Response.json({ status: "healthy" });
      if (failure === "wrong-content-type") return new Response(JSON.stringify(settings));
      return goodResponse(url);
    } });
    assert.equal(await probe(), false);
  });
}

test("deadline bounds a backend timeout, aborts both checks, and caches the failure", async () => {
  const signals = [];
  let calls = 0;
  const probe = createReadinessProbe({ configuration: healthConfig, deadlineMs: 15, fetch: async (_url, options) => {
    calls += 1;
    signals.push(options.signal);
    return new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
  } });
  assert.equal(await probe(), false);
  assert.equal(calls, 2);
  assert.ok(signals.every((signal) => signal.aborted));
  assert.equal(await probe(), false);
  assert.equal(calls, 2);
});

test("oversized streaming responses are cancelled", async () => {
  let cancelled = false;
  const probe = createReadinessProbe({ configuration: healthConfig, fetch: async (url) => {
    if (!url.endsWith("/settings")) return goodResponse(url);
    return new Response(new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(16_385)); },
      cancel() { cancelled = true; },
    }), { headers: { "Content-Type": "application/json" } });
  } });
  assert.equal(await probe(), false);
  assert.equal(cancelled, true);
});

test("real HTTP probes reject invalid keys, redirects, and backend outage despite healthy Auth", async () => {
  let redirected = false;
  const server = createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.url === "/health/ready") return response.end(JSON.stringify({ status: "ready" }));
    if (request.url === "/auth/v1/settings" && request.headers.apikey === "actual-anon") return response.end(JSON.stringify(settings));
    if (request.url === "/auth/v1/settings" && request.headers.apikey === "redirect") {
      response.writeHead(302, { Location: "/redirect-target" });
      return response.end();
    }
    if (request.url === "/redirect-target") redirected = true;
    response.writeHead(401);
    response.end(JSON.stringify({ message: "invalid key" }));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const origin = `http://127.0.0.1:${server.address().port}`;
    for (const key of ["actual-anon", "wrong-key", "redirect"]) {
      const probe = createReadinessProbe({ configuration: () => ({ backend: origin, auth: origin, key }) });
      assert.equal(await probe(), key === "actual-anon");
    }
    assert.equal(redirected, false);
    const unavailableBackend = createReadinessProbe({ configuration: () => ({ backend: "http://127.0.0.1:1", auth: origin, key: "actual-anon" }) });
    assert.equal(await unavailableBackend(), false);
    assert.equal(liveness().status, 200);

  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
