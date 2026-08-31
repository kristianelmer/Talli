import type { SupportCaseResources } from "@talli/talli-api-client";

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
  cancellationId: string | null;
  cancellationStatus: string | null;
  cancellationUpdatedAt: string | null;
};

export function buildOperatorSupportSummaries(
  resources: SupportCaseResources,
): OperatorSupportSummary[] {
  return resources.companies.map((company) => {
    const readiness = resources.filingReadinessSnapshots.filter(
      (snapshot) => snapshot.companyId === company.id,
    );
    const submissions = resources.filingSubmissions.filter(
      (submission) => submission.companyId === company.id,
    );
    const billing = resources.billingAccounts.find(
      (account) => account.companyId === company.id,
    );
    const cancellation = resources.companyCancellations.find(
      (item) => item.companyId === company.id,
    );
    const auditEvents = resources.auditEvents
      .filter((event) => event.companyId === company.id)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

    const failedSubmission = submissions.find(
      (submission) => submission.status === "failed",
    );
    const latestSubmission = submissions[0];
    const missingRestoreEvidence = !auditEvents.some((event) =>
      event.action.includes("restore"),
    );

    return {
      companyId: company.id,
      orgNumber: company.orgNumber,
      companyName: company.name,
      filingStatus:
        failedSubmission?.status ?? latestSubmission?.status ?? "no_submission",
      readinessBlockCount: readiness.reduce(
        (sum, snapshot) => sum + snapshot.hardBlocks.length,
        0,
      ),
      authorityProductionEnabled: resources.authorityPermissions.filter(
        (permission) =>
          permission.companyId === company.id && permission.productionEnabled,
      ).length,
      billingStatus: billing?.refundCompleted
        ? "refund_completed"
        : billing?.refundEligible
          ? "refund_eligible"
          : billing?.filingPackagePaid
            ? "paid"
            : billing?.subscriptionActive
              ? "subscription_active"
              : "unpaid",
      refundStatus: billing?.refundCompleted
        ? (billing.refundProviderRef ?? "refund_completed")
        : billing?.refundEligible
          ? "refund_eligible"
          : "none",
      restoreStatus:
        missingRestoreEvidence ||
        (Array.isArray(cancellation?.evidence.missingDocumentIds) &&
          cancellation.evidence.missingDocumentIds.length > 0)
          ? "missing_evidence"
          : "ok",
      recentAuditActions: auditEvents.slice(0, 5).map((event) => event.action),
      cancellationId: cancellation?.id ?? null,
      cancellationStatus: cancellation?.status ?? null,
      cancellationUpdatedAt: cancellation?.updatedAt ?? null,
    };
  });
}
