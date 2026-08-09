import {
  createTalliApiClient,
  type FinalizeCompanyDeletionRequest,
  type RequestCompanyCancellationRequest,
  type ResumeCompanyCancellationRequest,
  type ReviewCompanyDeletionRequest,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

// Backend worst case: authorization/company reads plus command/reconcile retry
// sequence, each bounded at five seconds. The outer caller retains 10s margin.
export const COMPANY_ACCESS_BACKEND_WORST_CASE_MS = 35_000;
export const COMPANY_ACCESS_CANCELLATION_TIMEOUT_MS = 45_000;

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(COMPANY_ACCESS_CANCELLATION_TIMEOUT_MS) };
}

export function listCompanyCancellations(
  accessToken: string,
  companyId: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessListCancellations(companyId, request(requestId));
}

export function requestCompanyCancellation(
  accessToken: string,
  command: RequestCompanyCancellationRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessRequestCancellation(command, request(requestId));
}

export function reviewCompanyDeletion(
  accessToken: string,
  cancellationId: string,
  command: ReviewCompanyDeletionRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessReviewDeletion(
    cancellationId,
    command,
    request(requestId),
  );
}

export function resumeCompanyCancellation(
  accessToken: string,
  cancellationId: string,
  command: ResumeCompanyCancellationRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessResumeCancellation(
    cancellationId,
    command,
    request(requestId),
  );
}

export function finalizeCompanyDeletion(
  accessToken: string,
  cancellationId: string,
  command: FinalizeCompanyDeletionRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessFinalizeDeletion(
    cancellationId,
    command,
    request(requestId),
  );
}
