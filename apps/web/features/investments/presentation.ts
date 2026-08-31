import {
  TalliApiError,
  type AcquisitionLotWire,
  type InvestmentPositionWire,
} from "@talli/talli-api-client";

function nok(value: { amount: string; currency: "NOK" }): number {
  const amount = Number(value.amount);
  if (!Number.isFinite(amount)) throw new Error("Investment amount is invalid.");
  return amount;
}

export type InvestmentPositionPresentation = {
  id: string;
  company_id: string;
  investment_key: string;
  name: string;
  kind: "norwegian_private_company";
  tax_treatment: "fritaksmetoden";
  org_number: string | null;
  share_count: number;
  cost_basis: number;
  lot_history_status: "complete" | "needs_reconstruction";
  movements: unknown[];
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type AcquisitionLotPresentation = {
  id: string;
  company_id: string;
  position_id: string;
  acquisition_action_id: string;
  acquisition_date: string;
  original_share_count: number;
  remaining_share_count: number;
  original_cost_basis: number;
  remaining_cost_basis: number;
  created_by: string;
  created_at: string;
};

export function presentInvestmentPositions(
  positions: readonly InvestmentPositionWire[],
): InvestmentPositionPresentation[] {
  return positions.map((position) => ({
    id: position.id,
    company_id: position.companyId,
    investment_key: position.investmentKey,
    name: position.name,
    kind: position.kind,
    tax_treatment: position.taxTreatment,
    org_number: position.orgNumber ?? null,
    share_count: position.shareCount,
    cost_basis: nok(position.costBasis),
    lot_history_status: position.lotHistoryStatus,
    movements: Array.from({ length: position.movementCount }, () => null),
    created_by: position.createdBy,
    created_at: position.createdAt,
    updated_at: position.updatedAt,
  }));
}

export function presentAcquisitionLots(
  lots: readonly AcquisitionLotWire[],
): AcquisitionLotPresentation[] {
  return lots.map((lot) => ({
    id: lot.id,
    company_id: lot.companyId,
    position_id: lot.positionId,
    acquisition_action_id: lot.acquisitionActionId,
    acquisition_date: lot.acquisitionDate,
    original_share_count: lot.originalShareCount,
    remaining_share_count: lot.remainingShareCount,
    original_cost_basis: nok(lot.originalCostBasis),
    remaining_cost_basis: nok(lot.remainingCostBasis),
    created_by: lot.createdBy,
    created_at: lot.createdAt,
  }));
}

const ERROR_MESSAGES: Record<string, string> = {
  INVESTMENTS_INVALID_INPUT: "Kontroller opplysningene for aksjekjøpet.",
  INVESTMENTS_FORBIDDEN: "Du har ikke tilgang til å registrere aksjekjøpet.",
  INVESTMENTS_IDEMPOTENCY_KEY_REUSED: "Forespørsels-ID-en er allerede brukt med andre opplysninger.",
  INVESTMENTS_IDEMPOTENCY_IN_PROGRESS: "Aksjekjøpet behandles allerede. Prøv samme forespørsel igjen.",
  LEDGER_COMPANY_YEAR_NOT_ADMITTED: "Selskapsåret er ikke godkjent for denne handlingen.",
  LEDGER_PERIOD_LOCKED: "Inntektsåret er låst.",
  REQUEST_VALIDATION_FAILED: "Kontroller feltene og prøv igjen.",
};

export function investmentsActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Investeringstjenesten svarte ikke som forventet. Prøv igjen."
      : ERROR_MESSAGES[code] ?? "Aksjekjøpet kunne ikke fullføres.";
  }
  return "Forbindelsen til investeringstjenesten ble brutt. Prøv samme forespørsel igjen.";
}

export function investmentsOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError)
    || error.status >= 500
    || error.problem?.code === "INVESTMENTS_IDEMPOTENCY_IN_PROGRESS";
}
