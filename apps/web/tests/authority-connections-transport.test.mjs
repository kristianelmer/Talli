import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { loadSystemUserRequests } from "../features/authority-connections/transport.ts";

const companyId = "12345678-1234-4234-8234-123456789abc";
const requestId = "22345678-1234-4234-8234-123456789abc";
const body = { companyId, requestId };
const value = { requestId, companyId, status: "new", confirmationUrl: "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=42345678-1234-4234-8234-123456789abc", preflightVerifiedAt: null, failureCode: null };

test("company connection reads batch more than 100 memberships without dropping or trusting unrelated records", async (t) => {
  const priorUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (priorUrl === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = priorUrl; });
  const companies = Array.from({ length: 201 }, (_, index) => `12345678-1234-4234-8234-${String(index).padStart(12, "0")}`);
  const batches = [];
  let unrelated = false;
  t.mock.method(globalThis, "fetch", async (url, request) => {
    const ids = new URL(url).searchParams.getAll("companyIds");
    batches.push(ids);
    assert.ok(ids.length <= 100);
    assert.equal(request.headers.Authorization, "Bearer owner-session");
    assert.equal(request.cache, "no-store");
    return Response.json({ requests: ids.map((id, index) => ({ ...value, companyId: unrelated ? companies[200] : id,
      initiatingOwnerUserId: requestId, obligation: "aksjonaerregisteroppgaven",
      externalReference: "A".repeat(43), providerRequestId: null, operatorEvidenceId: null,
      acceptedAt: null, lastStatusCheckedAt: null, requestedAt: null, resolvedAt: null,
      createdAt: index === 0 ? "2026-09-09T01:00:00Z" : "2026-09-08T01:00:00Z", updatedAt: "2026-09-09T01:00:00Z" })) });
  });
  const rows = await loadSystemUserRequests("owner-session", [...companies, companies[0]]);
  assert.deepEqual(batches.map(batch => batch.length), [100, 100, 1]);
  assert.deepEqual(batches.flat(), companies);
  assert.equal(rows.length, companies.length);
  assert.ok(rows.every((row, index) => index === 0 || rows[index - 1].createdAt >= row.createdAt));
  unrelated = true;
  await assert.rejects(loadSystemUserRequests("owner-session", companies), error => error instanceof TalliApiError && error.status === 502);
});

for (const [method, suffix] of [
  ["authorityConnectionsStartSystemUserRequest", ""],
  ["authorityConnectionsRetrySystemUserRequest", "/retries"],
  ["authorityConnectionsReconcileSystemUserRequest", "/reconciliations"],
]) {
  test(`${method} carries only intent identity through authenticated no-store generated transport`, async () => {
    const calls = [];
    const api = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer test-owner" }, fetch: async (url, request) => {
      calls.push({ url, request });
      return Response.json(value);
    } });
    assert.deepEqual(await api[method](body), value);
    assert.equal(calls[0].url, `https://backend.example/api/v1/authority-connections/system-user-requests${suffix}`);
    assert.equal(calls[0].request.method, "POST");
    assert.equal(calls[0].request.cache, "no-store");
    assert.deepEqual(JSON.parse(calls[0].request.body), body);
    assert.equal(calls[0].request.headers.Authorization, "Bearer test-owner");
    assert.equal(calls[0].request.headers["X-Talli-Authority-Callback-Proof"], undefined);
  });
}

test("callback generated transport forwards proof separately from its sole request identity", async () => {
  let captured;
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
    captured = { url, request }; return Response.json(value);
  } });
  await api.authorityConnectionsReconcileSystemUserCallback({ requestId }, "signed-server-proof");
  assert.equal(captured.url, "https://backend.example/api/v1/authority-connections/system-user-callbacks");
  assert.deepEqual(JSON.parse(captured.request.body), { requestId });
  assert.equal(captured.request.headers["X-Talli-Authority-Callback-Proof"], "signed-server-proof");
  assert.equal(captured.request.cache, "no-store");
});

test("generated authority result rejects unknown statuses and malformed response contracts", async () => {
  for (const response of [{ ...value, status: "provider_says_success" }, { ...value, requestId: null }, { ...value, failureCode: "raw_secret_error" }]) {
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json(response) });
    await assert.rejects(api.authorityConnectionsStartSystemUserRequest(body), error => error instanceof TalliApiError && error.status === 502);
  }
});

test("generated operator mutation preserves exact audit identity and redacted response", async () => {
  const body = { operationId: requestId, operation: "register_rf1086_system", confirmation: "REGISTER TALLI RF1086 SYSTEM" };
  const row = { operationId: requestId, operation: body.operation, actorId: companyId, status: "succeeded",
    requestHash: "a".repeat(64), resultCode: "already_verified", metadata: { systemId: "930835978_talli" },
    authorityHttpStatus: 200, createdAt: "2026-09-09T12:00:00Z", completedAt: "2026-09-09T12:00:01Z" };
  const calls = [];
  const api = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer operator" }, fetch: async (url, request) => {
    calls.push({ url, request }); return Response.json(request.method === "POST" ? row : { operations: [row] });
  } });
  assert.deepEqual(await api.authorityConnectionsRunOperation(body), row);
  assert.deepEqual(await api.authorityConnectionsListOperations(), { operations: [row] });
  assert.deepEqual(JSON.parse(calls[0].request.body), body);
  for (const call of calls) {
    assert.equal(call.url, "https://backend.example/api/v1/authority-connections/operations");
    assert.equal(call.request.cache, "no-store");
    assert.equal(call.request.headers.Authorization, "Bearer operator");
  }
  const invalid = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json({ ...row, resultCode: "arbitrary_provider_body" }) });
  await assert.rejects(invalid.authorityConnectionsRunOperation(body), error => error instanceof TalliApiError && error.status === 502);
});

test("technical signoff command has no recording actor or trusted timestamp", async () => {
  const body = { key: "security_restore", status: "approved", reviewer: "Reviewer", reviewedAt: "2026-09-01T00:00:00Z", evidenceLink: "local-evidence", decision: "approved" };
  const result = { ...body, recordedBy: companyId, updatedAt: "2026-09-09T12:00:00Z" };
  const calls = [];
  const api = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer admin" }, fetch: async (url, request) => {
    calls.push({ url, request }); return Response.json(request.method === "POST" ? result : { signoffs: [result] });
  } });
  assert.deepEqual(await api.operatorControlsRecordLaunchSignoff(body), result);
  assert.deepEqual(await api.operatorControlsListLaunchSignoffs(), { signoffs: [result] });
  assert.deepEqual(JSON.parse(calls[0].request.body), body);
  assert.ok(calls.every(call => call.url === "https://backend.example/api/v1/operator-controls/launch-signoffs" && call.request.cache === "no-store"));
});
