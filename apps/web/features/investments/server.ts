import {
  loadInvestmentAcquisitionLots,
  loadInvestmentPositions,
} from "./transport.ts";
import {
  presentAcquisitionLots,
  presentInvestmentPositions,
  type AcquisitionLotPresentation,
  type InvestmentPositionPresentation,
} from "./presentation.ts";

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
