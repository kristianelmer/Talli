import { TalliApiError } from "@talli/talli-api-client";
import {
  loadCompanyAccessRecord,
  loadCompanyAccessContext,
  loadOperatorContext,
  presentCompanyAccessRecord,
  presentCompanyAccessContext,
  type AcceptedMembershipCompanyPresentation,
  type CompanyAccessPresentation,
} from "../../features/company-access/index.ts";

type CompanyAccessOptions = {
  companyId?: string;
};

type CompanyAccessContextDependencies = {
  getAccessToken(): Promise<string | null>;
  loadContext: typeof loadCompanyAccessContext;
};

const companyAccessContextDependencies: CompanyAccessContextDependencies = {
  async getAccessToken() {
    const { getCurrentSessionAccessToken } = await import("./supabase/auth-session.ts");
    return getCurrentSessionAccessToken();
  },
  loadContext: loadCompanyAccessContext,
};

async function currentAccessToken() {
  return companyAccessContextDependencies.getAccessToken();
}

export async function listCompanyAccessContexts(
  options: CompanyAccessOptions = {},
  dependencies: CompanyAccessContextDependencies = companyAccessContextDependencies,
) {
  const accessToken = await dependencies.getAccessToken();
  if (!accessToken) {
    return { companies: [] as CompanyAccessPresentation[], error: "Authentication required." };
  }
  try {
    const context = await dependencies.loadContext(accessToken, undefined, options);
    return { companies: context.companies.map(presentCompanyAccessContext), error: null };
  } catch (error) {
    if (
      error instanceof TalliApiError
      && error.status === 404
      && error.problem?.code === "COMPANY_CONTEXT_NOT_FOUND"
    ) {
      return { companies: [] as CompanyAccessPresentation[], error: null };
    }
    if (
      error instanceof TalliApiError
      && error.status === 403
      && error.problem?.code === "AAL2_REQUIRED"
    ) {
      return {
        companies: [] as CompanyAccessPresentation[],
        error: "Company access is temporarily unavailable.",
        requiresAal2: true,
      };
    }
    return { companies: [] as CompanyAccessPresentation[], error: "Company access is temporarily unavailable." };
  }
}

export async function loadAcceptedMembershipCompany(companyId: string) {
  const accessToken = await currentAccessToken();
  if (!accessToken) return null;
  try {
    const response = await loadCompanyAccessRecord(accessToken, companyId);
    return presentCompanyAccessRecord(response.company);
  } catch {
    return null;
  }
}

export async function loadAuthorizedSupportOperator() {
  const accessToken = await currentAccessToken();
  if (!accessToken) return null;
  try {
    return await loadOperatorContext(accessToken);
  } catch {
    return null;
  }
}

export type { AcceptedMembershipCompanyPresentation };
