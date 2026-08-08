import {
  listCompanyInvitations,
  listCompanyMemberships,
} from "../../features/company-access";
import { getCurrentSessionAccessToken } from "./supabase/auth-session";

export async function listCompanyAccessAdministration(companyId: string | undefined) {
  if (!companyId) return { invitations: [], memberships: [], error: null };
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return { invitations: [], memberships: [], error: "Authentication required." };
  }
  try {
    const [invitationResponse, membershipResponse] = await Promise.all([
      listCompanyInvitations(accessToken, companyId),
      listCompanyMemberships(accessToken, companyId),
    ]);
    return {
      invitations: invitationResponse.invitations,
      memberships: membershipResponse.memberships,
      error: null,
    };
  } catch {
    return {
      invitations: [],
      memberships: [],
      error: "Company access administration is temporarily unavailable.",
    };
  }
}
