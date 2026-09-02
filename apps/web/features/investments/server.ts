import {
  loadInvestmentAcquisitionLots,
  loadInvestmentPositions,
  loadInvestmentActivity,
  loadInvestmentEconomicEvents,
  loadInvestmentShareSaleAllocations,
  loadInvestmentCorrections,
} from "./transport.ts";
import {
  presentAcquisitionLots,
  presentInvestmentPositions,
  presentInvestmentActivity,
  presentInvestmentLifecycleEvents,
  type AcquisitionLotPresentation,
  type InvestmentPositionPresentation,
  type InvestmentActivityPresentation,
  presentShareSaleAllocations,
  type ShareSaleAllocationPresentation,
  presentInvestmentCorrections,
  type InvestmentCorrectionPresentation,
} from "./presentation.ts";

export async function listPresentedInvestmentActivity(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ actions: InvestmentActivityPresentation[]; error: string | null }> {
  try {
    const [legacy, lifecycle] = await Promise.all([
      loadInvestmentActivity(accessToken, companyIds),
      loadInvestmentEconomicEvents(accessToken, companyIds),
    ]);
    const byId = new Map(
      presentInvestmentActivity(legacy).map((item) => [item.id, item]),
    );
    for (const item of presentInvestmentLifecycleEvents(lifecycle)) {
      byId.set(item.id, item);
    }
    return {
      actions: [...byId.values()],
      error: null,
    };
  } catch {
    return { actions: [], error: "Kunne ikke laste investeringsaktiviteten." };
  }
}

export async function listPresentedInvestmentLifecycleEvents(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ actions: InvestmentActivityPresentation[]; error: string | null }> {
  try {
    return {
      actions: presentInvestmentLifecycleEvents(
        await loadInvestmentEconomicEvents(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return {
      actions: [],
      error: "Kunne ikke laste investeringshendelsene.",
    };
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

export async function listPresentedInvestmentCorrections(
  accessToken: string,
  companyIds: readonly string[],
): Promise<{ corrections: InvestmentCorrectionPresentation[]; error: string | null }> {
  try {
    return {
      corrections: presentInvestmentCorrections(
        await loadInvestmentCorrections(accessToken, companyIds),
      ),
      error: null,
    };
  } catch {
    return { corrections: [], error: "Kunne ikke laste investeringskorrigeringene." };
  }
}
