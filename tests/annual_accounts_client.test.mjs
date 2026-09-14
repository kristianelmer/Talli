import assert from "node:assert/strict";
import test from "node:test";
import { createTalliApiClient, TalliApiError } from "../packages/talli-api-client/src/generated/client.ts";

const companyId = "15300000-0000-4000-8000-000000000001";
const recordId = "15300000-0000-4000-8000-000000000020";
const empty = { companyId, incomeYear: 2025, previews: [], submissions: [], overrides: [], reviewComments: [], permissions: [], testEvidence: [] };

test("Accounts source facts bind complete history to authenticated company/year evidence", async (t) => {
  const evidence = { companyId, incomeYear: 2025, reference: `annual-accounts:${companyId}:2025`,
    version: "annual-accounts-source-v1:fixture", digest: "a".repeat(64), evaluatedAt: "2026-09-14T12:00:00Z",
    obligation: "aarsregnskap", scope: "talli_recorded_annual_accounts" };
  const valid = { evidence, readinessStatus: "blocked", hardBlocks: ["annual_accounts_production_disabled"],
    historyCoverage: { status: "complete", reasons: [], evidenceReference: evidence.reference,
      asOf: evidence.evaluatedAt, submissionCount: 0, scope: evidence.scope },
    recordedSubmissions: [], productionAttempts: [], correctionLinks: [], incidents: [], outcomes: [] };
  let response = valid;
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/annual-accounts/source-facts");
    assert.equal(new URL(url).searchParams.get("companyId"), companyId);
    assert.equal(new URL(url).searchParams.get("incomeYear"), "2025");
    assert.equal(request.cache, "no-store");
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer fixture");
    return Response.json(response);
  });
  const client = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer fixture" } });
  assert.deepEqual(await client.annualAccountsGetSourceFacts(companyId, 2025), valid);
  for (const invalid of [
    { ...valid, evidence: { ...evidence, companyId: recordId } },
    { ...valid, evidence: { ...evidence, incomeYear: 2024 } },
    { ...valid, historyCoverage: { ...valid.historyCoverage, evidenceReference: "foreign" } },
    { ...valid, evidence: { ...evidence, obligation: "skattemelding" } },
    { ...valid, historyCoverage: { ...valid.historyCoverage, status: "invented" } },
  ]) {
    response = invalid;
    await assert.rejects(client.annualAccountsGetSourceFacts(companyId, 2025), error => error instanceof TalliApiError && error.status === 502);
  }
});

test("Accounts workspace uses authenticated uncached transport and rejects foreign scope", async (t) => {
  let response = empty;
  t.mock.method(globalThis, "fetch", async (url, request) => {
    assert.equal(new URL(url).pathname, "/api/v1/annual-accounts/filing-workspace");
    assert.equal(new URL(url).searchParams.get("incomeYear"), "2025");
    assert.equal(request.cache, "no-store");
    assert.equal(new Headers(request.headers).get("Authorization"), "Bearer fixture");
    return Response.json(response);
  });
  const client = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer fixture" } });
  assert.deepEqual(await client.annualAccountsGetFilingWorkspace(companyId, 2025), empty);
  response = { ...empty, companyId: recordId };
  await assert.rejects(client.annualAccountsGetFilingWorkspace(companyId, 2025), error => error instanceof TalliApiError && error.status === 502);
});

test("Accounts import posts original evidence once and validates the inserted reference result", async (t) => {
  const body = { companyId, evidenceJson: '{"synthetic":true}', evidenceUrl: "legacy reference" };
  const result = { recordId, testReference: "tt02:synthetic" };
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, request) => {
    calls += 1;
    assert.equal(new URL(url).pathname, "/api/v1/annual-accounts/tt02-evidence-imports");
    assert.deepEqual(JSON.parse(request.body), body);
    return Response.json(result);
  });
  const client = createTalliApiClient({ baseUrl: "https://backend.example", headers: { Authorization: "Bearer fixture" } });
  assert.deepEqual(await client.annualAccountsImportTt02Evidence(body), result);
  assert.equal(calls, 1);
});
