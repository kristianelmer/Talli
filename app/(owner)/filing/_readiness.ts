import type { AuthorityObligation } from "../../lib/authority-permission";
import { buildAnnualAccountsPayload } from "../../lib/annual-accounts";
import { buildAnnualCloseBasis } from "../../lib/annual-corporate-documents";
import type { AnnualReadinessInput } from "../../lib/annual-readiness";
import { corporateAnnualSourceHash } from "../../lib/corporate-decision-facts";
import type { WorkspaceData } from "../../lib/workspace-data";

export { obligationFilingString } from "./_presentation";

/** Owner-facing filing obligations, in the order shown on the hub. */
export const FILING_OBLIGATIONS: AuthorityObligation[] = [
  "aksjonaerregisteroppgaven",
  "skattemelding",
  "aarsregnskap",
];

export function isFilingObligation(value: string): value is AuthorityObligation {
  return (FILING_OBLIGATIONS as string[]).includes(value);
}

/**
 * Builds the pure readiness input from the loaded workspace dataset, scoped to
 * the primary company. Mirrors the arrays passed by refreshAnnualReadinessSnapshots
 * so the live readiness shown to the owner matches the stored snapshot.
 */
export function buildReadinessInput(data: WorkspaceData): AnnualReadinessInput | null {
  const company = data.companies.find((item) => item.id === data.primaryCompanyId);
  if (!company) return null;
  const companyId = company.id;
  const scope = <T extends { company_id: string }>(rows: T[]) =>
    rows.filter((row) => row.company_id === companyId);
  const annualDecision = data.corporateDecisions.find(
    (decision) => decision.company_id === companyId
      && decision.income_year === data.primaryIncomeYear
      && decision.decision_kind === "annual_close",
  ) ?? null;
  const annualDocumentSet = annualDecision
    ? data.corporateDocumentSets.find((set) => set.decision_id === annualDecision.id) ?? null
    : null;
  let currentAnnualSourceHash = "";
  if (data.primaryAnnualData) {
    try {
      const annualBasis = buildAnnualCloseBasis({
        annualData: data.primaryAnnualData,
        annualAccountsPayload: buildAnnualAccountsPayload({
          incomeYear: data.primaryIncomeYear,
          annualData: data.primaryAnnualData,
          ledgerEntries: scope(data.entries).filter(
            (entry) => entry.income_year === data.primaryIncomeYear,
          ),
        }),
      });
      currentAnnualSourceHash = corporateAnnualSourceHash(annualBasis);
    } catch {
      currentAnnualSourceHash = "";
    }
  }

  return {
    company,
    incomeYear: data.primaryIncomeYear,
    setups: scope(data.setups),
    ledgerEntries: scope(data.entries),
    holdingActions: scope(data.actions),
    bankTransactions: scope(data.transactions),
    documents: scope(data.documents),
    overrides: scope(data.overrides),
    locks: scope(data.locks),
    annualData: data.primaryAnnualData ?? null,
    billingAccount: data.primaryBillingAccount ?? null,
    authorityPermissions: data.primaryAuthorityPermissions,
    filingPreviews: scope(data.previews),
    filingSubmissions: scope(data.submissions),
    corporateDocuments: {
      enabled: process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true",
      lifecycle: {
        currentDecisionHash: annualDecision?.decision_hash ?? "",
        currentSourceHash: currentAnnualSourceHash,
        decision: annualDecision ? {
          id: annualDecision.id,
          decision_kind: annualDecision.decision_kind,
          decision_hash: annualDecision.decision_hash,
          source_hash: annualDecision.source_hash,
        } : null,
        documentSet: annualDocumentSet ? {
          id: annualDocumentSet.id,
          decision_id: annualDocumentSet.decision_id,
          decision_hash: annualDocumentSet.decision_hash,
        } : null,
        artifacts: annualDocumentSet
          ? data.corporateDocumentArtifacts.filter((artifact) => artifact.set_id === annualDocumentSet.id)
          : [],
        events: annualDecision
          ? data.corporateDocumentEvents.filter((event) => event.decision_id === annualDecision.id)
          : [],
        finalizations: annualDecision
          ? data.corporateDecisionFinalizations.filter(
              (finalization) => finalization.decision_id === annualDecision.id,
            )
          : [],
      },
    },
  };
}
