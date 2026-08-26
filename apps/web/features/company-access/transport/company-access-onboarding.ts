import {
  createTalliApiClient,
  type CompanyAgreementAcceptanceRequest,
  type CompanyOnboardingRequest,
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

export function onboardCompanyThroughApi(
  accessToken: string,
  command: CompanyOnboardingRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessOnboardCompany(command, request(requestId));
}

export function reacceptCompanyAgreementThroughApi(
  accessToken: string,
  command: CompanyAgreementAcceptanceRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessReacceptAgreement(command, request(requestId));
}
