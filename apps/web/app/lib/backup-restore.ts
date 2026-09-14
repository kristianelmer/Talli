export const launchCriticalTables = [
  "companies",
  "company_memberships",
  "annual_data",
  "shareholder_register_filing.opening_balance_setups",
  "ledger.opening_bank_inputs",
  "shareholder_register_filing.opening_shareholders",
  "ledger_entries",
  "bank_transactions",
  "bank_suggestion_acceptances",
  "holding_actions",
  "investments.positions",
  "investments.acquisition_lots",
  "investments.share_purchases",
  "investments.share_sales",
  "investments.share_sale_allocations",
  "investments.received_dividends",
  "documents",
  "annual_accounts_filing.filing_previews",
  "shareholder_register_filing.filing_previews",
  "billing.production_pilot_entitlements",
  "shareholder_register_filing.filing_approval_snapshots",
  "shareholder_register_filing.production_filing_submissions",
  "shareholder_register_filing.production_filing_events",
  "shareholder_register_filing.production_feedback_artifacts",
  "annual_accounts_filing.authority_test_runs",
  "shareholder_register_filing.authority_test_runs",
  "annual_accounts_filing.filing_submissions",
  "shareholder_register_filing.filing_submissions",
  "filing_readiness_snapshots",
  "annual_accounts_filing.filing_overrides",
  "shareholder_register_filing.filing_overrides",
  "annual_accounts_filing.filing_review_comments",
  "shareholder_register_filing.filing_review_comments",
  "billing.billing_accounts",
  "billing.billing_payment_events",
  "annual_accounts_filing.authority_permissions",
  "shareholder_register_filing.authority_permissions",
  "audit_events",
  "corporate_governance.owner_dividend_accounting_policies",
  "corporate_governance.owner_dividend_decisions",
  "corporate_governance.owner_dividend_artifacts",
  "corporate_governance.owner_dividend_events",
  "corporate_governance.owner_dividend_finalizations",
  "corporate_governance.owner_dividend_payments",
  "corporate_governance.shareholder_loans",
  "corporate_governance.annual_close_decisions",
  "corporate_governance.annual_close_artifacts",
  "corporate_governance.annual_close_events",
  "corporate_governance.annual_close_finalizations",
] as const;

export type RestoreGateRecord = {
  testedAt: string;
  status: "passed" | "failed";
  target: string;
};

function filingSubmissionCollections(archive: Record<string, any>) {
  const rf1086Submissions = Array.isArray(archive.rf1086Submissions)
    ? archive.rf1086Submissions
    : [];
  const companyTaxSubmissions = Array.isArray(archive.companyTaxSubmissions)
    ? archive.companyTaxSubmissions
    : [];
  return {
    rf1086Submissions,
    companyTaxSubmissions,
    filingSubmissions: [...rf1086Submissions, ...companyTaxSubmissions],
  };
}

export function buildBackupManifest(archive: Record<string, any>) {
  const submissionCollections = filingSubmissionCollections(archive);
  const documentBackupProjection = archive.documentBackupProjection ?? {
    companyId: archive.company?.id,
    incomeYear: archive.incomeYear,
    objects: [],
  };
  const objectReferences = Array.isArray(documentBackupProjection.objects)
    ? documentBackupProjection.objects
    : [];

  return {
    manifestType: "talli_backup_restore_manifest",
    companyId: archive.company?.id,
    incomeYear: archive.incomeYear,
    launchCriticalTables,
    accountingPolicyVersionReferences: [...new Set(
      (archive.corporateDecisionFinalizations ?? [])
        .map((finalization: any) => finalization.accounting_policy_version)
        .filter(Boolean),
    )].sort(),
    objectReferences,
    counts: {
      ledgerEntries: archive.ledgerEntries?.length ?? 0,
      holdingActions: archive.taxSettlements?.length ?? 0,
      documents: objectReferences.length,
      filingPreviews: archive.filingPreviews?.length ?? 0,
      authorityTestRuns: archive.authorityTestRuns?.length ?? 0,
      filingSubmissions: submissionCollections.filingSubmissions.length,
      productionPilotEntitlements: archive.productionPilotEntitlements?.length ?? 0,
      filingApprovalSnapshots: archive.filingApprovalSnapshots?.length ?? 0,
      productionFilingSubmissions: archive.productionFilingSubmissions?.length ?? 0,
      productionFilingEvents: archive.productionFilingEvents?.length ?? 0,
      companyTaxSubmissions: submissionCollections.companyTaxSubmissions.length,
      reviewComments: archive.reviewComments?.length ?? 0,
      billingAccounts: archive.billingAccounts?.length ?? 0,
      auditEvents: archive.auditEvents?.length ?? 0,
      investmentPositions: archive.investmentPositions?.length ?? 0,
      investmentLots: archive.investmentLots?.length ?? 0,
      investmentLotAllocations: archive.investmentLotAllocations?.length ?? 0,
      bankSuggestionAcceptances: archive.bankSuggestionAcceptances?.length ?? 0,
      corporateDecisions: archive.corporateDecisions?.length ?? 0,
      corporateDocumentSets: archive.corporateDocumentSets?.length ?? 0,
      corporateDocumentArtifacts: archive.corporateDocumentArtifacts?.length ?? 0,
      corporateDocumentEvents: archive.corporateDocumentEvents?.length ?? 0,
      corporateDecisionFinalizations: archive.corporateDecisionFinalizations?.length ?? 0,
    },
  };
}

export function restoreCompanyYearArchive(archive: Record<string, any>, options: { targetCompanyId: string }) {
  const manifest = buildBackupManifest(archive);
  const submissionCollections = filingSubmissionCollections(archive);
  const missingObjectWarnings = manifest.objectReferences
    .filter((document: any) => !document.storageKey || String(document.status).startsWith("missing"))
    .map((document: any) => ({
      code: "document_object_missing_or_marked_missing",
      documentId: document.documentId,
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
      authorityTestRuns: archive.authorityTestRuns ?? [],
      rf1086Submissions: submissionCollections.rf1086Submissions,
      companyTaxSubmissions: submissionCollections.companyTaxSubmissions,
      filingSubmissions: submissionCollections.filingSubmissions,
      productionPilotEntitlements: archive.productionPilotEntitlements ?? [],
      filingApprovalSnapshots: archive.filingApprovalSnapshots ?? [],
      productionFilingSubmissions: archive.productionFilingSubmissions ?? [],
      productionFilingEvents: archive.productionFilingEvents ?? [],
      reviewComments: archive.reviewComments ?? [],
      billingAccounts: archive.billingAccounts ?? [],
      auditEvents: archive.auditEvents ?? [],
      investmentPositions: archive.investmentPositions ?? [],
      investmentLots: archive.investmentLots ?? [],
      investmentLotAllocations: archive.investmentLotAllocations ?? [],
      bankSuggestionAcceptances: archive.bankSuggestionAcceptances ?? [],
      corporateDecisions: archive.corporateDecisions ?? [],
      corporateDocumentSets: archive.corporateDocumentSets ?? [],
      corporateDocumentArtifacts: archive.corporateDocumentArtifacts ?? [],
      corporateDocumentEvents: archive.corporateDocumentEvents ?? [],
      corporateDecisionFinalizations: archive.corporateDecisionFinalizations ?? [],
    },
    warnings: missingObjectWarnings,
  };
}

export function assertRestoreIntegrity(restored: ReturnType<typeof restoreCompanyYearArchive>) {
  const failures: string[] = [];
  const fail = (code: string) => {
    if (!failures.includes(code)) failures.push(code);
  };
  if (!restored.restored.ledgerEntries.length) failures.push("ledger_entries_missing");
  if (!restored.restored.documents.length) failures.push("documents_metadata_missing");
  if (!restored.restored.filingPreviews.length) failures.push("filing_previews_missing");
  if (!restored.restored.filingSubmissions.length) failures.push("filing_submissions_missing");
  const productionSubmissions = restored.restored.productionFilingSubmissions;
  if (productionSubmissions.length) {
    const entitlementIds = new Set(restored.restored.productionPilotEntitlements.map((row: any) => row.id));
    const approvalIds = new Set(restored.restored.filingApprovalSnapshots.map((row: any) => row.id));
    const submissionIds = new Set(productionSubmissions.map((row: any) => row.id));
    if (productionSubmissions.some((row: any) => !entitlementIds.has(row.entitlement_id) || !approvalIds.has(row.approval_id))) {
      failures.push("production_filing_relationship_missing");
    }
    if (restored.restored.productionFilingEvents.some((row: any) => !submissionIds.has(row.submission_id))) {
      failures.push("production_filing_event_relationship_missing");
    }
  }
  if (!restored.restored.billingAccounts.length) failures.push("billing_accounts_missing");
  if (!restored.restored.auditEvents.length) failures.push("audit_events_missing");
  const authorityTestRuns = restored.restored.authorityTestRuns;
  const companyTaxSubmissions = restored.restored.companyTaxSubmissions;
  const authorityRunsById = new Map(authorityTestRuns.map((run: any) => [run.id, run]));
  const linkedAuthorityRunIds = new Set<string>();
  for (const submission of companyTaxSubmissions) {
    const authorityTestRunId = submission.authorityTestRunId
      ?? submission.authority_test_run_id;
    const authorityRun: any = authorityTestRunId
      ? authorityRunsById.get(authorityTestRunId)
      : null;
    if (!authorityTestRunId || !authorityRun) {
      fail("company_tax_authority_evidence_pair_missing");
      continue;
    }
    if (linkedAuthorityRunIds.has(authorityTestRunId)) {
      fail("company_tax_authority_evidence_pair_mismatch");
    }
    linkedAuthorityRunIds.add(authorityTestRunId);
    const receiptMetadata = submission.receiptMetadata ?? submission.receipt_metadata ?? {};
    const payloadHash = submission.payloadHash ?? submission.payload_hash;
    if (authorityRun.company_id !== restored.sourceCompanyId
      || authorityRun.obligation !== "skattemelding"
      || authorityRun.environment !== "test"
      || authorityRun.status !== "pending"
      || !payloadHash
      || authorityRun.payload_hash !== `sha256:${payloadHash}`
      || authorityRun.receipt_reference !== receiptMetadata.reference
      || authorityRun.archive_reference !== receiptMetadata.archiveReference) {
      fail("company_tax_authority_evidence_pair_mismatch");
    }
  }
  if (authorityTestRuns.some((run: any) => !linkedAuthorityRunIds.has(run.id))) {
    fail("company_tax_authority_evidence_pair_mismatch");
  }
  const decisions = restored.restored.corporateDecisions;
  const sets = restored.restored.corporateDocumentSets;
  const artifacts = restored.restored.corporateDocumentArtifacts;
  const events = restored.restored.corporateDocumentEvents;
  const finalizations = restored.restored.corporateDecisionFinalizations;
  if (decisions.length) {
    if (!sets.length) failures.push("corporate_document_sets_missing");
    if (!artifacts.length) failures.push("corporate_document_artifacts_missing");
    if (!events.length) failures.push("corporate_document_events_missing");
    if (events.some((event: any) => event.event_kind === "finalized") && !finalizations.length) {
      failures.push("corporate_decision_finalizations_missing");
    }
    const decisionIds = new Set(decisions.map((decision: any) => decision.id));
    const setIds = new Set(sets.map((set: any) => set.id));
    if (sets.some((set: any) => !decisionIds.has(set.decision_id))
      || artifacts.some((artifact: any) => !setIds.has(artifact.set_id))
      || events.some((event: any) => !decisionIds.has(event.decision_id) || !setIds.has(event.set_id))
      || finalizations.some((finalization: any) => !decisionIds.has(finalization.decision_id))) {
      failures.push("corporate_lifecycle_relationship_mismatch");
    }
    const documentsById = new Map(restored.restored.documents.map((document: any) => [document.id, document]));
    if (artifacts.some((artifact: any) => {
      const document: any = documentsById.get(artifact.document_id);
      return !document
        || !artifact.storage_key
        || document.storageKey !== artifact.storage_key
        || !/^[0-9a-f]{64}$/.test(String(artifact.content_sha256))
        || !Number.isSafeInteger(artifact.byte_length)
        || artifact.byte_length <= 0;
    })) {
      failures.push("corporate_artifact_object_reference_missing");
    }
  }
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
