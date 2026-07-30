import {
  loadCompanyAccessContext,
  presentCompanyAccessContext,
  type CompanyAccessPresentation,
} from "../../features/company-access";
import { getCurrentSessionAccessToken } from "./supabase/auth-session";

type CompanyAccessOptions = {
  companyId?: string;
};

export async function listCompanyAccessContexts(options: CompanyAccessOptions = {}) {
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return { companies: [] as CompanyAccessPresentation[], error: "Authentication required." };
  }
  try {
    const context = await loadCompanyAccessContext(accessToken, undefined, options);
    return { companies: context.companies.map(presentCompanyAccessContext), error: null };
  } catch {
    return { companies: [] as CompanyAccessPresentation[], error: "Company access is temporarily unavailable." };
  }
}
