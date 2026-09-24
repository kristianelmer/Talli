import type {
  AuthorityPermissionRow,
  AuthorityTestRunRow,
  BankSuggestionAcceptanceRow,
  BillingAccountRow,
  CompanyWorkspaceRow,
  CorporateDecisionFinalizationRow,
  CorporateDecisionRow,
  CorporateDocumentArtifactRow,
  CorporateDocumentEventRow,
  CorporateDocumentSetRow,
  DocumentRow,
  FilingPreviewRow,
  FilingReviewCommentRow,
  FilingSubmissionRow,
  HoldingActionRow,
  OpeningBalanceSetupRow,
  OpeningShareholderRow,
} from "./supabase/server";
import type {
  AcquisitionLotPresentation as InvestmentLotRow,
  InvestmentPositionPresentation as InvestmentPositionRow,
  ShareSaleAllocationPresentation,
  InvestmentCorrectionPresentation,
  InvestmentActivityPresentation,
} from "../../features/investments";
import type { DocumentBackupProjectionWire } from "../../features/documents";
import type { RecordedSupportedCorporateEventWire } from "../../features/corporate-governance";
import type { Rf1086ProductionArchiveSourceWire } from "../../features/shareholder-register-filing";

export type Rf1086ProductionArchive = Pick<Rf1086ProductionArchiveSourceWire,
  "companyId" | "incomeYear" | "approvals" | "productionSubmissions" | "productionEvents" | "feedbackArtifacts">;

/** Each retained RF receipt must resolve to the exact Documents-owned object. */
export function rf1086ArchiveReceiptsMatch(
  filing: Rf1086ProductionArchive, documents: DocumentBackupProjectionWire,
): boolean {
  if (filing.companyId !== documents.companyId || filing.incomeYear !== documents.incomeYear) return false;
  const objects = new Map(documents.objects.map(row => [row.documentId, row]));
  if (objects.size !== documents.objects.length) return false;
  return filing.feedbackArtifacts.every(receipt => {
    const object = objects.get(receipt.documentId);
    return receipt.companyId === filing.companyId && object !== undefined
      && object.contentSha256 === receipt.sha256 && object.byteLength === receipt.byteLength
      && object.contentType === receipt.contentType && Boolean(object.storageKey)
      && object.status === "stored" && object.removedAt === null;
  });
}

export type LedgerEntryRow = {
  id: string;
  company_id: string;
  setup_id: string | null;
  income_year: number;
  entry_type: string;
  memo: string;
  lines: unknown[];
  created_by: string;
  created_at: string;
};

export type AuditEventArchiveRow = {
  id: string;
  company_id: string;
  actor_id: string | null;
  category: string;
  action: string;
  message: string;
  created_at: string;
};

export function firstArchiveSourceError(
  results: readonly { error: unknown | null }[],
): unknown | null {
  return results.find(({ error }) => error !== null)?.error ?? null;
}

export function buildPersistedCompanyArchive(input: {
  company: CompanyWorkspaceRow;
  incomeYear: number;
  setups: OpeningBalanceSetupRow[];
  shareholders: OpeningShareholderRow[];
  ledgerEntries: LedgerEntryRow[];
  documents: DocumentRow[];
  documentBackupProjection?: DocumentBackupProjectionWire;
  holdingActions?: HoldingActionRow[];
  investmentPositions?: InvestmentPositionRow[];
  investmentLots?: InvestmentLotRow[];
  investmentLotAllocations?: ShareSaleAllocationPresentation[];
  investmentCorrections?: InvestmentCorrectionPresentation[];
  effectiveInvestmentActions?: InvestmentActivityPresentation[];
  bankSuggestionAcceptances?: BankSuggestionAcceptanceRow[];
  billingAccounts?: BillingAccountRow[];
  authorityPermissions?: AuthorityPermissionRow[];
  authorityTestRuns?: AuthorityTestRunRow[];
  auditEvents?: AuditEventArchiveRow[];
  reviewComments?: FilingReviewCommentRow[];
  filingPreviews: FilingPreviewRow[];
  filingSubmissions: FilingSubmissionRow[];
  rf1086Production?: Rf1086ProductionArchive;
  corporateDecisions?: CorporateDecisionRow[];
  corporateDocumentSets?: CorporateDocumentSetRow[];
  corporateDocumentArtifacts?: CorporateDocumentArtifactRow[];
  corporateDocumentEvents?: CorporateDocumentEventRow[];
  corporateDecisionFinalizations?: CorporateDecisionFinalizationRow[];
  supportedCorporateEvents?: RecordedSupportedCorporateEventWire[];
}) {
  const taxSettlementActions = (input.holdingActions ?? []).filter((action) => action.action_type === "tax_settlement");
  const investmentActivityHistory = (input.holdingActions ?? []).filter(
    (action) => [
      "share_purchase",
      "share_sale",
      "dividend_received",
      "fund_distribution_received",
    ].includes(action.action_type),
  );
  const taxSettlementLedgerIds = new Set(
    taxSettlementActions.map((action) => action.ledger_entry_id).filter((id): id is string => Boolean(id)),
  );

  const receipts = input.filingSubmissions
    .filter((submission) => submission.mode === "simulation" && submission.receipt_id)
    .map((submission) => ({
      filing: submission.filing,
      mode: submission.mode,
      adapterMode: submission.adapter_mode,
      status: submission.status,
      payloadHash: submission.payload_hash,
      idempotencyKey: submission.idempotency_key,
      submittedBy: submission.submitted_by,
      receiptId: submission.receipt_id,
      feedbackDocumentIds: submission.feedback_document_ids,
      feedbackItems: submission.feedback_items,
      receiptMetadata: submission.receipt_metadata,
      submittedPayloadReference: submission.submitted_payload_ref,
      submittedPayload: submission.submitted_payload,
      calls: submission.calls.map((call) => ({
        endpoint: call.endpoint,
        bodyHash: call.body_hash,
        idempotencyKey: call.idempotency_key,
        status: call.status,
      })),
    }));

  return {
    archiveType: "talli_company_year_archive",
    source: "supabase_persisted_workspace",
    exportedAt: new Date().toISOString(),
    company: input.company,
    incomeYear: input.incomeYear,
    openingBalanceSetups: input.setups,
    shareholders: input.shareholders,
    ledgerEntries: input.ledgerEntries,
    taxSettlements: taxSettlementActions.map((action) => ({
      id: action.id,
      incomeYear: action.income_year,
      actionDate: action.action_date,
      payload: action.payload,
      ledgerEntryId: action.ledger_entry_id,
      bankTransactionId: action.bank_transaction_id,
      documentId: action.document_id,
      riskLevel: action.risk_level,
      createdAt: action.created_at,
      ledgerEntry: action.ledger_entry_id
        ? input.ledgerEntries.find((entry) => entry.id === action.ledger_entry_id) ?? null
        : null,
      document: action.document_id
        ? input.documents.find((document) => document.id === action.document_id) ?? null
        : null,
    })),
    taxSettlementLedgerEntries: input.ledgerEntries.filter((entry) => taxSettlementLedgerIds.has(entry.id)),
    investmentActivityHistory,
    investmentPositions: input.investmentPositions ?? [],
    investmentLots: input.investmentLots ?? [],
    investmentLotAllocations: input.investmentLotAllocations ?? [],
    investmentCorrections: input.investmentCorrections ?? [],
    effectiveInvestmentActions: input.effectiveInvestmentActions ?? [],
    bankSuggestionAcceptances: input.bankSuggestionAcceptances ?? [],
    billingAccounts: input.billingAccounts ?? [],
    authorityPermissions: input.authorityPermissions ?? [],
    authorityTestRuns: (input.authorityTestRuns ?? []).map((run) => ({
      id: run.id,
      company_id: run.company_id,
      obligation: run.obligation,
      environment: run.environment,
      status: run.status,
      test_reference: run.test_reference,
      feedback_summary: run.feedback_summary,
      receipt_reference: run.receipt_reference,
      archive_reference: run.archive_reference,
      evidence_url: run.evidence_url,
      payload_hash: run.payload_hash,
      recorded_by: run.recorded_by,
      recorded_at: run.recorded_at,
    })),
    auditEvents: input.auditEvents ?? [],
    reviewComments: input.reviewComments ?? [],
    corporateDecisions: input.corporateDecisions ?? [],
    corporateDocumentSets: input.corporateDocumentSets ?? [],
    corporateDocumentArtifacts: (input.corporateDocumentArtifacts ?? []).map((artifact) => ({
      id: artifact.id,
      company_id: artifact.company_id,
      income_year: artifact.income_year,
      set_id: artifact.set_id,
      artifact_kind: artifact.artifact_kind,
      variant: artifact.variant,
      document_id: artifact.document_id,
      content_sha256: artifact.content_sha256,
      byte_length: artifact.byte_length,
      mime_type: artifact.mime_type,
      storage_key: artifact.storage_key,
      supersedes_artifact_id: artifact.supersedes_artifact_id,
      created_by: artifact.created_by,
      created_at: artifact.created_at,
    })),
    corporateDocumentEvents: input.corporateDocumentEvents ?? [],
    corporateDecisionFinalizations: input.corporateDecisionFinalizations ?? [],
    supportedCorporateEvents: (input.supportedCorporateEvents ?? []).map((event) => ({
      eventId: event.eventId,
      eventReference: event.eventReference,
      companyId: event.companyId,
      incomeYear: event.incomeYear,
      eventDate: event.eventDate,
      eventKind: event.eventKind,
      phase: event.phase,
      policyVersion: event.policyVersion,
      canonicalFacts: event.canonicalFacts,
      factsSha256: event.factsSha256,
      documentFacts: event.documentFacts,
      signedArtifactHashes: event.signedArtifactHashes,
      finalizationSha256: event.finalizationSha256,
      lifecycleState: event.lifecycleState,
      accountingEntryId: event.accountingEntryId,
      bankTransactionId: event.bankTransactionId,
      correctionOfEventId: event.correctionOfEventId,
      recordedAt: event.recordedAt,
    })),
    documents: input.documents.map((document) => ({
      id: document.id,
      incomeYear: document.income_year,
      documentType: document.document_type,
      name: document.name,
      linkedTo: document.linked_to,
      status: document.status,
      retentionYears: document.retention_years,
      storageKey: document.storage_key,
      createdAt: document.created_at,
    })),
    documentBackupProjection: input.documentBackupProjection ?? null,
    filingPreviews: input.filingPreviews.map((preview) => ({
      id: preview.id,
      filing: preview.filing,
      status: preview.status,
      preview: preview.preview,
      hovedskjemaXml: preview.hovedskjema_xml,
      underskjemaXml: preview.underskjema_xml,
      source: preview.source,
      createdAt: preview.created_at,
    })),
    rf1086Submissions: input.filingSubmissions
      .filter((submission) => submission.filing === "aksjonærregisteroppgaven")
      .map((submission) => ({
        id: submission.id,
        previewId: submission.preview_id,
        incomeYear: submission.income_year,
        mode: submission.mode,
        adapterMode: submission.adapter_mode,
        status: submission.status,
        payloadHash: submission.payload_hash,
        idempotencyKey: submission.idempotency_key,
        receiptId: submission.receipt_id,
        feedbackDocumentIds: submission.feedback_document_ids,
        feedbackItems: submission.feedback_items,
        receiptMetadata: submission.receipt_metadata,
        submittedPayloadReference: submission.submitted_payload_ref,
        submittedPayload: submission.submitted_payload,
        submittedBy: submission.submitted_by,
        createdAt: submission.created_at,
        updatedAt: submission.updated_at,
      })),
    // Canonical immutable records, separate from historical simulation shapes.
    rf1086Production: input.rf1086Production ?? null,
    rf1086ProductionEvidenceAvailability: input.rf1086Production ? "included" : "unavailable",
    companyTaxSubmissions: input.filingSubmissions
      .filter(
        (submission) => submission.filing === "skattemelding for AS" && submission.mode === "test_authority",
      )
      .map((submission) => ({
        id: submission.id,
        authorityTestRunId: submission.authority_test_run_id,
        incomeYear: submission.income_year,
        mode: submission.mode,
        adapterMode: submission.adapter_mode,
        status: submission.status,
        payloadHash: submission.payload_hash,
        idempotencyKey: submission.idempotency_key,
        receiptId: submission.receipt_id,
        feedbackDocumentIds: submission.feedback_document_ids,
        feedbackItems: submission.feedback_items,
        receiptMetadata: submission.receipt_metadata,
        submittedPayloadReference: submission.submitted_payload_ref,
        submittedPayload: null,
        calls: submission.calls.map((call) => ({
          endpoint: call.endpoint,
          bodyHash: call.body_hash,
          idempotencyKey: call.idempotency_key,
          status: call.status,
        })),
        submittedBy: submission.submitted_by,
        createdAt: submission.created_at,
        updatedAt: submission.updated_at,
      })),
    readinessReports: input.filingPreviews.map((preview) => ({
      filing: preview.filing,
      status: preview.status,
      issues: preview.issues,
      source: preview.source,
    })),
    simulatedReceipts: receipts,
    missingDocumentIds: input.documents.filter((document) => document.status.startsWith("missing")).map((document) => document.id),
  };
}
