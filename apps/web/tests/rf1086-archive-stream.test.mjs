import assert from "node:assert/strict";
import test from "node:test";
import { registerHooks } from "node:module";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { downloadRf1086Archive } from "../features/shareholder-register-filing/index.ts";

test("RF download keeps the body unconsumed and forwards scope, auth, correlation and cancellation", async () => {
  const controller = new AbortController();
  const response = new Response("partial stream", { headers: { "Content-Type": "application/x-ndjson" } });
  const calls = [];
  const api = createTalliApiClient({ baseUrl: "https://backend.example/", headers: { Authorization: "Bearer token" },
    fetch: async (...args) => { calls.push(args); return response; } });
  const result = await api.rf1086DownloadProductionArchive("company / id", 2025,
    { signal: controller.signal, requestId: "archive-read-123" });
  assert.equal(result, response);
  assert.equal(response.bodyUsed, false);
  assert.equal(calls.length, 1);
  const [url, request] = calls[0];
  assert.equal(new URL(url).pathname, "/api/v1/shareholder-register-filings/archive-source/production-stream");
  assert.equal(new URL(url).searchParams.get("companyId"), "company / id");
  assert.equal(new URL(url).searchParams.get("incomeYear"), "2025");
  assert.equal(request.method, "GET");
  assert.equal(request.cache, "no-store");
  assert.equal(request.signal, controller.signal);
  assert.equal(request.headers.Authorization, "Bearer token");
  assert.equal(request.headers["X-Request-ID"], "archive-read-123");
  await result.body.cancel();
});

for (const contentType of ["application/json", "text/html", "application/x-ndjson-other"]) {
  test(`RF stream refuses unexpected response type ${contentType}`, async () => {
    let cancelled = false;
    const body = new ReadableStream({ cancel() { cancelled = true; } });
    const api = createTalliApiClient({ baseUrl: "https://backend.example",
      fetch: async () => new Response(body, { headers: { "Content-Type": contentType } }) });
    await assert.rejects(api.rf1086DownloadProductionArchive("company", 2025),
      error => error instanceof TalliApiError && error.status === 502);
    assert.equal(cancelled, true);
  });
}

test("RF stream preserves safe HTTP error status without retry or treating it as a download", async () => {
  let calls = 0;
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => {
    calls += 1;
    return new Response("unavailable", { status: 503 });
  } });
  await assert.rejects(api.rf1086DownloadProductionArchive("company", 2025),
    error => error instanceof TalliApiError && error.status === 503);
  assert.equal(calls, 1);
});

test("a stream disconnect is exposed to its consumer and never causes a second download", async () => {
  let calls = 0;
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => {
    calls += 1;
    return new Response(new ReadableStream({ start(controller) { controller.error(new Error("disconnected")); } }),
      { headers: { "Content-Type": "application/x-ndjson" } });
  } });
  const response = await api.rf1086DownloadProductionArchive("company", 2025);
  await assert.rejects(response.text(), /disconnected/);
  assert.equal(calls, 1);
});

test("RF owner transport binds the request lifetime without buffering", async (t) => {
  const previous = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (previous === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = previous; });
  const ownerAbort = new AbortController();
  let sent;
  const upstream = new Response("incomplete", { headers: { "Content-Type": "application/x-ndjson" } });
  t.mock.method(globalThis, "fetch", async (url, request) => { sent = { url, request }; return upstream; });
  const result = await downloadRf1086Archive("private-token", "10000000-0000-4000-8000-000000000001", 2025, ownerAbort.signal, "archive-123");
  assert.equal(result, upstream);
  assert.equal(upstream.bodyUsed, false);
  assert.equal(sent.request.headers.Authorization, "Bearer private-token");
  assert.equal(sent.request.signal.aborted, false);
  ownerAbort.abort();
  assert.equal(sent.request.signal.aborted, true);
  await result.body.cancel();
  await assert.rejects(downloadRf1086Archive("private-token", "bad", 2025, ownerAbort.signal, "archive-123"),
    error => error instanceof TalliApiError && error.status === 400);
});

test("actual owner download route enforces scope, owner and MFA before forwarding a stream", async (t) => {
  const routeUrl = new URL("../app/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route.ts", import.meta.url);
  const key = Symbol.for("talli.rf.archive-route-test");
  const names = ["downloadRf1086Archive", "loadAcceptedMembershipCompany", "requireStepUpForAction",
    "getCurrentSessionAccessToken", "createSupabaseServerClient"];
  const hook = registerHooks({ resolve(specifier, context, nextResolve) {
    if (context.parentURL === routeUrl.href && specifier !== "node:crypto") {
      const code = names.map(name => `export const ${name} = (...args) => globalThis[Symbol.for("talli.rf.archive-route-test")].${name}(...args);`).join("\n");
      return { url: "data:text/javascript," + encodeURIComponent(code), shortCircuit: true };
    }
    return nextResolve(specifier, context);
  } });
  let GET;
  try { ({ GET } = await import(routeUrl.href)); } finally { hook.deregister(); }
  t.after(() => { delete globalThis[key]; });
  const companyId = "10000000-0000-4000-8000-000000000001";
  let calls, body, cancelled;
  function reset(overrides = {}) {
    calls = []; cancelled = false;
    body = new ReadableStream({ cancel() { cancelled = true; } });
    globalThis[key] = {
      getCurrentSessionAccessToken: async () => { calls.push("token"); return "private-token"; },
      loadAcceptedMembershipCompany: async id => { calls.push("owner"); assert.equal(id, companyId); return { id, role: "owner" }; },
      createSupabaseServerClient: async () => ({ auth: { getUser: async () => ({ data: { user: { id: "owner-id" } } }) } }),
      requireStepUpForAction: async input => {
        calls.push("mfa"); assert.equal(input.action, "archive_export");
        assert.equal(input.userId, "owner-id"); assert.equal(input.companyId, companyId);
      },
      downloadRf1086Archive: async (token, id, year, signal, requestId) => {
        calls.push("download"); assert.equal(token, "private-token"); assert.equal(id, companyId); assert.equal(year, 2025);
        assert.ok(signal instanceof AbortSignal); assert.match(requestId, /^[a-f0-9-]{36}$/);
        return new Response(body, { headers: { "Set-Cookie": "private=never-forward", "Content-Disposition": "unsafe", "X-Secret": "never-forward" } });
      }, ...overrides,
    };
  }
  const request = suffix => new Request(`https://talli.example/filing/aksjonaerregisteroppgaven/source/archive?${suffix ?? `companyId=${companyId}&incomeYear=2025`}`);

  await t.test("valid download preserves backpressure, safe headers and cancellation", async () => {
    reset();
    const response = await GET(request());
    assert.equal(response.status, 200);
    assert.deepEqual(calls, ["token", "owner", "mfa", "download"]);
    assert.equal(response.body, body);
    assert.equal(response.bodyUsed, false);
    assert.equal(response.headers.get("Content-Disposition"), `attachment; filename="rf1086-${companyId}-2025.ndjson"`);
    assert.equal(response.headers.get("Content-Type"), "application/x-ndjson");
    assert.equal(response.headers.get("Cache-Control"), "private, no-store");
    assert.equal(response.headers.get("Set-Cookie"), null);
    assert.equal(response.headers.get("X-Secret"), null);
    await response.body.cancel();
    assert.equal(cancelled, true);
  });
  for (const invalid of ["", "companyId=invalid&incomeYear=2025", `companyId=${companyId}&incomeYear=2025.0`,
    `companyId=${companyId}&incomeYear=1999`, `companyId=${companyId}&incomeYear=2101`,
    `companyId=${companyId}&incomeYear=2025&incomeYear=2024`, `companyId=${companyId}&companyId=${companyId}&incomeYear=2025`]) {
    await t.test(`reject invalid scope before dependencies: ${invalid}`, async () => {
      reset(); const response = await GET(request(invalid));
      assert.equal(response.status, 400); assert.deepEqual(calls, []);
    });
  }
  for (const role of ["advisor", "accountant", "viewer", "former_owner"]) {
    await t.test(`deny ${role} before MFA and download`, async () => {
      reset({ loadAcceptedMembershipCompany: async () => ({ id: companyId, role }) });
      assert.equal((await GET(request())).status, 403);
      assert.deepEqual(calls, ["token"]);
    });
  }
  await t.test("login, missing membership, wrong company, and MFA failures never download", async () => {
    for (const [overrides, status] of [
      [{ getCurrentSessionAccessToken: async () => null }, 401],
      [{ loadAcceptedMembershipCompany: async () => null }, 403],
      [{ loadAcceptedMembershipCompany: async () => ({ id: "other", role: "owner" }) }, 403],
      [{ createSupabaseServerClient: async () => ({ auth: { getUser: async () => ({ data: { user: null } }) } }) }, 401],
      [{ requireStepUpForAction: async () => { throw new Error("private MFA failure"); } }, 403],
    ]) {
      reset(overrides); const response = await GET(request());
      assert.equal(response.status, status);
      assert.equal(calls.includes("download"), false);
      assert.doesNotMatch(await response.text(), /private/);
    }
  });
  await t.test("dependency failures are safe and uncached", async () => {
    reset({ downloadRf1086Archive: async () => { throw new Error("private backend detail"); } });
    const response = await GET(request());
    assert.equal(response.status, 503); assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.doesNotMatch(await response.text(), /private backend/);
  });
  await t.test("a body failure stays a failed stream and cannot become an empty success", async () => {
    reset({ downloadRf1086Archive: async () => new Response(new ReadableStream({ start(controller) { controller.error(new Error("connection lost")); } })) });
    const response = await GET(request());
    await assert.rejects(response.text(), /connection lost/);
  });
});
