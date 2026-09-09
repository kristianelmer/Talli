import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` } });
}
// Preserve the existing bounded, sequential RF send and initial feedback polling.
function request() { return { signal: AbortSignal.timeout(300_000) }; }

export async function sendApprovedRf1086ThroughApi(accessToken: string, approvalId: string) {
  return client(accessToken).legacyRf1086SendApprovedFiling({ approvalId }, request());
}

export async function reconcileRf1086ThroughApi(accessToken: string, submissionId: string) {
  return client(accessToken).legacyRf1086ReconcileFeedback({ submissionId }, request());
}

const codes = new Set(["invalid_request", "authentication_required", "configuration_unavailable", "approval_expired",
  "basis_unavailable", "connection_unavailable", "payload_changed", "send_unavailable", "status_unavailable", "status_busy", "step_up_required"]);
export function rf1086ApiErrorCode(error: unknown) {
  if (error instanceof TalliApiError && error.problem?.code && codes.has(error.problem.code)) return error.problem.code;
  return "status_unavailable";
}
