import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import type {
  YearEndInterviewAnswers,
} from "../annual-data";
import type {
  AnnualReadinessIssue,
  AnnualReadinessStatus,
} from "../annual-readiness";
import type {
  Rf1086ReceiptMetadata,
  Rf1086SubmissionFeedbackItem,
  Rf1086SubmittedPayloadReference,
  Rf1086SubmittedPayloadSnapshot,
} from "../rf1086-submission";

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
};

export type CompanyMembershipRow = {
  company_id: string;
  user_id: string;
  role: "owner" | "reviewer" | "read_only";
  accepted_at: string | null;
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

export type FilingSubmissionRow = {
  id: string;
  preview_id: string;
  company_id: string;
  income_year: number;
  filing: string;
  mode: "simulation";
  adapter_mode: "simulation" | "production";
  payload_hash: string | null;
  idempotency_key: string | null;
  status: string;
  calls: { endpoint: string; body_hash: string; idempotency_key: string; status: string; created_at: string }[];
  receipt_id: string | null;
  feedback_document_ids: string[];
  feedback_items: Rf1086SubmissionFeedbackItem[];
  receipt_metadata: Rf1086ReceiptMetadata | null;
  submitted_payload_ref: Rf1086SubmittedPayloadReference | null;
  submitted_payload: Rf1086SubmittedPayloadSnapshot | null;
  authority_confirmed_at: string | null;
  preview_confirmed_at: string | null;
  created_at: string;
  updated_at: string;
  submitted_by: string | null;
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
  movements: unknown[];
  created_by: string;
  created_at: string;
  updated_at: string;
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
  no_charge_reason: string | null;
  updated_by: string;
  created_at: string;
  updated_at: string;
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

export type WorkspaceInvitationRow = {
  id: string;
  company_id: string;
  invited_email: string;
  invited_user_id: string | null;
  role: "reviewer" | "read_only";
  token_hash: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  invited_by: string;
  accepted_by: string | null;
  accepted_at: string | null;
  revoked_by: string | null;
  revoked_at: string | null;
  resent_at: string | null;
  delivery_events: unknown[];
  created_at: string;
  updated_at: string;
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

export async function listCompanyWorkspaces() {
  if (!hasSupabaseEnv()) {
    return { companies: [] as CompanyWorkspaceRow[], error: "Supabase environment variables are missing." };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .order("created_at", { ascending: false });

  return {
    companies: (data ?? []) as CompanyWorkspaceRow[],
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
    .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at")
    .in("company_id", companyIds)
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

  return {
    annualData: (data ?? []) as AnnualDataRow[],
    error: error?.message ?? null,
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
    .select("id, preview_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    submissions: (data ?? []) as FilingSubmissionRow[],
    error: error?.message ?? null,
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
    .select("id, company_id, investment_key, name, kind, tax_treatment, org_number, share_count, cost_basis, movements, created_by, created_at, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    positions: (data ?? []) as InvestmentPositionRow[],
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
      "company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason, updated_by, created_at, updated_at",
    )
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    billingAccounts: (data ?? []) as BillingAccountRow[],
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

export async function listWorkspaceInvitations(companyIds: string[]) {
  if (!hasSupabaseEnv() || companyIds.length === 0) {
    return { invitations: [] as WorkspaceInvitationRow[], error: null };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("company_invitations")
    .select("id, company_id, invited_email, invited_user_id, role, token_hash, status, expires_at, invited_by, accepted_by, accepted_at, revoked_by, revoked_at, resent_at, delivery_events, created_at, updated_at")
    .in("company_id", companyIds)
    .order("updated_at", { ascending: false });

  return {
    invitations: (data ?? []) as WorkspaceInvitationRow[],
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
