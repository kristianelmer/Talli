import type { SupabaseClient } from "@supabase/supabase-js";

const companyWorkspaceSelection =
  "id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at";

export async function listCompanyWorkspacesForUser(
  supabase: SupabaseClient,
  userId: string,
) {
  const { data: memberships, error: membershipError } = await supabase
    .from("company_memberships")
    .select("company_id")
    .eq("user_id", userId)
    .not("accepted_at", "is", null);
  if (membershipError || !memberships?.length) {
    return { companies: [], error: membershipError?.message ?? null };
  }

  const { data, error } = await supabase
    .from("companies")
    .select(companyWorkspaceSelection)
    .in("id", memberships.map(({ company_id }) => company_id))
    .order("created_at", { ascending: false });

  return { companies: data ?? [], error: error?.message ?? null };
}
