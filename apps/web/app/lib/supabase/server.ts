import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { createClient, type SupabaseClient, type User } from "@supabase/supabase-js";
import type {
  YearEndInterviewAnswers,
} from "../annual-data";
import type {
  AnnualReadinessIssue,
  AnnualReadinessStatus,
} from "../annual-readiness";
import type { CompanyCancellationRow } from "../cancellation";
import type { LaunchSignoffKey, LaunchSignoffStatus } from "../launch-signoff";
import { assertOperatorSearchAllowed, buildOperatorSupportSummaries } from "../operator-support";
import type {
  Rf1086ReceiptMetadata,
  Rf1086SubmittedPayloadReference,
  Rf1086SubmittedPayloadSnapshot,
} from "../rf1086-submission";
import type { SystemUserRequestStatus } from "../system-user-requests";

export type CompanyWorkspaceRow = {
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
  role?: "owner" | "reviewer" | "read_only";
};

export type CustomerAgreementAcceptanceRow = {
  company_id: string;
  business_terms_version: string;
  business_terms_sha256: string;
  dpa_version: string;
  dpa_sha256: string;
  accepted_at: string;
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
  metadata: { systemId?: string; clientId?: string; right?: string; callbackPath?: string };
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

export type PeriodLockRow = {
  id: string;
  company_id: string;
  income_year: number;
  reason: string;
  locked_by: string;
  locked_at: string;
};

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
  receipt_metadata: Rf1086ReceiptMetadata | CompanyTaxReturnReceiptMetadata | null;
  submitted_payload_ref: Rf1086SubmittedPayloadReference | CompanyTaxReturnPayloadReference | null;
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
  status: "approved" | "sending" | "received" | "processing" | "accepted" | "rejected" | "action_required" | "unknown";
  authority_references: Record<string, string>;
  failure_class: string | null;
  supersedes_submission_id: string | null;
  submitted_by: string;
  feedback_state: "sent" | "processing" | "accepted" | "rejected" | "action_required" | "unknown";
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
  content_type: "application/xml" | "text/xml" | "application/pdf" | "text/plain" | "application/octet-stream";
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

export type LedgerEntryRow = {
  id: string;
  company_id: string;
  setup_id: string | null;
  income_year: number;
  entry_type: string;
  memo: string;
  lines: unknown[];
  risk_flags: { code: string; account?: string; message: string }[];
  warning_accepted_by: string | null;
  warning_accepted_at: string | null;
  created_by: string;
  created_at: string;
};

export type BankTransactionRow = {
  id: string;
  company_id: string;
  income_year: number;
  transaction_date: string;
  text: string;
  amount: number;
  balance: number | null;
  source_hash: string;
  matched_entry_id: string | null;
  matched_action_id: string | null;
  accepted_warning: boolean;
  created_by: string;
  created_at: string;
};

export type BankSuggestionAcceptanceRow = {
  id: string;
  company_id: string;
  bank_transaction_id: string;
  ledger_entry_id: string;
  rule_id: "bank_fee" | "system_subscription" | "deposit_interest";
  rule_version: string;
  reason: string;
  lines: unknown[];
  accepted_by: string;
  accepted_at: string;
};

export type HoldingActionRow = {
  id: string;
  company_id: string;
  income_year: number;
  action_type:
    | "dividend_received"
    | "share_purchase"
    | "share_sale"
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

export type InvestmentPositionRow = {
  id: string;
  company_id: string;
  investment_key: string;
  name: string;
  kind: "norwegian_private_company";
  tax_treatment: "fritaksmetoden";
  org_number: string | null;
  share_count: number;
  cost_basis: number;
  lot_history_status: "complete" | "needs_reconstruction";
  movements: unknown[];
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type InvestmentLotRow = {
  id: string;
  company_id: string;
  position_id: string;
  acquisition_action_id: string;
  acquisition_date: string;
  original_share_count: number;
  remaining_share_count: number;
  original_cost_basis: number;
  remaining_cost_basis: number;
  created_by: string;
  created_at: string;
};

export type InvestmentLotAllocationRow = {
  id: string;
  company_id: string;
  position_id: string;
  lot_id: string;
  sale_action_id: string;
  allocated_share_count: number;
  allocated_cost_basis: number;
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
  kind: "subscription" | "subscription_cancellation" | "filing_package" | "refund";
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
  const { data: operator } = await supabase
    .from("support_operators")
    .select("role, active")
    .eq("user_id", user.id)
    .eq("active", true)
    .maybeSingle();
  const isOperator = Boolean(operator);
  return { user, isOperator, isAdminOperator: operator?.role === "admin" };
}

export async function listCustomerAgreementAcceptances(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { acceptances: [] as CustomerAgreementAcceptanceRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("customer_agreement_acceptances")
    .select("company_id, business_terms_version, business_terms_sha256, dpa_version, dpa_sha256, accepted_at")
    .in("company_id", companyIds)
    .order("accepted_at", { ascending: false });
  return {
    acceptances: (data ?? []) as CustomerAgreementAcceptanceRow[],
    error: error?.message ?? null,
  };
}

export async function listDocumentsForCompanies(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { documents: [] as DocumentRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("documents")
    .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at, removed_at, removed_by, removal_reason")
    .in("company_id", companyIds)
    .neq("status", "removed")
    .order("created_at", { ascending: false });

  return {
    documents: (data ?? []) as DocumentRow[],
    error: error?.message ?? null,
  };
}

export async function listOpeningSetups(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { setups: [] as OpeningBalanceSetupRow[], shareholders: [] as OpeningShareholderRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data: setups, error } = await supabase
    .from("opening_balance_setups")
    .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });
  const setupIds = (setups ?? []).map((setup) => setup.id);
  const { data: shareholders, error: shareholderError } = setupIds.length
    ? await supabase
        .from("opening_shareholders")
        .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
        .in("setup_id", setupIds)
    : { data: [], error: null };

  return {
    setups: (setups ?? []) as OpeningBalanceSetupRow[],
    shareholders: (shareholders ?? []) as OpeningShareholderRow[],
    error: error?.message ?? shareholderError?.message ?? null,
  };
}

export async function listPeriodLocks(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { locks: [] as PeriodLockRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("period_locks")
    .select("id, company_id, income_year, reason, locked_by, locked_at")
    .in("company_id", companyIds)
    .order("locked_at", { ascending: false });

  return {
    locks: (data ?? []) as PeriodLockRow[],
    error: error?.message ?? null,
  };
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
      error: null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const [decisions, sets, artifacts, events, finalizations] = await Promise.all([
    supabase
      .from("corporate_decisions")
      .select("id, company_id, income_year, decision_kind, annual_close_source_id, source_hash, canonical_input, decision_hash, supersedes_decision_id, created_by, created_at")
      .in("company_id", companyIds)
      .order("created_at", { ascending: false }),
    supabase
      .from("corporate_document_sets")
      .select("id, company_id, income_year, decision_id, template_family, template_version, decision_hash, supersedes_set_id, created_by, created_at")
      .in("company_id", companyIds)
      .order("created_at", { ascending: false }),
    supabase
      .from("corporate_document_artifacts")
      .select("id, company_id, income_year, set_id, artifact_kind, variant, document_id, content_sha256, byte_length, mime_type, storage_key, supersedes_artifact_id, created_by, created_at")
      .in("company_id", companyIds)
      .order("created_at", { ascending: true }),
    supabase
      .from("corporate_document_events")
      .select("id, company_id, income_year, decision_id, set_id, artifact_id, event_kind, actor_id, occurred_at, decision_hash, content_sha256, metadata, idempotency_key, created_at")
      .in("company_id", companyIds)
      .order("occurred_at", { ascending: true }),
    supabase
      .from("corporate_decision_finalizations")
      .select("id, company_id, income_year, decision_id, finalization_kind, holding_action_id, ledger_entry_id, annual_close_source_id, decision_hash, signed_artifact_hashes, accounting_policy_version, created_by, created_at")
      .in("company_id", companyIds)
      .order("created_at", { ascending: true }),
  ]);
  return {
    corporateDecisions: (decisions.data ?? []) as CorporateDecisionRow[],
    corporateDocumentSets: (sets.data ?? []) as CorporateDocumentSetRow[],
    corporateDocumentArtifacts: (artifacts.data ?? []) as CorporateDocumentArtifactRow[],
    corporateDocumentEvents: (events.data ?? []) as CorporateDocumentEventRow[],
    corporateDecisionFinalizations: (finalizations.data ?? []) as CorporateDecisionFinalizationRow[],
    error: decisions.error?.message
      ?? sets.error?.message
      ?? artifacts.error?.message
      ?? events.error?.message
      ?? finalizations.error?.message
      ?? null,
  };
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

function productionPilotSchemaUnavailable(errors: Array<{ code?: string; message?: string } | null>) {
  return errors.some((error) => error != null && (
    error.code === "PGRST205"
    || error.code === "42P01"
    || /production_(?:pilot|filing|feedback)|filing_approval_snapshots/iu.test(error.message ?? "")
  ));
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
  const [entitlements, approvals, submissions, artifacts] = await Promise.all([
    supabase.from("production_pilot_entitlements").select("*").in("company_id", companyIds).order("updated_at", { ascending: false }),
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
  const errors = [entitlements.error, approvals.error, submissions.error, artifacts.error];
  const rolloutSchemaPending = process.env.TALLI_RF1086_PRODUCTION_ENABLED !== "true"
    && productionPilotSchemaUnavailable(errors);
  return {
    productionPilotEntitlements: (entitlements.data ?? []) as ProductionPilotEntitlementRow[],
    filingApprovalSnapshots: (approvals.data ?? []) as FilingApprovalSnapshotRow[],
    productionFilingSubmissions: (submissions.data ?? []) as ProductionFilingSubmissionRow[],
    productionFeedbackArtifacts: (artifacts.data ?? []) as ProductionFeedbackArtifactRow[],
    error: rolloutSchemaPending
      ? null
      : entitlements.error?.message ?? approvals.error?.message ?? submissions.error?.message ?? artifacts.error?.message ?? null,
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
  const { data, error } = await supabase
    .from("bank_transactions")
    .select("id, company_id, income_year, transaction_date, text, amount, balance, source_hash, matched_entry_id, matched_action_id, accepted_warning, created_by, created_at")
    .in("company_id", companyIds)
    .order("transaction_date", { ascending: false });

  return {
    transactions: (data ?? []) as BankTransactionRow[],
    error: error?.message ?? null,
  };
}

export async function listBankSuggestionAcceptances(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { acceptances: [] as BankSuggestionAcceptanceRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("bank_suggestion_acceptances")
    .select("id, company_id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, reason, lines, accepted_by, accepted_at")
    .in("company_id", companyIds)
    .order("accepted_at", { ascending: false });

  return {
    acceptances: (data ?? []) as BankSuggestionAcceptanceRow[],
    error: error?.message ?? null,
  };
}

export async function listHoldingActions(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { actions: [] as HoldingActionRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("holding_actions")
    .select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at")
    .in("company_id", companyIds)
    .order("action_date", { ascending: false });

  return {
    actions: (data ?? []) as HoldingActionRow[],
    error: error?.message ?? null,
  };
}

export async function listInvestmentPositions(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { positions: [] as InvestmentPositionRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("investment_positions")
    .select("id, company_id, investment_key, name, kind, tax_treatment, org_number, share_count, cost_basis, lot_history_status, movements, created_by, created_at, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    positions: (data ?? []) as InvestmentPositionRow[],
    error: error?.message ?? null,
  };
}

export async function listInvestmentLots(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { lots: [] as InvestmentLotRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("investment_lots")
    .select("id, company_id, position_id, acquisition_action_id, acquisition_date, original_share_count, remaining_share_count, original_cost_basis, remaining_cost_basis, created_by, created_at")
    .in("company_id", companyIds)
    .order("acquisition_date", { ascending: true })
    .order("id", { ascending: true });

  return {
    lots: (data ?? []) as InvestmentLotRow[],
    error: error?.message ?? null,
  };
}

export async function listInvestmentLotAllocations(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { allocations: [] as InvestmentLotAllocationRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("investment_lot_allocations")
    .select("id, company_id, position_id, lot_id, sale_action_id, allocated_share_count, allocated_cost_basis, created_by, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: true });

  return {
    allocations: (data ?? []) as InvestmentLotAllocationRow[],
    error: error?.message ?? null,
  };
}

export async function listLedgerEntries(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { entries: [] as LedgerEntryRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("ledger_entries")
    .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    entries: (data ?? []) as LedgerEntryRow[],
    error: error?.message ?? null,
  };
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

export async function listBillingAccounts(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { billingAccounts: [] as BillingAccountRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("billing_accounts")
    .select(
      "company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref, updated_by, created_at, updated_at",
    )
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    billingAccounts: (data ?? []) as BillingAccountRow[],
    error: error?.message ?? null,
  };
}

export async function listBillingPaymentEvents(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { billingPaymentEvents: [] as BillingPaymentEventRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("billing_payment_events")
    .select("id, company_id, provider, provider_reference, idempotency_key, kind, status, amount_nok, income_year, payload, created_by, created_at")
    .in("company_id", companyIds)
    .order("created_at", { ascending: false });

  return {
    billingPaymentEvents: (data ?? []) as BillingPaymentEventRow[],
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
    return { launchSignoffs: [] as LaunchSignoffRow[], isOperator: false, isAdminOperator: false, error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data: operator, error: operatorError } = await supabase
    .from("support_operators")
    .select("user_id, role, active")
    .eq("user_id", actorId)
    .eq("active", true)
    .maybeSingle();
  if (operatorError) {
    return { launchSignoffs: [] as LaunchSignoffRow[], isOperator: false, isAdminOperator: false, error: operatorError.message };
  }
  const isOperator = Boolean(operator);
  const isAdminOperator = operator?.role === "admin";
  if (!isOperator) {
    return { launchSignoffs: [] as LaunchSignoffRow[], isOperator, isAdminOperator, error: null };
  }
  const { data, error } = await supabase
    .from("launch_signoffs")
    .select("key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by, updated_at")
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
    return { operations: [] as AuthorityOperationRow[], isAdminOperator: false, error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data: operator, error: operatorError } = await supabase
    .from("support_operators")
    .select("role, active")
    .eq("user_id", actorId)
    .eq("role", "admin")
    .eq("active", true)
    .maybeSingle();
  if (operatorError) {
    return {
      operations: [] as AuthorityOperationRow[],
      isAdminOperator: false,
      error: "authority_operator_lookup_failed",
    };
  }
  if (!operator) {
    return { operations: [] as AuthorityOperationRow[], isAdminOperator: false, error: null };
  }
  const { data, error } = await supabase.from("authority_operations").select("*").order("created_at", { ascending: false }).limit(10);
  return {
    operations: (data ?? []) as AuthorityOperationRow[],
    isAdminOperator: true,
    error: error ? "authority_operations_query_failed" : null,
  };
}

export async function searchOperatorSupportDashboard(query: string, actorId?: string | null) {
  if (!hasSupabaseEnv() || !actorId) {
    return { summaries: [], isOperator: false, error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data: operator } = await supabase
    .from("support_operators")
    .select("user_id")
    .eq("user_id", actorId)
    .eq("active", true)
    .maybeSingle();
  const isOperator = Boolean(operator);
  try {
    assertOperatorSearchAllowed({ isOperator, query });
  } catch (error) {
    return {
      summaries: [],
      isOperator,
      error: error instanceof Error ? error.message : "operator_search_failed",
    };
  }

  const normalized = query.trim();
  const { data: companies, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .or(`org_number.ilike.%${normalized}%,name.ilike.%${normalized}%`)
    .limit(10);
  if (companyError) {
    return { summaries: [], isOperator, error: companyError.message };
  }
  const companyRows = (companies ?? []) as CompanyWorkspaceRow[];
  const companyIds = companyRows.map((company) => company.id);
  if (!companyIds.length) {
    return { summaries: [], isOperator, error: null };
  }

  const [
    { data: readinessSnapshots },
    { data: submissions },
    { data: authorityPermissions },
    { data: billingAccounts },
    { data: billingPaymentEvents },
    { data: auditEvents },
  ] = await Promise.all([
    supabase
      .from("filing_readiness_snapshots")
      .select("id, company_id, income_year, obligation, status, ready, hard_blocks, warnings, accepted_warnings, evaluated_at, created_by, updated_at")
      .in("company_id", companyIds),
    supabase
      .from("filing_submissions")
      .select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
      .in("company_id", companyIds)
      .order("updated_at", { ascending: false }),
    supabase
      .from("authority_permissions")
      .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
      .in("company_id", companyIds),
    supabase
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref, updated_by, created_at, updated_at")
      .in("company_id", companyIds),
    supabase
      .from("billing_payment_events")
      .select("id, company_id, provider, provider_reference, idempotency_key, kind, status, amount_nok, income_year, payload, created_by, created_at")
      .in("company_id", companyIds),
    supabase
      .from("audit_events")
      .select("id, company_id, actor_id, category, action, message, created_at")
      .in("company_id", companyIds)
      .order("created_at", { ascending: false })
      .limit(50),
  ]);

  const { cancellations, error: cancellationLifecycleError } = await (
    await import("../company-access-cancellation")
  ).listCompanyCancellationLifecycle(companyIds);

  await supabase.from("audit_events").insert(
    companyIds.map((companyId) => ({
      company_id: companyId,
      actor_id: actorId,
      category: "support",
      action: "operator_dashboard_viewed",
      message: `Operator dashboard searched for ${normalized}.`,
    })),
  );

  return {
    summaries: buildOperatorSupportSummaries({
      companies: companyRows,
      readinessSnapshots: (readinessSnapshots ?? []) as FilingReadinessSnapshotRow[],
      submissions: (submissions ?? []) as FilingSubmissionRow[],
      authorityPermissions: (authorityPermissions ?? []) as AuthorityPermissionRow[],
      billingAccounts: (billingAccounts ?? []) as BillingAccountRow[],
      billingPaymentEvents: (billingPaymentEvents ?? []) as BillingPaymentEventRow[],
      cancellations: (cancellations ?? []) as CompanyCancellationRow[],
      auditEvents: auditEvents ?? [],
    }),
    isOperator,
    error: cancellationLifecycleError ?? null,
  };
}
