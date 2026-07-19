import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("overview leads with one next action and semantic obligation rows", async () => {
  const overview = await readFile("app/components/annual-workspace/AnnualOverview.tsx", "utf8");
  const row = await readFile("app/components/annual-workspace/ObligationRow.tsx", "utf8");
  assert.match(overview, /Neste steg/);
  assert.match(overview, /model\.obligations\.map/);
  assert.match(row, /data-status=/);
  assert.match(row, /aria-label=.*status/i);
  assert.doesNotMatch(overview, /metric|KPI|hero/i);
});

test("obligation workspace anchors issues and carries safe returns", async () => {
  const source = await readFile("app/components/annual-workspace/ObligationWorkspace.tsx", "utf8");
  const route = await readFile(
    "app/companies/[companyId]/annual-reporting/[incomeYear]/[obligation]/page.tsx",
    "utf8",
  );
  assert.match(source, /id={`issue-\$\{issue\.code\}`}/);
  assert.match(source, /name="returnTo"/);
  assert.match(source, /model\.role === "owner"/);
  assert.match(route, /validateAuthorityObligation/);
});

test("submission review renders gates and durable outcomes", async () => {
  const source = await readFile("app/components/annual-workspace/SubmissionReview.tsx", "utf8");
  assert.match(source, /Innsendingsrett/);
  assert.match(source, /Betaling/);
  assert.match(source, /Gjennomgang/);
  assert.match(source, /receipt_id/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /disabled={pending}/);
});
