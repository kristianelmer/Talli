import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { selectLatestRf1086ProductionSubmission } from "../app/lib/rf1086-production-presentation.ts";

const context = {
  companyId: "company-1",
  userId: "owner-1",
  incomeYear: 2025,
  obligation: "aksjonaerregisteroppgaven",
  caseProfile: "rf1086_no_activity_v1",
  environment: "production",
};

function submission(id, updatedAt, overrides = {}) {
  return {
    id,
    company_id: context.companyId,
    user_id: context.userId,
    income_year: context.incomeYear,
    obligation: context.obligation,
    case_profile: context.caseProfile,
    environment: context.environment,
    created_at: updatedAt,
    updated_at: updatedAt,
    ...overrides,
  };
}

test("selects the latest exact production submission independently of later gate state", () => {
  const older = submission("older", "2026-01-01T00:00:00.000Z");
  const latestAfterRevocation = submission("latest", "2026-02-01T00:00:00.000Z", {
    approval_invalidated_at: "2026-02-02T00:00:00.000Z",
    entitlement_status: "revoked",
    entitlement_expires_at: "2026-02-02T00:00:00.000Z",
  });
  const wrongCompany = submission("wrong-company", "2026-03-01T00:00:00.000Z", { company_id: "company-2" });
  const wrongUser = submission("wrong-user", "2026-03-02T00:00:00.000Z", { user_id: "owner-2" });
  const wrongYear = submission("wrong-year", "2026-03-03T00:00:00.000Z", { income_year: 2024 });
  const wrongObligation = submission("wrong-obligation", "2026-03-04T00:00:00.000Z", { obligation: "aarsregnskap" });
  const wrongCase = submission("wrong-case", "2026-03-05T00:00:00.000Z", { case_profile: "another-case" });
  const wrongEnvironment = submission("wrong-environment", "2026-03-06T00:00:00.000Z", { environment: "test" });

  assert.equal(
    selectLatestRf1086ProductionSubmission(
      [
        older,
        latestAfterRevocation,
        wrongCompany,
        wrongUser,
        wrongYear,
        wrongObligation,
        wrongCase,
        wrongEnvironment,
      ],
      context,
    ),
    latestAfterRevocation,
  );
});

test("owner page renders durable submissions before checking current approval or entitlement gates", () => {
  const ownerPage = readFileSync(
    new URL("../app/(owner)/filing/[obligation]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(ownerPage, /selectLatestRf1086ProductionSubmission/u);
  assert.match(ownerPage, /productionSubmission \|\| \(pilotEntitlement && previewReady\)/u);
  const section = ownerPage.slice(
    ownerPage.indexOf("Reell RF-1086-produksjonspilot"),
    ownerPage.indexOf("{/* Step 1"),
  );
  assert.ok(section.indexOf("productionSubmission ? (") < section.indexOf("!productionApproval ? ("));
  assert.match(section, /Rf1086ReconciliationControl/u);
  assert.match(section, /productionFeedbackArtifacts/u);
});
