import { createTalliApiClient, TalliApiError, type AnnualAccountsOverrideRequest, type AnnualAccountsReviewRequest,
  type AnnualAccountsPermissionRequest, type AnnualAccountsTestEvidenceRequest, type AnnualAccountsEvidenceImportRequest,
  type AnnualAccountsReadinessPreviewRequest } from "@talli/talli-api-client";
import { backendClientOptions } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ ...backendClientOptions(), headers: { Authorization: `Bearer ${accessToken}` } });
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

export function loadAnnualAccountsSourceFacts(accessToken: string, companyId: string, incomeYear: number) {
  return client(accessToken).annualAccountsGetSourceFacts(companyId, incomeYear, { signal: AbortSignal.timeout(10_000) });
}

export function loadAccountsDeliveryWorkspace(accessToken: string,companyId: string,incomeYear: number) {
  return client(accessToken).annualAccountsGetDeliveryWorkspace(companyId,incomeYear,{signal:AbortSignal.timeout(10_000),includeSyntheticContext:true});
}

export function loadAccountsDeliveryOriginal(accessToken: string,companyId: string,incomeYear: number,filingId: string,key: string) {
  return client(accessToken).annualAccountsGetDeliveryOriginal(companyId,incomeYear,filingId,key,{signal:AbortSignal.timeout(10_000)});
}

export function prepareAccountsDelivery(accessToken: string,command: import("@talli/talli-api-client").AccountsPrepareDeliveryRequest,key: string) {
  return client(accessToken).annualAccountsPrepareDeliveryDraft(command,{idempotencyKey:key,signal:AbortSignal.timeout(20_000)});
}

export function reviewAccountsDelivery(accessToken: string,command: import("@talli/talli-api-client").AccountsReviewDeliveryRequest,key: string) {
  return client(accessToken).annualAccountsReviewDelivery(command,{idempotencyKey:key,signal:AbortSignal.timeout(20_000)});
}

export function advanceAccountsDelivery(accessToken: string,command: import("@talli/talli-api-client").AccountsAdvanceDeliveryRequest) {
  return client(accessToken).annualAccountsAdvanceDelivery(command,{signal:AbortSignal.timeout(20_000)});
}

export function reconcileAccountsDelivery(accessToken: string,command: import("@talli/talli-api-client").AccountsDeliveryBoundRequest) {
  return client(accessToken).annualAccountsReconcileDelivery(command,{signal:AbortSignal.timeout(60_000)});
}

export function accountsDeliveryMfaRequired(error: unknown) {
  return error instanceof TalliApiError && error.problem?.code==="ANNUAL_ACCOUNTS_MFA_REQUIRED";
}

export function prepareAccountsCorrection(accessToken: string,command: import("@talli/talli-api-client").AccountsPrepareCorrectionRequest,key: string) {
  return client(accessToken).annualAccountsPrepareDeliveryCorrection(command,{idempotencyKey:key,signal:AbortSignal.timeout(60_000)});
}

export async function loadAccountsCompanyArchiveSource(accessToken: string, companyId: string, incomeYear: number) {
  const api = client(accessToken);
  try {
    const data = await api.annualAccountsGetCompanyYearArchive(companyId, incomeYear, {signal: AbortSignal.timeout(60_000)});
    return {data, legacyEmpty: null, error: null};
  } catch (error) {
    // The preceding owning workspace contract positively enumerates all retained
    // drafts/events. Only an explicit empty history permits its older export;
    // it cannot manufacture the new archive codec or a complete restore claim.
    if (error instanceof TalliApiError && error.status === 404) {
      try {
        const workspace = await api.annualAccountsGetDeliveryWorkspace(companyId, incomeYear, {signal: AbortSignal.timeout(10_000)});
        if (workspace.rows.length === 0) return {data: null, legacyEmpty: workspace, error: null};
      } catch { /* An unavailable or unauthorized predecessor is not empty. */ }
    }
    return {data: null, legacyEmpty: null, error: new Error("Accounts company archive source unavailable.")};
  }
}
