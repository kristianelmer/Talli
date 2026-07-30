import assert from "node:assert/strict";
import test from "node:test";

import { scopeAnnualWorkspaceRecords } from "../apps/web/app/lib/annual-workspace-scope.ts";

test("scopes every annual collection to the selected company and year", () => {
  const scoped = scopeAnnualWorkspaceRecords(
    { companyId: "company-1", incomeYear: 2025 },
    {
      documents: [
        { id: "keep", company_id: "company-1", income_year: 2025 },
        { id: "drop-company", company_id: "company-2", income_year: 2025 },
        { id: "drop-year", company_id: "company-1", income_year: 2024 },
      ],
      comments: [
        { id: "comment", company_id: "company-1" },
        { id: "other", company_id: "company-2" },
      ],
      snapshots: [
        { id: "snapshot", company_id: "company-1", income_year: 2025 },
        { id: "old", company_id: "company-1", income_year: 2024 },
      ],
      submissions: [{ id: "submission", company_id: "company-1", income_year: 2025 }],
      authorityPermissions: [
        { id: "permission", company_id: "company-1" },
        { id: "foreign", company_id: "company-2" },
      ],
    },
  );

  assert.deepEqual(scoped.documents.map((item) => item.id), ["keep"]);
  assert.deepEqual(scoped.comments.map((item) => item.id), ["comment"]);
  assert.deepEqual(scoped.snapshots.map((item) => item.id), ["snapshot"]);
  assert.deepEqual(scoped.submissions.map((item) => item.id), ["submission"]);
  assert.deepEqual(scoped.authorityPermissions.map((item) => item.id), ["permission"]);
});
