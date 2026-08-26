import {
  TalliApiError,
  type CompanyAccessRecord,
  type CompanyContext,
  type OperatorCompanyRecord,
} from "@talli/talli-api-client";

export function companyAccessActionErrorMessage(error: unknown) {
  if (!(error instanceof TalliApiError)) return "Tjenesten er midlertidig utilgjengelig.";
  if (error.status === 401) return "Innlogging kreves.";
  if (error.problem?.code === "UNSUPPORTED_COMPANY") {
    return "Talli støtter kun AS i første versjon.";
  }
  if (error.problem?.code === "COMPANY_REGISTRY_NOT_FOUND") {
    return "Fant ikke organisasjonsnummeret i Enhetsregisteret.";
  }
  if (error.problem?.code === "COMPANY_REGISTRY_UNAVAILABLE") {
    return "Kunne ikke hente selskapsdata fra Brønnøysundregistrene.";
  }
  if (error.problem?.code === "COMPANY_ACCESS_NOT_FOUND") return "Ugyldig selskap.";
  return "Tjenesten er midlertidig utilgjengelig.";
}

export type CompanyRegistryPresentation = {
  id: string;
  org_number: string;
  name: string;
  entity_type: string;
  address: string;
  postal_code: string;
  city: string;
  status_text: string;
  source: string;
  created_by: string;
  identity_confirmed_at: string | null;
  identity_locked_at: string | null;
  created_at: string;
};

/**
 * Company data deliberately owned by the company-access feature at the web
 * boundary. It is a presentation model, not a Supabase persistence row.
 */
export type CompanyAccessPresentation = CompanyRegistryPresentation & {
  role: "owner";
  currentAgreementAccepted: boolean;
};

export type AcceptedMembershipCompanyPresentation = CompanyRegistryPresentation & {
  role: "owner" | "reviewer" | "read_only";
};

function presentCompanyRegistry(
  company: CompanyContext | CompanyAccessRecord | OperatorCompanyRecord,
): CompanyRegistryPresentation {
  return {
    id: company.id,
    org_number: company.orgNumber,
    name: company.name,
    entity_type: company.entityType,
    address: company.address,
    postal_code: company.postalCode,
    city: company.city,
    status_text: company.statusText,
    source: company.source,
    created_by: company.createdBy,
    identity_confirmed_at: company.identityConfirmedAt,
    identity_locked_at: company.identityLockedAt,
    created_at: company.createdAt,
  };
}

export function presentCompanyAccessContext(context: CompanyContext): CompanyAccessPresentation {
  return {
    ...presentCompanyRegistry(context),
    role: context.role,
    currentAgreementAccepted: context.currentAgreementAccepted,
  };
}

export function presentCompanyAccessRecord(
  company: CompanyAccessRecord,
): AcceptedMembershipCompanyPresentation {
  return { ...presentCompanyRegistry(company), role: company.role };
}

export function presentOperatorCompanyRecord(
  company: OperatorCompanyRecord,
): CompanyRegistryPresentation {
  return presentCompanyRegistry(company);
}
