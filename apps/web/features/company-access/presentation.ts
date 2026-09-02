import {
  TalliApiError,
  type CompanyAccessRecord,
  type CompanyContext,
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

export function eligibilityActionErrorMessage(error: unknown) {
  if (!(error instanceof TalliApiError)) {
    return "Talli fikk ikke fullført sjekken. Prøv igjen om litt.";
  }
  if (error.problem?.code === "COMPANY_REGISTRY_NOT_FOUND") {
    return "Fant ikke organisasjonsnummeret i Enhetsregisteret. Kontroller nummeret.";
  }
  if (error.problem?.code === "COMPANY_REGISTRY_UNAVAILABLE") {
    return "Brønnøysundregistrene svarer ikke nå. Dette betyr ikke at selskapet er utenfor Talli.";
  }
  if (error.problem?.code === "ELIGIBILITY_MANIFEST_CHANGED") {
    return "Talli har oppdatert grensene. Start den gratis sjekken på nytt.";
  }
  if (error.problem?.code === "ELIGIBILITY_FACTS_CHANGED") {
    return "Offentlige selskapsopplysninger er endret. Start sjekken på nytt.";
  }
  if (error.problem?.code === "COMPANY_YEAR_NOT_ELIGIBLE") {
    return "Selskapet er ikke lenger innenfor Talli-grensen. Start sjekken på nytt.";
  }
  if (error.problem?.code === "ADMISSION_EVIDENCE_CHANGED") {
    return "Vilkårene eller Talli-grensen er oppdatert. Start sjekken på nytt.";
  }
  return "Talli fikk ikke fullført sjekken. Prøv igjen om litt.";
}

export function eligibilityAdmissionRestartRequired(error: unknown) {
  return error instanceof TalliApiError && [
    "ELIGIBILITY_MANIFEST_CHANGED",
    "ELIGIBILITY_FACTS_CHANGED",
    "COMPANY_YEAR_NOT_ELIGIBLE",
    "ADMISSION_EVIDENCE_CHANGED",
  ].includes(error.problem?.code ?? "");
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
  companyYearAdmissionId: string | null;
  admittedAccountingYear: number | null;
  currentEligibilityDecision: "supported" | "clarify" | "blocked" | null;
  eligibilityReasonExplanations: string[];
  eligibilityNextStepCode: string | null;
  eligibilityNextStep: string | null;
  consequentialOperationsAllowed: boolean;
  archiveExportAvailable: boolean;
};

export type AcceptedMembershipCompanyPresentation = CompanyRegistryPresentation & {
  role: "owner" | "reviewer" | "read_only";
};

function presentCompanyRegistry(
  company: CompanyContext | CompanyAccessRecord,
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
    companyYearAdmissionId: context.companyYearAdmissionId,
    admittedAccountingYear: context.admittedAccountingYear,
    currentEligibilityDecision: context.currentEligibilityDecision,
    eligibilityReasonExplanations: context.eligibilityReasonExplanations,
    eligibilityNextStepCode: context.eligibilityNextStepCode,
    eligibilityNextStep: context.eligibilityNextStep,
    consequentialOperationsAllowed: context.consequentialOperationsAllowed,
    archiveExportAvailable: context.archiveExportAvailable,
  };
}

export function presentCompanyAccessRecord(
  company: CompanyAccessRecord,
): AcceptedMembershipCompanyPresentation {
  return { ...presentCompanyRegistry(company), role: company.role };
}
