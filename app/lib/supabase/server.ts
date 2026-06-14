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
