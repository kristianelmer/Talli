import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "../../packages/talli-api-client/src/generated/client.ts";

const companyId = "10000000-0000-0000-0000-000000000001";
const otherCompany = "10000000-0000-0000-0000-000000000002";
const path = "/api/v1/shareholder-register-filings/company-test-retention";
const record = () => ({
  id: "10000000-0000-0000-0000-000000000003", company_id: companyId,
  obligation: "aksjonaerregisteroppgaven", environment: "original", status: "historic",
  test_reference: " raw reference ", feedback_summary: "original feedback",
  receipt_reference: null, archive_reference: " original archive ", evidence_url: null,
  payload_hash: " opaque hash ", recorded_by: "10000000-0000-0000-0000-000000000004",
  recorded_at: "2025-01-01T01:00:00+01:00",
});
const complete = () => ({
  codec: "rf1086-company-test-retention-v1", scope: "company_no_intrinsic_income_year",
  companyId, coverage: "complete", observedAt: "2026-10-11T01:00:00+01:00",
  recordCount: 1, recordsSha256: "a".repeat(64), records: [record()],
});
const unavailable = () => ({ codec: complete().codec, scope: complete().scope, companyId, coverage: "unavailable" });
const isBadGateway = (error) => error instanceof TalliApiError && error.status === 502;

function clientWith(fetch) {
  return createTalliApiClient({ baseUrl: "https://backend.example/", headers: { Authorization: "Bearer synthetic" }, fetch });
}

for (const value of [complete(), unavailable(), { ...complete(), recordCount: 0, records: [] }]) {
  test(`query preserves the exact ${value.coverage}/${value.recordCount ?? "unknown"} value and company-only scope`, async () => {
    const calls = [];
    const signal = new AbortController().signal;
    const client = clientWith(async (url, init) => { calls.push({ url, init }); return Response.json(value); });
    assert.deepEqual(await client.rf1086ReadCompanyTestRetention(companyId, { signal, requestId: "retention-query" }), value);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, `https://backend.example${path}?companyId=${companyId}`);
    assert.equal(calls[0].init.method, "GET");
    assert.equal(calls[0].init.cache, "no-store");
    assert.equal(calls[0].init.signal, signal);
    assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic");
    assert.equal(calls[0].init.headers["X-Request-ID"], "retention-query");
  });
}

for (const [name, change] of [
  ["legacy codec", (v) => { v.codec = "rf1086-production-archive-v6"; }],
  ["year scope", (v) => { v.incomeYear = 2025; }],
  ["wrong company", (v) => { v.companyId = otherCompany; }],
  ["wrong record company", (v) => { v.records[0].company_id = otherCompany; }],
  ["wrong count", (v) => { v.recordCount = 0; }],
  ["fractional count", (v) => { v.recordCount = 1.5; }],
  ["oversized count", (v) => { v.recordCount = 100001; }],
  ["bad digest", (v) => { v.recordsSha256 = "opaque"; }],
  ["missing raw field", (v) => { delete v.records[0].recorded_by; }],
  ["extra raw field", (v) => { v.records[0].incomeYear = 2025; }],
  ["rewritten timestamp type", (v) => { v.records[0].recorded_at = 123; }],
]) {
  test(`query rejects ${name} without an older endpoint fallback`, async () => {
    const value = complete(); change(value); let calls = 0;
    const client = clientWith(async () => { calls++; return Response.json(value); });
    await assert.rejects(client.rf1086ReadCompanyTestRetention(companyId), isBadGateway);
    assert.equal(calls, 1);
  });
}

test("unavailable rejects invented completeness metadata", async () => {
  const client = clientWith(async () => Response.json({ ...unavailable(), recordCount: 0 }));
  await assert.rejects(client.rf1086ReadCompanyTestRetention(companyId), isBadGateway);
});

test("download returns the original response; headers do not establish footer completion", async () => {
  const signal = new AbortController().signal;
  const response = new Response("incomplete header only\n", { headers: { "content-type": "application/x-ndjson; charset=utf-8" } });
  const calls = [];
  const client = clientWith(async (url, init) => { calls.push({ url, init }); return response; });
  assert.equal(await client.rf1086DownloadCompanyTestRetention(companyId, { signal, requestId: "retention-download" }), response);
  assert.equal(response.bodyUsed, false);
  assert.equal(await response.text(), "incomplete header only\n");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `https://backend.example${path}/stream-v1?companyId=${companyId}`);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[0].init.signal, signal);
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic");
  assert.equal(calls[0].init.headers["X-Request-ID"], "retention-download");
});

test("download cancels a successful body with the wrong content type", async () => {
  let cancelled = false;
  const body = new ReadableStream({ cancel() { cancelled = true; } });
  const client = clientWith(async () => new Response(body, { headers: { "content-type": "application/json" } }));
  await assert.rejects(client.rf1086DownloadCompanyTestRetention(companyId), isBadGateway);
  assert.equal(cancelled, true);
});

test("download rejects a missing body", async () => {
  const client = clientWith(async () => new Response(null, { headers: { "content-type": "application/x-ndjson" } }));
  await assert.rejects(client.rf1086DownloadCompanyTestRetention(companyId), isBadGateway);
});

for (const method of ["rf1086ReadCompanyTestRetention", "rf1086DownloadCompanyTestRetention"]) {
  test(`${method} preserves finite denial and propagates abort without retry`, async () => {
    let calls = 0;
    const denied = clientWith(async () => { calls++; return new Response("denied", { status: 403 }); });
    await assert.rejects(denied[method](companyId), (error) => error instanceof TalliApiError && error.status === 403);
    assert.equal(calls, 1);
    const failure = new DOMException("synthetic abort", "AbortError");
    const aborted = clientWith(async () => { throw failure; });
    await assert.rejects(aborted[method](companyId), (error) => error === failure);
  });
}
