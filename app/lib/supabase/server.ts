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
