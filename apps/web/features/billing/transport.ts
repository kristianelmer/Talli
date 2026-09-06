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
  type AnnualCheckoutCommandWire,
  type AnnualCheckoutWire,
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

export async function prepareAnnualCheckout(accessToken: string, companyId: string, incomeYear: number) {
  try {
    const result = await client(accessToken).billingPrepareAnnualCheckout(companyId, incomeYear, request());
    if (result.companyId !== companyId || result.incomeYear !== incomeYear
      || (result.state === "available" && (!result.offer || !result.consentVersion || result.purchaseId !== null
        || result.offer.companyId !== companyId || result.offer.incomeYear !== incomeYear))
      || (result.state === "existing" && (result.offer !== null || result.consentVersion !== null || !result.purchaseId))) {
      throw new TalliApiError(502, undefined);
    }
    return result;
  } catch (error) {
    // Web-first overlap: a predecessor has no preparation route.
    if (error instanceof TalliApiError && error.status === 404 && !error.problem) return null;
    throw error;
  }
}

function checkedCheckout(value: AnnualCheckoutWire, companyId: string, purchaseId?: string) {
  if (value.companyId !== companyId || value.offer.companyId !== companyId
    || value.incomeYear !== value.offer.incomeYear || (purchaseId && value.purchaseId !== purchaseId)) {
    throw new TalliApiError(502, undefined);
  }
  if (value.checkoutUrl !== null) {
    let url;
    try { url = new URL(value.checkoutUrl); } catch { throw new TalliApiError(502, undefined); }
    // Provider origin approval belongs to the backend adapter. This boundary
    // also rejects browser-executable URLs and inconsistent terminal links.
    if (value.status !== "pending" || url.protocol !== "https:" || url.username || url.password || url.hash) {
      throw new TalliApiError(502, undefined);
    }
  }
  return value;
}

export async function startAnnualCheckout(
  accessToken: string, body: AnnualCheckoutCommandWire, idempotencyKey: string,
) {
  const value = checkedCheckout(await client(accessToken).billingStartAnnualCheckout(body, mutation(idempotencyKey)), body.companyId);
  if (value.incomeYear !== body.incomeYear || value.offer.offerVersion !== body.offerVersion
    || value.offer.termsDigest !== body.termsDigest) throw new TalliApiError(502, undefined);
  return value;
}

export async function withdrawAnnualCheckoutRequest(
  accessToken: string, body: AnnualCheckoutCommandWire, idempotencyKey: string,
) {
  const value = await client(accessToken).billingWithdrawAnnualCheckoutRequest(body, mutation(idempotencyKey));
  if (value.companyId !== body.companyId || value.incomeYear !== body.incomeYear
    || (value.state === "withdrawn" && (value.purchaseId !== null || !value.withdrawalId || !value.withdrawnAt))
    || (value.state === "existing" && (!value.purchaseId || value.withdrawalId !== null || value.withdrawnAt !== null))) {
    throw new TalliApiError(502, undefined);
  }
  return value;
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

export async function observeAnnualCheckout(
  accessToken: string,
  body: AnnualCheckoutObservationCommandWire,
  requestId?: string,
) {
  return checkedCheckout(await client(accessToken).billingObserveAnnualCheckout(body, request(requestId)), body.companyId, body.purchaseId);
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

export function annualCheckoutNeedsWithdrawal(error: unknown): boolean {
  return error instanceof TalliApiError && ["BILLING_INVALID_INPUT", "BILLING_IDEMPOTENCY_KEY_REUSED", "BILLING_CHECKOUT_REQUEST_WITHDRAWN"].includes(error.problem?.code ?? "");
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
