import assert from "node:assert/strict";
import test from "node:test";

import {
  assertStepUpAllowed,
  requireStepUpForAction,
  stepUpContextFromClaims,
} from "../app/lib/security.ts";

const now = new Date("2026-06-16T10:00:00.000Z");

function claims(overrides = {}) {
  return {
    sub: "owner",
    aal: "aal2",
    amr: [
      { method: "password", timestamp: Date.parse("2026-06-16T09:00:00.000Z") / 1000 },
      { method: "totp", timestamp: Date.parse("2026-06-16T09:55:00.000Z") / 1000 },
    ],
    ...overrides,
  };
}

test("step-up accepts fresh signed AAL2 claims for the matching actor", () => {
  const context = stepUpContextFromClaims("owner", claims());

  assert.deepEqual(context, {
    actorId: "owner",
    mfaVerifiedAt: "2026-06-16T09:55:00.000Z",
  });
  assert.doesNotThrow(() => assertStepUpAllowed("invite_reviewer", context, now));
});

test("step-up accepts supported signed MFA method references and uses the newest one", () => {
  for (const method of ["totp", "mfa/totp", "mfa/phone", "mfa/webauthn"]) {
    const context = stepUpContextFromClaims(
      "owner",
      claims({
        amr: [
          { method, timestamp: Date.parse("2026-06-16T09:54:00.000Z") / 1000 },
          { method: "mfa/totp", timestamp: Date.parse("2026-06-16T09:57:00.000Z") / 1000 },
        ],
      }),
    );

    assert.equal(context.mfaVerifiedAt, "2026-06-16T09:57:00.000Z");
  }
});

test("step-up fails closed for AAL1, cross-user, missing AMR, and string-only AMR claims", () => {
  for (const untrustedClaims of [
    claims({ aal: "aal1" }),
    claims({ sub: "other" }),
    claims({ amr: undefined }),
    claims({ amr: ["password", "totp"] }),
  ]) {
    const context = stepUpContextFromClaims("owner", untrustedClaims);
    assert.equal(context.mfaVerifiedAt, null);
    assert.throws(() => assertStepUpAllowed("billing_admin", context, now), /fersk MFA\/step-up/);
  }
});

test("step-up rejects invalid, stale, and future MFA timestamps", () => {
  const invalid = stepUpContextFromClaims(
    "owner",
    claims({ amr: [{ method: "totp", timestamp: Number.NaN }] }),
  );
  assert.equal(invalid.mfaVerifiedAt, null);

  const stale = stepUpContextFromClaims(
    "owner",
    claims({ amr: [{ method: "totp", timestamp: Date.parse("2026-06-16T09:44:59.000Z") / 1000 }] }),
  );
  assert.throws(() => assertStepUpAllowed("confirm_authority", stale, now), /nyere enn 15 minutter/);

  const future = stepUpContextFromClaims(
    "owner",
    claims({ amr: [{ method: "totp", timestamp: Date.parse("2026-06-16T10:00:01.000Z") / 1000 }] }),
  );
  assert.throws(
    () => assertStepUpAllowed("confirm_authority", future, now),
    (error) => error.code === "expired_mfa_step_up" && /utløpt/.test(error.userMessage),
  );
});

test("all protected corporate actions require fresh AAL2 user presence", () => {
  for (const action of [
    "authority_operations",
    "production_filing",
    "approve_corporate_facts",
    "attest_signed_corporate_document",
    "finalize_corporate_decision",
    "record_owner_dividend_payment",
  ]) {
    assert.throws(
      () => assertStepUpAllowed(action, { actorId: "owner", mfaVerifiedAt: null }, now),
      /fersk MFA\/step-up/,
    );
    assert.doesNotThrow(() =>
      assertStepUpAllowed(
        action,
        { actorId: "owner", mfaVerifiedAt: "2026-06-16T09:59:00.000Z" },
        now,
      ),
    );
  }
});

test("server gate verifies claims, never reads legacy step-up rows, and audits allow/block", async () => {
  const auditEvents = [];
  let currentClaims = claims({
    amr: [{ method: "totp", timestamp: Date.parse("2026-06-16T09:59:00.000Z") / 1000 }],
  });
  const queriedTables = [];
  const supabase = fakeSupabase(() => currentClaims, auditEvents, queriedTables);

  await requireStepUpForAction({
    supabase,
    userId: "owner",
    companyId: "company-id",
    action: "billing_admin",
    now,
  });

  assert.deepEqual(queriedTables, ["audit_events"]);
  assert.equal(auditEvents.at(-1).action, "sensitive_action_allowed");
  assert.match(auditEvents.at(-1).message, /Billing-admin tillatt/);

  currentClaims = claims({
    amr: [{ method: "totp", timestamp: Date.parse("2026-06-16T09:00:00.000Z") / 1000 }],
  });
  await assert.rejects(
    () =>
      requireStepUpForAction({
        supabase,
        userId: "owner",
        companyId: "company-id",
        action: "billing_admin",
        now,
      }),
    /nyere enn 15 minutter/,
  );

  assert.deepEqual(queriedTables, ["audit_events", "audit_events"]);
  assert.equal(auditEvents.at(-1).action, "sensitive_action_blocked");
  assert.match(auditEvents.at(-1).message, /expired_mfa_step_up/);
});

test("claims lookup failures are blocked and audited without leaking provider details", async () => {
  const auditEvents = [];
  const supabase = fakeSupabase(() => null, auditEvents, [], new Error("raw provider detail"));

  await assert.rejects(
    () =>
      requireStepUpForAction({
        supabase,
        userId: "owner",
        companyId: "company-id",
        action: "billing_admin",
        now,
      }),
    (error) => error.code === "trusted_claims_lookup_failed" && !error.userMessage.includes("raw provider detail"),
  );

  assert.equal(auditEvents.at(-1).action, "sensitive_action_blocked");
  assert.match(auditEvents.at(-1).message, /trusted_claims_lookup_failed/);
  assert.doesNotMatch(auditEvents.at(-1).message, /provider detail/);
});

function fakeSupabase(readClaims, auditEvents, queriedTables, claimsError = null) {
  return {
    auth: {
      async getClaims() {
        if (claimsError) {
          return { data: null, error: claimsError };
        }
        return { data: { claims: readClaims() }, error: null };
      },
    },
    from(table) {
      queriedTables.push(table);
      if (table !== "audit_events") {
        throw new Error(`Unexpected table ${table}`);
      }
      return {
        async insert(row) {
          auditEvents.push(row);
          return { data: row, error: null };
        },
      };
    },
  };
}
