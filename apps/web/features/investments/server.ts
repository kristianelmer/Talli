import {
  loadInvestmentAcquisitionLots,
  loadInvestmentPositions,
  loadInvestmentActivity,
  loadInvestmentShareSaleAllocations,
} from "./transport.ts";
import {
  presentAcquisitionLots,
  presentInvestmentPositions,
  presentInvestmentActivity,
  type AcquisitionLotPresentation,
  type InvestmentPositionPresentation,
  type InvestmentActivityPresentation,
  presentShareSaleAllocations,
  type ShareSaleAllocationPresentation,
} from "./presentation.ts";

export async function listPresentedInvestmentActivity(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ actions: InvestmentActivityPresentation[]; error: string | null }> {
  try {
    return {
      actions: presentInvestmentActivity(
        await loadInvestmentActivity(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return { actions: [], error: "Kunne ikke laste investeringsaktiviteten." };
  }
}

export async function listPresentedInvestmentPositions(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ positions: InvestmentPositionPresentation[]; error: string | null }> {
  try {
    return {
      positions: presentInvestmentPositions(
        await loadInvestmentPositions(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return { positions: [], error: "Kunne ikke laste investeringene." };
  }
}

export async function listPresentedAcquisitionLots(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ lots: AcquisitionLotPresentation[]; error: string | null }> {
  try {
    return {
      lots: presentAcquisitionLots(
        await loadInvestmentAcquisitionLots(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return { lots: [], error: "Kunne ikke laste investeringspartiene." };
  }
}

export async function listPresentedShareSaleAllocations(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ allocations: ShareSaleAllocationPresentation[]; error: string | null }> {
  try {
    return {
      allocations: presentShareSaleAllocations(
        await loadInvestmentShareSaleAllocations(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return { allocations: [], error: "Kunne ikke laste FIFO-fordelingene." };
  }
}
