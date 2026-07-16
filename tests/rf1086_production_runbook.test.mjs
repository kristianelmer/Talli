import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const runbook = readFileSync(new URL("../docs/filing/rf1086-production-pilot-runbook.md", import.meta.url), "utf8");

test("runbook covers the hand-held first production filing and immediate rollback", () => {
  for (const phrase of [
    "TALLI_RF1086_PRODUCTION_ENABLED=false", "deployed Git SHA", "named customer",
    "rf1086_no_activity_v1", "alternative/support route", "kill switch",
    "duplicate risk", "Do not repeat a POST", "final acceptance", "Evidence closeout",
    "supersedes_submission_id",
  ]) assert.match(runbook, new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  assert.match(runbook, /never the key itself/i);
  assert.match(runbook, /never XML, tokens, personal\s+identifiers, or organization numbers in logs/i);
});

test("release docs require callback verification before self-service activation", () => {
  assert.match(runbook, /callback_already_verified|callback_updated_and_verified/);
  assert.match(runbook, /TALLI_AUTHORITY_OPS_ENABLED=false/);
  assert.match(runbook, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
  assert.match(runbook, /rollback/i);
});

test("runbook defines the activation order, recovery matrix, and local-proof boundary", () => {
  for (const phrase of [
    "stale callback",
    "duplicate/pending request",
    "failed preflight",
    "processing archive",
    "unknown feedback",
    "failed artifact persistence",
    "monitoring and on-call questions",
    "stop conditions",
    "rollback steps",
    "local mocked proof",
  ]) {
    assert.match(runbook, new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  }
  assert.match(
    runbook,
    /did not make a live request, change Systemregister, enable a switch, grant an entitlement, or submit a filing/i,
  );
  assert.match(runbook, /does not prove a production callback/i);
});
