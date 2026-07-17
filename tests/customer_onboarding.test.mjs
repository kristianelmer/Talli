import assert from "node:assert/strict";
import test from "node:test";

import {
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} from "../app/lib/customer-agreements.ts";
import { onboardCustomer } from "../app/lib/customer-onboarding.ts";

const validForm = {
  agreementAccepted: "accepted",
  businessTermsVersion: currentCustomerAgreements.businessTerms.version,
  dpaVersion: currentCustomerAgreements.dpa.version,
  orgNumber: "123456789",
};

const identity = {
  orgNumber: "123456789",
  name: "Talli Holding AS",
  entityType: "AS",
  address: "Karl Johans gate 1",
  postalCode: "0154",
  city: "OSLO",
  statusText: "aktiv",
  source: "brreg",
};

function dependencies(overrides = {}) {
  const privilegedCalls = [];
  return {
    privilegedCalls,
    deps: {
      getAuthenticatedUser: async () => ({ id: "00000000-0000-4000-8000-000000000001" }),
      lookupCompanyIdentity: async () => identity,
      assertSupportedCompanyIdentity: () => undefined,
      createCompanyWorkspace: async (payload) => {
        privilegedCalls.push(payload);
      },
      ...overrides,
    },
  };
}

test("unauthenticated onboarding stops before lookup and privileged creation", async () => {
  let lookupCalls = 0;
  const { deps, privilegedCalls } = dependencies({
    getAuthenticatedUser: async () => null,
    lookupCompanyIdentity: async () => {
      lookupCalls += 1;
      return identity;
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, { ok: false, code: "unauthenticated", message: "Innlogging kreves." });
  assert.equal(lookupCalls, 0);
  assert.equal(privilegedCalls.length, 0);
});

test("authentication failure maps to the typed unauthenticated result", async () => {
  const { deps, privilegedCalls } = dependencies({
    getAuthenticatedUser: async () => {
      throw new Error("Auth provider unavailable");
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, { ok: false, code: "unauthenticated", message: "Innlogging kreves." });
  assert.equal(privilegedCalls.length, 0);
});

test("missing assent stops before lookup and privileged creation", async () => {
  let lookupCalls = 0;
  const { deps, privilegedCalls } = dependencies({
    lookupCompanyIdentity: async () => {
      lookupCalls += 1;
      return identity;
    },
  });

  const result = await onboardCustomer({ ...validForm, agreementAccepted: "" }, deps);

  assert.deepEqual(result, {
    ok: false,
    code: "invalid_agreement",
    message: "Du må bekrefte fullmakt og godta avtalevilkårene.",
  });
  assert.equal(lookupCalls, 0);
  assert.equal(privilegedCalls.length, 0);
});

test("stale agreement versions stop before lookup and privileged creation", async () => {
  let lookupCalls = 0;
  const { deps, privilegedCalls } = dependencies({
    lookupCompanyIdentity: async () => {
      lookupCalls += 1;
      return identity;
    },
  });

  const result = await onboardCustomer({ ...validForm, dpaVersion: "stale" }, deps);

  assert.deepEqual(result, {
    ok: false,
    code: "invalid_agreement",
    message: "Avtalevilkårene er oppdatert. Les dem og bekreft på nytt.",
  });
  assert.equal(lookupCalls, 0);
  assert.equal(privilegedCalls.length, 0);
});

test("Brønnøysund lookup failure returns its message without privileged creation", async () => {
  const { deps, privilegedCalls } = dependencies({
    lookupCompanyIdentity: async () => {
      throw new Error("Fant ikke organisasjonsnummeret i Enhetsregisteret.");
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, {
    ok: false,
    code: "identity_lookup_failed",
    message: "Fant ikke organisasjonsnummeret i Enhetsregisteret.",
  });
  assert.equal(privilegedCalls.length, 0);
});

test("unsupported entity stops before privileged creation", async () => {
  const { deps, privilegedCalls } = dependencies({
    assertSupportedCompanyIdentity: () => {
      throw new Error("Talli støtter kun AS i første versjon. Enkelt er ENK.");
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, {
    ok: false,
    code: "unsupported_entity",
    message: "Talli støtter kun AS i første versjon. Enkelt er ENK.",
  });
  assert.equal(privilegedCalls.length, 0);
});

test("RPC failure is returned after exactly one privileged creation attempt", async () => {
  let privilegedCalls = 0;
  const { deps } = dependencies({
    createCompanyWorkspace: async () => {
      privilegedCalls += 1;
      throw new Error("Atomic workspace creation failed.");
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, {
    ok: false,
    code: "workspace_creation_failed",
    message: "Atomic workspace creation failed.",
  });
  assert.equal(privilegedCalls, 1);
});

test("success invokes atomic creation once with every exact registry and identity argument", async () => {
  const events = [];
  const payloads = [];
  const { deps } = dependencies({
    getAuthenticatedUser: async () => {
      events.push("authenticated");
      return { id: "00000000-0000-4000-8000-000000000001" };
    },
    lookupCompanyIdentity: async () => {
      events.push("looked-up");
      return identity;
    },
    assertSupportedCompanyIdentity: () => {
      events.push("supported");
    },
    createCompanyWorkspace: async (payload) => {
      events.push("privileged");
      payloads.push(payload);
    },
  });

  const result = await onboardCustomer(validForm, deps);

  assert.deepEqual(result, { ok: true });
  assert.deepEqual(events, ["authenticated", "looked-up", "supported", "privileged"]);
  assert.deepEqual(payloads, [{
    p_actor_id: "00000000-0000-4000-8000-000000000001",
    p_org_number: identity.orgNumber,
    p_name: identity.name,
    p_entity_type: identity.entityType,
    p_address: identity.address,
    p_postal_code: identity.postalCode,
    p_city: identity.city,
    p_status_text: identity.statusText,
    p_source: identity.source,
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
  assert.equal(Object.keys(payloads[0]).length, 19);
});
