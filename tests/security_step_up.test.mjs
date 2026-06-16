import assert from "node:assert/strict";
import test from "node:test";

import {
  assertStepUpAllowed,
  requireStepUpForAction,
  stepUpContextFromEvent,
} from "../app/lib/security.ts";

const now = new Date("2026-06-16T10:00:00.000Z");

test("step-up blocks missing and expired MFA for sensitive actions", () => {
  assert.throws(
    () => assertStepUpAllowed("billing_admin", { actorId: "owner", mfaVerifiedAt: null }, now),
    /fersk MFA\/step-up/,
  );
  assert.throws(
    () =>
      assertStepUpAllowed(
        "confirm_authority",
        { actorId: "owner", mfaVerifiedAt: "2026-06-16T09:40:00.000Z" },
        now,
      ),
    /nyere enn 15 minutter/,
  );
});

test("step-up allows fresh matching actor and ignores cross-user events", () => {
  const allowed = stepUpContextFromEvent("owner", {
    actor_id: "owner",
    mfa_verified_at: "2026-06-16T09:55:00.000Z",
    security_review_approved: false,
    production_credentials_enabled: false,
  });
  assert.doesNotThrow(() => assertStepUpAllowed("invite_reviewer", allowed, now));

  const crossed = stepUpContextFromEvent("owner", {
    actor_id: "other",
    mfa_verified_at: "2026-06-16T09:59:00.000Z",
    security_review_approved: true,
    production_credentials_enabled: true,
  });
  assert.equal(crossed.mfaVerifiedAt, null);
  assert.throws(() => assertStepUpAllowed("billing_admin", crossed, now), /fersk MFA\/step-up/);
});

test("production filing requires MFA, security review, and production credential gate", () => {
  assert.throws(
    () =>
      assertStepUpAllowed(
        "production_filing",
        {
          actorId: "owner",
          mfaVerifiedAt: "2026-06-16T09:59:00.000Z",
          securityReviewApproved: true,
          productionCredentialsEnabled: false,
        },
        now,
      ),
    /produksjonscredential-gate/,
  );
  assert.doesNotThrow(() =>
    assertStepUpAllowed(
      "production_filing",
      {
        actorId: "owner",
        mfaVerifiedAt: "2026-06-16T09:59:00.000Z",
        securityReviewApproved: true,
        productionCredentialsEnabled: true,
      },
      now,
    ),
  );
});

test("server gate records allowed and blocked sensitive action audit events", async () => {
  const auditEvents = [];
  const stepUpRows = [
    {
      actor_id: "owner",
      mfa_verified_at: "2026-06-16T09:59:00.000Z",
      security_review_approved: false,
      production_credentials_enabled: false,
    },
  ];
  const supabase = fakeSupabase(stepUpRows, auditEvents);

  await requireStepUpForAction({
    supabase,
    userId: "owner",
    companyId: "company-id",
    action: "billing_admin",
    now,
  });

  assert.equal(auditEvents.at(-1).action, "sensitive_action_allowed");
  assert.match(auditEvents.at(-1).message, /Billing-admin tillatt/);

  stepUpRows[0].mfa_verified_at = "2026-06-16T09:00:00.000Z";
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

  assert.equal(auditEvents.at(-1).action, "sensitive_action_blocked");
  assert.match(auditEvents.at(-1).message, /expired_mfa_step_up/);
});

function fakeSupabase(stepUpRows, auditEvents) {
  return {
    from(table) {
      if (table === "audit_events") {
        return {
          async insert(row) {
            auditEvents.push(row);
            return { data: row, error: null };
          },
        };
      }
      if (table === "step_up_events") {
        const query = {
          actorId: null,
          eq(column, value) {
            if (column === "actor_id") {
              this.actorId = value;
            }
            return this;
          },
          order() {
            return this;
          },
          limit() {
            return this;
          },
          async maybeSingle() {
            return { data: stepUpRows.find((row) => row.actor_id === this.actorId) ?? null, error: null };
          },
          select() {
            return this;
          },
        };
        return query;
      }
      throw new Error(`Unexpected table ${table}`);
    },
  };
}
