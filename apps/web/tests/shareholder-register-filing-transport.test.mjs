import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import {
  loadRf1086Workspaces, generateRf1086PreviewThroughApi, loadRf1086Preview,
  presentRf1086Approval, presentRf1086Simulation, rf1086ApiErrorCode,
} from "../features/shareholder-register-filing/index.ts";

const company = "10000000-0000-4000-8000-000000000001";
const other = "10000000-0000-4000-8000-000000000002";
const previewId = "20000000-0000-4000-8000-000000000003";
const setupId = "30000000-0000-4000-8000-000000000004";
const preview = (companyId = company, incomeYear = 2025) => ({
  id: previewId, companyId, incomeYear, setupId, filing: "aksjonærregisteroppgaven",
  status: "ready", issues: [], preview: "Original æ preview", hovedskjemaXml: "<H>original</H>\r\n",
  underskjemaXml: { [setupId]: "<U>original</U>" }, source: "deterministic_rf1086_engine", createdAt: "2026-09-09T12:00:00Z",
});
const workspace = (companyId = company, incomeYear = null) => ({
  companyId, incomeYear, previews: [preview(companyId, incomeYear ?? 2025)], simulations: [], overrides: [],
  reviewComments: [], permissions: [], testEvidence: [], approvals: [], productionSubmissions: [], feedbackArtifacts: [], actions: [],
});
function environment(t) {
  const prior = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (prior === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = prior; });
}
const invalidResponse = (error) => error instanceof TalliApiError && error.status === 502;

test("retained history reads keep every requested company and all years with authenticated no-store transport", async (t) => {
  environment(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    const query = new URL(url).searchParams;
    calls.push(query.get("companyId"));
    assert.equal(query.has("incomeYear"), false);
    assert.equal(request.headers.Authorization, "Bearer owner");
    assert.equal(request.cache, "no-store");
    const value = workspace(query.get("companyId"));
    value.previews.push({ ...preview(query.get("companyId"), 2024), id: setupId });
    return Response.json(value);
  });
  const values = await loadRf1086Workspaces("owner", [company, other, company]);
  assert.deepEqual(calls, [company, other]);
  assert.deepEqual(values.flatMap(value => value.previews.map(row => row.incomeYear)), [2025, 2024, 2025, 2024]);
});

for (const corruption of ["company", "child-company", "duplicate", "year", "invalid-status"]) {
  test(`workspace rejects ${corruption} instead of presenting a successful partial history`, async (t) => {
    environment(t);
    const value = workspace(company, 2025);
    if (corruption === "company") value.companyId = other;
    if (corruption === "child-company") value.previews[0].companyId = other;
    if (corruption === "duplicate") value.previews.push(value.previews[0]);
    if (corruption === "year") value.previews[0].incomeYear = 2024;
    if (corruption === "invalid-status") value.previews[0].status = "provider_claims_ready";
    t.mock.method(globalThis, "fetch", async () => Response.json(value));
    await assert.rejects(loadRf1086Workspaces("owner", [company], 2025), invalidResponse);
  });
}

test("preview generation sends only original input identities and rejects a misbound audit scope", async (t) => {
  environment(t);
  const calls = [];
  let misbound = false;
  t.mock.method(globalThis, "fetch", async (url, request) => {
    calls.push({ url, request });
    return Response.json({ recordId: previewId, companyId: misbound ? other : company, incomeYear: 2025 });
  });
  await generateRf1086PreviewThroughApi("owner", { companyId: company, openingSnapshotId: setupId });
  assert.equal(calls[0].url, "https://backend.example/api/v1/shareholder-register-filings/previews");
  assert.deepEqual(JSON.parse(calls[0].request.body), { companyId: company, openingSnapshotId: setupId });
  assert.equal(calls[0].request.cache, "no-store");
  misbound = true;
  await assert.rejects(generateRf1086PreviewThroughApi("owner", { companyId: company, openingSnapshotId: setupId }), invalidResponse);
});

test("a preview read cannot substitute another aggregate", async (t) => {
  environment(t);
  t.mock.method(globalThis, "fetch", async () => Response.json({ ...preview(), id: setupId }));
  await assert.rejects(loadRf1086Preview("owner", previewId), invalidResponse);
});

test("shipped Send and recovery generated contracts keep exact paths and nullable recovery result", async () => {
  const calls = [];
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
    calls.push({ url, request });
    return Response.json(url.endsWith("production-filings") ? { submissionId: setupId }
      : { state: null, errorCode: "status_unavailable", requiresManualRetry: true });
  } });
  assert.deepEqual(await api.legacyRf1086SendApprovedFiling({ approvalId: previewId }), { submissionId: setupId });
  assert.deepEqual(await api.legacyRf1086ReconcileFeedback({ submissionId: setupId }),
    { state: null, errorCode: "status_unavailable", requiresManualRetry: true });
  assert.deepEqual(calls.map(call => new URL(call.url).pathname), [
    "/api/v1/legacy-rf1086/production-filings", "/api/v1/legacy-rf1086/feedback-reconciliations",
  ]);
  assert.deepEqual(calls.map(call => JSON.parse(call.request.body)), [{ approvalId: previewId }, { submissionId: setupId }]);
  assert.ok(calls.every(call => call.request.cache === "no-store"));
});

test("presentation preserves nested original payload/manifest bytes and field names", () => {
  const manifest = { documentHashes: [{ name: "æ/Original", sha256: "a".repeat(64) }], warnings: ["Original æ"] };
  const approval = presentRf1086Approval({ manifest });
  assert.strictEqual(approval.manifest, manifest);
  const submittedPayload = { filing: "aksjonærregisteroppgaven", companyId: company, incomeYear: 2025,
    payloadHash: "b".repeat(64), hovedskjemaXml: "<H>æ</H>\r\n", underskjemaXml: { [setupId]: "<U>original</U>" } };
  const receiptMetadata = { authority: "simulation", receiptId: "original", status: "receipt_stored",
    receivedAt: "2026-09-09T12:00:00Z", feedbackDocumentIds: ["original-child"] };
  const simulation = presentRf1086Simulation({ calls: [{ endpoint: "original", bodyHash: "c".repeat(64),
    idempotencyKey: "original", status: "accepted", createdAt: "2026-09-09T12:00:00Z" }],
    submittedPayload, receiptMetadata, feedbackItems: [{ documentId: "original-child" }] });
  assert.strictEqual(simulation.submitted_payload, submittedPayload);
  assert.strictEqual(simulation.receipt_metadata, receiptMetadata);
  assert.deepEqual(simulation.feedback_items, [{ documentId: "original-child" }]);
  assert.equal(simulation.calls[0].body_hash, "c".repeat(64));
});

test("canonical invalid approval input and stale MFA retain existing owner guidance codes", () => {
  const problem = (code) => new TalliApiError(422, { code, status: 422, title: "RF request failed",
    detail: "RF request failed", instance: "/api/v1/shareholder-register-filings/production-approvals",
    requestId: "approval-error-proof", type: "https://talli.no/problems/rf-input" });
  assert.equal(rf1086ApiErrorCode(problem("SHAREHOLDER_REGISTER_FILING_INVALID_INPUT")), "invalid_request");
  assert.equal(rf1086ApiErrorCode(problem("step_up_required")), "step_up_required");
  assert.equal(rf1086ApiErrorCode(problem("untrusted_provider_body")), "status_unavailable");
});
