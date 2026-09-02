import { randomUUID } from "node:crypto";

import type { CompanyYearEligibilityStateResponse } from "@talli/talli-api-client";

import type {
  loadCompanyAccessContext,
  recheckCompanyYearEligibilityThroughApi,
} from "../../features/company-access/index.ts";
import type { getCurrentSessionAccessToken } from "./supabase/auth-session.ts";

type EligibilityGateTrigger =
  | "public_fact_changed"
  | "manifest_changed"
  | "before_payment"
  | "before_filing";

type GateDependencies = {
  getAccessToken: typeof getCurrentSessionAccessToken;
  loadContext: typeof loadCompanyAccessContext;
  recheck: typeof recheckCompanyYearEligibilityThroughApi;
  operationId(): string;
};

const gateDependencies: GateDependencies = {
  async getAccessToken() {
    const { getCurrentSessionAccessToken } = await import("./supabase/auth-session.ts");
    return getCurrentSessionAccessToken();
  },
  async loadContext(...args) {
    const { loadCompanyAccessContext } = await import("../../features/company-access/index.ts");
    return loadCompanyAccessContext(...args);
  },
  async recheck(...args) {
    const { recheckCompanyYearEligibilityThroughApi } = await import("../../features/company-access/index.ts");
    return recheckCompanyYearEligibilityThroughApi(...args);
  },
  operationId: randomUUID,
};

export class CompanyYearEligibilityGateError extends Error {
  readonly state: CompanyYearEligibilityStateResponse | null;

  constructor(
    message: string,
    state: CompanyYearEligibilityStateResponse | null = null,
  ) {
    super(message);
    this.name = "CompanyYearEligibilityGateError";
    this.state = state;
  }
}

export async function requireCompanyYearEligibilityGate(
  companyId: string,
  trigger: EligibilityGateTrigger,
  dependencies: GateDependencies = gateDependencies,
) {
  const accessToken = await dependencies.getAccessToken();
  if (!accessToken) {
    throw new CompanyYearEligibilityGateError("Innlogging kreves.");
  }
  const context = await dependencies.loadContext(accessToken, dependencies.operationId(), {
    companyId,
  });
  const company = context.selectedCompany;
  if (
    company.id !== companyId
    || company.companyYearAdmissionId === null
    || company.admittedAccountingYear === null
  ) {
    throw new CompanyYearEligibilityGateError(
      "Selskapsåret har ingen gyldig Talli-godkjenning.",
    );
  }
  const state = await dependencies.recheck(
    accessToken,
    company.companyYearAdmissionId,
    { operationId: dependencies.operationId(), trigger },
    dependencies.operationId(),
  );
  if (
    state.companyId !== companyId
    || state.accountingYear !== company.admittedAccountingYear
    || state.decision !== "supported"
    || !state.consequentialOperationsAllowed
  ) {
    throw new CompanyYearEligibilityGateError(state.nextStep, state);
  }
  return state;
}

export function companyYearEligibilityGateMessage(error: unknown) {
  if (error instanceof CompanyYearEligibilityGateError) return error.message;
  return "Talli kunne ikke kontrollere selskapsgrensen nå. Ingen opplysninger eller status ble endret.";
}
