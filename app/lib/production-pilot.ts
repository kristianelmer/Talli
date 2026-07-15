import type { AuthorityObligation } from "./authority-permission.ts";

export type ProductionPilotCaseProfile = "rf1086_no_activity_v1";
export type ProductionPilotStatus = "pending" | "active" | "suspended" | "completed" | "revoked";

export type ProductionPilotEntitlement = {
  id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: AuthorityObligation;
  case_profile: string;
  status: ProductionPilotStatus;
  billing_exempt: boolean;
  starts_at: string;
  expires_at: string;
};

export type ProductionPilotContext = {
  companyId: string;
  userId: string;
  incomeYear: number;
  obligation: AuthorityObligation;
  caseProfile: ProductionPilotCaseProfile;
};

export type ProductionPilotGate = {
  allowed: boolean;
  reason: string;
};

export function evaluateProductionPilotEntitlement(
  context: ProductionPilotContext,
  entitlement: ProductionPilotEntitlement | null,
  now = new Date(),
): ProductionPilotGate {
  if (!entitlement) return { allowed: false, reason: "pilot_entitlement_missing" };
  if (entitlement.company_id !== context.companyId) {
    return { allowed: false, reason: "pilot_entitlement_company_mismatch" };
  }
  if (entitlement.user_id !== context.userId) {
    return { allowed: false, reason: "pilot_entitlement_user_mismatch" };
  }
  if (entitlement.income_year !== context.incomeYear) {
    return { allowed: false, reason: "pilot_entitlement_year_mismatch" };
  }
  if (entitlement.obligation !== context.obligation) {
    return { allowed: false, reason: "pilot_entitlement_obligation_mismatch" };
  }
  if (entitlement.case_profile !== context.caseProfile) {
    return { allowed: false, reason: "pilot_entitlement_profile_mismatch" };
  }
  if (entitlement.status !== "active") {
    return { allowed: false, reason: `pilot_entitlement_${entitlement.status}` };
  }
  const startsAt = new Date(entitlement.starts_at);
  const expiresAt = new Date(entitlement.expires_at);
  if (
    Number.isNaN(startsAt.valueOf())
    || Number.isNaN(expiresAt.valueOf())
    || now < startsAt
    || now >= expiresAt
  ) {
    return { allowed: false, reason: "pilot_entitlement_inactive_interval" };
  }
  return { allowed: true, reason: "pilot_entitlement_active" };
}

export function isBillingExemptProductionPilot(entitlement: ProductionPilotEntitlement | null) {
  return entitlement?.status === "active" && entitlement.billing_exempt === true;
}
