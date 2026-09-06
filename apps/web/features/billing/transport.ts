import {
  createTalliApiClient,
  TalliApiError,
  type AnnualBillingSnapshotRequest,
  type AnnualPurchaseHistoryRequest,
  type AnnualRefundRecoveryTargetsRequest,
  type AnnualRefundRecoveryCommandWire,
  type AnnualSupportRequest,
  type AnnualAgreementCleanupCommandWire,
  type AnnualCheckoutObservationCommandWire,
  type AnnualRenewalCancellationCommandWire,
  type BillingAccountWire,
  type BillingCompanyWire,
  type BillingEntitlementRequest,
  type BillingFilingPackageWire,
  type BillingPilotEntitlementCommandWire,
  type BillingSnapshotRequest,
  type BillingUnsupportedWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(10_000) };
}

function mutation(idempotencyKey: string, requestId?: string) {
  return { ...request(requestId), idempotencyKey };
}

export function loadAnnualSupportPurchases(accessToken: string, input: AnnualSupportRequest) {
  return client(accessToken).billingReadAnnualSupportPurchases({ ...input, ...request(input.requestId) });
}

export async function loadAnnualPurchaseHistory(accessToken: string, input: AnnualPurchaseHistoryRequest) {
  try {
    return await client(accessToken).billingReadAnnualPurchaseHistory({ ...input, ...request(input.requestId) });
  } catch (error) {
    // A predecessor backend has no such route. A scoped BILLING_NOT_FOUND
    // problem is an invalid cursor, and must remain an error.
    if (error instanceof TalliApiError && error.status === 404 && !error.problem) return null;
    throw error;
  }
}

export async function loadAnnualRefundRecoveryTargets(accessToken: string, input: AnnualRefundRecoveryTargetsRequest) {
  try {
    return await client(accessToken).billingReadAnnualRefundRecoveryTargets({ ...input, ...request(input.requestId) });
  } catch (error) {
    if (error instanceof TalliApiError && error.status === 404 && !error.problem) return null;
    throw error;
  }
}

export function recoverAnnualRefund(accessToken: string, body: AnnualRefundRecoveryCommandWire) {
  return client(accessToken).billingRecoverAnnualRefund(body, request());
}

export async function loadAnnualBillingSnapshot(accessToken: string, input: AnnualBillingSnapshotRequest) {
  const api = client(accessToken);
  try {
    return await api.billingReadAnnualRefundSnapshot({ ...input, ...request(input.requestId) });
  } catch (error) {
    // During web-first deployment the predecessor backend lacks this read.
    // Keep history available, with refund details explicitly unavailable.
    if (!(error instanceof TalliApiError && error.status === 404)) throw error;
    return api.billingReadAnnualSnapshot({ ...input, ...request(input.requestId) });
  }
}

export function cancelAnnualRenewal(
  accessToken: string,
  body: AnnualRenewalCancellationCommandWire,
  operationId: string,
) {
  return client(accessToken).billingCancelAnnualRenewal(body, mutation(operationId));
}

export function cleanupAnnualAgreement(
  accessToken: string,
  body: AnnualAgreementCleanupCommandWire,
  requestId?: string,
) {
  return client(accessToken).billingCleanupAnnualAgreement(body, request(requestId));
}

export function observeAnnualCheckout(
  accessToken: string,
  body: AnnualCheckoutObservationCommandWire,
  requestId?: string,
) {
  return client(accessToken).billingObserveAnnualCheckout(body, request(requestId));
}

export function annualBillingRecovery(error: unknown): "sign-in" | "step-up" | "unavailable" {
  if (error instanceof TalliApiError && error.status === 401) return "sign-in";
  if (error instanceof TalliApiError && error.problem?.code === "BILLING_STEP_UP_REQUIRED") {
    return "step-up";
  }
  return "unavailable";
}

export function annualBillingAccessRejected(error: unknown): boolean {
  return error instanceof TalliApiError && (error.status === 401 || error.status === 403);
}

export function loadBillingSnapshot(
  accessToken: string,
  input: BillingSnapshotRequest,
) {
  return client(accessToken).billingReadSnapshot({ ...input, ...request(input.requestId) });
}

export function loadBillingEntitlement(
  accessToken: string,
  input: BillingEntitlementRequest,
) {
  return client(accessToken).billingReadEntitlement({ ...input, ...request(input.requestId) });
}

export async function loadAnnualBillingEntitlements(
  accessToken: string,
  companyId: string,
  incomeYear: number,
) {
  const entries = await Promise.all(
    (["aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"] as const).map(
      async (obligation) => [obligation, await loadBillingEntitlement(accessToken, {
        companyId,
        incomeYear,
        obligation,
        ...(obligation === "aksjonaerregisteroppgaven"
          ? { caseProfile: "rf1086_no_activity_v1" }
          : {}),
      })] as const,
    ),
  );
  return Object.fromEntries(entries);
}

export function presentBillingAccount(account: BillingAccountWire) {
  return {
    company_id: account.companyId,
    pricing_plan: account.pricingPlan,
    monthly_nok: account.monthlyNok,
    filing_package_nok: account.filingPackageNok,
    founder_cohort_number: account.founderCohortNumber,
    subscription_active: account.subscriptionActive,
    filing_package_paid: account.filingPackagePaid,
    supported_case: account.supportedCase,
    refund_eligible: account.refundEligible,
    refund_completed: account.refundCompleted,
    no_charge_reason: account.noChargeReason,
    provider_customer_ref: account.providerCustomerReference,
    subscription_provider_ref: account.subscriptionProviderReference,
    filing_package_payment_ref: account.filingPackagePaymentReference,
    refund_provider_ref: account.refundProviderReference,
    updated_by: account.updatedBy,
    created_at: account.createdAt,
    updated_at: account.updatedAt,
  };
}

export function cancelBillingSubscription(
  accessToken: string,
  body: BillingCompanyWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingCancelSubscription(body, mutation(operationId, requestId));
}

export function refundBillingFilingPackage(
  accessToken: string,
  body: BillingFilingPackageWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingRefundFilingPackage(body, mutation(operationId, requestId));
}

export function markBillingCaseUnsupported(
  accessToken: string,
  body: BillingUnsupportedWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingMarkUnsupported(body, mutation(operationId, requestId));
}

export function manageProductionPilotEntitlement(
  accessToken: string,
  body: BillingPilotEntitlementCommandWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingManagePilotEntitlement(body, mutation(operationId, requestId));
}

export function billingActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    return error.problem?.detail ?? error.problem?.code ?? `Faktureringsfeil (${error.status}).`;
  }
  return error instanceof Error ? error.message : "Faktureringsforespørselen mislyktes.";
}

export function billingOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError) || error.status >= 500;
}
