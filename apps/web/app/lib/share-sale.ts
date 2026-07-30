import {
  allocateFifoShareSale,
  FifoLotValidationError,
  type ShareAcquisitionLot,
} from "./share-lots.ts";

export type ShareSaleDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type ShareSaleInput = {
  positionId: string;
  investmentKey: string;
  investmentName: string;
  currentShareCount: number;
  currentCostBasis: number;
  acquisitionLots: ShareAcquisitionLot[];
  saleDate: string;
  soldShareCount: number;
  proceeds: number;
  bankTransactionId?: string | null;
  documentId?: string | null;
  documentStatus: ShareSaleDocumentStatus;
};

export type ShareSaleActionPayload = {
  position_id: string;
  investment_key: string;
  investment_name: string;
  sale_date: string;
  sold_share_count: number;
  proceeds: number;
  cost_basis_reduction: number;
  gain_or_loss: number;
  tax_treatment: "fritaksmetoden";
  remaining_share_count: number;
  remaining_cost_basis: number;
  lot_allocations: Array<{
    lot_id: string;
    acquisition_date: string;
    share_count: number;
    cost_basis: number;
  }>;
  bank_transaction_id: string | null;
  document_id: string | null;
  document_status: ShareSaleDocumentStatus;
};

export class ShareSaleValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "ShareSaleValidationError";
    this.code = code;
  }
}

export function validateShareSale(input: ShareSaleInput): ShareSaleActionPayload {
  const positionId = input.positionId.trim();
  const investmentKey = input.investmentKey.trim();
  const investmentName = input.investmentName.trim();
  const saleDate = input.saleDate.trim();
  if (!positionId || !investmentKey || !investmentName) {
    throw new ShareSaleValidationError("Investeringsposisjon mangler.", "missing_position");
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(saleDate)) {
    throw new ShareSaleValidationError("Salgsdato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isSafeInteger(input.currentShareCount) || input.currentShareCount <= 0) {
    throw new ShareSaleValidationError("Posisjonen har ingen aksjer å selge.", "empty_position");
  }
  if (!Number.isFinite(input.currentCostBasis) || input.currentCostBasis < 0) {
    throw new ShareSaleValidationError("Ugyldig kostpris på posisjon.", "invalid_cost_basis");
  }
  if (!Number.isSafeInteger(input.soldShareCount) || input.soldShareCount <= 0) {
    throw new ShareSaleValidationError("Solgt antall må være større enn 0.", "invalid_sold_share_count");
  }
  if (input.soldShareCount > input.currentShareCount) {
    throw new ShareSaleValidationError("Salg kan ikke overstige tilgjengelig aksjebeholdning.", "sale_exceeds_position");
  }
  if (!Number.isFinite(input.proceeds) || input.proceeds < 0) {
    throw new ShareSaleValidationError("Salgsproveny kan ikke være negativt.", "invalid_proceeds");
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new ShareSaleValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  let fifo;
  try {
    fifo = allocateFifoShareSale({
      lots: input.acquisitionLots,
      saleDate,
      soldShareCount: input.soldShareCount,
    });
  } catch (error) {
    if (error instanceof FifoLotValidationError) {
      throw new ShareSaleValidationError(error.message, error.code);
    }
    throw error;
  }
  if (
    fifo.remainingShareCount + input.soldShareCount !== input.currentShareCount ||
    roundMoney(fifo.remainingCostBasis + fifo.costBasisReduction) !== roundMoney(input.currentCostBasis)
  ) {
    throw new ShareSaleValidationError(
      "Anskaffelsespostene stemmer ikke med investeringsposisjonen.",
      "lot_position_mismatch",
    );
  }
  const costBasisReduction = fifo.costBasisReduction;
  const gainOrLoss = roundMoney(input.proceeds - costBasisReduction);
  return {
    position_id: positionId,
    investment_key: investmentKey,
    investment_name: investmentName,
    sale_date: saleDate,
    sold_share_count: roundMoney(input.soldShareCount),
    proceeds: roundMoney(input.proceeds),
    cost_basis_reduction: costBasisReduction,
    gain_or_loss: gainOrLoss,
    tax_treatment: "fritaksmetoden",
    remaining_share_count: fifo.remainingShareCount,
    remaining_cost_basis: fifo.remainingCostBasis,
    lot_allocations: fifo.allocations.map((allocation) => ({
      lot_id: allocation.lotId,
      acquisition_date: allocation.acquisitionDate,
      share_count: allocation.shareCount,
      cost_basis: allocation.costBasis,
    })),
    bank_transaction_id: input.bankTransactionId || null,
    document_id: input.documentId || null,
    document_status: input.documentStatus,
  };
}

export function shareSaleLedgerLines(payload: ShareSaleActionPayload) {
  const lines = [
    { account: "1920", description: "Sale proceeds received in bank", debit: payload.proceeds, credit: 0 },
    {
      account: "1800",
      description: `Cost basis reduction: ${payload.investment_name}`,
      debit: 0,
      credit: payload.cost_basis_reduction,
    },
  ];
  if (payload.gain_or_loss > 0) {
    lines.push({
      account: "8070",
      description: `Share sale gain: ${payload.investment_name}`,
      debit: 0,
      credit: payload.gain_or_loss,
    });
  } else if (payload.gain_or_loss < 0) {
    lines.push({
      account: "8090",
      description: `Share sale loss: ${payload.investment_name}`,
      debit: Math.abs(payload.gain_or_loss),
      credit: 0,
    });
  }
  return lines;
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
