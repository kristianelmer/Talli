import assert from "node:assert/strict";
import test from "node:test";

import { currentCustomerAgreements, customerAgreementAuthorityStatementVersion } from "../apps/web/app/lib/customer-agreements.ts";
import {
  companiesRequiringCurrentCustomerAgreement,
  reacceptCustomerAgreement,
} from "../apps/web/app/lib/customer-agreement-reacceptance.ts";

const company = { id: "10000000-0000-4000-8000-000000000001", name: "Existing AS" };
const currentEvidence = {
  company_id: company.id,
  business_terms_version: currentCustomerAgreements.businessTerms.version,
  business_terms_sha256: currentCustomerAgreements.businessTerms.contentSha256,
  dpa_version: currentCustomerAgreements.dpa.version,
  dpa_sha256: currentCustomerAgreements.dpa.contentSha256,
};
const validInput = {
  companyId: company.id,
  agreementAccepted: "accepted",
  businessTermsVersion: currentCustomerAgreements.businessTerms.version,
  businessTermsSha256: currentCustomerAgreements.businessTerms.contentSha256,
  dpaVersion: currentCustomerAgreements.dpa.version,
  dpaSha256: currentCustomerAgreements.dpa.contentSha256,
};

test("agreement gate allows no-company owners and blocks missing or stale evidence", () => {
  assert.deepEqual(companiesRequiringCurrentCustomerAgreement([], []), []);
  assert.deepEqual(companiesRequiringCurrentCustomerAgreement([company], []), [company]);
  assert.deepEqual(companiesRequiringCurrentCustomerAgreement([company], [{ ...currentEvidence, dpa_sha256: "0".repeat(64) }]), [company]);
  assert.deepEqual(companiesRequiringCurrentCustomerAgreement([company], [currentEvidence]), []);
});

function dependencies(overrides = {}) {
  const calls = [];
  return {
    calls,
    deps: {
      getAuthenticatedUser: async () => ({ id: "20000000-0000-4000-8000-000000000002" }),
      appendAcceptance: async (payload) => calls.push(payload),
      ...overrides,
    },
  };
}

for (const [name, input, code] of [
  ["missing assent", { ...validInput, agreementAccepted: "" }, "invalid_agreement"],
  ["stale version", { ...validInput, businessTermsVersion: "stale" }, "invalid_agreement"],
  ["stale digest", { ...validInput, dpaSha256: "0".repeat(64) }, "invalid_agreement"],
  ["invalid company ID", { ...validInput, companyId: "not-a-uuid" }, "invalid_company_id"],
]) {
  test(`${name} fails before privileged append`, async () => {
    const { deps, calls } = dependencies();
    const result = await reacceptCustomerAgreement(input, deps);
    assert.equal(result.ok, false);
    assert.equal(result.code, code);
    assert.equal(calls.length, 0);
  });
}

test("unauthenticated reacceptance fails before privileged append", async () => {
  const { deps, calls } = dependencies({ getAuthenticatedUser: async () => null });
  assert.deepEqual(await reacceptCustomerAgreement(validInput, deps), {
    ok: false,
    code: "unauthenticated",
    message: "Innlogging kreves.",
  });
  assert.equal(calls.length, 0);
});

test("RPC failure maps to a typed failure", async () => {
  const { deps } = dependencies({ appendAcceptance: async () => { throw new Error("Append failed."); } });
  assert.deepEqual(await reacceptCustomerAgreement(validInput, deps), {
    ok: false,
    code: "acceptance_append_failed",
    message: "Append failed.",
  });
});

test("success sends all 12 exact append arguments once", async () => {
  const { deps, calls } = dependencies();
  assert.deepEqual(await reacceptCustomerAgreement(validInput, deps), { ok: true });
  assert.deepEqual(calls, [{
    p_actor_id: "20000000-0000-4000-8000-000000000002",
    p_company_id: company.id,
    p_business_terms_version: currentCustomerAgreements.businessTerms.version,
    p_business_terms_effective_date: currentCustomerAgreements.businessTerms.effectiveDate,
    p_business_terms_path: currentCustomerAgreements.businessTerms.path,
    p_business_terms_sha256: currentCustomerAgreements.businessTerms.contentSha256,
    p_dpa_version: currentCustomerAgreements.dpa.version,
    p_dpa_effective_date: currentCustomerAgreements.dpa.effectiveDate,
    p_dpa_path: currentCustomerAgreements.dpa.path,
    p_dpa_sha256: currentCustomerAgreements.dpa.contentSha256,
    p_authority_statement_version: customerAgreementAuthorityStatementVersion,
    p_acceptance_method: "in_app_clickwrap",
  }]);
  assert.equal(Object.keys(calls[0]).length, 12);
});
