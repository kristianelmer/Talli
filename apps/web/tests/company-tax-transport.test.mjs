import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { previewTaxSettlement, postTaxSettlement, taxPreviewErrorMessage, taxSubmissionErrorMessage } from "../features/company-tax-filing/index.ts";

const operationId = "70000000-0000-4000-8000-000000000001";
const companyId = "10000000-0000-4000-8000-000000000001";
const input = { settlementDate: " 2026-04-15 ", amount: 1.005, settlementType: "payment", documentStatus: "attached" };
const preview = {
  payload: { settlement_date: "2026-04-15", amount: 1, settlement_type: "payment", document_status: "attached", bank_transaction_id: null, document_id: null },
  lines: [{ account: "2500", description: "Betalt skatt", debit: 1, credit: 0 }, { account: "1920", description: "Bank", debit: 0, credit: 1 }],
  expectedBankAmount: -1,
};
function environment(t) {
  const prior = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  t.after(() => { if (prior === undefined) delete process.env.TALLI_BACKEND_URL; else process.env.TALLI_BACKEND_URL = prior; });
}

test("preview sends original facts and returns authoritative normalized payload and account lines", async (t) => {
  environment(t);
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/company-tax/settlement-previews");
    assert.equal(request.method, "POST");
    assert.equal(request.headers.Authorization, "Bearer owner");
    assert.equal(request.cache, "no-store");
    assert.deepEqual(JSON.parse(request.body), input);
    return Response.json(preview);
  });
  assert.deepEqual(await previewTaxSettlement("owner", input), preview);
});

test("capture keeps released path and stable identity without retrying an ambiguous outcome", async (t) => {
  environment(t); let calls = 0;
  const command = { companyId, incomeYear: 2026, actionId: operationId, settlementDate: "2026-04-15", amount: { amount: "1", currency: "NOK" }, settlementKind: "payment", documentStatus: "attached" };
  t.mock.method(globalThis, "fetch", async (url, request) => {
    calls += 1;
    assert.equal(new URL(url).pathname, "/api/v1/ledger/tax-settlements");
    assert.equal(new Headers(request.headers).get("Idempotency-Key"), operationId);
    assert.equal(new Headers(request.headers).get("X-Request-ID"), operationId);
    assert.deepEqual(JSON.parse(request.body), command);
    throw new TypeError("Connection lost after commit");
  });
  await assert.rejects(postTaxSettlement("owner", command, operationId), TypeError);
  assert.equal(calls, 1);
});

for (const corrupted of [{ ...preview, lines: [{}] }, { ...preview, payload: { ...preview.payload, amount: "1" } }, { ...preview, expectedBankAmount: "-1" }]) {
  test("generated preview guard rejects malformed backend output", async (t) => {
    environment(t);
    t.mock.method(globalThis, "fetch", async () => Response.json(corrupted));
    await assert.rejects(previewTaxSettlement("owner", input), error => error instanceof TalliApiError && error.status === 502);
  });
}

test("Archive read preserves all source fields and conceals malformed or foreign output as a failed source", async (t) => {
  environment(t);
  const { loadTaxSettlementArchiveSource } = await import("../features/company-tax-filing/index.ts");
  const row = { id: operationId, company_id: companyId, income_year: 2026, action_type: "tax_settlement", action_date: "2026-04-15", payload: { ...preview.payload, original_extra: { retained: true } }, ledger_entry_id: operationId, bank_transaction_id: null, document_id: null, risk_level: "ready", blocker_code: null, created_by: operationId, created_at: "2026-04-15T12:00:00.123456+00:00" };
  let result = { companyId, incomeYear: 2026, settlements: [row] };
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/company-tax/settlement-archive-source");
    assert.deepEqual([...new URL(url).searchParams], [["companyId", companyId], ["incomeYear", "2026"]]);
    assert.equal(request.cache, "no-store");
    return Response.json(result);
  });
  assert.deepEqual(await loadTaxSettlementArchiveSource("owner", companyId, 2026), { data: [row], error: null });
  for (const corruption of [{ ...result, incomeYear: 2025 }, { ...result, settlements: [{ ...row, company_id: operationId }] }, { ...result, settlements: [row, row] }]) {
    result = corruption;
    const failed = await loadTaxSettlementArchiveSource("owner", companyId, 2026);
    assert.ok(failed.error);
    assert.deepEqual(failed.data, []);
  }
});

const characterization = JSON.parse(readFileSync(new URL("../../../architecture/evidence/issues/146/legacy-preview-cases.json", import.meta.url), "utf8"));
for (const example of characterization.cases.filter(item => item.error)) {
  test(`submission preserves the original coded validation redirect: ${example.name}`, () => {
    const { code, message } = example.error;
    const error = new TalliApiError(422, { code, detail: message });
    assert.equal(taxPreviewErrorMessage(error), message);
    assert.equal(taxSubmissionErrorMessage(error), `${code}: ${message}`);
  });
}

for (const value of ["abc", "Infinity", "1,5"]) {
  test(`unparseable amount text retains backend-owned validation: ${value}`, async (t) => {
    environment(t);
    t.mock.method(globalThis, "fetch", async (_url, request) => {
      assert.equal(JSON.parse(request.body).amount, null);
      return Response.json({ type: "about:blank", title: "Ugyldig skatteoppgjør", status: 422,
        code: "invalid_amount", detail: "Skattebeløp må være større enn 0.",
        instance: "/api/v1/company-tax/settlement-previews", requestId: "fixture" }, { status: 422, headers: { "content-type": "application/problem+json" } });
    });
    await assert.rejects(previewTaxSettlement("owner", { ...input, amount: Number(value) }), error => {
      assert.equal(taxPreviewErrorMessage(error), "Skattebeløp må være større enn 0.");
      assert.equal(taxSubmissionErrorMessage(error), "invalid_amount: Skattebeløp må være større enn 0.");
      return true;
    });
  });
}

test("filing workspace keeps a failed source unavailable and checks returned scope", async (t) => {
  environment(t);
  const { loadCompanyTaxFilingWorkspace } = await import("../features/company-tax-filing/index.ts");
  let status = 200;
  let result = { companyId, incomeYear: 2025, previews: [], submissions: [], overrides: [], reviewComments: [], permissions: [], testEvidence: [] };
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/company-tax/filing-workspace");
    assert.deepEqual([...new URL(url).searchParams], [["companyId", companyId], ["incomeYear", "2025"]]);
    assert.equal(request.cache, "no-store");
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer owner");
    return Response.json(result, { status });
  });
  assert.deepEqual(await loadCompanyTaxFilingWorkspace("owner", companyId, 2025), result);
  for (const malformed of [{ ...result, companyId: operationId }, { ...result, incomeYear: 2024 }, { ...result, testEvidence: null }, { ...result, submissions: [{}] }]) {
    result = malformed;
    await assert.rejects(loadCompanyTaxFilingWorkspace("owner", companyId, 2025), error => error instanceof TalliApiError && error.status === 502);
  }
  status = 503;
  result = { code: "COMPANY_TAX_DEPENDENCY_UNAVAILABLE" };
  await assert.rejects(loadCompanyTaxFilingWorkspace("owner", companyId, 2025), error => error instanceof TalliApiError && error.status === 503);
});

test("TT02 import preserves evidence bytes, IDs, replay and MFA presentation", async (t) => {
  environment(t);
  const { importCompanyTaxTt02Evidence, taxEvidenceImportErrorMessage } = await import("../features/company-tax-filing/index.ts");
  const body = { companyId, incomeYear: 2025, evidenceJson: '{"synthetic":"ø", "nested": {"original":true}}', evidenceUrl: null };
  let result = { authorityTestRunId: operationId, filingSubmissionId: companyId, created: true };
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/company-tax/tt02-evidence-imports");
    assert.equal(request.method, "POST");
    assert.equal(request.headers.Authorization, "Bearer owner");
    assert.equal(request.cache, "no-store");
    assert.deepEqual(JSON.parse(request.body), body);
    return Response.json(result);
  });
  assert.deepEqual(await importCompanyTaxTt02Evidence("owner", body), result);
  result = { ...result, created: false };
  assert.deepEqual(await importCompanyTaxTt02Evidence("owner", body), result);
  result = { ...result, created: "false" };
  await assert.rejects(importCompanyTaxTt02Evidence("owner", body), error => error instanceof TalliApiError && error.status === 502);
  assert.equal(taxEvidenceImportErrorMessage(new TalliApiError(403, { code: "COMPANY_TAX_MFA_REQUIRED" })), "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.");
});

test("TT02 presenter distinguishes projection validation from persistence rejection", async () => {
  const { taxEvidenceImportErrorMessage } = await import("../features/company-tax-filing/index.ts");
  assert.equal(taxEvidenceImportErrorMessage(new TalliApiError(422, { code: "COMPANY_TAX_INVALID_INPUT" })), "Ugyldig TT02-evidens");
  assert.equal(taxEvidenceImportErrorMessage(new TalliApiError(422, { code: "COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED" })), "TT02-evidensen kunne ikke lagres.");
});

test("Tax preparation sends generated commands and rejects foreign scope", async (t) => {
  environment(t);
  const tax = await import("../features/company-tax-filing/index.ts");
  let result = { recordId: operationId, companyId, incomeYear: null };
  const sent = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    sent.push({ path: new URL(url).pathname, method: request.method, body: JSON.parse(request.body) });
    assert.equal(request.cache, "no-store");
    assert.equal(request.headers.Authorization, "Bearer owner");
    return Response.json(result);
  });
  for (const [name, path, body] of [
    ["companyTaxRecordOverride", "overrides", { previewId: operationId, fieldTarget: " field ", oldValue: "old", newValue: "new", reason: "reason", riskLevel: "warning", ownerConfirmed: true }],
    ["companyTaxAddReviewComment", "review-comments", { previewId: operationId, body: " review ", severity: "advisory" }],
    ["companyTaxConfirmPermission", "permissions", { companyId, productionEnabled: true }],
    ["companyTaxRecordTestEvidence", "test-evidence", { companyId, environment: "manual_evidence", status: "pending", testReference: " reference " }],
  ]) {
    assert.deepEqual(await tax[name]("owner", body), result);
    assert.deepEqual(sent.at(-1), { path: `/api/v1/company-tax/${path}`, method: "POST", body });
  }
  result = { ...result, companyId: operationId };
  await assert.rejects(tax.companyTaxConfirmPermission("owner", { companyId, productionEnabled: false }), error => error.status === 502);
});

test("Tax lookup and acknowledgement only return absence for an explicit owned not-found", async (t) => {
  environment(t);
  const { findCompanyTaxPreview, acknowledgeOwnedCompanyTaxComment } = await import("../features/company-tax-filing/index.ts");
  let status = 404; let code = "COMPANY_TAX_NOT_FOUND";
  t.mock.method(globalThis, "fetch", async () => Response.json({
    type: "about:blank", title: "Tax request failed", status, code, detail: "Synthetic", instance: "/api/v1/company-tax", requestId: "fixture",
  }, { status, headers: { "content-type": "application/problem+json" } }));
  for (const method of [findCompanyTaxPreview, acknowledgeOwnedCompanyTaxComment]) {
    assert.equal(await method("owner", operationId), null);
    for (const failure of [[503, "COMPANY_TAX_DEPENDENCY_UNAVAILABLE"], [403, "COMPANY_TAX_FORBIDDEN"], [404, "OTHER_NOT_FOUND"]]) {
      [status, code] = failure;
      await assert.rejects(method("owner", operationId), error => error instanceof TalliApiError && error.status === status);
    }
    status = 404; code = "COMPANY_TAX_NOT_FOUND";
  }
});

test("TT02 import retains the missing-company message", async () => {
  const { taxEvidenceImportErrorMessage } = await import("../features/company-tax-filing/index.ts");
  assert.equal(taxEvidenceImportErrorMessage(new TalliApiError(404, { code: "COMPANY_TAX_NOT_FOUND" })), "Selskapet finnes ikke");
});

test("Tax assessment previews send ordered source facts unchanged through generated endpoints", async (t) => {
  environment(t);
  const { previewAnnualTaxEstimate, previewCompanyTaxReadiness } = await import("../features/company-tax-filing/index.ts");
  const facts = { annualData: null, ledgerEntries: [{ entry_type: "admin_cost", lines: [{ account: "7770", debit: "1.005" }] }], holdingActions: [] };
  const estimate = { adminCosts: 1, interestIncome: 0, fritaksmetodenAddBack: 0, taxableShareSaleGain: 0,
    deductibleShareSaleLoss: 0, taxBasis: -1, estimatedTax: 0, status: "zero" };
  const readiness = { companyId, incomeYear: 2024, issues: [{ level: "warning", code: "tax_settlement_missing", message: "Missing", source: "tax_settlement", accepted: false }] };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    const path = new URL(url).pathname; calls.push(path);
    assert.equal(request.method, "POST"); assert.equal(request.headers.Authorization, "Bearer owner");
    assert.equal(request.cache, "no-store");
    assert.deepEqual(JSON.parse(request.body), path.endsWith("readiness-previews") ? { ...facts, companyId, incomeYear: 2024 } : facts);
    return Response.json(path.endsWith("readiness-previews") ? readiness : estimate);
  });
  assert.deepEqual(await previewAnnualTaxEstimate("owner", facts), estimate);
  assert.deepEqual(await previewCompanyTaxReadiness("owner", { ...facts, companyId, incomeYear: 2024 }), readiness);
  assert.deepEqual(calls, ["/api/v1/company-tax/annual-estimate-previews", "/api/v1/company-tax/readiness-previews"]);
});

for (const corruption of [
  { companyId: operationId }, { incomeYear: 2023 },
  { issues: [{ level: "info", code: "x", message: "x", source: "tax", accepted: false }] },
  { issues: [{ level: "warning", code: "x", message: "x", source: "tax", accepted: true }] },
]) test("readiness transport rejects wrong scope or corrupt policy output", async (t) => {
  environment(t);
  const { previewCompanyTaxReadiness } = await import("../features/company-tax-filing/index.ts");
  t.mock.method(globalThis, "fetch", async () => Response.json({ companyId, incomeYear: 2025, issues: [], ...corruption }));
  await assert.rejects(previewCompanyTaxReadiness("owner", { companyId, incomeYear: 2025, annualData: null, ledgerEntries: [], holdingActions: [] }),
    error => error instanceof TalliApiError && error.status === 502);
});


function sourceFacts() {
  const reference = `company-tax:${companyId}:2025`;
  return {
    evidence: { companyId, incomeYear: 2025, obligation: "skattemelding", scope: "talli_recorded_company_tax",
      reference, version: "company-tax-source-v1:" + "0".repeat(64), digest: "0".repeat(64), evaluatedAt: "2026-09-14T00:00:00Z" },
    readinessStatus: "blocked", hardBlocks: ["company_tax_production_disabled"],
    historyCoverage: { status: "complete", reasons: [], evidenceReference: reference,
      asOf: "2026-09-14T00:00:00Z", submissionCount: 0, scope: "talli_recorded_company_tax" },
    recordedSubmissions: [], productionAttempts: [], correctionLinks: [], incidents: [], outcomes: [],
  };
}

test("generated Tax source client binds company/year and preserves complete empty-history evidence", async () => {
  const expected = sourceFacts();
  const api = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer fixture" },
    fetch: async (url, request) => {
      assert.equal(new URL(url).pathname, "/api/v1/company-tax/source-facts");
      assert.equal(new URL(url).searchParams.get("companyId"), companyId);
      assert.equal(new URL(url).searchParams.get("incomeYear"), "2025");
      assert.equal(request.method, "GET");
      assert.equal(request.headers.Authorization, "Bearer fixture");
      return Response.json(expected);
    },
  });
  assert.deepEqual(await api.companyTaxGetSourceFacts(companyId, 2025), expected);
});

test("generated Tax source client refuses incomplete shapes and mismatched scope", async () => {
  for (const mutate of [
    value => { delete value.historyCoverage; },
    value => { value.evidence.companyId = "00000000-0000-0000-0000-000000000199"; },
    value => { value.evidence.incomeYear = 2024; },
    value => { value.evidence.obligation = "aarsregnskap"; },
    value => { value.historyCoverage.evidenceReference = "different"; },
    value => { value.readinessStatus = "ready"; },
  ]) {
    const value = sourceFacts(); mutate(value);
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json(value) });
    await assert.rejects(api.companyTaxGetSourceFacts(companyId, 2025), error => error instanceof TalliApiError && error.status === 502);
  }
});
