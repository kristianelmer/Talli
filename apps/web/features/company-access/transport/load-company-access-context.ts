import {
  createTalliApiClient,
  type GrantSupportAccessRequest,
  type OpenSupportCaseRequest,
  type RevokeSupportAccessRequest,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

export {
  BackendConfigurationError,
  backendBaseUrl as companyAccessBackendBaseUrl,
  type BackendConfigurationErrorCode,
} from "#backend-configuration";

export async function loadCompanyAccessContext(
  accessToken: string,
  requestId?: string,
  options: { companyId?: string } = {},
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  return client.companyAccessGetSelectedContext({
    ...options,
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function loadCompanyAccessRecord(
  accessToken: string,
  companyId: string,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessGetCompanyRecord(companyId, {
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function loadOperatorContext(
  accessToken: string,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessGetOperatorContext({
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function grantOperatorSupportAccess(
  accessToken: string,
  command: GrantSupportAccessRequest,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessGrantSupportAccess(command, {
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function revokeOperatorSupportAccess(
  accessToken: string,
  caseId: string,
  command: RevokeSupportAccessRequest,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessRevokeSupportAccess(caseId, command, {
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function openOperatorSupportCase(
  accessToken: string,
  caseId: string,
  command: OpenSupportCaseRequest,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessOpenSupportCase(caseId, command, {
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function readOperatorSupportCase(
  accessToken: string,
  caseId: string,
  requestId?: string,
) {
  const client = createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.companyAccessReadSupportCase(caseId, {
    requestId,
    signal: AbortSignal.timeout(10_000),
  });
}
