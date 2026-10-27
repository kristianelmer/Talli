import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createHash, webcrypto } from "node:crypto";
import vm from "node:vm";
import ts from "typescript";
import { createTalliApiClient, TalliApiError, verifyCompanyTaxDeliveryDraftArchive } from "../../packages/talli-api-client/src/index.ts";

const company = "10000000-0000-4000-8000-000000000001";
const source = () => ({
  evidence: { companyId: company, incomeYear: 2025, obligation: "skattemelding",
    scope: "talli_recorded_company_tax", reference: "retained-source", version: "company-tax-source-v2:"+"a".repeat(64),
    digest: "a".repeat(64), evaluatedAt: "2026-10-26T07:00:00Z" },
  historyCoverage: { status: "complete", reasons: [], evidenceReference: "retained-source",
    asOf: "2026-10-26T07:00:00Z", submissionCount: 0, scope: "talli_recorded_company_tax" },
  readinessStatus: "blocked", hardBlocks: ["company_tax_production_disabled"],
  recordedSubmissions: [], productionAttempts: [], correctionLinks: [], incidents: [], outcomes: [],
});
const draft = () => ({ filingId: "10000000-0000-4000-8000-000000000002", preparedBy: company,
  recordedAt: "2026-10-26T06:59:59Z", draftSha256: "b".repeat(64), reviewSha256: "c".repeat(64),
  schemaSha256: "d".repeat(64), status: "prepared_only" });

test("new client accepts the unchanged source response without opting into drafts", async () => {
  const value = source(); let called;
  const client = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async url => {
    called = new URL(url); return Response.json(value);
  } });
  assert.deepEqual(await client.companyTaxGetSourceFacts(company,2025),value);
  assert.equal(called.searchParams.has("includeDeliveryDrafts"),false);
});

test("draft summaries require explicit opt-in and retain prepared-only semantics", async () => {
  const value = { ...source(), deliveryDrafts: [draft()] }; let called;
  const client = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async url => {
    called = new URL(url); return Response.json(value);
  } });
  assert.deepEqual(await client.companyTaxGetSourceFacts(company,2025,{},true),value);
  assert.equal(called.searchParams.get("includeDeliveryDrafts"),"true");
});

for (const [name, value] of [
  ["older backend omits requested enumeration",source()],
  ["invalid digest",{ ...source(), deliveryDrafts: [{ ...draft(), draftSha256: "invalid" }] }],
  ["invented submitted status",{ ...source(), deliveryDrafts: [{ ...draft(), status: "submitted" }] }],
  ["raw XML in summary",{ ...source(), deliveryDrafts: [{ ...draft(), envelopeXml: "<private/>" }] }],
]) test(`draft opt-in rejects ${name}`, async () => {
  const client = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json(value) });
  await assert.rejects(client.companyTaxGetSourceFacts(company,2025,{},true),
    error => error instanceof TalliApiError && error.status===502);
});

const command = () => ({ companyId: company, incomeYear: 2025, filingId: draft().filingId });
const prepared = () => ({ ...command(), recordedAt: draft().recordedAt, draftSha256: draft().draftSha256,
  reviewSha256: draft().reviewSha256, schemaSha256: draft().schemaSha256, status: "prepared_only" });

test("server preparation sends only scope and caller command identity with authenticated idempotency", async () => {
  let called;
  const client = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, init) => {
    called = { url, init }; return Response.json(prepared());
  } });
  assert.deepEqual(await client.companyTaxPrepareDeliveryDraft(command(), {
    headers: { Authorization: "Bearer synthetic" }, idempotencyKey: "one-preparation-command",
  }), prepared());
  assert.equal(called.url, "https://backend.example/api/v1/company-tax/delivery-drafts");
  assert.equal(called.init.method, "POST");
  assert.equal(new Headers(called.init.headers).get("Idempotency-Key"), "one-preparation-command");
  assert.equal(new Headers(called.init.headers).get("Authorization"), "Bearer synthetic");
  assert.deepEqual(JSON.parse(called.init.body), command());
});

for (const [name, change] of [
  ["another company", { companyId: draft().filingId }],
  ["another filing", { filingId: company }],
  ["another year", { incomeYear: 2026 }],
  ["provider outcome", { status: "submitted" }],
  ["malformed digest", { draftSha256: "bad" }],
  ["original Tax bytes", { currentDocument: "private" }],
]) test(`server preparation rejects ${name} in its receipt`, async () => {
  const client = createTalliApiClient({ baseUrl: "https://backend.example",
    fetch: async () => Response.json({ ...prepared(), ...change }) });
  await assert.rejects(client.companyTaxPrepareDeliveryDraft(command(), { idempotencyKey: "one-preparation-command" }),
    error => error instanceof TalliApiError && error.status === 502);
});

for (const version of ["company-tax-delivery-draft-v1", "company-tax-delivery-draft-v2", "unknown"])
  for (const tamper of [false, true]) test(`archive reader checks exact ${version} originals, tamper=${tamper}`, async () => {
    const canonicalJson = JSON.stringify({ version, draft: { filing_id: draft().filingId,
      envelope: { source: { company_id: { value: company }, income_year: { value: 2025 } } },
      ...(version.endsWith("v2") ? { current_document: { original: "retained å" } } : {}),
    } });
    const original = { codec: "company-tax-delivery-draft-archive-v1", coverage: "complete",
      sourceSha256: source().evidence.digest, companyId: company, incomeYear: 2025,
      recordCount: 1, records: [{ filingId: draft().filingId, canonicalJson,
        draftSha256: tamper ? "0".repeat(64) : createHash("sha256").update(canonicalJson).digest("hex") }] };
    const exports = {};
    const dependencies = { backendBaseUrl: () => "https://backend.example", TalliApiError, verifyCompanyTaxDeliveryDraftArchive,
      createTalliApiClient: () => ({ companyTaxGetSourceFacts: async () => source(),
        companyTaxGetDeliveryDraftArchive: async () => original }) };
    const text = readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts", import.meta.url), "utf8");
    vm.runInNewContext(ts.transpileModule(text, { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    } }).outputText, { exports, require: () => dependencies, AbortSignal, TextEncoder, crypto: webcrypto });
    const result = await exports.loadTaxDeliveryDraftArchiveSource("synthetic", company, 2025);
    if (tamper || version === "unknown") {
      assert.equal(result.data, null); assert.ok(result.error);
    } else {
      assert.equal(result.error, null);
      assert.equal(result.data.originals.records[0].canonicalJson, canonicalJson);
    }
  });
