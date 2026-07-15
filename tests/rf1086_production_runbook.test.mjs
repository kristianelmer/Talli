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
