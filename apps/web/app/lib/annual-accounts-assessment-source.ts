import { previewAnnualAccountsReadiness, type AnnualAccountsReadinessPreviewRequest } from "../../features/annual-accounts-filing/index.ts";

export async function loadAnnualAccountsAssessmentSource(input: {
  accessToken: string | null;
  companyId: string | null;
  incomeYear: number;
  annualData: AnnualAccountsReadinessPreviewRequest["annualData"];
  ledgerEntries: AnnualAccountsReadinessPreviewRequest["ledgerEntries"];
  corporateEnabled: boolean;
  corporateBlockers: AnnualAccountsReadinessPreviewRequest["corporateBlockers"];
  sourceUnavailable: boolean;
}) {
  if (!input.companyId) return { readiness: null, error: null };
  try {
    if (!input.accessToken || input.sourceUnavailable) throw new Error("Accounts source is unavailable.");
    const readiness = await previewAnnualAccountsReadiness(input.accessToken, {
      companyId: input.companyId, incomeYear: input.incomeYear, annualData: input.annualData ?? null,
      ledgerEntries: input.ledgerEntries.filter(row => row.company_id === input.companyId),
      corporateEnabled: input.corporateEnabled, corporateBlockers: input.corporateBlockers,
    });
    return { readiness, error: null };
  } catch {
    return { readiness: null, error: "Årsregnskapsgrunnlaget kunne ikke vurderes. Prøv igjen." };
  }
}
