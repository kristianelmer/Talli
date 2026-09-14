import {
  loadAnnualAccountsFilingWorkspace, presentAnnualAccountsPreview, presentAnnualAccountsSubmission,
  presentAnnualAccountsOverride, presentAnnualAccountsComment, presentAnnualAccountsPermission,
  presentAnnualAccountsTestEvidence,
} from "../../features/annual-accounts-filing/index.ts";

// Compose one complete owned Accounts read per company.
export async function loadPresentedAnnualAccountsSource(accessToken: string | null, companyIds: string[], incomeYear?: number) {
  try {
    if (!accessToken) {
      if (companyIds.length) throw new Error("Accounts filing authentication is unavailable.");
      return { error: null, previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] };
    }
    const sources = await Promise.all(companyIds.map(companyId => loadAnnualAccountsFilingWorkspace(accessToken, companyId, incomeYear ?? null)));
    return {
      error: null,
      previews: sources.flatMap(source => source.previews.map(presentAnnualAccountsPreview)),
      submissions: sources.flatMap(source => source.submissions.map(presentAnnualAccountsSubmission)),
      overrides: sources.flatMap(source => source.overrides.map(presentAnnualAccountsOverride)),
      comments: sources.flatMap(source => source.reviewComments.map(presentAnnualAccountsComment)),
      authorityPermissions: sources.flatMap(source => source.permissions.map(presentAnnualAccountsPermission)),
      authorityTestRuns: sources.flatMap(source => source.testEvidence.map(presentAnnualAccountsTestEvidence)),
    };
  } catch {
    return { error: "Årsregnskapsgrunnlaget kunne ikke leses. Prøv igjen.", previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] };
  }
}
