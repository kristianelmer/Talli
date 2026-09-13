import { createTalliApiClient, TalliApiError, type CompanyTaxEvidenceImportRequest, type LedgerTaxSettlementWire, type TaxSettlementPreviewInputWire } from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` } });
}

export function previewTaxSettlement(accessToken: string, input: TaxSettlementPreviewInputWire) {
  return client(accessToken).companyTaxPreviewSettlement(input, { signal: AbortSignal.timeout(10_000) });
}

export function postTaxSettlement(accessToken: string, command: LedgerTaxSettlementWire, operationId: string) {
  return client(accessToken).ledgerPostTaxSettlement(command, {
    idempotencyKey: operationId, requestId: operationId, signal: AbortSignal.timeout(10_000),
  });
}

export function taxPreviewErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError && error.status === 422) {
    return error.problem?.code === "REQUEST_VALIDATION_FAILED"
      ? "Kontroller opplysningene i skatteoppgjøret."
      : error.problem?.detail ?? "Ugyldig skatteoppgjør";
  }
  return "Forhåndsvisningen kunne ikke hentes. Prøv igjen.";
}

export function taxSubmissionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError && error.status === 422 && error.problem?.code
      && error.problem.code !== "REQUEST_VALIDATION_FAILED" && error.problem.detail) {
    return `${error.problem.code}: ${error.problem.detail}`;
  }
  return taxPreviewErrorMessage(error);
}

export async function loadTaxSettlementArchiveSource(accessToken: string, companyId: string, incomeYear: number) {
  try {
    const result = await client(accessToken).companyTaxGetSettlementArchiveSource(companyId, incomeYear, { signal: AbortSignal.timeout(10_000) });
    return { data: result.settlements, error: null };
  } catch {
    return { data: [], error: { message: "Kunne ikke lese skatteoppgjørene." } };
  }
}

export function loadCompanyTaxFilingWorkspace(accessToken: string, companyId: string, incomeYear: number | null = null) {
  return client(accessToken).companyTaxGetFilingWorkspace(companyId, incomeYear, { signal: AbortSignal.timeout(10_000) });
}

export function importCompanyTaxTt02Evidence(accessToken: string, input: CompanyTaxEvidenceImportRequest) {
  return client(accessToken).companyTaxImportTt02Evidence(input, { signal: AbortSignal.timeout(10_000) });
}

export function taxEvidenceImportErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError && error.problem?.code === "COMPANY_TAX_MFA_REQUIRED") {
    return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
  }
  if (error instanceof TalliApiError && error.status === 422) return "Ugyldig TT02-evidens";
  return "TT02-evidensen kunne ikke lagres.";
}
