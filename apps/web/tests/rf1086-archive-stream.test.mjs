import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

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
