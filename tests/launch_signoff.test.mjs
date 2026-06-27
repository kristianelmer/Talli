import assert from "node:assert/strict";
import test from "node:test";

import {
  buildLaunchSignoffRecord,
  buildLaunchSignoffGate,
  launchSignoffKeys,
  launchSignoffLabel,
} from "../app/lib/launch-signoff.ts";

function approvedSignoff(key, reviewedAt = "2026-06-20T10:00:00Z") {
  return {
    key,
    status: "approved",
    reviewer: `${key}-reviewer`,
    reviewedAt,
    evidenceLink: `https://evidence.example/${key}`,
    decision: `${key} approved for launch rehearsal.`,
  };
}

test("blocks launch when required signoffs are missing", () => {
  const gate = buildLaunchSignoffGate({
    signoffs: [approvedSignoff("launch_legal_name_public_copy")],
    now: new Date("2026-06-20T12:00:00Z"),
  });

  assert.equal(gate.ready, false);
  assert.equal(gate.status, "launch_signoff_blocked");
  assert.ok(gate.missing.includes("legal_policy_pack"));
  assert.ok(gate.missing.includes("security_restore"));
  assert.ok(gate.messages.some((message) => /Legal\/privacy/.test(message)));
});

test("blocks launch when signoff is rejected or incomplete", () => {
  const signoffs = launchSignoffKeys.map((key) => approvedSignoff(key));
  signoffs[1] = { ...signoffs[1], status: "rejected", decision: "Legal review rejected pending counsel." };
  signoffs[2] = { ...signoffs[2], evidenceLink: "" };

  const gate = buildLaunchSignoffGate({
    signoffs,
    now: new Date("2026-06-20T12:00:00Z"),
  });

  assert.equal(gate.ready, false);
  assert.deepEqual(gate.rejected, ["legal_policy_pack"]);
  assert.ok(gate.missing.includes("security_restore"));
});

test("requires fresh restore signoff", () => {
  const gate = buildLaunchSignoffGate({
    signoffs: launchSignoffKeys.map((key) =>
      approvedSignoff(key, key === "security_restore" ? "2026-05-01T10:00:00Z" : "2026-06-20T10:00:00Z"),
    ),
    now: new Date("2026-06-20T12:00:00Z"),
  });

  assert.equal(gate.ready, false);
  assert.deepEqual(gate.stale, ["security_restore"]);
  assert.ok(gate.messages.some((message) => /gammel/.test(message)));
});

test("passes only when every launch signoff is approved with evidence", () => {
  const gate = buildLaunchSignoffGate({
    signoffs: launchSignoffKeys.map((key) => approvedSignoff(key)),
    now: new Date("2026-06-20T12:00:00Z"),
  });

  assert.equal(launchSignoffLabel("rf1086_authority"), "RF-1086 authority filing");
  assert.equal(gate.ready, true);
  assert.equal(gate.status, "launch_signoff_ready");
  assert.deepEqual(gate.missing, []);
  assert.deepEqual(gate.rejected, []);
  assert.deepEqual(gate.stale, []);
});

test("builds persisted launch signoff record and validates approved evidence", () => {
  const record = buildLaunchSignoffRecord(
    {
      key: "legal_policy_pack",
      status: "approved",
      reviewer: "Legal Reviewer",
      reviewedAt: "2026-06-20T10:00:00Z",
      evidenceLink: "https://evidence.example/legal",
      decision: "Approved for private launch.",
      recordedBy: "operator-1",
    },
    new Date("2026-06-20T11:00:00Z"),
  );

  assert.equal(record.key, "legal_policy_pack");
  assert.equal(record.reviewed_at, "2026-06-20T10:00:00Z");
  assert.equal(record.updated_at, "2026-06-20T11:00:00.000Z");

  assert.throws(
    () =>
      buildLaunchSignoffRecord({
        key: "legal_policy_pack",
        status: "approved",
        reviewer: "",
        reviewedAt: "2026-06-20T10:00:00Z",
        evidenceLink: "https://evidence.example/legal",
        decision: "Approved.",
        recordedBy: "operator-1",
      }),
    /reviewer/,
  );
  assert.throws(
    () =>
      buildLaunchSignoffRecord({
        key: "bad_key",
        status: "approved",
        reviewer: "Legal",
        reviewedAt: "2026-06-20T10:00:00Z",
        evidenceLink: "https://evidence.example/legal",
        decision: "Approved.",
        recordedBy: "operator-1",
      }),
    /Ugyldig/,
  );
});

test("documented launch_legal_name_public_copy entry is a valid approved record", () => {
  // Mirrors the "Launch Signoff Record To Apply" entry in
  // docs/launch/talli-clearance-evidence-register.md so the documented operator-form
  // values cannot drift from the validation rules in buildLaunchSignoffRecord.
  const record = buildLaunchSignoffRecord(
    {
      key: "launch_legal_name_public_copy",
      status: "approved",
      reviewer: "Kristian Elmer (founder)",
      reviewedAt: "2026-06-24T00:00:00Z",
      evidenceLink: "docs/launch/talli-clearance-evidence-register.md",
      decision:
        "Trademark (Patentstyret), company-name (Brønnøysund), talli.no ownership, " +
        "fallback (not required), public copy, and authority wording all approved " +
        "2026-06-24; pre-production public-copy baseline enforced by test:launch-copy.",
      recordedBy: "admin-operator",
    },
    new Date("2026-06-27T00:00:00Z"),
  );

  assert.equal(record.key, "launch_legal_name_public_copy");
  assert.equal(record.status, "approved");
  assert.equal(record.reviewer, "Kristian Elmer (founder)");
  assert.equal(record.reviewed_at, "2026-06-24T00:00:00Z");
});
