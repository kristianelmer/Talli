import {
  createTalliApiClient,
  type CompanyAgreementAcceptanceRequest,
  type CompanyYearAdmissionRequest,
  type CompanyYearEligibilityRecheckRequest,
  type EligibilityDefinitiveRequest,
  type EligibilityPrecheckRequest,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function publicClient() {
  return createTalliApiClient({ baseUrl: backendBaseUrl() });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(10_000) };
}

export function precheckCompanyEligibility(
  command: EligibilityPrecheckRequest,
  requestId?: string,
) {
  return publicClient().companyAccessEligibilityPrecheck(command, request(requestId));
}

export function assessCompanyEligibility(
  command: EligibilityDefinitiveRequest,
  requestId?: string,
) {
  return publicClient().companyAccessEligibilityDefinitive(command, request(requestId));
}

export function admitCompanyYearThroughApi(
  accessToken: string,
  command: CompanyYearAdmissionRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessAdmitCompanyYear(command, request(requestId));
}

export function recheckCompanyYearEligibilityThroughApi(
  accessToken: string,
  companyYearAdmissionId: string,
  command: CompanyYearEligibilityRecheckRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessRecheckCompanyYearEligibility(
    companyYearAdmissionId,
    command,
    request(requestId),
  );
}

export function reacceptCompanyAgreementThroughApi(
  accessToken: string,
  command: CompanyAgreementAcceptanceRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessReacceptAgreement(command, request(requestId));
}
