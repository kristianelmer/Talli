import assert from "node:assert/strict";
import test from "node:test";
import { TalliApiError } from "@talli/talli-api-client";
import { loadRf1086RegisterObservationLifecycle } from "../features/shareholder-register-filing/index.ts";

const company = "10000000-0000-4000-8000-000000000001";
const other = "10000000-0000-4000-8000-000000000002";
const previewId = "30000000-0000-4000-8000-000000000001";
const documentId = "40000000-0000-4000-8000-000000000001";
const base = "/api/v1/shareholder-register-filings";
const hash = "a".repeat(64);
const civilTime = "2025-03-30T02:30:00";
const document = () => ({ documentId, companyId: company, contentVersionSha256: hash, contentSha256: hash,
  createdAt: "2024-12-31T12:00:00Z", sourceIncomeYear: 2024, documentType: "corporate_document",
  integrityStatus: "attached", byteLength: 12, metadataSha256: hash });
const registerBody = () => ({ companyId: company, incomeYear: 2025, effectiveAt: civilTime, eventKind: "cash_issue",
  before: { shareCapital: "30000.000000", shareCount: 100, nominalValue: "300", holdings: [
    { shareholderId: "holder", name: "Owner", kind: "norwegian_person", identifier: "12345678901", shareCount: 100 }] },
  after: { shareCapital: "60000.000000", shareCount: 200, nominalValue: "300", holdings: [
    { shareholderId: "holder", name: "Owner", kind: "norwegian_person", identifier: "12345678901", shareCount: 200 }] },
  documents: ["register_before", "register_after", "registration"].map(role => ({ ...document(), role })),
  completeRegisterConfirmed: true, registrationConfirmed: true, singleShareClassConfirmed: true,
  supersedesObservationId: null, supersedesObservationSha256: null, correctionReason: null });
const registerReceipt = () => ({ observationId: previewId, companyId: company, incomeYear: 2025,
  factSha256: hash, version: 1, confirmedAt: "2026-09-24T12:00:00Z" });

function environment(t, response, status = 200) {
  const old = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (old === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = old; });
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    calls.push({ url: new URL(url), request });
    return Response.json(response, { status, headers: { "content-type": status < 400 ? "application/json" : "application/problem+json" } });
  });
  return calls;
}
const invalid = error => error instanceof TalliApiError && error.status === 502;

const observation = () => ({ receipt: registerReceipt(), draft: { ...registerBody(),
  completeRegisterConfirmed: false, registrationConfirmed: false, singleShareClassConfirmed: false,
  supersedesObservationId: previewId, supersedesObservationSha256: hash },
  status: "active", supersededBy: null, withdrawal: null });
const lifecycle = () => ({ companyId: company, incomeYear: 2025, observedAt: "2026-09-24T13:00:00Z", observations: [observation()] });
const withdrawal = () => ({ withdrawalId: other, withdrawnAt: "2026-09-24T12:01:00.123456Z", reason: "  Feil original – behold teksten.\n", withdrawalSha256: hash });
const load = () => loadRf1086RegisterObservationLifecycle("owner", company, 2025);

test("generated lifecycle read preserves exact facts, withdrawal history and authenticated no-store request", async t => {
  const value = lifecycle(); value.observations[0].status = "withdrawn"; value.observations[0].withdrawal = withdrawal();
  const calls = environment(t, value);
  assert.deepEqual(await load(), value);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, base + "/register-observations/lifecycle");
  assert.equal(calls[0].url.searchParams.get("companyId"), company);
  assert.equal(calls[0].url.searchParams.get("incomeYear"), "2025");
  assert.equal(calls[0].request.method, "GET"); assert.equal(calls[0].request.cache, "no-store");
  assert.equal(calls[0].request.headers.Authorization, "Bearer owner");
  assert.ok(calls[0].request.signal instanceof AbortSignal);
});

test("superseded ancestor remains superseded when its head is withdrawn and another root is active", async t => {
  const value = lifecycle(), original = value.observations[0], head = structuredClone(original), independent = structuredClone(original);
  head.receipt.observationId = other; head.receipt.version = 2; head.receipt.confirmedAt = "2026-09-24T12:00:01Z";
  head.draft.supersedesObservationId = other; head.status = "withdrawn"; head.withdrawal = withdrawal();
  original.status = "superseded"; original.supersededBy = other;
  independent.receipt.observationId = documentId; independent.draft.supersedesObservationId = documentId;
  value.observations.push(head, independent); environment(t, value);
  assert.deepEqual(await load(), value);
});

for (const [label, change] of [
  ["foreign scope", v => { v.companyId = other; }],
  ["foreign row", v => { v.observations[0].receipt.companyId = other; }],
  ["duplicate identity", v => { v.observations.push(v.observations[0]); }],
  ["missing lifecycle", v => { delete v.observations[0].status; v.observations[0].isCurrent = true; }],
  ["invented status", v => { v.observations[0].status = "current"; }],
  ["active withdrawal", v => { v.observations[0].withdrawal = withdrawal(); }],
  ["missing withdrawal receipt", v => { v.observations[0].status = "withdrawn"; }],
  ["invalid observation time", v => { v.observedAt = "yesterday"; }],
  ["future capture", v => { v.observedAt = "2026-09-24T11:00:00Z"; }],
  ["orphan revision", v => { v.observations[0].receipt.version = 2; }],
  ["unknown successor", v => { v.observations[0].status = "superseded"; v.observations[0].supersededBy = other; }],
  ["self successor", v => { v.observations[0].status = "superseded"; v.observations[0].supersededBy = previewId; }],
  ["timezone on civil effective time", v => { v.observations[0].draft.effectiveAt += "Z"; }],
  ["review flags", v => { v.observations[0].draft.registrationConfirmed = true; }],
  ["draft binding", v => { v.observations[0].draft.supersedesObservationSha256 = "b".repeat(64); }],
  ["withdrawal digest", v => { v.observations[0].status = "withdrawn"; v.observations[0].withdrawal = { ...withdrawal(), withdrawalSha256: "bad" }; }],
  ["withdrawal before capture", v => { v.observations[0].status = "withdrawn"; v.observations[0].withdrawal = { ...withdrawal(), withdrawnAt: "2026-09-24T11:00:00Z" }; }],
  ["future withdrawal", v => { v.observations[0].status = "withdrawn"; v.observations[0].withdrawal = { ...withdrawal(), withdrawnAt: "2026-09-24T14:00:00Z" }; }],
]) test(`lifecycle refuses ${label} instead of falling back to legacy currentness`, async t => {
  const value = lifecycle(); change(value); const calls = environment(t, value);
  await assert.rejects(load(), invalid); assert.equal(calls.length, 1);
});

for (const [status, code] of [[404, undefined], [404, "RESOURCE_NOT_FOUND"], [404, "rf1086_register_not_found"], [401, "authentication_required"], [403, "forbidden"], [409, "rf1086_register_lifecycle_upgrade_required"], [503, "unavailable"]]) {
  test(`status ${status}/${code} is visibly unavailable with no legacy request`, async t => {
    const calls = environment(t, code === undefined ? { detail: "Not Found" } : {
      type: "about:blank", title: "Unavailable", status, code, detail: "Unavailable", requestId: "lifecycle-test" }, status);
    await assert.rejects(load(), error => error instanceof TalliApiError && error.status === status);
    assert.equal(calls.length, 1);
  });
}

for (const delta of [0, 1]) test(`microsecond lineage ordering ${delta ? "preserves exact instants" : "rejects equal instants"}`, async t => {
  const value = lifecycle(), original = value.observations[0], head = structuredClone(original);
  original.receipt.confirmedAt = "2026-09-24T12:00:00.123456Z";
  head.receipt.confirmedAt = `2026-09-24T14:00:00.12345${6 + delta}+02:00`;
  head.receipt.observationId = other; head.receipt.version = 2; head.draft.supersedesObservationId = other;
  original.status = "superseded"; original.supersededBy = other; value.observations.push(head);
  environment(t, value);
  if (delta) assert.deepEqual(await load(), value);
  else await assert.rejects(load(), invalid);
});
