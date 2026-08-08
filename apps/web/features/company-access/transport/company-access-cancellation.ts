import {
  createTalliApiClient,
  type FinalizeCompanyDeletionRequest,
  type RequestCompanyCancellationRequest,
  type ReviewCompanyDeletionRequest,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(25_000) };
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
