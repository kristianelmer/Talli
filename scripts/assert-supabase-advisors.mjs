import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const result = spawnSync(
  "npm",
  ["exec", "--", "supabase", "db", "advisors", "--local", "--output", "json"],
  { encoding: "utf8" },
);

assert.equal(result.status, 0, result.stderr || result.stdout);

const findings = JSON.parse(result.stdout);
assert.ok(Array.isArray(findings), "Supabase advisors must return a JSON array.");

const blocking = findings.filter(
  (finding) =>
    finding?.level === "ERROR"
    || (finding?.facing === "EXTERNAL" && finding?.categories?.includes("SECURITY")),
);

assert.deepEqual(blocking, [], JSON.stringify(blocking, null, 2));

const performanceWarnings = findings.filter((finding) => finding?.categories?.includes("PERFORMANCE"));
console.log(
  `Supabase advisors: 0 blocking security/error findings; ${performanceWarnings.length} performance warnings.`,
);
