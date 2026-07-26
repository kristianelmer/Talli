import assert from "node:assert/strict";
import test from "node:test";

import {
  buildInvitationEmail,
  invitationDeliveryEvent,
  invitationExpiry,
  invitationStatus,
  invitationTokenHash,
  normalizeInvitationEmail,
  reviewChecklistStatus,
  validateInvitationRole,
} from "../apps/web/app/lib/invitations.ts";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "../apps/web/app/lib/review.ts";

test("advisory review comments can be acknowledged", () => {
  assert.doesNotThrow(() => assertAdvisoryCanBeAcknowledged({ severity: "advisory" }));
});

test("hard review comments cannot be acknowledged as advisory", () => {
  assert.throws(() => assertAdvisoryCanBeAcknowledged({ severity: "hard_block" }), /Hard review-blokk/);
});

test("hard review comments block simulated submission", () => {
  assert.throws(
    () => assertNoHardReviewBlocks([{ severity: "advisory" }, { severity: "hard_block" }]),
    /simulert innsending/,
  );
});

test("workspace invitations normalize email, enforce role, expire, and queue email payload", async () => {
  assert.equal(normalizeInvitationEmail(" Reviewer@Example.NO "), "reviewer@example.no");
  assert.equal(validateInvitationRole("reviewer"), "reviewer");
  assert.throws(() => validateInvitationRole("owner"), /Ugyldig/);

  const expiresAt = invitationExpiry(new Date("2026-06-16T12:00:00Z"));
  assert.equal(expiresAt, "2026-06-30T12:00:00.000Z");
  assert.equal(
    invitationStatus({ status: "pending", expires_at: expiresAt }, new Date("2026-06-20T12:00:00Z")),
    "pending",
  );
  assert.equal(
    invitationStatus({ status: "pending", expires_at: expiresAt }, new Date("2026-07-01T12:00:00Z")),
    "expired",
  );

  const tokenHash = await invitationTokenHash("secret-token");
  assert.match(tokenHash, /^[a-f0-9]{64}$/);

  const event = invitationDeliveryEvent({
    recipientEmail: "Reviewer@Example.NO",
    queuedAt: "2026-06-16T12:00:00.000Z",
  });
  assert.deepEqual(event, {
    channel: "email",
    status: "queued",
    template: "workspace_invitation",
    recipientEmail: "reviewer@example.no",
    queuedAt: "2026-06-16T12:00:00.000Z",
  });

  const email = buildInvitationEmail({
    companyName: "Demo Holding AS",
    recipientEmail: "reviewer@example.no",
    role: "read_only",
    acceptUrl: "/invite/accept?token=secret-token",
  });
  assert.equal(email.to, "reviewer@example.no");
  assert.match(email.subject, /Demo Holding AS/);
  assert.match(email.body, /read-only/);
});

test("review checklist keeps advisory comments separate from hard system blocks", () => {
  assert.deepEqual(
    reviewChecklistStatus([
      { severity: "advisory", acknowledged_by: "owner" },
      { severity: "advisory", acknowledged_by: null },
    ]),
    {
      advisoryCount: 2,
      hardBlockCount: 0,
      acknowledgedAdvisoryCount: 1,
      readinessImpact: "advisory_only",
    },
  );
  assert.equal(reviewChecklistStatus([{ severity: "hard_block" }]).readinessImpact, "hard_block");
});
