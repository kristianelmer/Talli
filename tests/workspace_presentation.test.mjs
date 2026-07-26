import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceUrl = new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url);
const dashboardUrl = new URL("../apps/web/app/(owner)/dashboard/page.tsx", import.meta.url);

test("customer forms do not seed synthetic accounting facts", async () => {
  const source = await readFile(workspaceUrl, "utf8");

  assert.doesNotMatch(source, /defaultValue="2025"/);
  assert.doesNotMatch(
    source,
    /defaultValue=(?:"(?:30000|20000|50000|1000|Ola Nordmann|Portfolio AS|portfolio-as|Manuell justering|Manuell kostnad)"|\{"date,text,amount,balance)/,
  );
  assert.match(source, /name="csvText"[\s\S]+placeholder=/);
  assert.match(source, /name="incomeYear"[\s\S]+defaultValue=\{primaryIncomeYear\}/);
});

test("dashboard enters the dedicated annual workspace", async () => {
  const source = await readFile(dashboardUrl, "utf8");

  assert.match(source, /redirect\(annualOverviewHref\(/);
  assert.match(source, /redirect\("\/onboarding"\)/);
  assert.doesNotMatch(source, /href: "\/(?:workspace|filing|year-end)"/);
});
