import assert from "node:assert/strict";
import test from "node:test";

import {
  invitationStatus,
  reviewChecklistStatus,
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

test("workspace invitation presentation marks pending invitations expired", () => {
  const expiresAt = "2026-06-30T12:00:00.000Z";
  assert.equal(
    invitationStatus({ status: "pending", expires_at: expiresAt }, new Date("2026-06-20T12:00:00Z")),
    "pending",
  );
  assert.equal(
    invitationStatus({ status: "pending", expires_at: expiresAt }, new Date("2026-07-01T12:00:00Z")),
    "expired",
  );

  assert.equal(
    invitationStatus({ status: "pending", expiresAt }, new Date("2026-07-01T12:00:00Z")),
    "expired",
  );
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
