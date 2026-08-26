import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";
import { TalliApiError } from "@talli/talli-api-client";

import {
  loadCompanyAccessRecord,
  loadOperatorContext,
  searchOperatorCompanyRecords,
} from "../features/company-access/transport/load-company-access-context.ts";
import { listCompanyAccessContexts } from "../app/lib/company-access-context.ts";
import { createSystemUserCallbackHandler } from "../app/auth/systembruker/confirm/route.ts";

test("company records and operator access use authenticated generated-client queries", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return Response.json({
      type: "https://talli.no/problems/company-access-unavailable",
      title: "Company access unavailable",
      status: 503,
      detail: "Company access is temporarily unavailable.",
      instance: new URL(String(url)).pathname,
      code: "COMPANY_ACCESS_UNAVAILABLE",
      requestId: "request-test",
    }, { status: 503, headers: { "content-type": "application/problem+json" } });
  };

  try {
    const results = await Promise.allSettled([
      loadCompanyAccessRecord("session-token", "company-1", "request-company"),
      loadOperatorContext("session-token", "request-operator"),
      searchOperatorCompanyRecords("session-token", "  Rolig Holding  ", "request-search"),
    ]);
    assert.deepEqual(results.map(({ status }) => status), ["rejected", "rejected", "rejected"]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }

  assert.deepEqual(calls.map(({ url }) => url), [
    "https://backend.example/api/v1/company-access/companies/company-1",
    "https://backend.example/api/v1/company-access/operator-context",
    "https://backend.example/api/v1/company-access/operator-companies?query=++Rolig+Holding++",
  ]);
  assert.ok(calls.every(({ init }) => init.method === "GET"));
  assert.ok(calls.every(({ init }) => new Headers(init.headers).get("Authorization") === "Bearer session-token"));
  assert.ok(calls.every(({ init }) => init.signal instanceof AbortSignal));
  assert.deepEqual(calls.map(({ init }) => new Headers(init.headers).get("X-Request-ID")), [
    "request-company",
    "request-operator",
    "request-search",
  ]);
});

function problem(status, code) {
  return {
    type: `https://talli.no/problems/${code.toLowerCase().replaceAll("_", "-")}`,
    title: code,
    status,
    detail: code,
    instance: "/api/v1/company-access/context",
    code,
    requestId: "request-context",
  };
}

test("a verified user without an owner company reaches onboarding but other context failures stay closed", async () => {
  const dependencies = (error) => ({
    async getAccessToken() { return "session-token"; },
    async loadContext() { throw error; },
  });

  assert.deepEqual(
    await listCompanyAccessContexts(
      {},
      dependencies(new TalliApiError(404, problem(404, "COMPANY_CONTEXT_NOT_FOUND"))),
    ),
    { companies: [], error: null },
  );

  for (const [status, code] of [
    [401, "AUTHENTICATION_REQUIRED"],
    [403, "AAL2_REQUIRED"],
    [503, "COMPANY_ACCESS_UNAVAILABLE"],
    [503, "COMPANY_CONTEXT_NOT_FOUND"],
  ]) {
    const result = await listCompanyAccessContexts(
      {},
      dependencies(new TalliApiError(status, problem(status, code))),
    );
    assert.deepEqual(result, code === "AAL2_REQUIRED"
      ? {
          companies: [],
          error: "Company access is temporarily unavailable.",
          requiresAal2: true,
        }
      : { companies: [], error: "Company access is temporarily unavailable." });
  }
});

test("system-user callback resolves company authorization through its injected company-access query", async () => {
  const requestId = "22345678-1234-4234-8234-123456789abc";
  const companyId = "12345678-1234-4234-8234-123456789abc";
  const ownerId = "32345678-1234-4234-8234-123456789abc";
  const companyLoads = [];
  const reconciliations = [];
  const deletedCookies = [];
  const queriedTables = [];
  let companyRole = "owner";
  const supabase = {
    auth: {
      async getUser() {
        return { data: { user: { id: ownerId } }, error: null };
      },
    },
    from(table) {
      queriedTables.push(table);
      assert.equal(table, "system_user_requests");
      const builder = {
        select() { return builder; },
        eq() { return builder; },
        async maybeSingle() {
          return {
            data: {
              id: requestId,
              company_id: companyId,
              initiating_owner_user_id: ownerId,
            },
            error: null,
          };
        },
      };
      return builder;
    },
  };
  const handler = createSystemUserCallbackHandler({
    siteOrigin: "https://talli.no",
    async createSupabaseClient() { return supabase; },
    async getCookieStore() {
      return {
        get() { return { value: requestId }; },
        delete(options) { deletedCookies.push(options); },
      };
    },
    async loadCompany(candidate) {
      companyLoads.push(candidate);
      return { id: companyId, org_number: "310279617", role: companyRole };
    },
    async reconcileRequest(input) {
      reconciliations.push(input);
      return {
        requestId,
        companyId,
        status: "accepted",
        preflightVerifiedAt: "2026-08-26T00:00:00Z",
        confirmUrl: null,
        failureCode: null,
      };
    },
  });

  const response = await handler(new Request("https://talli.no/auth/systembruker/confirm"));

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `https://talli.no/connections?company=${companyId}&systembruker=connected`);
  assert.deepEqual(queriedTables, ["system_user_requests"]);
  assert.deepEqual(companyLoads, [companyId]);
  assert.equal(reconciliations[0].orgNumber, "310279617");
  assert.deepEqual(deletedCookies, [{
    name: "talli_system_user_request",
    path: "/auth/systembruker/confirm",
  }]);

  companyRole = "reviewer";
  const concealed = await handler(new Request("https://talli.no/auth/systembruker/confirm"));
  assert.equal(concealed.headers.get("location"), "https://talli.no/connections?systembruker=manual");
  assert.equal(reconciliations.length, 1);
});

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(?:ts|tsx)$/u.test(entry.name) ? [path] : [];
  }));
  return nested.flat();
}

test("every Stage 1 web consumer authorizes through company-access contracts", async () => {
  const roots = [
    new URL("../app/", import.meta.url),
    new URL("../features/", import.meta.url),
  ];
  const files = (await Promise.all(roots.map(sourceFiles))).flat();
  const sources = await Promise.all(files.map(async (file) => ({
    file: file.pathname,
    source: await readFile(file, "utf8"),
  })));
  const companyAccessTables = [
    "companies",
    "company_memberships",
    "company_invitations",
    "customer_agreement_acceptances",
    "company_cancellations",
    "company_deletion_reviews",
    "step_up_events",
    "support_operators",
  ].join("|");
  const directTable = new RegExp(`\\.from\\(["'](?:${companyAccessTables})["']\\)`, "u");
  const directRpc = /\.rpc\(["'](?:company_access_[^"']+|create_company_workspace_with_acceptance|append_company_agreement_acceptance)["']/u;
  const violations = sources.flatMap(({ file, source }) => [
    ...(directTable.test(source) ? [`${file}: direct company-access table`] : []),
    ...(directRpc.test(source) ? [`${file}: direct company-access RPC`] : []),
  ]);
  assert.deepEqual(violations, []);

  const read = (path) => readFile(new URL(path, import.meta.url), "utf8");
  const [
    actions,
    supabaseServer,
    callbackRoute,
    previewRoute,
    corporateDecisionPage,
    archiveRoute,
    ownerLayout,
  ] = await Promise.all([
    read("../app/actions.ts"),
    read("../app/lib/supabase/server.ts"),
    read("../app/auth/systembruker/confirm/route.ts"),
    read("../app/documents/[documentId]/preview/route.ts"),
    read("../app/(owner)/corporate-decisions/[decisionId]/page.tsx"),
    read("../app/archive/[companyId]/[incomeYear]/download/route.ts"),
    read("../app/(owner)/layout.tsx"),
  ]);

  assert.match(actions, /loadAcceptedMembershipCompany/u);
  assert.match(actions, /loadAuthorizedSupportOperator/u);
  assert.match(supabaseServer, /loadOperatorContext/u);
  assert.match(supabaseServer, /searchOperatorCompanyRecords/u);
  assert.match(callbackRoute, /loadCompany\(companyId: string\)/u);
  assert.match(callbackRoute, /dependencies\.loadCompany\(request\.company_id\)/u);
  assert.match(previewRoute, /loadAcceptedMembershipCompany/u);
  assert.match(previewRoute, /company\.role !== "owner"/u);
  assert.match(corporateDecisionPage, /loadAcceptedMembershipCompany/u);
  assert.match(corporateDecisionPage, /company\.role !== "owner"/u);
  assert.match(archiveRoute, /loadAcceptedMembershipCompany/u);
  assert.match(archiveRoute, /requireStepUpForAction/u);
  assert.match(ownerLayout, /pendingCompany \?/u);
  assert.match(ownerLayout, /stoppedCompanies\.map/u);
  assert.match(ownerLayout, /\{children\}/u);
});
