export const launchCriticalTables = [
  "companies",
  "company_memberships",
  "annual_data",
  "opening_balance_setups",
  "opening_shareholders",
  "ledger_entries",
  "bank_transactions",
  "bank_suggestion_acceptances",
  "holding_actions",
  "investment_positions",
  "investment_lots",
  "investment_lot_allocations",
  "documents",
  "filing_previews",
  "filing_submissions",
  "filing_readiness_snapshots",
  "filing_overrides",
  "filing_review_comments",
  "billing_accounts",
  "authority_permissions",
  "audit_events",
] as const;

export type RestoreGateRecord = {
  testedAt: string;
  status: "passed" | "failed";
  target: string;
};

export function buildBackupManifest(archive: Record<string, any>) {
  const objectReferences = (archive.documents ?? [])
    .map((document: any) => ({
      documentId: document.id,
      storageKey: document.storageKey,
      status: document.status,
      retentionYears: document.retentionYears,
    }))
    .filter((reference: any) => reference.storageKey);

  return {
    manifestType: "talli_backup_restore_manifest",
    companyId: archive.company?.id,
    incomeYear: archive.incomeYear,
    launchCriticalTables,
    objectReferences,
    counts: {
      ledgerEntries: archive.ledgerEntries?.length ?? 0,
      holdingActions: archive.taxSettlements?.length ?? 0,
      documents: archive.documents?.length ?? 0,
      filingPreviews: archive.filingPreviews?.length ?? 0,
      filingSubmissions: archive.rf1086Submissions?.length ?? 0,
      reviewComments: archive.reviewComments?.length ?? 0,
      billingAccounts: archive.billingAccounts?.length ?? 0,
      auditEvents: archive.auditEvents?.length ?? 0,
      investmentPositions: archive.investmentPositions?.length ?? 0,
      investmentLots: archive.investmentLots?.length ?? 0,
      investmentLotAllocations: archive.investmentLotAllocations?.length ?? 0,
      bankSuggestionAcceptances: archive.bankSuggestionAcceptances?.length ?? 0,
    },
  };
}

export function restoreCompanyYearArchive(archive: Record<string, any>, options: { targetCompanyId: string }) {
  const manifest = buildBackupManifest(archive);
  const missingObjectWarnings = (archive.documents ?? [])
    .filter((document: any) => !document.storageKey || String(document.status).startsWith("missing"))
    .map((document: any) => ({
      code: "document_object_missing_or_marked_missing",
      documentId: document.id,
      message: "Document metadata restored, but object storage content must be rehydrated or accepted as missing.",
    }));

  return {
    restoreType: "talli_company_year_restore_fixture",
    sourceCompanyId: archive.company?.id,
    targetCompanyId: options.targetCompanyId,
    incomeYear: archive.incomeYear,
    manifest,
    restored: {
      company: { ...archive.company, id: options.targetCompanyId },
      ledgerEntries: archive.ledgerEntries ?? [],
      holdingActions: archive.taxSettlements ?? [],
      documents: archive.documents ?? [],
      filingPreviews: archive.filingPreviews ?? [],
      filingSubmissions: archive.rf1086Submissions ?? [],
      reviewComments: archive.reviewComments ?? [],
      billingAccounts: archive.billingAccounts ?? [],
      auditEvents: archive.auditEvents ?? [],
      investmentPositions: archive.investmentPositions ?? [],
      investmentLots: archive.investmentLots ?? [],
      investmentLotAllocations: archive.investmentLotAllocations ?? [],
      bankSuggestionAcceptances: archive.bankSuggestionAcceptances ?? [],
    },
    warnings: missingObjectWarnings,
  };
}

export function assertRestoreIntegrity(restored: ReturnType<typeof restoreCompanyYearArchive>) {
  const failures = [];
  if (!restored.restored.ledgerEntries.length) failures.push("ledger_entries_missing");
  if (!restored.restored.documents.length) failures.push("documents_metadata_missing");
  if (!restored.restored.filingPreviews.length) failures.push("filing_previews_missing");
  if (!restored.restored.filingSubmissions.length) failures.push("filing_submissions_missing");
  if (!restored.restored.billingAccounts.length) failures.push("billing_accounts_missing");
  if (!restored.restored.auditEvents.length) failures.push("audit_events_missing");
  return {
    ok: failures.length === 0,
    failures,
    warnings: restored.warnings,
  };
}

export function productionRestoreLaunchGate(records: RestoreGateRecord[], now = new Date()) {
  const latestPassed = records
    .filter((record) => record.status === "passed")
    .map((record) => ({ ...record, testedAtTime: new Date(record.testedAt).getTime() }))
    .filter((record) => Number.isFinite(record.testedAtTime))
    .sort((a, b) => b.testedAtTime - a.testedAtTime)[0];
  if (!latestPassed) {
    return { allowed: false, status: "restore_test_missing", message: "Production direct filing is blocked until backup/restore test passes." };
  }
  const ageDays = (now.getTime() - latestPassed.testedAtTime) / 86_400_000;
  if (ageDays > 30) {
    return { allowed: false, status: "restore_test_stale", message: "Backup/restore test is older than 30 days." };
  }
  return { allowed: true, status: "restore_test_recent", message: "Recent backup/restore test passed." };
}
