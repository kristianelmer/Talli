import type { AuthorityObligation } from "../../lib/authority-permission";
import type { AnnualReadinessInput } from "../../lib/annual-readiness";
import type { WorkspaceData } from "../../lib/workspace-data";

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
 * Maps the obligation enum to the `filing` string stored on preview/submission
 * rows (these use Norwegian spelling with accents, unlike the enum).
 */
export function obligationFilingString(obligation: AuthorityObligation): string {
  if (obligation === "aksjonaerregisteroppgaven") return "aksjonærregisteroppgaven";
  if (obligation === "skattemelding") return "skattemelding for AS";
  return "årsregnskap";
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
  };
}
