import {
  createTalliApiClient, TalliApiError,
  type Rf1086GeneratePreviewWire, type Rf1086OverrideCommandWire,
  type Rf1086ReviewCommentCommandWire, type Rf1086ReviewAcknowledgementWire,
  type Rf1086SimulationCommandWire, type Rf1086PermissionCommandWire,
  type Rf1086TestEvidenceCommandWire, type Rf1086ProductionApprovalCommandWire,
  type Rf1086RecordedResultWire, type Rf1086WorkspaceWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` } });
}
function request() { return { signal: AbortSignal.timeout(30_000) }; }
// Preserve the existing bounded, sequential RF send and initial feedback polling.
function authorityRequest() { return { signal: AbortSignal.timeout(300_000) }; }

function recorded(value: Rf1086RecordedResultWire, companyId?: string) {
  if (companyId !== undefined && value.companyId !== companyId) throw new TalliApiError(502, undefined);
  return value;
}

function scopedWorkspace(value: Rf1086WorkspaceWire, companyId: string, incomeYear?: number) {
  if (value.companyId !== companyId || value.incomeYear !== (incomeYear ?? null)) {
    throw new TalliApiError(502, undefined);
  }
  for (const rows of [value.previews, value.simulations, value.overrides, value.reviewComments,
    value.permissions, value.testEvidence, value.approvals, value.productionSubmissions, value.feedbackArtifacts]) {
    if (rows.some((row) => row.companyId !== companyId)
        || new Set(rows.map((row) => row.id)).size !== rows.length) throw new TalliApiError(502, undefined);
  }
  if (incomeYear !== undefined && [value.previews, value.simulations, value.overrides,
    value.approvals, value.productionSubmissions].some((rows) => rows.some((row) => row.incomeYear !== incomeYear))) {
    throw new TalliApiError(502, undefined);
  }
  return value;
}

export async function loadRf1086Workspaces(accessToken: string, companyIds: readonly string[], incomeYear?: number) {
  const api = client(accessToken);
  const results: Rf1086WorkspaceWire[] = [];
  // No year means all retained years; never substitute a current-year-only result.
  for (const companyId of new Set(companyIds)) {
    results.push(scopedWorkspace(await api.rf1086Workspace(companyId, incomeYear, request()), companyId, incomeYear));
  }
  return results;
}

export async function loadRf1086Preview(accessToken: string, previewId: string) {
  const result = await client(accessToken).rf1086Preview(previewId, request());
  if (result.id !== previewId) throw new TalliApiError(502, undefined);
  return result;
}

export async function generateRf1086PreviewThroughApi(accessToken: string, body: Rf1086GeneratePreviewWire) {
  return recorded(await client(accessToken).rf1086GeneratePreview(body, request()), body.companyId);
}
export async function recordRf1086OverrideThroughApi(accessToken: string, body: Rf1086OverrideCommandWire) {
  return recorded(await client(accessToken).rf1086RecordOverride(body, request()));
}
export async function addRf1086ReviewCommentThroughApi(accessToken: string, body: Rf1086ReviewCommentCommandWire) {
  return recorded(await client(accessToken).rf1086AddReviewComment(body, request()));
}
export async function acknowledgeRf1086ReviewCommentThroughApi(accessToken: string, body: Rf1086ReviewAcknowledgementWire) {
  return recorded(await client(accessToken).rf1086AcknowledgeReviewComment(body, request()));
}
export async function confirmRf1086SimulationThroughApi(accessToken: string, body: Rf1086SimulationCommandWire) {
  return recorded(await client(accessToken).rf1086ConfirmSimulation(body, request()));
}
export async function confirmRf1086PermissionThroughApi(accessToken: string, body: Rf1086PermissionCommandWire) {
  return recorded(await client(accessToken).rf1086ConfirmFilingPermission(body, request()), body.companyId);
}
export async function recordRf1086TestEvidenceThroughApi(accessToken: string, body: Rf1086TestEvidenceCommandWire) {
  return recorded(await client(accessToken).rf1086RecordTestEvidence(body, request()), body.companyId);
}
export async function approveRf1086ProductionThroughApi(accessToken: string, body: Rf1086ProductionApprovalCommandWire) {
  return recorded(await client(accessToken).rf1086ApproveProduction(body, request()));
}
export async function sendApprovedRf1086ThroughApi(accessToken: string, approvalId: string) {
  return client(accessToken).legacyRf1086SendApprovedFiling({ approvalId }, authorityRequest());
}
export async function reconcileRf1086ThroughApi(accessToken: string, submissionId: string) {
  return client(accessToken).legacyRf1086ReconcileFeedback({ submissionId }, authorityRequest());
}

const codes = new Set(["invalid_request", "authentication_required", "configuration_unavailable", "approval_expired",
  "basis_unavailable", "connection_unavailable", "payload_changed", "send_unavailable", "status_unavailable", "status_busy", "step_up_required"]);
export function rf1086ApiErrorCode(error: unknown) {
  if (error instanceof TalliApiError && error.problem?.code === "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT") return "invalid_request";
  if (error instanceof TalliApiError && error.problem?.code && codes.has(error.problem.code)) return error.problem.code;
  return "status_unavailable";
}
export function rf1086ActionErrorMessage(error: unknown) {
  const code = error instanceof TalliApiError ? error.problem?.code : undefined;
  if (code === "authentication_required") return "Innlogging kreves.";
  if (code === "step_up_required") return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
  if (code === "SHAREHOLDER_REGISTER_FILING_NOT_FOUND") return "Fant ikke RF-1086-grunnlaget.";
  if (code === "SHAREHOLDER_REGISTER_FILING_FORBIDDEN") return "Du har ikke tilgang til RF-1086-handlingen.";
  if (code === "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT" || code === "invalid_request") return "Kontroller feltene og bekreftelsene før du prøver igjen.";
  return "RF-1086-handlingen kunne ikke bekreftes. Se lagret status før du prøver igjen.";
}
