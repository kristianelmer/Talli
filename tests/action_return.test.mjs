import assert from "node:assert/strict";
import test from "node:test";

import { actionReturnPath, actionReturnPathWithMessage } from "../apps/web/app/lib/action-return.ts";

test("accepts only company annual-reporting paths", () => {
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
