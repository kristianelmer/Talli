import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "../../packages/talli-api-client/src/generated/client.ts";

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
