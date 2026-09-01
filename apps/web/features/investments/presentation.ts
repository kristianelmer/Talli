import {
  TalliApiError,
  type AcquisitionLotWire,
  type InvestmentPositionWire,
  type InvestmentActivityWire,
  type ShareSaleAllocationWire,
  type InvestmentCorrectionWire,
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
  kind: "norwegian_private_company" | "norwegian_listed_share" | "norwegian_equity_fund";
  accounting_classification: "subsidiary" | "associate" | "other_long_term" | "current_listed_share" | "current_fund";
  tax_treatment: "fritaksmetoden";
  org_number: string | null;
  fund_equity_ratio_basis_points: number | null;
  fund_tax_statement_reference: string | null;
  share_count: number;
  cost_basis: number;
  tax_basis: number;
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
  original_tax_basis: number;
  remaining_tax_basis: number;
  acquisition_year_fund_equity_ratio_basis_points: number | null;
  fund_tax_statement_reference: string | null;
  created_by: string;
  created_at: string;
};

export type InvestmentActivityPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  action_type: "share_purchase" | "share_sale" | "dividend_received" | "fund_distribution_received";
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
  allocated_book_cost_basis: number;
  allocated_tax_basis: number;
  allocated_net_proceeds: number;
  average_fund_equity_ratio_basis_points: number | null;
  tax_gain_or_loss: number;
  exempt_gain: number;
  taxable_gain: number;
  non_deductible_loss: number;
  deductible_loss: number;
  created_by: string;
  created_at: string;
};

export type InvestmentCorrectionPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  target_kind: InvestmentCorrectionWire["targetKind"];
  original_record_id: string;
  original_activity_kind: InvestmentActivityWire["activityKind"];
  reversal_accounting_entry_id: string;
  replacement_record_id: string;
  replacement_activity_kind: InvestmentActivityWire["activityKind"];
  replacement_accounting_entry_id: string;
  reason: string;
  document_facts: InvestmentCorrectionWire["documentFacts"];
  legacy_bank_transaction_id: string | null;
  legacy_document_id: string | null;
  legacy_document_status: InvestmentCorrectionWire["legacyDocumentStatus"];
  legacy: boolean;
  evidence_mode: InvestmentCorrectionWire["evidenceMode"];
  evidence_reference: string;
  evidence_digest: string;
  owner_attested: boolean;
  created_by: string;
  created_at: string;
};

export function presentInvestmentCorrections(
  corrections: readonly InvestmentCorrectionWire[],
): InvestmentCorrectionPresentation[] {
  return corrections.map((correction) => ({
    id: correction.id,
    company_id: correction.companyId,
    income_year: correction.incomeYear,
    target_kind: correction.targetKind,
    original_record_id: correction.originalRecordId,
    original_activity_kind: correction.originalActivityKind,
    reversal_accounting_entry_id: correction.reversalAccountingEntryId,
    replacement_record_id: correction.replacementRecordId,
    replacement_activity_kind: correction.replacementActivityKind,
    replacement_accounting_entry_id: correction.replacementAccountingEntryId,
    reason: correction.reason,
    document_facts: correction.documentFacts,
    legacy_bank_transaction_id: correction.legacyBankTransactionId,
    legacy_document_id: correction.legacyDocumentId,
    legacy_document_status: correction.legacyDocumentStatus,
    legacy: correction.legacy,
    evidence_mode: correction.evidenceMode,
    evidence_reference: correction.evidenceReference,
    evidence_digest: correction.evidenceDigest,
    owner_attested: correction.ownerAttested,
    created_by: correction.createdBy,
    created_at: correction.createdAt,
  }));
}

export function effectiveInvestmentActivity(
  activity: readonly InvestmentActivityPresentation[],
  corrections: readonly InvestmentCorrectionPresentation[],
): InvestmentActivityPresentation[] {
  const correctedOriginals = new Set(
    corrections
      .filter((correction) => correction.target_kind === "economic_event")
      .map((correction) => correction.original_record_id),
  );
  return activity.filter((item) => !correctedOriginals.has(item.id));
}

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
      accounting_classification: item.accountingClassification,
      tax_treatment: item.taxTreatment,
      org_number: item.orgNumber,
      fund_equity_ratio_basis_points: item.fundEquityRatioBasisPoints,
      fund_tax_statement_reference: item.fundTaxStatementReference,
      evidence_mode: item.evidenceMode,
      evidence_reference: item.evidenceReference,
      evidence_digest: item.evidenceDigest,
      calculation_id: item.calculationId,
      owner_attested: item.ownerAttested,
      bank_transaction_id: item.bankTransactionId,
      document_id: item.documentId,
      document_status: item.documentStatus,
      ...(item.activityKind === "share_purchase" ? {
        acquisition_date: item.actionDate,
        share_count: item.shareCount,
        purchase_amount: item.purchaseAmount ? nok(item.purchaseAmount) : null,
        transaction_costs: item.transactionCosts ? nok(item.transactionCosts) : null,
        capitalized_cost: item.capitalizedCost ? nok(item.capitalizedCost) : null,
        acquisition_lot_id: item.acquisitionLotId,
      } : {}),
      ...(item.activityKind === "share_sale" ? {
        sale_date: item.actionDate,
        sold_share_count: item.soldShareCount,
        proceeds: item.proceeds ? nok(item.proceeds) : null,
        transaction_costs: item.transactionCosts ? nok(item.transactionCosts) : null,
        net_proceeds: item.netProceeds ? nok(item.netProceeds) : null,
        cost_basis_reduction: item.fifoCostBasisReduction
          ? nok(item.fifoCostBasisReduction)
          : null,
        tax_basis_reduction: item.fifoTaxBasisReduction
          ? nok(item.fifoTaxBasisReduction)
          : null,
        remaining_share_count: item.remainingShareCount,
        remaining_cost_basis: item.remainingCostBasis
          ? nok(item.remainingCostBasis)
          : null,
        remaining_tax_basis: item.remainingTaxBasis
          ? nok(item.remainingTaxBasis)
          : null,
        book_gain_or_loss: item.bookGainOrLoss ? nok(item.bookGainOrLoss) : null,
        tax_gain_or_loss: item.taxGainOrLoss ? nok(item.taxGainOrLoss) : null,
        exempt_gain: item.exemptGain ? nok(item.exemptGain) : null,
        taxable_gain: item.taxableGain ? nok(item.taxableGain) : null,
        non_deductible_loss: item.nonDeductibleLoss ? nok(item.nonDeductibleLoss) : null,
        deductible_loss: item.deductibleLoss ? nok(item.deductibleLoss) : null,
      } : {}),
      ...(item.activityKind === "dividend_received" ? {
        paying_company_name: item.payingCompanyName,
        declared_date: item.declaredDate,
        paid_date: item.actionDate,
        linked_investment_id: item.positionId,
        lawful_dividend_confirmed: item.lawfulDividendConfirmed,
        group_exception_claimed: item.groupExceptionClaimed,
        group_exception_applied: item.groupExceptionApplied,
        year_end_ownership_basis_points: item.yearEndOwnershipBasisPoints,
        year_end_voting_basis_points: item.yearEndVotingBasisPoints,
        group_evidence_reference: item.groupEvidenceReference,
      } : {}),
      ...(item.activityKind === "fund_distribution_received" ? {
        fund_name: item.fundName,
        entitlement_date: item.entitlementDate,
        paid_date: item.actionDate,
        gross_amount: item.grossAmount ? nok(item.grossAmount) : null,
        opening_fund_equity_ratio_basis_points: item.openingFundEquityRatioBasisPoints,
        dividend_portion: item.dividendPortion ? nok(item.dividendPortion) : null,
        interest_portion: item.interestPortion ? nok(item.interestPortion) : null,
        total_taxable_income: item.totalTaxableIncome ? nok(item.totalTaxableIncome) : null,
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
    accounting_classification: position.accountingClassification,
    tax_treatment: position.taxTreatment,
    org_number: position.orgNumber ?? null,
    fund_equity_ratio_basis_points: position.fundEquityRatioBasisPoints ?? null,
    fund_tax_statement_reference: position.fundTaxStatementReference ?? null,
    share_count: position.shareCount,
    cost_basis: nok(position.costBasis),
    tax_basis: nok(position.taxBasis),
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
    original_tax_basis: nok(lot.originalTaxBasis),
    remaining_tax_basis: nok(lot.remainingTaxBasis),
    acquisition_year_fund_equity_ratio_basis_points:
      lot.acquisitionYearFundEquityRatioBasisPoints ?? null,
    fund_tax_statement_reference: lot.fundTaxStatementReference ?? null,
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
    allocated_book_cost_basis: nok(allocation.allocatedBookCostBasis),
    allocated_tax_basis: nok(allocation.allocatedTaxBasis),
    allocated_net_proceeds: nok(allocation.allocatedNetProceeds),
    average_fund_equity_ratio_basis_points:
      allocation.averageFundEquityRatioBasisPoints === null
        ? null
        : Number(allocation.averageFundEquityRatioBasisPoints),
    tax_gain_or_loss: nok(allocation.taxGainOrLoss),
    exempt_gain: nok(allocation.exemptGain),
    taxable_gain: nok(allocation.taxableGain),
    non_deductible_loss: nok(allocation.nonDeductibleLoss),
    deductible_loss: nok(allocation.deductibleLoss),
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
