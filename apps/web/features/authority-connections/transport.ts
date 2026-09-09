import {
  createTalliApiClient,
  TalliApiError,
  type AuthorityOperationCommandWire,
  type SystemUserCommandWire,
  type SystemUserResultWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// A provider reconciliation can make several bounded reads in sequence.
function request() { return { signal: AbortSignal.timeout(90_000) }; }

function checked(value: SystemUserResultWire, requestId: string, companyId?: string) {
  if (value.requestId !== requestId || (companyId !== undefined && value.companyId !== companyId)) {
    throw new TalliApiError(502, undefined);
  }
  if (value.confirmationUrl !== null) {
    let url;
    try { url = new URL(value.confirmationUrl); } catch { throw new TalliApiError(502, undefined); }
    if (url.protocol !== "https:" || url.username || url.password || url.hash) {
      throw new TalliApiError(502, undefined);
    }
  }
  return value;
}

export async function loadSystemUserRequests(accessToken: string, companyIds: string[]) {
  const uniqueIds = [...new Set(companyIds)];
  if (uniqueIds.length === 0) return [];
  const requests = [];
  const api = client(accessToken);
  for (let offset = 0; offset < uniqueIds.length; offset += 100) {
    const batch = uniqueIds.slice(offset, offset + 100);
    const result = await api.authorityConnectionsListSystemUserRequests(batch, request());
    if (result.requests.some((value) => !batch.includes(value.companyId))) throw new TalliApiError(502, undefined);
    requests.push(...result.requests);
  }
  return requests.sort((left, right) => (right.createdAt ?? "").localeCompare(left.createdAt ?? ""));
}

export async function startOwnerSystemUserRequest(accessToken: string, body: SystemUserCommandWire) {
  return checked(await client(accessToken).authorityConnectionsStartSystemUserRequest(body, request()), body.requestId, body.companyId);
}

export async function refreshOwnerSystemUserRequest(accessToken: string, body: SystemUserCommandWire) {
  return checked(await client(accessToken).authorityConnectionsRetrySystemUserRequest(body, request()), body.requestId, body.companyId);
}

export async function reconcileOwnerSystemUserCallback(accessToken: string, requestId: string, proof: string) {
  return checked(await client(accessToken).authorityConnectionsReconcileSystemUserCallback({ requestId }, proof, request()), requestId);
}


export async function loadAuthorityOperations(accessToken: string) {
  return (await client(accessToken).authorityConnectionsListOperations(request())).operations;
}

export async function runAuthorityOperation(accessToken: string, body: AuthorityOperationCommandWire) {
  const result = await client(accessToken).authorityConnectionsRunOperation(body, request());
  if (result.operationId !== body.operationId || result.operation !== body.operation) throw new TalliApiError(502, undefined);
  return result;
}

export function authorityOperationErrorCode(error: unknown): string {
  if (error instanceof TalliApiError && error.problem?.code && /^[a-z_]{1,80}$/.test(error.problem.code)) {
    return error.problem.code;
  }
  return "authority_operation_failed";
}
