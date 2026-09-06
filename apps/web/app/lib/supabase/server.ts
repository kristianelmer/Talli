import { annualBillingRecovery, loadAnnualSupportPurchases, type AnnualSupportPageWire } from "../../../features/billing";
import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import {
  createClient,
  type SupabaseClient,
  type User,
} from "@supabase/supabase-js";
import type { YearEndInterviewAnswers } from "../annual-data";
import type {
  AnnualReadinessIssue,
  AnnualReadinessStatus,
} from "../annual-readiness";
import type { CompanyCancellationRow } from "../cancellation";
import type { LaunchSignoffKey, LaunchSignoffStatus } from "../launch-signoff";
import { buildOperatorSupportSummaries, operatorReadRecovery, type OperatorReadRecovery } from "../operator-support";
import type {
  Rf1086ReceiptMetadata,
  Rf1086SubmittedPayloadReference,
  Rf1086SubmittedPayloadSnapshot,
} from "../rf1086-submission";
import type { SystemUserRequestStatus } from "../system-user-requests";
import {
  loadBankSuggestionAcceptances,
  loadBankTransactions,
  presentBankSuggestionAcceptances,
  presentBankTransactions,
  type BankSuggestionAcceptancePresentation,
  type BankTransactionPresentation,
} from "../../../features/banking";
import {
  loadOperatorContext,
  readOperatorSupportCase,
  type CompanyRegistryPresentation,
} from "../../../features/company-access";
import {
  loadLedgerEntries,
  loadLedgerPeriodLocks,
  loadOpeningSnapshots,
  presentLedgerEntries,
  presentLedgerPeriodLocks,
  presentOpeningSnapshots,
  type LedgerEntryPresentation,
  type LedgerPeriodLockPresentation,
} from "../../../features/ledger";
import {
  listCorporateDecisionLifecycle,
  readCorporateDecisionReadiness,
} from "../../../features/corporate-governance";
import {
  listDocuments,
  presentDocument,
} from "../../../features/documents";

async function backendAccessToken(supabase: SupabaseClient) {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

async function backendOperatorSession(supabase: SupabaseClient) {
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken) return null;
  try {
    return {
      accessToken,
      operator: await loadOperatorContext(accessToken),
    };
  } catch {
    return null;
  }
}

export type CompanyWorkspaceRow = CompanyRegistryPresentation & {
  role?: "owner" | "reviewer" | "read_only";
};

export type LaunchSignoffRow = {
  key: LaunchSignoffKey;
  status: LaunchSignoffStatus;
  reviewer: string;
  reviewed_at: string;
  evidence_link: string;
  decision: string;
  recorded_by: string;
  updated_at: string;
};

export type AuthorityOperationRow = {
  id: string;
  operation: "register_rf1086_system" | "set_rf1086_systembruker_callback";
  actor_id: string;
  status: "started" | "succeeded" | "failed" | "conflict";
  request_hash: string;
  result_code: string;
  authority_http_status: number | null;
  metadata: {
    systemId?: string;
    clientId?: string;
    right?: string;
    callbackPath?: string;
  };
  created_at: string;
  completed_at: string | null;
};

export type DocumentRow = {
  id: string;
  company_id: string;
  income_year: number;
  document_type: string;
  name: string;
  linked_to: string;
  status: string;
  retention_years: number;
  storage_key: string;
  content_sha256?: string | null;
  created_by: string;
  created_at: string;
  removed_at: string | null;
  removed_by: string | null;
  removal_reason: string | null;
};

export type OpeningBalanceSetupRow = {
  id: string;
  company_id: string;
  income_year: number;
  bank_balance: number;
  share_capital: number;
  share_count: number;
  nominal_value: number;
  locked_at: string;
  created_by: string;
};

export type PeriodLockRow = LedgerPeriodLockPresentation;

export type AnnualDataRow = {
  id: string;
  company_id: string;
  income_year: number;
  answers: YearEndInterviewAnswers;
  confirmations: string[];
  no_activity_confirmed: boolean;
  annual_full_time_equivalents: number | null;
  completed_by: string;
  completed_at: string;
  updated_by: string;
  updated_at: string;
};

export type CorporateDecisionRow = {
  id: string;
  company_id: string;
  income_year: number;
  decision_kind: "owner_dividend" | "annual_close";
  annual_close_source_id: string;
  source_hash: string;
  canonical_input: Record<string, unknown>;
  decision_hash: string;
  supersedes_decision_id: string | null;
  created_by: string;
  created_at: string;
};

export type CorporateDocumentSetRow = {
  id: string;
  company_id: string;
  income_year: number;
  decision_id: string;
  template_family: string;
  template_version: string;
  decision_hash: string;
  supersedes_set_id: string | null;
  created_by: string;
  created_at: string;
};

export type CorporateDocumentArtifactRow = {
  id: string;
  company_id: string;
  income_year: number;
  set_id: string;
  artifact_kind: string;
  variant: "unsigned" | "signed_owner_attested";
  document_id: string;
  content_sha256: string;
  byte_length: number;
  mime_type: "application/pdf";
  storage_key: string;
  supersedes_artifact_id: string | null;
  created_by: string;
  created_at: string;
};

export type CorporateDocumentEventRow = {
  id: string;
  company_id: string;
  income_year: number;
  decision_id: string;
  set_id: string;
  artifact_id: string | null;
  event_kind: string;
  actor_id: string;
  occurred_at: string;
  decision_hash: string;
  content_sha256: string | null;
  metadata: Record<string, unknown>;
  idempotency_key: string;
  created_at: string;
};

export type CorporateDecisionFinalizationRow = {
  id: string;
  company_id: string;
  income_year: number;
  decision_id: string;
  finalization_kind: "owner_dividend_declared" | "annual_close_adopted";
  holding_action_id: string | null;
  ledger_entry_id: string | null;
  annual_close_source_id: string | null;
  decision_hash: string;
  signed_artifact_hashes: Record<string, string>;
  accounting_policy_version: string | null;
  created_by: string;
  created_at: string;
};

export type OpeningShareholderRow = {
  id: string;
  setup_id: string;
  company_id: string;
  name: string;
  shareholder_kind: "norwegian_person" | "norwegian_company";
  national_id: string | null;
  org_number: string | null;
  share_count: number;
};

export type FilingPreviewRow = {
  id: string;
  company_id: string;
  setup_id: string | null;
  income_year: number;
  filing: string;
  status: "ready" | "blocked" | "warning";
  issues: { level: string; code: string; message: string }[];
  preview: string;
  hovedskjema_xml: string | null;
  underskjema_xml: Record<string, string>;
  source: string;
  created_at: string;
};

export type FilingSubmissionCall = {
  endpoint: string;
  body_hash: string;
  idempotency_key: string | null;
  status: string;
  created_at: string;
};

export type FilingSubmissionFeedbackItem = {
  severity: "accepted" | "error" | "warning";
  code: string;
  message: string;
  documentId: string | null;
};

export type CompanyTaxReturnReceiptMetadata = {
  authority: "skatteetaten";
  receiptId: string;
  status: "feedback_ready";
  receivedAt: string;
  feedbackDocumentIds: string[];
  dataType: "tilbakemelding";
  contentType: "application/xml" | "text/xml";
  byteLength: number;
  contentSha256: string;
  reference: string;
  archiveReference: string;
  processEndedAt: string;
  archivedAt: string;
};

export type CompanyTaxReturnPayloadReference = {
  companyOrgNumber: string;
  incomeYear: number;
  envelopeDataId: string;
  archiveReference: string;
  payloadHash: string;
  skattemeldingHash: string;
  naeringsspesifikasjonHash: string;
  validationEnvelopeHash: string;
  submissionEnvelopeHash: string;
  currentDocumentReferenceHash: string;
  storedAt: string;
};

export type FilingSubmissionRow = {
  id: string;
  preview_id: string | null;
  authority_test_run_id: string | null;
  company_id: string;
  income_year: number;
  filing: string;
  mode: "simulation" | "test_authority";
  adapter_mode: "simulation" | "test_authority" | "production";
  payload_hash: string | null;
  idempotency_key: string | null;
  status: string;
  calls: FilingSubmissionCall[];
  receipt_id: string | null;
  feedback_document_ids: string[];
  feedback_items: FilingSubmissionFeedbackItem[];
  receipt_metadata:
    Rf1086ReceiptMetadata | CompanyTaxReturnReceiptMetadata | null;
  submitted_payload_ref:
    Rf1086SubmittedPayloadReference | CompanyTaxReturnPayloadReference | null;
  submitted_payload: Rf1086SubmittedPayloadSnapshot | null;
  authority_confirmed_at: string | null;
  preview_confirmed_at: string | null;
  created_at: string;
  updated_at: string;
  submitted_by: string | null;
};

export type ProductionPilotEntitlementRow = {
  id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: "aksjonaerregisteroppgaven";
  case_profile: "rf1086_no_activity_v1";
  status: "pending" | "active" | "suspended" | "completed" | "revoked";
  billing_exempt: boolean;
  system_user_request_id: string | null;
  system_user_external_reference: string;
  starts_at: string;
  expires_at: string;
  evidence_reference: string;
  approved_by: string;
  created_at: string;
  updated_at: string;
};

export type SystemUserRequestRow = {
  id: string;
  company_id: string;
  initiating_owner_user_id: string;
  obligation: "aksjonaerregisteroppgaven";
  external_ref: string;
  altinn_request_id: string | null;
  status: SystemUserRequestStatus;
  confirm_url: string | null;
  preflight_verified_at: string | null;
  failure_code: string | null;
  operator_evidence_id: string | null;
  requested_at: string | null;
  last_status_checked_at: string | null;
  accepted_at: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export type FilingApprovalSnapshotRow = {
  id: string;
  entitlement_id: string;
  preview_id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: "aksjonaerregisteroppgaven";
  case_profile: "rf1086_no_activity_v1";
  adapter_version: string;
  payload_hash: string;
  manifest_hash: string;
  manifest: Record<string, unknown>;
  approved_by: string;
  approved_at: string;
  invalidated_at: string | null;
  invalidation_reason: string | null;
};

export type ProductionFilingSubmissionRow = {
  id: string;
  approval_id: string;
  entitlement_id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: "aksjonaerregisteroppgaven";
  case_profile: "rf1086_no_activity_v1";
  payload_hash: string;
  adapter_version: string;
  environment: "production";
  status:
    | "approved"
    | "sending"
    | "received"
    | "processing"
    | "accepted"
    | "rejected"
    | "action_required"
    | "unknown";
  authority_references: Record<string, string>;
  failure_class: string | null;
  supersedes_submission_id: string | null;
  submitted_by: string;
  feedback_state:
    | "sent"
    | "processing"
    | "accepted"
    | "rejected"
    | "action_required"
    | "unknown";
  feedback_artifact_count: number;
  feedback_last_checked_at: string | null;
  feedback_last_changed_at: string | null;
  feedback_safe_error_code: string | null;
  feedback_correlation_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ProductionFeedbackArtifactRow = {
  id: string;
  company_id: string;
  submission_id: string;
  document_id: string;
  content_type:
    | "application/xml"
    | "text/xml"
    | "application/pdf"
    | "text/plain"
    | "application/octet-stream";
  byte_length: number;
  sha256: string;
  retrieved_at: string;
  classification: "accepted" | "rejected" | "action_required";
};

export type FilingOverrideRow = {
  id: string;
  preview_id: string | null;
  company_id: string;
  income_year: number;
  filing: string;
  field_target: string;
  old_value: string;
  new_value: string;
  reason: string;
  risk_level: "advisory" | "warning" | "block";
  owner_confirmed_by: string;
  owner_confirmed_at: string;
  created_by: string;
  created_at: string;
};

export type FilingReadinessSnapshotRow = {
  id: string;
  company_id: string;
  income_year: number;
  obligation: "aksjonaerregisteroppgaven" | "skattemelding" | "aarsregnskap";
  status: AnnualReadinessStatus;
  ready: boolean;
  hard_blocks: AnnualReadinessIssue[];
  warnings: AnnualReadinessIssue[];
  accepted_warnings: AnnualReadinessIssue[];
  evaluated_at: string;
  created_by: string;
  updated_at: string;
};

export type LedgerEntryRow = LedgerEntryPresentation;

export type BankTransactionRow = BankTransactionPresentation;

export type BankSuggestionAcceptanceRow = BankSuggestionAcceptancePresentation;

export type HoldingActionRow = {
  id: string;
  company_id: string;
  income_year: number;
  action_type:
    | "dividend_received"
    | "share_purchase"
    | "share_sale"
    | "fund_distribution_received"
    | "dividend_to_owner"
    | "shareholder_loan"
    | "tax_settlement";
  action_date: string;
  payload: Record<string, unknown>;
  ledger_entry_id: string | null;
  bank_transaction_id: string | null;
  document_id: string | null;
  risk_level: "ready" | "warning" | "block";
  blocker_code: string | null;
  created_by: string;
  created_at: string;
};

export type FilingReviewCommentRow = {
  id: string;
  preview_id: string;
  company_id: string;
  target: string;
  severity: "advisory" | "hard_block";
  body: string;
  created_by: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
};

export type BillingAccountRow = {
  company_id: string;
  pricing_plan: "founder" | "standard";
  monthly_nok: number;
  filing_package_nok: number;
  founder_cohort_number: number | null;
  subscription_active: boolean;
  filing_package_paid: boolean;
  supported_case: boolean;
  refund_eligible: boolean;
  refund_completed: boolean;
  no_charge_reason: string | null;
  provider_customer_ref: string | null;
  subscription_provider_ref: string | null;
  filing_package_payment_ref: string | null;
  refund_provider_ref: string | null;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type BillingPaymentEventRow = {
  id: string;
  company_id: string;
  provider: string;
  provider_reference: string;
  idempotency_key: string;
  kind:
    "subscription" | "subscription_cancellation" | "filing_package" | "refund";
  status: "created" | "succeeded" | "failed" | "refunded" | "canceled";
  amount_nok: number;
  income_year: number | null;
  payload: Record<string, unknown>;
  created_by: string;
  created_at: string;
};

export type AuthorityPermissionRow = {
  id: string;
  company_id: string;
  obligation: "aksjonaerregisteroppgaven" | "skattemelding" | "aarsregnskap";
  submitter_user_id: string;
  confirmed_by: string;
  confirmed_at: string;
  production_enabled: boolean;
  updated_at: string;
};

export type AuthorityTestRunRow = {
  id: string;
  company_id: string;
  obligation: "aksjonaerregisteroppgaven" | "skattemelding" | "aarsregnskap";
  environment: "test" | "manual_evidence";
  status: "accepted" | "rejected" | "blocked" | "pending";
  test_reference: string;
  feedback_summary: string;
  receipt_reference: string | null;
  archive_reference: string | null;
  evidence_url: string | null;
  payload_hash: string | null;
  recorded_by: string;
  recorded_at: string;
};

export type NotificationOutboxRow = {
  id: string;
  company_id: string;
  recipient_email: string;
  template: string;
  payload: Record<string, unknown>;
  status: "queued" | "sent" | "failed";
  created_by: string;
  created_at: string;
};

export function hasSupabaseEnv() {
  return Boolean(process.env.SUPABASE_URL && process.env.SUPABASE_ANON_KEY);
}

export async function createSupabaseServerClient() {
  const cookieStore = await cookies();
  return createServerClient(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
        } catch {
          // Server Components cannot set cookies. Server Actions can.
        }
      },
    },
  });
}

export function createSupabaseServiceRoleClient() {
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
    throw new Error("Supabase service role is not configured for production filing.");
  }
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function getCurrentUser() {
  if (!hasSupabaseEnv()) {
    return null;
  }
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}

/**
 * True when an owner must still confirm their email before entering the app.
 * OAuth sign-ins (e.g. Google) arrive with a verified identity, so they are
 * never gated even if `email_confirmed_at` is momentarily absent.
 */
export function needsEmailVerification(user: User): boolean {
  if (user.email_confirmed_at) {
    return false;
  }
  const providers =
    user.app_metadata?.providers ??
    (user.app_metadata?.provider ? [user.app_metadata.provider] : []);
  const hasOAuthIdentity = providers.some((provider) => provider && provider !== "email");
  return !hasOAuthIdentity;
}

/**
 * Resolves the current user's support-operator role. Used to server-side guard
 * the (operator) route group and to conditionally surface operator navigation.
 */
export async function getOperatorContext() {
  const user = await getCurrentUser();
  if (!user) {
    return { user: null, isOperator: false, isAdminOperator: false };
  }
  const supabase = await createSupabaseServerClient();
  const operator = (await backendOperatorSession(supabase))?.operator ?? null;
  const isOperator = Boolean(operator);
  return { user, isOperator, isAdminOperator: operator?.role === "admin" };
}

/** Page entry only: retain rejected-session recovery before protected loaders run. */
export async function getOperatorPageAccess() {
  try {
    if (!hasSupabaseEnv()) return { recovery: "unavailable" as const };
    const user = await getCurrentUser();
    if (!user) return { recovery: "sign-in" as const };
    const accessToken = await backendAccessToken(await createSupabaseServerClient());
    if (!accessToken) return { recovery: "sign-in" as const };
    const operator = await loadOperatorContext(accessToken);
    return { recovery: null, user, operator };
  } catch (error) {
    return { recovery: operatorReadRecovery(error) };
  }
}

export async function listDocumentsForCompanies(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { documents: [] as DocumentRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken) return { documents: [] as DocumentRow[], error: "Innlogging kreves." };
  try {
    const pages = await Promise.all(companyIds.map((companyId) => listDocuments(accessToken, companyId)));
    const documents = pages
      .flatMap((page) => page.documents)
      .filter((document) => document.status !== "removed")
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
      .map(presentDocument);
    return { documents, error: null };
  } catch {
    return { documents: [] as DocumentRow[], error: "Dokumentene kunne ikke hentes." };
  }
}

export async function listOpeningSetups(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return {
      setups: [] as OpeningBalanceSetupRow[],
      shareholders: [] as OpeningShareholderRow[],
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken) {
    return {
      setups: [] as OpeningBalanceSetupRow[],
      shareholders: [] as OpeningShareholderRow[],
      error: "Innlogging kreves.",
    };
  }
  try {
    const projection = presentOpeningSnapshots(
      await loadOpeningSnapshots(accessToken, companyIds),
    );
    return { ...projection, error: null };
  } catch {
    return {
      setups: [] as OpeningBalanceSetupRow[],
      shareholders: [] as OpeningShareholderRow[],
      error: "Åpningsopplysningene kunne ikke hentes.",
    };
  }
}

export async function listPeriodLocks(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { locks: [] as PeriodLockRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken)
    return { locks: [] as PeriodLockRow[], error: "Innlogging kreves." };
  try {
    const locks = await loadLedgerPeriodLocks(accessToken, companyIds);
    return { locks: presentLedgerPeriodLocks(locks), error: null };
  } catch {
    return {
      locks: [] as PeriodLockRow[],
      error: "Periodesperrer kunne ikke lastes.",
    };
  }
}

export async function listAnnualData(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { annualData: [] as AnnualDataRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("annual_data")
    .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, annual_full_time_equivalents, completed_by, completed_at, updated_by, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  if (error?.message.includes("annual_full_time_equivalents")) {
    const fallback = await supabase
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, completed_by, completed_at, updated_by, updated_at")
      .in("company_id", companyIds)
      .order("updated_at", { ascending: false });
    return {
      annualData: (fallback.data ?? []).map((item) => ({
        ...item,
        annual_full_time_equivalents: null,
      })) as AnnualDataRow[],
      error: fallback.error?.message ?? null,
    };
  }

  return {
    annualData: (data ?? []) as AnnualDataRow[],
    error: error?.message ?? null,
  };
}

export async function listCorporateDocumentLifecycle(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return {
      corporateDecisions: [] as CorporateDecisionRow[],
      corporateDocumentSets: [] as CorporateDocumentSetRow[],
      corporateDocumentArtifacts: [] as CorporateDocumentArtifactRow[],
      corporateDocumentEvents: [] as CorporateDocumentEventRow[],
      corporateDecisionFinalizations: [] as CorporateDecisionFinalizationRow[],
      corporateDecisionReadiness: [],
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken) {
    return {
      corporateDecisions: [] as CorporateDecisionRow[],
      corporateDocumentSets: [] as CorporateDocumentSetRow[],
      corporateDocumentArtifacts: [] as CorporateDocumentArtifactRow[],
      corporateDocumentEvents: [] as CorporateDocumentEventRow[],
      corporateDecisionFinalizations: [] as CorporateDecisionFinalizationRow[],
      corporateDecisionReadiness: [],
      error: "Innlogging kreves.",
    };
  }
  try {
    const [lifecycle, ...documentPages] = await Promise.all([
      listCorporateDecisionLifecycle(accessToken, companyIds),
      ...companyIds.map((companyId) => listDocuments(accessToken, companyId)),
    ]);
    const documentsById = new Map(
      documentPages.flatMap((page) => page.documents).map((document) => [
        document.id,
        document,
      ]),
    );
    const artifacts = lifecycle.corporateDocumentArtifacts.map((artifact) => {
      const document = documentsById.get(artifact.document_id);
      return {
        ...artifact,
        storage_key: document?.storageKey ?? "",
      };
    });
    const corporateDecisionReadiness = await Promise.all(
      lifecycle.corporateDecisions.map((decision) => readCorporateDecisionReadiness(
        accessToken,
        {
          companyId: decision.company_id,
          incomeYear: decision.income_year,
          decisionKind: decision.decision_kind,
        },
      )),
    );
    const missingDocument = artifacts.some((artifact) => !artifact.storage_key);
    return {
      corporateDecisions: lifecycle.corporateDecisions as CorporateDecisionRow[],
      corporateDocumentSets: lifecycle.corporateDocumentSets as CorporateDocumentSetRow[],
      corporateDocumentArtifacts: artifacts as CorporateDocumentArtifactRow[],
      corporateDocumentEvents: lifecycle.corporateDocumentEvents as CorporateDocumentEventRow[],
      corporateDecisionFinalizations: lifecycle.corporateDecisionFinalizations as CorporateDecisionFinalizationRow[],
      corporateDecisionReadiness,
      error: missingDocument
        ? "Selskapsdokumentenes lagringsbevis er ufullstendig."
        : null,
    };
  } catch (error) {
    return {
      corporateDecisions: [] as CorporateDecisionRow[],
      corporateDocumentSets: [] as CorporateDocumentSetRow[],
      corporateDocumentArtifacts: [] as CorporateDocumentArtifactRow[],
      corporateDocumentEvents: [] as CorporateDocumentEventRow[],
      corporateDecisionFinalizations: [] as CorporateDecisionFinalizationRow[],
      corporateDecisionReadiness: [],
      error: error instanceof Error ? error.message : "Selskapsbeslutningene kunne ikke leses.",
    };
  }
}

export async function listFilingPreviews(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { previews: [] as FilingPreviewRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("filing_previews")
    .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    previews: (data ?? []) as FilingPreviewRow[],
    error: error?.message ?? null,
  };
}

export async function listFilingSubmissions(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { submissions: [] as FilingSubmissionRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("filing_submissions")
    .select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    submissions: (data ?? []) as FilingSubmissionRow[],
    error: error?.message ?? null,
  };
}

function productionPilotSchemaUnavailable(
  errors: Array<{ code?: string; message?: string } | null>,
) {
  return errors.some(
    (error) =>
      error != null &&
      (error.code === "PGRST205" ||
        error.code === "42P01" ||
        /production_(?:pilot|filing|feedback)|filing_approval_snapshots/iu.test(
          error.message ?? "",
        )),
  );
}

export async function listSystemUserRequests(
  supabase: SupabaseClient,
  companyIds: string[],
): Promise<SystemUserRequestRow[]> {
  if (companyIds.length === 0) return [];

  const { data, error } = await supabase
    .from("system_user_requests")
    .select("id,company_id,initiating_owner_user_id,obligation,external_ref,altinn_request_id,status,confirm_url,preflight_verified_at,failure_code,operator_evidence_id,requested_at,last_status_checked_at,accepted_at,created_at,updated_at,resolved_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  if (error) throw error;
  return (data ?? []) as SystemUserRequestRow[];
}

export async function listProductionFilingState(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return {
      productionPilotEntitlements: [] as ProductionPilotEntitlementRow[],
      filingApprovalSnapshots: [] as FilingApprovalSnapshotRow[],
      productionFilingSubmissions: [] as ProductionFilingSubmissionRow[],
      productionFeedbackArtifacts: [] as ProductionFeedbackArtifactRow[],
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const [approvals, submissions, artifacts] = await Promise.all([
    supabase.from("filing_approval_snapshots").select("*").in("company_id", companyIds).order("approved_at", { ascending: false }),
    supabase.from("production_filing_submissions")
      .select("id,approval_id,entitlement_id,company_id,user_id,income_year,obligation,case_profile,payload_hash,adapter_version,environment,status,supersedes_submission_id,submitted_by,feedback_state,feedback_artifact_count,feedback_last_checked_at,feedback_last_changed_at,feedback_safe_error_code,feedback_correlation_id,created_at,updated_at")
      .in("company_id", companyIds)
      .order("updated_at", { ascending: false }),
    supabase.from("production_feedback_artifacts")
      .select("id,company_id,submission_id,document_id,content_type,byte_length,sha256,retrieved_at,classification")
      .in("company_id", companyIds)
      .order("retrieved_at", { ascending: false }),
  ]);
  const errors = [approvals.error, submissions.error, artifacts.error];
  const rolloutSchemaPending = process.env.TALLI_RF1086_PRODUCTION_ENABLED !== "true"
    && productionPilotSchemaUnavailable(errors);
  return {
    productionPilotEntitlements: [] as ProductionPilotEntitlementRow[],
    filingApprovalSnapshots: (approvals.data ?? []) as FilingApprovalSnapshotRow[],
    productionFilingSubmissions: (submissions.data ?? []) as ProductionFilingSubmissionRow[],
    productionFeedbackArtifacts: (artifacts.data ?? []) as ProductionFeedbackArtifactRow[],
    error: rolloutSchemaPending
      ? null
      : approvals.error?.message ?? submissions.error?.message ?? artifacts.error?.message ?? null,
  };
}

export async function listFilingOverrides(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { overrides: [] as FilingOverrideRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("filing_overrides")
    .select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by, owner_confirmed_at, created_by, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    overrides: (data ?? []) as FilingOverrideRow[],
    error: error?.message ?? null,
  };
}

export async function listBankTransactions(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { transactions: [] as BankTransactionRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken)
    return {
      transactions: [] as BankTransactionRow[],
      error: "Innlogging kreves.",
    };
  try {
    const transactions = presentBankTransactions(
      await loadBankTransactions(accessToken, companyIds),
    ).sort((left, right) =>
      right.transaction_date.localeCompare(left.transaction_date),
    );
    return { transactions, error: null };
  } catch {
    return {
      transactions: [] as BankTransactionRow[],
      error: "Kunne ikke laste bankbevegelser.",
    };
  }
}

export async function listBankSuggestionAcceptances(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { acceptances: [] as BankSuggestionAcceptanceRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken)
    return {
      acceptances: [] as BankSuggestionAcceptanceRow[],
      error: "Innlogging kreves.",
    };
  try {
    const acceptances = presentBankSuggestionAcceptances(
      await loadBankSuggestionAcceptances(accessToken, companyIds),
    ).sort((left, right) => right.accepted_at.localeCompare(left.accepted_at));
    return { acceptances, error: null };
  } catch {
    return {
      acceptances: [] as BankSuggestionAcceptanceRow[],
      error: "Kunne ikke laste bankforslag.",
    };
  }
}

export async function listLedgerEntries(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { entries: [] as LedgerEntryRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const accessToken = await backendAccessToken(supabase);
  if (!accessToken)
    return { entries: [] as LedgerEntryRow[], error: "Innlogging kreves." };
  try {
    const entries = await loadLedgerEntries(accessToken, companyIds);
    return { entries: presentLedgerEntries(entries), error: null };
  } catch {
    return {
      entries: [] as LedgerEntryRow[],
      error: "Hovedboken kunne ikke lastes.",
    };
  }
}

export async function listFilingReadinessSnapshots(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { readinessSnapshots: [] as FilingReadinessSnapshotRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("filing_readiness_snapshots")
    .select("id, company_id, income_year, obligation, status, ready, hard_blocks, warnings, accepted_warnings, evaluated_at, created_by, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    readinessSnapshots: (data ?? []) as FilingReadinessSnapshotRow[],
    error: error?.message ?? null,
  };
}

export async function listFilingReviewComments(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { comments: [] as FilingReviewCommentRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("filing_review_comments")
    .select("id, preview_id, company_id, target, severity, body, created_by, acknowledged_by, acknowledged_at, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    comments: (data ?? []) as FilingReviewCommentRow[],
    error: error?.message ?? null,
  };
}

export async function listAuthorityPermissions(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { authorityPermissions: [] as AuthorityPermissionRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("authority_permissions")
    .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    authorityPermissions: (data ?? []) as AuthorityPermissionRow[],
    error: error?.message ?? null,
  };
}

export async function listAuthorityTestRuns(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { authorityTestRuns: [] as AuthorityTestRunRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("authority_test_runs")
    .select("id, company_id, obligation, environment, status, test_reference, feedback_summary, receipt_reference, archive_reference, evidence_url, payload_hash, recorded_by, recorded_at")
    .in("company_id", companyIds)
    .order("recorded_at", { ascending: false });

  return {
    authorityTestRuns: (data ?? []) as AuthorityTestRunRow[],
    error: error?.message ?? null,
  };
}

export async function listNotificationOutbox(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { notifications: [] as NotificationOutboxRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("notification_outbox")
    .select("id, company_id, recipient_email, template, payload, status, created_by, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    notifications: (data ?? []) as NotificationOutboxRow[],
    error: error?.message ?? null,
  };
}

export async function listLaunchSignoffs(actorId?: string | null) {
  if (!hasSupabaseEnv() || !actorId) {
    return {
      launchSignoffs: [] as LaunchSignoffRow[],
      isOperator: false,
      isAdminOperator: false,
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const operator = (await backendOperatorSession(supabase))?.operator ?? null;
  const isOperator = Boolean(operator);
  const isAdminOperator = operator?.role === "admin";
  if (!isOperator) {
    return {
      launchSignoffs: [] as LaunchSignoffRow[],
      isOperator,
      isAdminOperator,
      error: null,
    };
  }
  const { data, error } = await supabase
    .from("launch_signoffs")
    .select(
      "key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by, updated_at",
    )
    .order("updated_at", { ascending: false });

  return {
    launchSignoffs: (data ?? []) as LaunchSignoffRow[],
    isOperator,
    isAdminOperator,
    error: error?.message ?? null,
  };
}

export async function listAuthorityOperations(actorId?: string | null) {
  if (!hasSupabaseEnv() || !actorId) {
    return {
      operations: [] as AuthorityOperationRow[],
      isAdminOperator: false,
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const operator = (await backendOperatorSession(supabase))?.operator ?? null;
  if (!operator || operator.role !== "admin") {
    return {
      operations: [] as AuthorityOperationRow[],
      isAdminOperator: false,
      error: null,
    };
  }
  const { data, error } = await supabase
    .from("authority_operations")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(10);
  return {
    operations: (data ?? []) as AuthorityOperationRow[],
    isAdminOperator: true,
    error: error ? "authority_operations_query_failed" : null,
  };
}

export async function readOperatorSupportDashboard(
  caseId: string,
  actorId?: string | null,
  beforePurchaseId?: string,
) {
  const emptyAnnual = {
    annualBilling: null as AnnualSupportPageWire | null,
    annualBillingError: null as ReturnType<typeof annualBillingRecovery> | null,
  };
  const failed = (recovery: OperatorReadRecovery, isOperator = false) => ({
    summaries: [], isOperator, error: "support_case_read_failed", ...emptyAnnual, recovery,
  });
  if (!hasSupabaseEnv()) return failed("unavailable");
  if (!actorId) return failed("sign-in");
  let isOperator = false;
  let accessToken: string;
  let snapshot: Awaited<ReturnType<typeof readOperatorSupportCase>>;
  try {
    const token = await backendAccessToken(await createSupabaseServerClient());
    if (!token) return failed("sign-in");
    accessToken = token;
    await loadOperatorContext(accessToken);
    isOperator = true;
    snapshot = await readOperatorSupportCase(accessToken, caseId);
    if (snapshot.caseId !== caseId) return failed("unavailable", isOperator);
  } catch (error) {
    return failed(operatorReadRecovery(error), isOperator);
  }

  let annualBilling: AnnualSupportPageWire | null = null;
  if (snapshot.scopes.includes("billing")) {
    try {
      // A billing-only grant need not include profile resources. The backend
      // rechecks current admin, opened-case and MFA authority for this read.
      annualBilling = await loadAnnualSupportPurchases(accessToken, {
        companyId: snapshot.companyId, supportCaseId: snapshot.caseId, beforePurchaseId,
      });
      if (annualBilling.companyId !== snapshot.companyId || annualBilling.supportCaseId !== snapshot.caseId) {
        return failed("unavailable", isOperator);
      }
    } catch (error) {
      return { ...failed(operatorReadRecovery(error), isOperator), annualBillingError: annualBillingRecovery(error) };
    }
  }
  return {
    summaries: buildOperatorSupportSummaries(snapshot.resources),
    isOperator,
    error: null,
    annualBilling,
    annualBillingError: null,
    recovery: null,
  };
}
