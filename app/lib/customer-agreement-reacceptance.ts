import {
  assertCurrentCustomerAgreementForm,
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} from "./customer-agreements.ts";

export type CustomerAgreementEvidence = {
  company_id: string;
  business_terms_version: string;
  business_terms_sha256: string;
  dpa_version: string;
  dpa_sha256: string;
};

export function hasCurrentCustomerAgreementEvidence(evidence: CustomerAgreementEvidence) {
  return evidence.business_terms_version === currentCustomerAgreements.businessTerms.version
    && evidence.business_terms_sha256 === currentCustomerAgreements.businessTerms.contentSha256
    && evidence.dpa_version === currentCustomerAgreements.dpa.version
    && evidence.dpa_sha256 === currentCustomerAgreements.dpa.contentSha256;
}

export function companiesRequiringCurrentCustomerAgreement<T extends { id: string }>(
  companies: readonly T[],
  acceptances: readonly CustomerAgreementEvidence[],
) {
  return companies.filter((company) => !acceptances.some(
    (acceptance) => acceptance.company_id === company.id && hasCurrentCustomerAgreementEvidence(acceptance),
  ));
}

export type CustomerAgreementReacceptanceInput = {
  companyId: string;
  agreementAccepted: string;
  businessTermsVersion: string;
  businessTermsSha256: string;
  dpaVersion: string;
  dpaSha256: string;
};

export type CustomerAgreementReacceptancePayload = {
  p_actor_id: string;
  p_company_id: string;
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

export type CustomerAgreementReacceptanceDependencies = {
  getAuthenticatedUser: () => Promise<{ id: string } | null>;
  appendAcceptance: (payload: CustomerAgreementReacceptancePayload) => Promise<void>;
};

export type CustomerAgreementReacceptanceResult =
  | { ok: true }
  | { ok: false; code: "unauthenticated" | "invalid_agreement" | "invalid_company_id" | "acceptance_append_failed"; message: string };

export async function reacceptCustomerAgreement(
  input: CustomerAgreementReacceptanceInput,
  dependencies: CustomerAgreementReacceptanceDependencies,
): Promise<CustomerAgreementReacceptanceResult> {
  let user: { id: string } | null;
  try {
    user = await dependencies.getAuthenticatedUser();
  } catch {
    user = null;
  }
  if (!user) return { ok: false, code: "unauthenticated", message: "Innlogging kreves." };

  try {
    assertCurrentCustomerAgreementForm(input);
  } catch (error) {
    return {
      ok: false,
      code: "invalid_agreement",
      message: error instanceof Error ? error.message : "Avtaleaksept mangler.",
    };
  }

  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(input.companyId)) {
    return { ok: false, code: "invalid_company_id", message: "Ugyldig selskap." };
  }

  try {
    await dependencies.appendAcceptance({
      p_actor_id: user.id,
      p_company_id: input.companyId,
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
      code: "acceptance_append_failed",
      message: error instanceof Error ? error.message : "Kunne ikke lagre avtaleaksept.",
    };
  }
  return { ok: true };
}
