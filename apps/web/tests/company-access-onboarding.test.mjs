import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

import {
  companyAccessActionErrorMessage,
  reacceptCompanyAgreementThroughApi,
} from "../features/company-access/index.ts";
import { TalliApiError } from "@talli/talli-api-client";

const agreementEvidence = {
  agreementAccepted: true,
  businessTermsVersion: "2026-07-17",
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
  dpaVersion: "2026-07-17",
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
};

test("an unknown organization keeps the specific Enhetsregisteret guidance", () => {
  assert.equal(
    companyAccessActionErrorMessage(new TalliApiError(404, {
      type: "https://talli.no/problems/company-registry-not-found",
      title: "Company registry record not found",
      status: 404,
      detail: "No eligible company was found.",
      instance: "/api/v1/company-access/onboarding",
      code: "COMPANY_REGISTRY_NOT_FOUND",
      requestId: "request-registry-not-found",
    })),
    "Fant ikke organisasjonsnummeret i Enhetsregisteret.",
  );
});

test("agreement reacceptance uses an authenticated generated-client request", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return Response.json(
      {
        type: "https://talli.no/problems/service-unavailable",
        title: "Service unavailable",
        status: 503,
        detail: "Temporarily unavailable.",
        instance: "/api/v1/company-access/onboarding",
        code: "SERVICE_UNAVAILABLE",
        requestId: "request-test",
      },
      { status: 503, headers: { "content-type": "application/problem+json" } },
    );
  };

  try {
    const results = await Promise.allSettled([
      reacceptCompanyAgreementThroughApi(
        "session-token",
        { companyId: "company-1", ...agreementEvidence },
        "request-reaccept",
      ),
    ]);
    assert.deepEqual(results.map(({ status }) => status), ["rejected"]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }

  assert.deepEqual(calls.map(({ url }) => url), [
    "https://backend.example/api/v1/company-access/agreements/reaccept",
  ]);
  assert.ok(calls.every(({ init }) => init.method === "POST"));
  assert.ok(calls.every(({ init }) => new Headers(init.headers).get("Authorization") === "Bearer session-token"));
  assert.ok(calls.every(({ init }) => init.signal instanceof AbortSignal));
  assert.deepEqual(calls.map(({ init }) => new Headers(init.headers).get("X-Request-ID")), [
    "request-reaccept",
  ]);
  assert.deepEqual(calls.map(({ init }) => JSON.parse(init.body)), [
    { companyId: "company-1", ...agreementEvidence },
  ]);
});

test("actions and agreement gates have no direct business-persistence facade", async () => {
  const [actions, ownerLayout, annualWorkspace, supabaseServer, manifest, documentation] = await Promise.all([
    readFile(new URL("../app/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/annual-workspace-server.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8"),
    readFile(new URL("../features/company-access/module.json", import.meta.url), "utf8"),
    readFile(new URL("../features/company-access/MODULE.md", import.meta.url), "utf8"),
  ]);
  const reacceptAgreement = actions.match(
    /export async function reacceptCompanyAgreement[\s\S]+?\n\}\n\nexport async function/gu,
  )?.[0] ?? "";

  assert.match(reacceptAgreement, /reacceptCompanyAgreementThroughApi/u);
  assert.match(reacceptAgreement, /currentAgreementCommand/u);
  assert.doesNotMatch(actions, /createWorkspace|onboardCompanyThroughApi/u);
  assert.match(ownerLayout, /companies\.filter\(\(\{ currentAgreementAccepted \}\) => !currentAgreementAccepted\)/u);
  assert.match(annualWorkspace, /if \(!company\.currentAgreementAccepted\)/u);
  assert.doesNotMatch(actions, /\.\/lib\/(?:brreg|customer-onboarding|customer-agreement-reacceptance)/u);
  assert.doesNotMatch(
    reacceptAgreement,
    /createSupabaseServiceRoleClient|\.rpc\(/u,
  );
  assert.doesNotMatch(
    `${ownerLayout}\n${annualWorkspace}\n${supabaseServer}`,
    /listCustomerAgreementAcceptances|\.from\("customer_agreement_acceptances"\)/u,
  );

  for (const legacyFile of [
    "../app/lib/brreg.ts",
    "../app/lib/customer-onboarding.ts",
    "../app/lib/customer-agreement-reacceptance.ts",
  ]) {
    await assert.rejects(access(new URL(legacyFile, import.meta.url)), { code: "ENOENT" });
  }

  const operationIds = [
    "companyAccessEligibilityPrecheck",
    "companyAccessEligibilityDefinitive",
    "companyAccessAdmitCompanyYear",
    "companyAccessRecheckCompanyYearEligibility",
    "companyAccessReacceptAgreement",
  ];
  const feature = JSON.parse(manifest);
  for (const operationId of operationIds) {
    assert.ok(feature.apiOperations.includes(operationId));
    assert.match(documentation, new RegExp(operationId, "u"));
  }
});
