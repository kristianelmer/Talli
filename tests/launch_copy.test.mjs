import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  preProductionDirectFilingCopy,
  requiredNonAffiliationCopy,
  validateLaunchCopy,
} from "../app/lib/launch-copy.ts";

test("requires non-affiliation and pre-production gate language in public app copy", () => {
  // The canonical launch strings are wired into the central owner copy module
  // (see app/lib/copy.ts -> ownerCopy.filing) since the UX rebuild (#89/#93).
  const copy = readFileSync(new URL("../app/lib/copy.ts", import.meta.url), "utf8");

  assert.match(copy, /requiredNonAffiliationCopy/);
  assert.match(copy, /preProductionDirectFilingCopy/);

  // ...and that copy is surfaced on the owner dashboard (the public app home).
  const dashboard = readFileSync(
    new URL("../app/(owner)/dashboard/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(dashboard, /ownerCopy\.filing\.notAffiliated/);
  assert.match(dashboard, /ownerCopy\.filing\.preProductionGate/);

  const result = validateLaunchCopy(`${requiredNonAffiliationCopy}\n${preProductionDirectFilingCopy}`);

  assert.equal(result.hasRequiredNonAffiliation, true);
  assert.equal(result.hasPreProductionGate, true);
  assert.deepEqual(result.violations, []);
  assert.equal(result.approved, true);
});

test("rejects launch claims that outrun authority evidence", () => {
  const result = validateLaunchCopy(
    `${requiredNonAffiliationCopy}\n${preProductionDirectFilingCopy}\nGodkjent av Skatteetaten og ferdig innsendt.`,
  );

  assert.equal(result.approved, false);
  assert.ok(result.violations.length >= 2);
});
