import assert from "node:assert/strict";
import test from "node:test";

import {
  CompanyYearEligibilityGateError,
  companyYearEligibilityGateMessage,
  requireCompanyYearEligibilityGate,
} from "../app/lib/company-year-eligibility-gate.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const admissionId = "20000000-0000-4000-8000-000000000002";

function context(overrides = {}) {
  const selectedCompany = {
    id: companyId,
    companyYearAdmissionId: admissionId,
    admittedAccountingYear: 2026,
    ...overrides,
  };
  return { selectedCompany, companies: [selectedCompany] };
}

function state(overrides = {}) {
  return {
    companyId,
    companyYearAdmissionId: admissionId,
    accountingYear: 2026,
    decision: "supported",
    consequentialOperationsAllowed: true,
    nextStep: "Fortsett selskapsåret i Talli.",
    ...overrides,
  };
}

function dependencies({ contextValue = context(), stateValue = state() } = {}) {
  const calls = [];
  return {
    calls,
    value: {
      async getAccessToken() { return "session-token"; },
      async loadContext(_token, _requestId, options) {
        calls.push(["context", options]);
        return contextValue;
      },
      async recheck(_token, candidateAdmissionId, command) {
        calls.push(["recheck", candidateAdmissionId, command]);
        return stateValue;
      },
      operationId() { return "40000000-0000-4000-8000-000000000004"; },
    },
  };
}

test("the recheck helper carries future serialized triggers through the API", async () => {
  const deps = dependencies();

  const result = await requireCompanyYearEligibilityGate(
    companyId,
    "before_filing",
    deps.value,
  );

  assert.equal(result.decision, "supported");
  assert.deepEqual(deps.calls, [
    ["context", { companyId }],
    ["recheck", admissionId, {
      operationId: "40000000-0000-4000-8000-000000000004",
      trigger: "before_filing",
    }],
  ]);
});

test("a blocked recheck stops the consequential operation and preserves its next step", async () => {
  const blocked = state({
    decision: "blocked",
    consequentialOperationsAllowed: false,
    nextStep: "Stopp innsendingen og eksporter arkivet.",
  });
  const deps = dependencies({ stateValue: blocked });

  await assert.rejects(
    requireCompanyYearEligibilityGate(companyId, "before_payment", deps.value),
    (error) => (
      error instanceof CompanyYearEligibilityGateError
      && error.state === blocked
      && error.message === blocked.nextStep
    ),
  );
});

test("missing admission and provider failure both fail closed", async () => {
  const missing = dependencies({
    contextValue: context({ companyYearAdmissionId: null }),
  });
  await assert.rejects(
    requireCompanyYearEligibilityGate(companyId, "before_payment", missing.value),
    CompanyYearEligibilityGateError,
  );
  assert.equal(missing.calls.some(([kind]) => kind === "recheck"), false);
  assert.match(
    companyYearEligibilityGateMessage(new Error("provider secret")),
    /Ingen opplysninger eller status ble endret/u,
  );
});
