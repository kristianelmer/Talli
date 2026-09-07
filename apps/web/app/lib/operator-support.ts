import { TalliApiError, type SupportCaseResources } from "@talli/talli-api-client";

export type OperatorReadRecovery = "sign-in" | "step-up" | "forbidden" | "unavailable";

export function operatorReadRecovery(error: unknown): OperatorReadRecovery {
  if (!(error instanceof TalliApiError)) return "unavailable";
  if (error.status === 401) return "sign-in";
  if (error.status === 403) {
    return ["FRESH_MFA_REQUIRED", "AAL2_REQUIRED", "BILLING_STEP_UP_REQUIRED"].includes(error.problem?.code ?? "")
      ? "step-up" : "forbidden";
  }
  return "unavailable";
}

export function operatorRecoveryHref(recovery: OperatorReadRecovery, returnTo: string) {
  if (recovery === "sign-in") return `/login?reauth=1&next=${encodeURIComponent(returnTo)}`;
  if (recovery === "step-up") return `/mfa?fresh=1&next=${encodeURIComponent(returnTo)}`;
  return returnTo.split("#")[0];
}

export type OperatorAnnualRefundSelection = {
  companyId?: string;
  purchaseId?: string;
  refundRequestId?: string;
  beforeRefundRequestId?: string;
};

export function operatorSupportLocation(params?: {
  supportCase?: unknown; annualBefore?: unknown; companyId?: unknown;
  refundPurchaseId?: unknown; refundRequestId?: unknown; beforeRefundRequestId?: unknown;
}) {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  let invalid = false;
  function identity(value: unknown) {
    if (value === undefined) return undefined;
    if (typeof value === "string" && uuid.test(value)) return value;
    invalid = true;
    return undefined;
  }
  const supportCaseId = identity(params?.supportCase) ?? "";
  const beforePurchaseId = identity(params?.annualBefore);
  const companyId = identity(params?.companyId);
  const purchaseId = identity(params?.refundPurchaseId);
  const refundRequestId = identity(params?.refundRequestId);
  const beforeRefundRequestId = identity(params?.beforeRefundRequestId);
  if ((!supportCaseId && (beforePurchaseId || companyId || purchaseId || refundRequestId || beforeRefundRequestId))
      || (purchaseId && !companyId) || ((refundRequestId || beforeRefundRequestId) && !purchaseId)) invalid = true;
  const query = new URLSearchParams();
  if (supportCaseId) query.set("supportCase", supportCaseId);
  if (beforePurchaseId) query.set("annualBefore", beforePurchaseId);
  if (companyId) query.set("companyId", companyId);
  if (purchaseId) query.set("refundPurchaseId", purchaseId);
  if (refundRequestId) query.set("refundRequestId", refundRequestId);
  if (beforeRefundRequestId) query.set("beforeRefundRequestId", beforeRefundRequestId);
  return {
    supportCaseId, beforePurchaseId, companyId, purchaseId, refundRequestId, beforeRefundRequestId,
    returnTo: supportCaseId ? `/operator?${query}#annual-billing` : "/operator",
    invalid,
  };
}

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
