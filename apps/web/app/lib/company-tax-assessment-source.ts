import {
  previewAnnualTaxEstimate, previewCompanyTaxReadiness,
  type CompanyTaxAssessmentFactsRequest,
} from "../../features/company-tax-filing/index.ts";

// The owner workspace historically estimates the whole loaded portfolio, while
// its live readiness receives the primary company's records across loaded years.
// Keep those two snapshots distinct and preserve their original ordering.
export async function loadCompanyTaxAssessmentSource(input: {
  accessToken: string | null;
  companyId: string | null;
  incomeYear: number;
  annualData: CompanyTaxAssessmentFactsRequest["annualData"];
  ledgerEntries: CompanyTaxAssessmentFactsRequest["ledgerEntries"];
  holdingActions: CompanyTaxAssessmentFactsRequest["holdingActions"];
  sourceUnavailable: boolean;
}) {
  if (!input.companyId) return { estimate: null, readiness: null, error: null };
  try {
    if (!input.accessToken || input.sourceUnavailable) throw new Error("Tax assessment source is unavailable.");
    const [estimate, readiness] = await Promise.all([
      previewAnnualTaxEstimate(input.accessToken, { ledgerEntries: input.ledgerEntries, holdingActions: input.holdingActions }),
      previewCompanyTaxReadiness(input.accessToken, {
        companyId: input.companyId, incomeYear: input.incomeYear, annualData: input.annualData ?? null,
        ledgerEntries: input.ledgerEntries.filter(row => row.company_id === input.companyId),
        holdingActions: input.holdingActions.filter(row => row.company_id === input.companyId),
      }),
    ]);
    return { estimate, readiness, error: null };
  } catch {
    return { estimate: null, readiness: null, error: "Skattegrunnlaget kunne ikke vurderes. Prøv igjen." };
  }
}
