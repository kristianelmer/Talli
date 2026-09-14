import {
  loadCompanyTaxFilingWorkspace, presentCompanyTaxPreview, presentCompanyTaxSubmission,
  presentCompanyTaxOverride, presentCompanyTaxComment, presentCompanyTaxPermission,
  presentCompanyTaxTestEvidence,
} from "../../features/company-tax-filing/index.ts";

// Compose one complete owned Tax read per company outside the frozen Accounts reads.
export async function loadPresentedCompanyTaxSource(accessToken: string, companyIds: string[], incomeYear?: number) {
  try {
    const sources = await Promise.all(companyIds.map(companyId => loadCompanyTaxFilingWorkspace(accessToken, companyId, incomeYear ?? null)));
    return {
      error: null,
      previews: sources.flatMap(source => source.previews.map(presentCompanyTaxPreview)),
      submissions: sources.flatMap(source => source.submissions.map(presentCompanyTaxSubmission)),
      overrides: sources.flatMap(source => source.overrides.map(presentCompanyTaxOverride)),
      comments: sources.flatMap(source => source.reviewComments.map(presentCompanyTaxComment)),
      authorityPermissions: sources.flatMap(source => source.permissions.map(presentCompanyTaxPermission)),
      authorityTestRuns: sources.flatMap(source => source.testEvidence.map(presentCompanyTaxTestEvidence)),
    };
  } catch {
    return { error: "Skattemeldingsgrunnlaget kunne ikke leses. Prøv igjen.", previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] };
  }
}
