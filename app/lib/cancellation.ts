export type CancellationStatus = "export_required" | "retention_hold" | "deletion_approved" | "deleted";

export type CancellationEvidence = {
  archiveExportedAt?: string | null;
  archiveIncomeYear?: number | null;
  archiveDownloadPath?: string | null;
  retentionClasses?: string[];
  missingDocumentIds?: string[];
  legalReviewRequired?: boolean;
};

export type CompanyCancellationRow = {
  id: string;
  company_id: string;
  status: CancellationStatus;
  reason: string;
  evidence: CancellationEvidence;
  requested_by: string;
  requested_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  deleted_by: string | null;
  deleted_at: string | null;
  updated_at: string;
};

export type CancellationLifecycleItem = {
  key: "archive_export" | "soft_delete" | "retention_hold" | "final_deletion";
  label: string;
  state: "done" | "current" | "blocked" | "pending";
  message: string;
};

export const retentionClasses = [
  "accounting_documents",
  "ledger_and_holding_actions",
  "filing_payloads_feedback_receipts",
  "billing_refund_records",
  "audit_security_logs",
];

export function cancellationStatusLabel(status: CancellationStatus) {
  switch (status) {
    case "export_required":
      return "Arkiv må eksporteres";
    case "retention_hold":
      return "Retention hold";
    case "deletion_approved":
      return "Sletting godkjent";
    case "deleted":
      return "Slettet";
  }
}

export function nextCancellationStatus(input: {
  archiveExportedAt?: string | null;
  legalReviewApproved?: boolean;
  deletedAt?: string | null;
}): CancellationStatus {
  if (input.deletedAt) {
    return "deleted";
  }
  if (input.legalReviewApproved) {
    return "deletion_approved";
  }
  if (input.archiveExportedAt) {
    return "retention_hold";
  }
  return "export_required";
}

export function buildCancellationEvidence(input: {
  companyId: string;
  incomeYear: number;
  archiveExportedAt?: string | null;
  missingDocumentIds?: string[];
}): CancellationEvidence {
  return {
    archiveExportedAt: input.archiveExportedAt ?? null,
    archiveIncomeYear: input.incomeYear,
    archiveDownloadPath: `/archive/${input.companyId}/${input.incomeYear}/download`,
    retentionClasses,
    missingDocumentIds: input.missingDocumentIds ?? [],
    legalReviewRequired: true,
  };
}

export function buildCancellationLifecycle(cancellation: Pick<CompanyCancellationRow, "status" | "evidence" | "deleted_at" | "reviewed_at"> | null | undefined): CancellationLifecycleItem[] {
  const archiveDone = Boolean(cancellation?.evidence?.archiveExportedAt);
  const deleted = cancellation?.status === "deleted" || Boolean(cancellation?.deleted_at);
  const deletionApproved = cancellation?.status === "deletion_approved" || deleted;
  const retentionDone = cancellation?.status === "retention_hold" || deletionApproved || deleted;

  return [
    {
      key: "archive_export",
      label: "Arkiveksport",
      state: archiveDone ? "done" : "current",
      message: archiveDone ? "Selskapsarkiv er registrert før kansellering." : "Arkiv må eksporteres før destruktiv handling.",
    },
    {
      key: "soft_delete",
      label: "Soft-delete",
      state: archiveDone ? (deleted ? "done" : "current") : "blocked",
      message: archiveDone
        ? "Arbeidsflaten kan markeres kansellert uten å slette pliktig dokumentasjon."
        : "Blokkert til arkiv finnes.",
    },
    {
      key: "retention_hold",
      label: "Retention hold",
      state: retentionDone ? "done" : archiveDone ? "current" : "blocked",
      message: retentionDone
        ? "Retention-vurdering er aktiv eller godkjent."
        : "Juridisk/accounting retention må avklares før endelig sletting.",
    },
    {
      key: "final_deletion",
      label: "Endelig sletting",
      state: deleted ? "done" : deletionApproved ? "current" : "blocked",
      message: deleted
        ? "Endelig sletting er registrert."
        : deletionApproved
          ? "Klar for separat destruktiv sletting etter godkjenning."
          : "Blokkert til legal/security review og retention er godkjent.",
    },
  ];
}
