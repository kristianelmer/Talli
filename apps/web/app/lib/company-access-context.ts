import { loadCompanyAccessContext } from "../../features/company-access";
import { getCurrentSessionAccessToken } from "./supabase/auth-session";
import type { CompanyWorkspaceRow } from "./supabase/server";

type CompanyAccessOptions = {
  companyId?: string;
  resourceScope?: "workspace" | "owner" | "owner_sensitive";
};

function companyRow(context: Awaited<ReturnType<typeof loadCompanyAccessContext>>["companies"][number]): CompanyWorkspaceRow {
  return {
    id: context.id,
    org_number: context.orgNumber,
    name: context.name,
    entity_type: context.entityType,
    address: context.address,
    postal_code: context.postalCode,
    city: context.city,
    status_text: context.statusText,
    source: context.source,
    created_by: context.createdBy,
    identity_confirmed_at: context.identityConfirmedAt,
    identity_locked_at: context.identityLockedAt,
    created_at: context.createdAt,
    role: context.role,
  };
}

export async function listCompanyAccessContexts(options: CompanyAccessOptions = {}) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return { companies: [] as CompanyWorkspaceRow[], error: "Authentication required." };
  }
  try {
    const context = await loadCompanyAccessContext(accessToken, undefined, options);
    return { companies: context.companies.map(companyRow), error: null };
  } catch {
    return { companies: [] as CompanyWorkspaceRow[], error: "Company access is temporarily unavailable." };
  }
}
