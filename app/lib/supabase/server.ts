import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

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
  status: string;
  calls: { endpoint: string; body_hash: string; idempotency_key: string; status: string; created_at: string }[];
  receipt_id: string | null;
  feedback_document_ids: string[];
  authority_confirmed_at: string | null;
  preview_confirmed_at: string | null;
  created_at: string;
  updated_at: string;
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
  action_type: "dividend_received" | "share_purchase" | "share_sale" | "dividend_to_owner";
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
    .select("id, preview_id, company_id, income_year, filing, mode, status, calls, receipt_id, feedback_document_ids, authority_confirmed_at, preview_confirmed_at, created_at, updated_at")
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
