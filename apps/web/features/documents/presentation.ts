import { TalliApiError, type DocumentWire } from "@talli/talli-api-client";

export type DocumentPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  document_type: string;
  name: string;
  linked_to: string;
  status: string;
  retention_years: number;
  storage_key: string;
  content_sha256: string | null;
  created_by: string;
  created_at: string;
  removed_at: string | null;
  removed_by: string | null;
  removal_reason: string | null;
};

export function presentDocument(document: DocumentWire): DocumentPresentation {
  return {
    id: document.id,
    company_id: document.companyId,
    income_year: document.incomeYear,
    document_type: document.documentType,
    name: document.name,
    linked_to: document.linkedTo,
    status: document.status,
    retention_years: document.retentionYears,
    storage_key: document.storageKey,
    content_sha256: document.contentSha256,
    created_by: document.createdBy,
    created_at: document.createdAt,
    removed_at: document.removedAt,
    removed_by: null,
    removal_reason: document.removalReason,
  };
}

export function documentsActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    switch (error.problem?.code) {
      case "DOCUMENT_EVIDENCE_LINKED":
        return "Dokumentet brukes som regnskaps- eller innsendingsbevis og kan derfor ikke fjernes.";
      case "DOCUMENT_STEP_UP_REQUIRED":
        return "Bekreft identiteten din med MFA før du laster ned dokumentet.";
      case "DOCUMENT_INTEGRITY_FAILED":
        return "Dokumentets integritet kunne ikke bekreftes.";
      case "DOCUMENT_NOT_FOUND":
        return "Dokumentet finnes ikke, eller du har ikke tilgang.";
      case "DOCUMENT_INVALID_INPUT":
        return "Bare gyldige PDF-dokumenter på maksimalt 10 MB kan lastes opp.";
      default:
        break;
    }
  }
  return "Dokumenttjenesten svarte ikke. Prøv igjen senere.";
}
