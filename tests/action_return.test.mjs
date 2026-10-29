import assert from "node:assert/strict";
import test from "node:test";

import { actionReturnPath, actionReturnPathWithMessage } from "../apps/web/app/lib/action-return.ts";

test("accepts company annual-reporting paths and rejects unrelated destinations", () => {
  assert.equal(
    actionReturnPath("/companies/company-1/annual-reporting/2025/aarsregnskap#issue-notes_missing"),
    "/companies/company-1/annual-reporting/2025/aarsregnskap#issue-notes_missing",
  );
  assert.equal(actionReturnPath("https://evil.example/companies/company-1/annual-reporting/2025"), "/");
  assert.equal(actionReturnPath("//evil.example/companies/company-1/annual-reporting/2025"), "/");
  assert.equal(actionReturnPath("/admin"), "/");
});

test("inserts messages before a fragment and preserves existing query values", () => {
  assert.equal(
    actionReturnPathWithMessage(
      "/companies/company-1/annual-reporting/2025/aarsregnskap?panel=notes#issue-notes_missing",
      "error",
      "Noter må fullføres",
    ),
    "/companies/company-1/annual-reporting/2025/aarsregnskap?panel=notes&error=Noter+m%C3%A5+fullf%C3%B8res#issue-notes_missing",
  );
});


test("onboarding keeps only an explicit company-year and optional bank step", () => {
  const companyId = "10000000-0000-4000-8000-000000000001";
  for (const year of [2025, 2026]) {
    for (const step of ["", "&step=bank"]) {
      const path = `/onboarding?companyId=${companyId}&accountingYear=${year}${step}`;
      assert.equal(actionReturnPath(path), path);
    }
  }
  for (const path of [
    `/onboarding?companyId=${companyId}&accountingYear=2024`,
    `/onboarding?companyId=${companyId}&accountingYear=2025&accountingYear=2026`,
    `/onboarding?companyId=${companyId}&accountingYear=2025&next=https://evil.example`,
    `/onboarding?companyId=${companyId}&accountingYear=2025&step=admin`,
    `/onboarding?companyId=${companyId}&accountingYear=2025#untrusted`,
    `/onboarding?companyId=${companyId}`, "/onboarding?accountingYear=2025",
    "/onboarding?companyId=bad&accountingYear=2025",
    `//evil.example/onboarding?companyId=${companyId}&accountingYear=2025`,
  ]) assert.equal(actionReturnPath(path), "/", path);
});
