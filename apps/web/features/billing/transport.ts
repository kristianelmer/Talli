import {
  createTalliApiClient,
  TalliApiError,
  type BillingCompanyWire,
  type BillingConfigureWire,
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

export function configureBillingAccount(
  accessToken: string,
  body: BillingConfigureWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingConfigureAccount(body, mutation(operationId, requestId));
}

export function activateBillingSubscription(
  accessToken: string,
  body: BillingCompanyWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingActivateSubscription(body, mutation(operationId, requestId));
}

export function cancelBillingSubscription(
  accessToken: string,
  body: BillingCompanyWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingCancelSubscription(body, mutation(operationId, requestId));
}

export function purchaseBillingFilingPackage(
  accessToken: string,
  body: BillingFilingPackageWire,
  operationId: string,
  requestId?: string,
) {
  return client(accessToken).billingPurchaseFilingPackage(body, mutation(operationId, requestId));
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
