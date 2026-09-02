import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import { listCompanyAccessContexts } from "../app/lib/company-access-context.ts";
import {
  inspectOwnerMfa,
  ownerMfaEnrollmentControl,
  ownerMfaCopy,
  startOwnerMfaEnrollment,
  verifyOwnerMfa,
} from "../app/lib/owner-mfa.ts";

function problem(status, code) {
  return {
    type: `https://talli.no/problems/${code.toLowerCase().replaceAll("_", "-")}`,
    title: code,
    status,
    detail: code,
    instance: "/api/v1/company-access/context",
    code,
    requestId: "request-owner-mfa",
  };
}

function mfaApi(overrides = {}) {
  return {
    async getAuthenticatorAssuranceLevel() {
      return {
        data: { currentLevel: "aal1", nextLevel: "aal1", currentAuthenticationMethods: [] },
        error: null,
      };
    },
    async listFactors() {
      return { data: { all: [], phone: [], totp: [], webauthn: [] }, error: null };
    },
    async enroll() {
      return {
        data: {
          id: "new-factor",
          type: "totp",
          totp: {
            qr_code: "data:image/svg+xml;utf-8,qr",
            secret: "OWNERSECRET",
            uri: "otpauth://totp/Talli",
          },
        },
        error: null,
      };
    },
    async challengeAndVerify() {
      return { data: { access_token: "aal2-token" }, error: null };
    },
    ...overrides,
  };
}

test("owner AAL2 is distinguished from other context failures without weakening the gate", async () => {
  const dependencies = (error) => ({
    async getAccessToken() { return "session-token"; },
    async loadContext() { throw error; },
  });

  assert.deepEqual(
    await listCompanyAccessContexts(
      {},
      dependencies(new TalliApiError(403, problem(403, "AAL2_REQUIRED"))),
    ),
    {
      companies: [],
      error: "Company access is temporarily unavailable.",
      requiresAal2: true,
    },
  );
  assert.deepEqual(
    await listCompanyAccessContexts(
      {},
      dependencies(new TalliApiError(503, problem(503, "COMPANY_ACCESS_UNAVAILABLE"))),
    ),
    {
      companies: [],
      error: "Company access is temporarily unavailable.",
    },
  );
});

test("owner MFA inspection chooses enrollment, challenge, or verified state and fails closed", async () => {
  assert.deepEqual(await inspectOwnerMfa(mfaApi()), { kind: "enrollment" });
  assert.deepEqual(
    await inspectOwnerMfa(mfaApi({
      async listFactors() {
        return {
          data: {
            all: [],
            phone: [],
            totp: [{ id: "verified-factor", status: "verified", factor_type: "totp" }],
            webauthn: [],
          },
          error: null,
        };
      },
    })),
    { kind: "challenge", factorId: "verified-factor" },
  );
  assert.deepEqual(
    await inspectOwnerMfa(mfaApi({
      async getAuthenticatorAssuranceLevel() {
        return {
          data: { currentLevel: "aal2", nextLevel: "aal2", currentAuthenticationMethods: [] },
          error: null,
        };
      },
    })),
    { kind: "verified" },
  );
  assert.deepEqual(
    await inspectOwnerMfa(mfaApi({
      async getAuthenticatorAssuranceLevel() {
        throw new Error("network detail must not leak");
      },
    })),
    { kind: "error", message: ownerMfaCopy.statusError },
  );
});

test("enrollment and verification expose no provider errors and only resume after confirmed AAL2", async () => {
  assert.deepEqual(
    ownerMfaEnrollmentControl({ busy: false, errorKind: "enrollment" }),
    { disabled: false, label: "Prøv igjen" },
  );
  assert.deepEqual(
    ownerMfaEnrollmentControl({ busy: true, errorKind: "enrollment" }),
    { disabled: true, label: "Starter …" },
  );
  assert.deepEqual(
    ownerMfaEnrollmentControl({ busy: false, errorKind: "status" }),
    { disabled: true, label: "Sett opp autentiseringsapp" },
  );
  assert.deepEqual(await startOwnerMfaEnrollment(mfaApi()), {
    ok: true,
    factorId: "new-factor",
    qrCode: "data:image/svg+xml;utf-8,qr",
    secret: "OWNERSECRET",
  });
  assert.deepEqual(
    await startOwnerMfaEnrollment(mfaApi({
      async enroll() { throw new Error("provider secret"); },
    })),
    { ok: false, message: ownerMfaCopy.enrollmentError },
  );

  let assuranceChecks = 0;
  assert.deepEqual(
    await verifyOwnerMfa(mfaApi({
      async getAuthenticatorAssuranceLevel() {
        assuranceChecks += 1;
        return {
          data: { currentLevel: "aal2", nextLevel: "aal2", currentAuthenticationMethods: [] },
          error: null,
        };
      },
    }), "verified-factor", "123456"),
    { ok: true },
  );
  assert.equal(assuranceChecks, 1);

  assert.deepEqual(
    await verifyOwnerMfa(mfaApi(), "verified-factor", "123456"),
    { ok: false, message: ownerMfaCopy.verificationError },
  );
  assert.deepEqual(
    await verifyOwnerMfa(mfaApi(), "verified-factor", "12345"),
    { ok: false, message: ownerMfaCopy.codeError },
  );
});

test("owner transition is reachable after company-year admission and exposes an accessible, Norwegian MFA gate", async () => {
  const [admissionActions, ownerLayout, page, component] = await Promise.all([
    readFile(new URL("../app/(owner)/onboarding/actions.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/mfa/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/mfa/OwnerMfa.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(admissionActions, /export async function admitCompanyYear/u);
  assert.match(admissionActions, /redirect\("\/mfa\?next=%2Fonboarding"\)/u);
  assert.match(ownerLayout, /requiresAal2/u);
  assert.match(ownerLayout, /href="\/mfa\?next=%2Fonboarding"/u);
  assert.match(page, /sanitizeInternalRedirect\(params\?\.next, "\/onboarding"\)/u);
  assert.match(component, /role="alert"/u);
  assert.match(component, /tabIndex=\{-1\}/u);
  assert.match(component, /errorRef\.current\?\.focus\(\)/u);
  assert.match(component, /htmlFor="ownerMfaCode"/u);
  assert.match(component, /aria-describedby/u);
  assert.match(component, /autoComplete="one-time-code"/u);
  assert.match(component, /window\.location\.assign\(returnTo\)/u);
  assert.equal(ownerMfaCopy.heading, "Beskytt kontoen før du fortsetter");
  assert.match(ownerMfaCopy.intro, /Selskapet er opprettet/u);
  assert.match(ownerMfaCopy.statusError, /fortsatt stengt/u);
});
