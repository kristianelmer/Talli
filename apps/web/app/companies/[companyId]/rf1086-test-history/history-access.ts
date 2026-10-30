import { TalliApiError } from "@talli/talli-api-client";
import { loadCompanyAccessRecord } from "../../../../features/company-access";
import { isCompanyTestHistoryCompany } from "../../../../features/shareholder-register-filing";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";
import { createSupabaseServerClient } from "../../../lib/supabase/server";

export async function loadCompanyTestHistoryMember(companyId: string, requestId: string) {
  if (!isCompanyTestHistoryCompany(companyId)) throw new TalliApiError(400, undefined);
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) throw new TalliApiError(401, undefined);
  const supabase = await createSupabaseServerClient();
  // Cookie/session extraction supplies transport credentials only. Verify this
  // exact bearer with the server before using any company metadata or inventory.
  const { data: { user }, error } = await supabase.auth.getUser(accessToken);
  if (error) {
    throw new TalliApiError([400, 401, 403].includes(error.status ?? 0) ? 401 : 503, undefined);
  }
  if (!user) throw new TalliApiError(401, undefined);
  const { company } = await loadCompanyAccessRecord(accessToken, companyId, requestId);
  if (company.id !== companyId || !["owner", "reviewer", "read_only"].includes(company.role)) {
    throw new TalliApiError(502, undefined);
  }
  return { accessToken, company };
}
