import type {
  BillingAccountRow,
  CompanyWorkspaceRow,
  DocumentRow,
  FilingPreviewRow,
  FilingSubmissionRow,
  HoldingActionRow,
  OpeningBalanceSetupRow,
  OpeningShareholderRow,
} from "./supabase/server";

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

export function buildPersistedCompanyArchive(input: {
  company: CompanyWorkspaceRow;
  incomeYear: number;
  setups: OpeningBalanceSetupRow[];
  shareholders: OpeningShareholderRow[];
  ledgerEntries: LedgerEntryRow[];
  documents: DocumentRow[];
  holdingActions?: HoldingActionRow[];
  billingAccounts?: BillingAccountRow[];
  filingPreviews: FilingPreviewRow[];
  filingSubmissions: FilingSubmissionRow[];
}) {
  const taxSettlementActions = (input.holdingActions ?? []).filter((action) => action.action_type === "tax_settlement");
  const taxSettlementLedgerIds = new Set(
    taxSettlementActions.map((action) => action.ledger_entry_id).filter((id): id is string => Boolean(id)),
  );

  const receipts = input.filingSubmissions
    .filter((submission) => submission.mode === "simulation" && submission.receipt_id)
    .map((submission) => ({
      filing: submission.filing,
      mode: submission.mode,
      status: submission.status,
      receiptId: submission.receipt_id,
      feedbackDocumentIds: submission.feedback_document_ids,
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
    billingAccounts: input.billingAccounts ?? [],
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
