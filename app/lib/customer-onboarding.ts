import type { BrregCompanyIdentity } from "./brreg.ts";
import {
  assertCurrentCustomerAgreementForm,
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} from "./customer-agreements.ts";

export type CustomerWorkspaceRpcPayload = {
  p_actor_id: string;
  p_org_number: string;
  p_name: string;
  p_entity_type: string;
  p_address: string;
  p_postal_code: string;
  p_city: string;
  p_status_text: string;
  p_source: string;
  p_business_terms_version: string;
  p_business_terms_effective_date: string;
  p_business_terms_path: string;
  p_business_terms_sha256: string;
  p_dpa_version: string;
  p_dpa_effective_date: string;
  p_dpa_path: string;
  p_dpa_sha256: string;
  p_authority_statement_version: string;
  p_acceptance_method: "in_app_clickwrap";
};

export type CustomerOnboardingInput = {
  agreementAccepted: string;
  businessTermsVersion: string;
  dpaVersion: string;
  orgNumber: string;
};

export type CustomerOnboardingDependencies = {
  getAuthenticatedUser: () => Promise<{ id: string } | null>;
  lookupCompanyIdentity: (orgNumber: string) => Promise<BrregCompanyIdentity>;
  assertSupportedCompanyIdentity: (identity: BrregCompanyIdentity) => void;
  createCompanyWorkspace: (payload: CustomerWorkspaceRpcPayload) => Promise<void>;
};

export type CustomerOnboardingFailureCode =
  | "unauthenticated"
  | "invalid_agreement"
  | "invalid_org_number"
  | "identity_lookup_failed"
  | "unsupported_entity"
  | "workspace_creation_failed";

export type CustomerOnboardingResult =
  | { ok: true }
  | { ok: false; code: CustomerOnboardingFailureCode; message: string };

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export async function onboardCustomer(
  input: CustomerOnboardingInput,
  dependencies: CustomerOnboardingDependencies,
): Promise<CustomerOnboardingResult> {
  let user: { id: string } | null;
  try {
    user = await dependencies.getAuthenticatedUser();
  } catch {
    user = null;
  }
  if (!user) {
    return { ok: false, code: "unauthenticated", message: "Innlogging kreves." };
  }

  try {
    assertCurrentCustomerAgreementForm(input);
  } catch (error) {
    return {
      ok: false,
      code: "invalid_agreement",
      message: errorMessage(error, "Avtaleaksept mangler."),
    };
  }

  if (!/^\d{9}$/.test(input.orgNumber)) {
    return {
      ok: false,
      code: "invalid_org_number",
      message: "Organisasjonsnummer må ha 9 sifre.",
    };
  }

  let identity: BrregCompanyIdentity;
  try {
    identity = await dependencies.lookupCompanyIdentity(input.orgNumber);
  } catch (error) {
    return {
      ok: false,
      code: "identity_lookup_failed",
      message: errorMessage(error, "Brønnøysund-oppslag feilet"),
    };
  }

  try {
    dependencies.assertSupportedCompanyIdentity(identity);
  } catch (error) {
    return {
      ok: false,
      code: "unsupported_entity",
      message: errorMessage(error, "Selskapsform støttes ikke"),
    };
  }

  try {
    await dependencies.createCompanyWorkspace({
      p_actor_id: user.id,
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
    });
  } catch (error) {
    return {
      ok: false,
      code: "workspace_creation_failed",
      message: errorMessage(error, "Kunne ikke opprette selskap"),
    };
  }

  return { ok: true };
}
