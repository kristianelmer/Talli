import { createTalliApiClient, TalliApiError, type AnnualAccountsOverrideRequest, type AnnualAccountsReviewRequest,
  type AnnualAccountsPermissionRequest, type AnnualAccountsTestEvidenceRequest, type AnnualAccountsEvidenceImportRequest,
  type AnnualAccountsReadinessPreviewRequest } from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` } });
}

export function loadAnnualAccountsFilingWorkspace(accessToken: string, companyId: string, incomeYear: number | null = null) {
  return client(accessToken).annualAccountsGetFilingWorkspace(companyId, incomeYear, { signal: AbortSignal.timeout(10_000) });
}

export function importAnnualAccountsTt02Evidence(accessToken: string, input: AnnualAccountsEvidenceImportRequest) {
  return client(accessToken).annualAccountsImportTt02Evidence(input, { signal: AbortSignal.timeout(10_000) });
}

export function annualAccountsEvidenceImportErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "ANNUAL_ACCOUNTS_NOT_FOUND") {
    return "Selskapet finnes ikke";
  }
  if (error instanceof TalliApiError && error.problem?.code === "ANNUAL_ACCOUNTS_MFA_REQUIRED") {
    return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
  }
  if (error instanceof TalliApiError && error.status === 422
      && error.problem?.code === "ANNUAL_ACCOUNTS_INVALID_INPUT") return error.problem.detail ?? "Ugyldig TT02-evidens";
  return "TT02-evidensen kunne ikke lagres.";
}

export async function findAnnualAccountsPreview(accessToken: string, previewId: string) {
  try { return await client(accessToken).annualAccountsGetPreview(previewId, { signal: AbortSignal.timeout(10_000) }); }
  catch (error) {
    if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "ANNUAL_ACCOUNTS_NOT_FOUND") return null;
    throw error;
  }
}

export async function acknowledgeOwnedAnnualAccountsComment(accessToken: string, commentId: string) {
  try { return await client(accessToken).annualAccountsAcknowledgeReviewComment(commentId, { signal: AbortSignal.timeout(10_000) }); }
  catch (error) {
    if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "ANNUAL_ACCOUNTS_NOT_FOUND") return null;
    throw error;
  }
}

export function annualAccountsActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    if (error.problem?.code === "ANNUAL_ACCOUNTS_MFA_REQUIRED") return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
    if (["ANNUAL_ACCOUNTS_INVALID_INPUT", "ANNUAL_ACCOUNTS_HARD_REVIEW_BLOCK"].includes(error.problem?.code ?? "") && error.problem?.detail) return error.problem.detail;
  }
  return "Årsregnskapet kunne ikke oppdateres. Prøv igjen.";
}

export function annualAccountsRecordOverride(accessToken: string, input: AnnualAccountsOverrideRequest) {
  return client(accessToken).annualAccountsRecordOverride(input, { signal: AbortSignal.timeout(10_000) });
}

export function annualAccountsAddReviewComment(accessToken: string, input: AnnualAccountsReviewRequest) {
  return client(accessToken).annualAccountsAddReviewComment(input, { signal: AbortSignal.timeout(10_000) });
}

export function annualAccountsConfirmPermission(accessToken: string, input: AnnualAccountsPermissionRequest) {
  return client(accessToken).annualAccountsConfirmPermission(input, { signal: AbortSignal.timeout(10_000) });
}

export function annualAccountsRecordTestEvidence(accessToken: string, input: AnnualAccountsTestEvidenceRequest) {
  return client(accessToken).annualAccountsRecordTestEvidence(input, { signal: AbortSignal.timeout(10_000) });
}

export function previewAnnualAccountsReadiness(accessToken: string, facts: AnnualAccountsReadinessPreviewRequest) {
  return client(accessToken).annualAccountsPreviewReadiness(facts, { signal: AbortSignal.timeout(10_000) });
}
