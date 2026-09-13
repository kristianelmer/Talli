import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { TalliApiError } from "@talli/talli-api-client";
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
