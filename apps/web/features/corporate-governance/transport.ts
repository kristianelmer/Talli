import {
  createTalliApiClient,
  type OwnerDividendApprovalWire,
  type OwnerDividendDocumentsWire,
  type OwnerDividendFinalizationWire,
  type OwnerDividendPaymentWire,
  type OwnerDividendProposalWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function mutation(idempotencyKey: string, requestId?: string) {
  return {
    idempotencyKey,
    requestId,
    signal: AbortSignal.timeout(10_000),
  };
}

export function proposeOwnerDividend(
  accessToken: string,
  body: OwnerDividendProposalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceProposeOwnerDividend(
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function registerOwnerDividendDocuments(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendDocumentsWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRegisterOwnerDividendDocuments(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function approveOwnerDividend(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendApprovalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceApproveOwnerDividend(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function finalizeOwnerDividend(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendFinalizationWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceFinalizeOwnerDividend(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function recordOwnerDividendPayment(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendPaymentWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordOwnerDividendPayment(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}
