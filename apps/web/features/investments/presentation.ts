import {
  TalliApiError,
  type AcquisitionLotWire,
  type InvestmentPositionWire,
  type InvestmentActivityWire,
  type ShareSaleAllocationWire,
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

export type InvestmentActivityPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  action_type: "share_purchase" | "share_sale" | "dividend_received";
  action_date: string;
  payload: Record<string, unknown>;
  ledger_entry_id: string | null;
  bank_transaction_id: string | null;
  document_id: string | null;
  risk_level: "ready";
  blocker_code: null;
  created_by: string;
  created_at: string;
};

export type ShareSaleAllocationPresentation = {
  id: string;
  company_id: string;
  position_id: string;
  lot_id: string;
  sale_action_id: string;
  allocated_share_count: number;
  allocated_cost_basis: number;
  created_by: string;
  created_at: string;
};

export function presentInvestmentActivity(
  activity: readonly InvestmentActivityWire[],
): InvestmentActivityPresentation[] {
  return activity.map((item) => ({
    id: item.id,
    company_id: item.companyId,
    income_year: item.incomeYear,
    action_type: item.activityKind,
    action_date: item.actionDate,
    payload: {
      position_id: item.positionId,
      investment_key: item.investmentKey,
      investment_name: item.investmentName,
      investment_kind: item.investmentKind,
      tax_treatment: item.taxTreatment,
      org_number: item.orgNumber,
      bank_transaction_id: item.bankTransactionId,
      document_id: item.documentId,
      document_status: item.documentStatus,
      ...(item.activityKind === "share_purchase" ? {
        acquisition_date: item.actionDate,
        share_count: item.shareCount,
        purchase_amount: item.purchaseAmount ? nok(item.purchaseAmount) : null,
        acquisition_lot_id: item.acquisitionLotId,
      } : {}),
      ...(item.activityKind === "share_sale" ? {
        sale_date: item.actionDate,
        sold_share_count: item.soldShareCount,
        proceeds: item.proceeds ? nok(item.proceeds) : null,
        cost_basis_reduction: item.fifoCostBasisReduction
          ? nok(item.fifoCostBasisReduction)
          : null,
        remaining_share_count: item.remainingShareCount,
        remaining_cost_basis: item.remainingCostBasis
          ? nok(item.remainingCostBasis)
          : null,
      } : {}),
      ...(item.activityKind === "dividend_received" ? {
        paying_company_name: item.payingCompanyName,
        declared_date: item.declaredDate,
        paid_date: item.actionDate,
        linked_investment_id: item.positionId,
      } : {}),
      ...(item.grossAmount ? { gross_amount: nok(item.grossAmount) } : {}),
      ...(item.taxableAddBack ? { taxable_add_back: nok(item.taxableAddBack) } : {}),
      ...(item.gainOrLoss ? { gain_or_loss: nok(item.gainOrLoss) } : {}),
    },
    ledger_entry_id: item.accountingEntryId,
    bank_transaction_id: item.bankTransactionId,
    document_id: item.documentId,
    risk_level: "ready",
    blocker_code: null,
    created_by: item.createdBy,
    created_at: item.createdAt,
  }));
}

export function summarizeReceivedDividendAnnualImpact(
  activity: readonly InvestmentActivityPresentation[],
) {
  return activity
    .filter((item) => item.action_type === "dividend_received")
    .reduce(
      (summary, item) => ({
        dividendIncome: roundMoney(
          summary.dividendIncome + Number(item.payload.gross_amount ?? 0),
        ),
        fritaksmetodenAddBack: roundMoney(
          summary.fritaksmetodenAddBack
            + Number(item.payload.taxable_add_back ?? 0),
        ),
      }),
      { dividendIncome: 0, fritaksmetodenAddBack: 0 },
    );
}

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
    movements: position.movements,
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

export function presentShareSaleAllocations(
  allocations: readonly ShareSaleAllocationWire[],
): ShareSaleAllocationPresentation[] {
  return allocations.map((allocation) => ({
    id: allocation.id,
    company_id: allocation.companyId,
    position_id: allocation.positionId,
    lot_id: allocation.lotId,
    sale_action_id: allocation.saleActionId,
    allocated_share_count: allocation.allocatedShareCount,
    allocated_cost_basis: nok(allocation.allocatedCostBasis),
    created_by: allocation.createdBy,
    created_at: allocation.createdAt,
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

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100;
}
