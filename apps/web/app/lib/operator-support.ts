import type {
  AuthorityPermissionRow,
  BillingAccountRow,
  BillingPaymentEventRow,
  CompanyCancellationRow,
  CompanyWorkspaceRow,
  FilingReadinessSnapshotRow,
  FilingSubmissionRow,
} from "./supabase/server";

export type SupportAuditRow = {
  id: string;
  company_id: string;
  actor_id: string | null;
  category: string;
  action: string;
  message: string;
  created_at: string;
};

export type OperatorSupportSummary = {
  companyId: string;
  orgNumber: string;
  companyName: string;
  filingStatus: string;
  readinessBlockCount: number;
  authorityProductionEnabled: number;
  billingStatus: string;
  refundStatus: string;
  restoreStatus: string;
  recentAuditActions: string[];
};

export function assertOperatorSearchAllowed(input: { isOperator: boolean; query: string }) {
  if (!input.isOperator) {
    throw new Error("operator_access_required");
  }
  if (input.query.trim().length < 3) {
    throw new Error("operator_search_query_too_short");
  }
}

export function buildOperatorSupportSummaries(input: {
  companies: CompanyWorkspaceRow[];
  readinessSnapshots: FilingReadinessSnapshotRow[];
  submissions: FilingSubmissionRow[];
  authorityPermissions: AuthorityPermissionRow[];
  billingAccounts: BillingAccountRow[];
  billingPaymentEvents: BillingPaymentEventRow[];
  cancellations: CompanyCancellationRow[];
  auditEvents: SupportAuditRow[];
}): OperatorSupportSummary[] {
  return input.companies.map((company) => {
    const readiness = input.readinessSnapshots.filter((snapshot) => snapshot.company_id === company.id);
    const submissions = input.submissions.filter((submission) => submission.company_id === company.id);
    const billing = input.billingAccounts.find((account) => account.company_id === company.id);
    const cancellation = input.cancellations.find((item) => item.company_id === company.id);
    const paymentEvents = input.billingPaymentEvents.filter((event) => event.company_id === company.id);
    const auditEvents = input.auditEvents
      .filter((event) => event.company_id === company.id)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));

    const failedSubmission = submissions.find((submission) => submission.status === "failed");
    const latestSubmission = submissions[0];
    const missingRestoreEvidence = !auditEvents.some((event) => event.action.includes("restore"));

    return {
      companyId: company.id,
      orgNumber: company.org_number,
      companyName: company.name,
      filingStatus: failedSubmission?.status ?? latestSubmission?.status ?? "no_submission",
      readinessBlockCount: readiness.reduce((sum, snapshot) => sum + (snapshot.hard_blocks?.length ?? 0), 0),
      authorityProductionEnabled: input.authorityPermissions.filter(
        (permission) => permission.company_id === company.id && permission.production_enabled,
      ).length,
      billingStatus: billing?.refund_completed
        ? "refund_completed"
        : billing?.refund_eligible
          ? "refund_eligible"
          : billing?.filing_package_paid
            ? "paid"
            : billing?.subscription_active
              ? "subscription_active"
              : "unpaid",
      refundStatus: billing?.refund_completed
        ? billing.refund_provider_ref ?? "refund_completed"
        : billing?.refund_eligible
          ? "refund_eligible"
          : "none",
      restoreStatus: missingRestoreEvidence || cancellation?.evidence?.missingDocumentIds?.length ? "missing_evidence" : "ok",
      recentAuditActions: auditEvents.slice(0, 5).map((event) => event.action),
    };
  });
}
