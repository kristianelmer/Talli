import assert from "node:assert/strict";
import test from "node:test";
import { TalliApiError } from "@talli/talli-api-client";
import {
  loadRf1086SourceIntakeBasis, loadRf1086CurrentYearSource, loadRf1086SourceDocument,
  captureRf1086YearSourceThroughApi, captureRf1086RegisterObservationThroughApi,
  generateRf1086SourcePreviewThroughApi, loadRf1086SourcePreview, rf1086SourceErrorMessage, rf1086SourceCaptureRejected,
} from "../features/shareholder-register-filing/index.ts";

const company = "10000000-0000-4000-8000-000000000001";
const other = "10000000-0000-4000-8000-000000000002";
const sourceId = "20000000-0000-4000-8000-000000000001";
const previewId = "30000000-0000-4000-8000-000000000001";
const documentId = "40000000-0000-4000-8000-000000000001";
const key = "source-owner-attempt-0001";
const base = "/api/v1/shareholder-register-filings";
const hash = "a".repeat(64);
const exactAmount = "9007199254740993.000001";
const civilTime = "2025-03-30T02:30:00";
const document = () => ({ documentId, companyId: company, contentVersionSha256: hash, contentSha256: hash,
  createdAt: "2024-12-31T12:00:00Z", sourceIncomeYear: 2024, documentType: "corporate_document",
  integrityStatus: "attached", byteLength: 12, metadataSha256: hash });
const receipt = () => ({ sourceId, companyId: company, incomeYear: 2025, version: 2, sourceSha256: hash,
  caseSha256: hash, confirmedAt: "2026-09-24T12:00:00Z" });
const draft = () => ({ companyId: company, incomeYear: 2025,
  case: { caseId: "owner-year", company: { orgNumber: "999999999", name: "Example AS", address: "Example 1",
    postalCode: "0150", city: "Oslo", incomeYear: 2025, shareType: "01", contactEmail: null },
    shareSnapshot: { previousShareCapital: "30000", currentShareCapital: "30000", previousNominalValue: "300",
      currentNominalValue: "300", previousShareCount: 100, currentShareCount: 100, previousPaidInShareCapital: "30000",
      currentPaidInShareCapital: "30000", previousPaidInPremium: "0.000001", currentPaidInPremium: "0.000001" },
    shareholders: [{ id: "holder", name: "Owner", kind: "norwegian_person", nationalId: "12345678901", orgNumber: null }],
    shareholderSnapshots: [{ shareholderId: "holder", previousShareCount: 100, currentShareCount: 100 }],
    events: [{ type: "dividend", timestamp: civilTime, totalAmount: exactAmount, perShareAmount: "90071992547409.93000001",
      allocations: [{ shareholderId: "holder", amount: exactAmount, shareCountBasis: 100 }] }] },
  paidIn: { openingCapital: "30000", closingCapital: "30000", openingPremium: "0.000001", closingPremium: "0.000001" },
  documents: [document()], openingDocumentIds: [documentId], closingDocumentIds: [documentId], paidInDocumentIds: [documentId],
  eventEvidence: [{ eventIndex: 0, documentIds: [documentId], eventSha256: hash, governanceReceiptId: other }],
  identitiesReviewed: false, completeYearConfirmed: false, paidInReviewed: false, noActivityConfirmed: false,
  supersedesSourceId: sourceId, supersedesSourceSha256: hash, correctionReason: null });
const current = () => ({ currentSource: { receipt: receipt(), draft: draft() } });
const preview = () => ({ previewId, companyId: company, incomeYear: 2025, sourceId, sourceSha256: hash, caseSha256: hash,
  readinessStatus: "ready", readinessIssues: [], previewText: "Original æ review\r\n", hovedskjemaXml: "<H>æ</H>\r\n",
  underskjemaXml: { holder: "<U>original</U>" }, renderingProfile: "rf1086-full-year-v1" });
const intake = () => ({ companyId: company, incomeYear: 2025, company: { orgNumber: "999999999", name: "Example AS",
  address: "Example 1", postalCode: "0150", city: "Oslo", identityConfirmedAt: "2025-01-01T12:00:00Z",
  identityLockedAt: "2025-01-01T12:00:00Z" }, enumerationComplete: true, enumerationSha256: hash,
  dividends: [], capitalEvents: [], ledgerAmendments: [], blockers: [] });
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

for (const [name, load, fixture, suffix, query] of [
  ["intake", () => loadRf1086SourceIntakeBasis("owner", company, 2025), intake, "/source-intake-basis", { companyId: company, incomeYear: "2025" }],
  ["current source", () => loadRf1086CurrentYearSource("owner", company, 2025), current, "/current-year-source", { companyId: company, incomeYear: "2025" }],
  ["document", () => loadRf1086SourceDocument("owner", company, documentId), document, "/source-documents/" + documentId, { companyId: company }],
  ["preview", () => loadRf1086SourcePreview("owner", company, 2025, sourceId, previewId), preview, "/source-previews/" + previewId, { companyId: company, incomeYear: "2025" }],
]) {
  test(`${name} read preserves complete wire values with authenticated no-store scope`, async t => {
    const value = fixture(), calls = environment(t, value);
    assert.deepEqual(await load(), value);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.pathname, base + suffix);
    assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), query);
    assert.equal(calls[0].request.method, "GET");
    assert.equal(calls[0].request.cache, "no-store");
    assert.equal(calls[0].request.headers.Authorization, "Bearer owner");
    assert.ok(calls[0].request.signal instanceof AbortSignal);
  });
}

for (const [name, load, fixture] of [
  ["intake", () => loadRf1086SourceIntakeBasis("owner", company, 2025), intake],
  ["document", () => loadRf1086SourceDocument("owner", company, documentId), document],
  ["preview", () => loadRf1086SourcePreview("owner", company, 2025, sourceId, previewId), preview],
]) {
  test(`${name} rejects cross-company responses`, async t => {
    environment(t, { ...fixture(), companyId: other });
    await assert.rejects(load(), invalid);
  });
}

for (const change of ["receipt-company", "receipt-year", "draft-company", "draft-year", "case-year", "source-id", "source-hash",
  "document-company", "duplicate-document", "identities-reviewed", "year-reviewed", "paid-in-reviewed", "no-activity-reviewed",
  "correction-reason", "version", "case-hash"]) {
  test(`retained source rejects mismatched ${change} and never substitutes an empty year`, async t => {
    const value = current(), { receipt: r, draft: d } = value.currentSource;
    if (change === "receipt-company") r.companyId = other;
    if (change === "receipt-year") r.incomeYear = 2024;
    if (change === "draft-company") d.companyId = other;
    if (change === "draft-year") d.incomeYear = 2024;
    if (change === "case-year") d.case.company.incomeYear = 2024;
    if (change === "source-id") d.supersedesSourceId = other;
    if (change === "source-hash") d.supersedesSourceSha256 = "b".repeat(64);
    if (change === "document-company") d.documents[0].companyId = other;
    if (change === "duplicate-document") d.documents.push(d.documents[0]);
    if (change === "identities-reviewed") d.identitiesReviewed = true;
    if (change === "year-reviewed") d.completeYearConfirmed = true;
    if (change === "paid-in-reviewed") d.paidInReviewed = true;
    if (change === "no-activity-reviewed") d.noActivityConfirmed = true;
    if (change === "correction-reason") d.correctionReason = "Old reviewed reason";
    if (change === "version") r.version = 0;
    if (change === "case-hash") r.caseSha256 = "unbound";
    const calls = environment(t, value);
    await assert.rejects(loadRf1086CurrentYearSource("owner", company, 2025), invalid);
    assert.equal(calls.length, 1);
  });
}

test("only explicit currentSource:null represents absence", async t => {
  environment(t, { currentSource: null });
  assert.deepEqual(await loadRf1086CurrentYearSource("owner", company, 2025), { currentSource: null });
});
for (const value of [{}, { currentSource: undefined }, { currentSource: [] }]) {
  test("malformed absent source cannot become a new-year draft", async t => {
    environment(t, value);
    await assert.rejects(loadRf1086CurrentYearSource("owner", company, 2025), invalid);
  });
}
for (const status of [401, 403, 404, 409, 503]) {
  test(`current source ${status} propagates with no guessed fallback`, async t => {
    const calls = environment(t, { status, code: "rf1086_source_not_found", type: "about:blank", title: "Sanitized",
      detail: "Sanitized", instance: "/fixture", requestId: "fixture-error" }, status);
    await assert.rejects(loadRf1086CurrentYearSource("owner", company, 2025), error => error instanceof TalliApiError && error.status === status);
    assert.equal(calls.length, 1);
  });
}

for (const [name, body, result, operation, suffix] of [
  ["year source", () => ({ ...draft(), supersedesSourceId: other }), receipt,
    captureRf1086YearSourceThroughApi, "/year-sources"],
  ["register observation", registerBody, registerReceipt,
    captureRf1086RegisterObservationThroughApi, "/register-observations"],
]) {
  test(`${name} captures preserve exact body and caller attempt key across deliberate retry`, async t => {
    const input = body(), before = structuredClone(input), output = result(), calls = environment(t, output);
    assert.deepEqual(await operation("owner", input, key), output);
    assert.deepEqual(await operation("owner", input, key), output);
    assert.equal(calls.length, 2);
    for (const call of calls) {
      assert.equal(call.url.pathname, base + suffix);
      assert.equal(call.request.method, "POST");
      assert.equal(call.request.headers["Idempotency-Key"], key);
      assert.equal(call.request.headers.Authorization, "Bearer owner");
      assert.equal(call.request.cache, "no-store");
      assert.deepEqual(JSON.parse(call.request.body), before);
    }
    assert.deepEqual(input, before);
  });
  for (const badKey of [undefined, "", "short", "bad key with spaces", "x".repeat(256)]) {
    test(`${name} refuses invalid or absent attempt key before sending`, async t => {
      const calls = environment(t, result());
      await assert.rejects(operation("owner", body(), badKey), error => error instanceof TalliApiError && error.status === 422);
      assert.equal(calls.length, 0);
    });
  }
  for (const change of ["company", "year", "version", "hash", "predecessor"]) {
    test(`${name} refuses misbound ${change} receipt`, async t => {
      const value = result(), input = body();
      if (change === "company") value.companyId = other;
      if (change === "year") value.incomeYear = 2024;
      if (change === "version") value.version = 0;
      if (change === "hash") value[name === "year source" ? "sourceSha256" : "factSha256"] = "invalid";
      if (change === "predecessor") input[name === "year source" ? "supersedesSourceId" : "supersedesObservationId"] = value[name === "year source" ? "sourceId" : "observationId"];
      environment(t, value);
      await assert.rejects(operation("owner", input, key), invalid);
    });
  }
}

test("preview generation preserves exact source scope as a separate non-replayed action", async t => {
  const body = { companyId: company, incomeYear: 2025, sourceId }, value = preview(), calls = environment(t, value);
  assert.deepEqual(await generateRf1086SourcePreviewThroughApi("owner", body), value);
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(calls[0].request.body), body);
  assert.equal(calls[0].request.headers["Idempotency-Key"], undefined);
});
for (const change of ["companyId", "incomeYear", "sourceId", "previewId"]) {
  test(`preview reads reject wrong ${change}`, async t => {
    const value = preview(); value[change] = change === "incomeYear" ? 2024 : other;
    environment(t, value);
    await assert.rejects(loadRf1086SourcePreview("owner", company, 2025, sourceId, previewId), invalid);
  });
}

test("original source document cannot be substituted with another owned document", async t => {
  environment(t, { ...document(), documentId: other });
  await assert.rejects(loadRf1086SourceDocument("owner", company, documentId), invalid);
});

test("source messages map known conflicts and validation without reflecting backend or provider detail", () => {
  const problem = (code, status = 409) => new TalliApiError(status, { type: "about:blank", title: "secret", detail: "private provider detail",
    instance: "/fixture", requestId: "fixture", code, status });
  assert.match(rf1086SourceErrorMessage(problem("rf1086_source_changed")), /Last inn/);
  assert.match(rf1086SourceErrorMessage(problem("rf1086_source_idempotency_conflict")), /lagringsforsøket/);
  assert.match(rf1086SourceErrorMessage(problem("rf1086_source_correction_reason_required")), /hvorfor/);
  assert.match(rf1086SourceErrorMessage(problem("rf1086_source_documents_unverified")), /originalene/);
  assert.match(rf1086SourceErrorMessage(problem("rf1086_source_invalid_request", 422)), /Kontroller feltene/);
  assert.match(rf1086SourceErrorMessage(problem("authentication_required", 401)), /Logg inn/);
  assert.equal(rf1086SourceErrorMessage(problem("untrusted_provider_code")), rf1086SourceErrorMessage(new Error("private provider detail")));
  assert.doesNotMatch(rf1086SourceErrorMessage(problem("untrusted_provider_code")), /secret|private|untrusted/);
});

test("intake retains unresolved cross-year governance rows without recomputing completeness", async t => {
  const value = intake();
  value.dividends = [{ decisionId: sourceId, decisionSha256: hash, sourceIncomeYear: 2024,
    reportingDate: "2026-01-02", reportingYear: 2026, status: "pending", supersedesDecisionId: other,
    economics: null, finalizations: [], documents: [], blockers: ["rf1086_source_governance_unresolved"] }];
  value.blockers = ["rf1086_source_governance_unresolved"];
  environment(t, value);
  assert.deepEqual(await loadRf1086SourceIntakeBasis("owner", company, 2025), value);
});

for (const kind of ["year", "register"]) {
  test(`${kind} capture refuses documents from a different company before sending`, async t => {
    const body = kind === "year" ? draft() : registerBody();
    body.documents[0].companyId = other;
    const calls = environment(t, kind === "year" ? receipt() : registerReceipt());
    const operation = kind === "year" ? captureRf1086YearSourceThroughApi : captureRf1086RegisterObservationThroughApi;
    await assert.rejects(operation("owner", body, key), error => error instanceof TalliApiError && error.status === 422);
    assert.equal(calls.length, 0);
  });
}

test("source capture refuses a case from a different reporting year before sending", async t => {
  const body = draft(); body.case.company.incomeYear = 2024;
  const calls = environment(t, receipt());
  await assert.rejects(captureRf1086YearSourceThroughApi("owner", body, key), error => error instanceof TalliApiError && error.status === 422);
  assert.equal(calls.length, 0);
});

for (const [field, value] of [["companyId", other], ["incomeYear", 2024], ["sourceId", other]]) {
  test(`generated preview refuses changed ${field}`, async t => {
    environment(t, { ...preview(), [field]: value });
    await assert.rejects(generateRf1086SourcePreviewThroughApi("owner", { companyId: company, incomeYear: 2025, sourceId }), invalid);
  });
}


test("only matching canonical 400/422 validation refusals release a rejected request", () => {
  const problem = (status, code, problemStatus = status) => new TalliApiError(status, {
    type: "about:blank", title: "Sanitized", detail: "Sanitized", instance: "/fixture", requestId: "fixture", code, status: problemStatus,
  });
  for (const status of [400, 422]) {
    for (const code of ["rf1086_source_invalid_request", "rf1086_source_event_evidence_incomplete", "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT", "invalid_request"]) {
      assert.equal(rf1086SourceCaptureRejected(problem(status, code)), true);
    }
    assert.equal(rf1086SourceCaptureRejected(problem(status, "unknown_provider_code")), false);
    assert.equal(rf1086SourceCaptureRejected(new TalliApiError(status, undefined)), false);
    assert.equal(rf1086SourceCaptureRejected(problem(status, "rf1086_source_invalid_request", 503)), false);
  }
  for (const status of [401, 403, 404, 409, 500, 502, 503]) {
    for (const code of ["rf1086_source_invalid_request", "rf1086_source_changed", "rf1086_source_idempotency_conflict"]) {
      assert.equal(rf1086SourceCaptureRejected(problem(status, code)), false);
    }
  }
  assert.equal(rf1086SourceCaptureRejected(new Error("network lost after commit")), false);
  assert.equal(rf1086SourceCaptureRejected(new DOMException("Aborted", "AbortError")), false);
});


test("known prewrite business validation at 409 allows correction of a first rejected request", () => {
  const rejected = code => rf1086SourceCaptureRejected(new TalliApiError(409, {
    type: "about:blank", title: "Sanitized", detail: "Sanitized", instance: "/fixture", requestId: "fixture", code, status: 409,
  }));
  for (const code of ["rf1086_source_amount_invalid", "rf1086_source_completeness_required", "rf1086_source_case_not_ready",
    "rf1086_source_event_evidence_incomplete", "rf1086_source_documents_unverified", "rf1086_source_paid_in_mismatch",
    "rf1086_source_correction_reason_required"]) assert.equal(rejected(code), true);
  for (const code of ["rf1086_source_idempotency_conflict", "rf1086_source_predecessor_mismatch", "rf1086_source_predecessor_required",
    "rf1086_source_changed", "rf1086_source_storage_invalid", "rf1086_source_snapshot_invalid", "rf1086_source_collision", "unknown"])
    assert.equal(rejected(code), false);
});
