import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  admitCompanyYearThroughApi,
  assessCompanyEligibility,
  precheckCompanyEligibility,
  recheckCompanyYearEligibilityThroughApi,
  eligibilityAdmissionRestartRequired,
  eligibilityActionErrorMessage,
} from "../features/company-access/index.ts";
import { TalliApiError } from "@talli/talli-api-client";

const supportedResult = {
  decision: "supported",
  provisional: false,
  capabilityManifestVersion: "2026.1",
  capabilityManifestSha256: "a".repeat(64),
  accountingYear: 2026,
  publicFacts: {
    orgNumber: "314159265",
    name: "Rolig Holding AS",
    entityType: "AS",
    statusText: "aktiv",
    source: "brreg",
  },
  publicFactsSha256: "b".repeat(64),
  questions: [],
  questionCodes: [],
  answers: { is_small_enterprise: "yes" },
  answersSha256: "c".repeat(64),
  reasonCodes: [],
  reasonExplanations: [],
  nextStepCode: "CREATE_ACCOUNT_AND_ACCEPT",
  nextStep: "Opprett konto og godta selskapsåret når du er klar.",
  companyYearPromise: {
    accountingYear: 2026,
    startsOn: "2026-01-01",
    endsOn: "2026-12-31",
    reconstructionRequiredFrom: "2026-01-01",
    onlyAccountingAndFilingProduct: true,
    customerClaims: [
      "komplett gjenoppbygging fra 1. januar",
      "bokføring gjennom hele året",
    ],
  },
};

test("stale admission evidence gets a truthful restart route", () => {
  for (const code of [
    "ELIGIBILITY_MANIFEST_CHANGED",
    "ELIGIBILITY_FACTS_CHANGED",
    "COMPANY_YEAR_NOT_ELIGIBLE",
    "ADMISSION_EVIDENCE_CHANGED",
  ]) {
    const error = new TalliApiError(409, {
      type: "https://talli.no/problems/eligibility",
      title: "Eligibility changed",
      status: 409,
      detail: "changed",
      instance: "/api/v1/company-access/company-year-admissions",
      code,
      requestId: "request-eligibility",
    });
    assert.equal(eligibilityAdmissionRestartRequired(error), true);
    assert.match(
      eligibilityActionErrorMessage(error),
      /Start (?:den gratis )?sjekken på nytt/u,
    );
  }
  assert.equal(eligibilityAdmissionRestartRequired(new Error("provider")), false);
});

test("precheck and definitive eligibility use public generated-client calls", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return Response.json(supportedResult);
  };
  try {
    const preliminary = await precheckCompanyEligibility(
      { orgNumber: "314159265", accountingYear: 2026 },
      "precheck-request",
    );
    const final = await assessCompanyEligibility({
      orgNumber: "314159265",
      accountingYear: 2026,
      expectedPublicFactsSha256: preliminary.publicFactsSha256,
      capabilityManifestVersion: preliminary.capabilityManifestVersion,
      capabilityManifestSha256: preliminary.capabilityManifestSha256,
      answers: { is_small_enterprise: "yes" },
    }, "definitive-request");
    assert.equal(final.decision, "supported");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }

  assert.deepEqual(calls.map(({ url }) => url), [
    "https://backend.example/api/v1/company-access/eligibility/precheck",
    "https://backend.example/api/v1/company-access/eligibility/definitive",
  ]);
  assert.ok(calls.every(({ init }) => init.method === "POST"));
  assert.ok(calls.every(({ init }) => !new Headers(init.headers).has("Authorization")));
  assert.deepEqual(calls.map(({ init }) => new Headers(init.headers).get("X-Request-ID")), [
    "precheck-request",
    "definitive-request",
  ]);
});

test("company-year admission is authenticated and carries the exact immutable boundary", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  let call;
  globalThis.fetch = async (url, init) => {
    call = { url: String(url), init };
    return Response.json({
      companyId: "10000000-0000-4000-8000-000000000001",
      companyYearAdmissionId: "20000000-0000-4000-8000-000000000002",
      accountingYear: 2026,
      reconstructFrom: "2026-01-01",
      capabilityManifestVersion: "2026.1",
      capabilityManifestSha256: "a".repeat(64),
      currentAgreementAccepted: true,
      replayed: false,
    }, { status: 201 });
  };
  try {
    await admitCompanyYearThroughApi("session-token", {
      operationId: "40000000-0000-4000-8000-000000000004",
      orgNumber: "314159265",
      accountingYear: 2026,
      expectedPublicFactsSha256: "b".repeat(64),
      capabilityManifestVersion: "2026.1",
      capabilityManifestSha256: "a".repeat(64),
      answers: { is_small_enterprise: "yes" },
      authorityAccepted: true,
      companyYearPromiseAccepted: true,
      agreementAccepted: true,
      businessTermsVersion: "2026-08-30",
      businessTermsSha256: "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04",
      dpaVersion: "2026-08-30",
      dpaSha256: "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a",
      privacyNoticeVersion: "2026-08-30",
      privacyNoticeSha256: "041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de",
    }, "admission-request");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
  assert.equal(call.url, "https://backend.example/api/v1/company-access/company-year-admissions");
  assert.equal(new Headers(call.init.headers).get("Authorization"), "Bearer session-token");
  assert.equal(new Headers(call.init.headers).get("X-Request-ID"), "admission-request");
  assert.equal(JSON.parse(call.init.body).companyYearPromiseAccepted, true);
  assert.equal(JSON.parse(call.init.body).authorityAccepted, true);
});

test("company-year recheck is authenticated, trigger-bound, and fail-closed decoded", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  let call;
  globalThis.fetch = async (url, init) => {
    call = { url: String(url), init };
    return Response.json({
      acceptedCapabilityManifestSha256: "a".repeat(64),
      acceptedCapabilityManifestVersion: "2026.1",
      acceptedCompanyYearPromise: supportedResult.companyYearPromise,
      accountingYear: 2026,
      archiveExportAvailable: true,
      companyId: "10000000-0000-4000-8000-000000000001",
      companyYearAdmissionId: "20000000-0000-4000-8000-000000000002",
      companyYearEligibilityAssessmentId: "30000000-0000-4000-8000-000000000003",
      consequentialOperationsAllowed: false,
      currentCapabilityManifestSha256: "d".repeat(64),
      currentCapabilityManifestVersion: "2026.1",
      decision: "blocked",
      nextStep: "Stopp berørt arbeid og innsending.",
      nextStepCode: "STOP_EXPORT_AND_CONTACT",
      reasonCodes: ["NOT_SMALL_ENTERPRISE"],
      reasonExplanations: ["Dette svaret er utenfor grensen: Er selskapet et lite foretak?"],
      replayed: false,
      trigger: "material_answer_changed",
    }, { status: 201 });
  };
  try {
    const result = await recheckCompanyYearEligibilityThroughApi(
      "session-token",
      "20000000-0000-4000-8000-000000000002",
      {
        operationId: "40000000-0000-4000-8000-000000000004",
        trigger: "material_answer_changed",
        answers: { is_small_enterprise: "no" },
      },
      "recheck-request",
    );
    assert.equal(result.consequentialOperationsAllowed, false);
    assert.equal(result.archiveExportAvailable, true);
    assert.equal(result.acceptedCompanyYearPromise.onlyAccountingAndFilingProduct, true);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
  assert.equal(
    call.url,
    "https://backend.example/api/v1/company-access/company-year-admissions/20000000-0000-4000-8000-000000000002/eligibility-rechecks",
  );
  assert.equal(new Headers(call.init.headers).get("Authorization"), "Bearer session-token");
  assert.equal(new Headers(call.init.headers).get("X-Request-ID"), "recheck-request");
  assert.deepEqual(JSON.parse(call.init.body), {
    answers: { is_small_enterprise: "no" },
    operationId: "40000000-0000-4000-8000-000000000004",
    trigger: "material_answer_changed",
  });
});

test("the functional public journey owns no policy, direct fetch, or business persistence", async () => {
  const [
    page,
    checker,
    actions,
    continuation,
    onboardingPage,
    admissionActions,
    loginPage,
    confirmationRoute,
    workspaceData,
    ownerLayout,
    eligibilityGate,
    globalActions,
    materialRecheckPage,
    materialRecheckActions,
    appNav,
  ] = await Promise.all([
    readFile(new URL("../app/sjekk-selskapet/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/sjekk-selskapet/EligibilityChecker.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/sjekk-selskapet/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/eligibility-continuation.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/onboarding/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/onboarding/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(auth)/login/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/auth/confirm/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/workspace-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/company-year-eligibility-gate.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/selskapsgrense/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/selskapsgrense/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/AppNav.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /Sjekk selskapet gratis/u);
  assert.match(page, /Foreløpig/u);
  assert.match(checker, /Foreløpig svar · Utenfor grensen/u);
  assert.match(actions, /precheckCompanyEligibility/u);
  assert.match(actions, /assessCompanyEligibility/u);
  assert.match(actions, /setEligibilityContinuation/u);
  assert.match(actions, /clearEligibilityContinuation/u);
  assert.match(continuation, /httpOnly:\s*true/u);
  assert.match(continuation, /sameSite:\s*"lax"/u);
  assert.match(onboardingPage, /CompanyYearAdmissionForm/u);
  assert.match(onboardingPage, /const eligibilityContinuation = await readEligibilityContinuation\(\)/u);
  assert.match(onboardingPage, /company\.org_number === eligibilityContinuation\.orgNumber/u);
  assert.match(onboardingPage, /pendingAdmission === null/u);
  assert.match(checker, /Offentlige selskapsopplysninger/u);
  assert.match(admissionActions, /admitCompanyYearThroughApi/u);
  assert.match(admissionActions, /getCurrentSessionAccessToken/u);
  assert.match(admissionActions, /clearEligibilityContinuation/u);
  assert.match(admissionActions, /eligibilityAdmissionRestartRequired/u);
  assert.match(admissionActions, /eligibilityActionErrorMessage/u);
  assert.match(loginPage, /signup\?next=/u);
  assert.match(confirmationRoute, /failure\.searchParams\.set\("next", next\)/u);
  assert.match(workspaceData, /companies\s*\.map\(\(company\) => company\.admittedAccountingYear\)/u);
  assert.match(ownerLayout, /stoppedCompanies\.map/u);
  assert.match(ownerLayout, /\{children\}/u);
  assert.match(ownerLayout, /Ferdige arkiver kan eksporteres fra arbeidsflaten/u);
  assert.doesNotMatch(ownerLayout, /archive\/\$\{stoppedCompany\.id\}/u);
  assert.match(ownerLayout, /mailto:post@talli\.no/u);
  assert.match(eligibilityGate, /loadCompanyAccessContext/u);
  assert.match(eligibilityGate, /recheckCompanyYearEligibilityThroughApi/u);
  assert.doesNotMatch(eligibilityGate, /createSupabaseServiceRoleClient|\.rpc\(|\.from\(/u);
  assert.equal(globalActions.match(/requireCompanyYearEligibilityGate\(/gu)?.length, 1);
  assert.doesNotMatch(globalActions, /requireCompanyYearEligibilityGate\([^\n]+"before_(?:payment|filing)"/u);
  assert.match(globalActions, /selskapsgrense\?companyId=\$\{companyId\}&error=/u);
  assert.match(materialRecheckPage, /EligibilityInterview/u);
  assert.match(materialRecheckPage, /companyId=\{selectedCompany\.id\}/u);
  assert.match(materialRecheckActions, /trigger:\s*"material_answer_changed"/u);
  assert.match(materialRecheckActions, /recheckCompanyYearEligibilityThroughApi/u);
  assert.match(materialRecheckActions, /listCompanyAccessContexts\(\{ companyId \}\)/u);
  assert.doesNotMatch(materialRecheckActions, /createSupabaseServiceRoleClient|\.rpc\(|\.from\(/u);
  assert.match(appNav, /href:\s*"\/selskapsgrense"/u);
  assert.match(admissionActions, /clearEligibilityContinuation/u);
  assert.doesNotMatch(`${page}\n${checker}\n${actions}\n${continuation}\n${admissionActions}`, /createSupabaseServiceRoleClient|\.rpc\(|\.from\(/u);
  assert.doesNotMatch(`${page}\n${checker}\n${actions}\n${admissionActions}`, /\bfetch\s*\(/u);
});
