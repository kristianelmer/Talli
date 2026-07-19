import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("root links authenticated owners into the annual workspace", async () => {
  const source = await readFile("app/page.tsx", "utf8");
  assert.match(source, /annualOverviewHref/);
  assert.match(source, /Åpne årsrapportering/);
});

test("annual routes retain launch-boundary language", async () => {
  const review = await readFile("app/components/annual-workspace/SubmissionReview.tsx", "utf8");
  assert.match(review, /preProductionDirectFilingCopy/);
  assert.match(review, /requiredNonAffiliationCopy/);
});
