import {verifyCompanyTaxDeliveryJournalArchive,verifyCompanyTaxDeliveryDraftArchive,verifyCompanyTaxOwnerReviewArtifact} from "@talli/talli-api-client";
import type { CompanyTaxAssessmentFactsRequest, CompanyTaxReadinessPreviewRequest, CompanyTaxSourceFactsWire, CompanyTaxDeliveryDraftArchiveWire, CompanyTaxDeliveryJournalArchiveWire } from "@talli/talli-api-client";
import { createTalliApiClient, TalliApiError, type CompanyTaxOverrideRequest, type CompanyTaxReviewRequest, type CompanyTaxPermissionRequest, type CompanyTaxTestEvidenceRequest, type CompanyTaxEvidenceImportRequest, type LedgerTaxSettlementWire, type TaxSettlementPreviewInputWire } from "@talli/talli-api-client";
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

export type TaxDeliveryDraftArchiveProjection = {
  sourceFacts: CompanyTaxSourceFactsWire;
  originals: CompanyTaxDeliveryDraftArchiveWire | null;
  journal?: CompanyTaxDeliveryJournalArchiveWire;
};

const verifyTaxJournalOriginals=verifyCompanyTaxDeliveryJournalArchive;
const verifyTaxDraftOriginals=verifyCompanyTaxDeliveryDraftArchive;

export async function loadTaxDeliveryOwnerReview(accessToken: string,companyId: string,incomeYear: number,filingId: string,approvalSha256: string) {
  const result=await client(accessToken).companyTaxGetDeliveryOwnerReview(companyId,incomeYear,filingId,approvalSha256,
    {signal:AbortSignal.timeout(10_000)});
  await verifyCompanyTaxOwnerReviewArtifact(result,approvalSha256);
  return result;
}

export async function loadTaxDeliveryDraftArchiveSource(accessToken: string, companyId: string, incomeYear: number) {
  try {
    const api = client(accessToken);
    const request = { signal: AbortSignal.timeout(10_000) };
    const source = await api.companyTaxGetSourceFacts(companyId,incomeYear,request);
    // A complete V1 source positively proves the original seven-table extent,
    // including absence of the new store. This supports frontend-first rollout.
    if (/^company-tax-source-v1:[0-9a-f]{64}$/u.test(source.evidence.version)
        && source.historyCoverage.status === "complete") {
      return { data: { sourceFacts: source, originals: null } satisfies TaxDeliveryDraftArchiveProjection, error: null };
    }
    if (/^company-tax-source-v[3456789]:[0-9a-f]{64}$/u.test(source.evidence.version)
        || (/^company-tax-source-v2:[0-9a-f]{64}$/u.test(source.evidence.version)
          && source.historyCoverage.reasons.includes("declaredDeliveryExtentValid_unproven"))) {
      // The nine-table successor supplies facts and originals from one guarded
      // snapshot. No failed or incomplete successor read falls back to V2.
      const journal = await api.companyTaxGetDeliveryJournalArchive(companyId,incomeYear,request);
      const originals: CompanyTaxDeliveryDraftArchiveWire = {companyId,incomeYear,
        codec:"company-tax-delivery-draft-archive-v1",coverage:"complete",sourceSha256:journal.sourceSha256,
        observedAt:journal.observedAt,recordCount:journal.draftCount,records:journal.drafts};
      await verifyTaxJournalOriginals(journal,companyId,incomeYear);
      return {data:{sourceFacts:journal.sourceFacts,originals,journal} satisfies TaxDeliveryDraftArchiveProjection,error:null};
    }
    if (!/^company-tax-source-v2:[0-9a-f]{64}$/u.test(source.evidence.version)) throw new Error("Unknown Tax archive source.");
    const originals = await api.companyTaxGetDeliveryDraftArchive(companyId,incomeYear,request);
    if (originals.sourceSha256 !== source.evidence.digest) throw new Error("Tax archive source changed.");
    await verifyTaxDraftOriginals(originals,companyId,incomeYear);
    return { data: { sourceFacts: source, originals } satisfies TaxDeliveryDraftArchiveProjection, error: null };
  } catch {
    return { data: null, error: { message: "Kunne ikke lese komplette skattemeldingsutkast." } };
  }
}

export function loadCompanyTaxFilingWorkspace(accessToken: string, companyId: string, incomeYear: number | null = null) {
  return client(accessToken).companyTaxGetFilingWorkspace(companyId, incomeYear, { signal: AbortSignal.timeout(10_000) });
}

export function importCompanyTaxTt02Evidence(accessToken: string, input: CompanyTaxEvidenceImportRequest) {
  return client(accessToken).companyTaxImportTt02Evidence(input, { signal: AbortSignal.timeout(10_000) });
}

export function taxEvidenceImportErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "COMPANY_TAX_NOT_FOUND") {
    return "Selskapet finnes ikke";
  }
  if (error instanceof TalliApiError && error.problem?.code === "COMPANY_TAX_MFA_REQUIRED") {
    return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
  }
  if (error instanceof TalliApiError && error.status === 422
      && error.problem?.code !== "COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED") return "Ugyldig TT02-evidens";
  return "TT02-evidensen kunne ikke lagres.";
}

export async function findCompanyTaxPreview(accessToken: string, previewId: string) {
  try { return await client(accessToken).companyTaxGetPreview(previewId, { signal: AbortSignal.timeout(10_000) }); }
  catch (error) {
    if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "COMPANY_TAX_NOT_FOUND") return null;
    throw error;
  }
}

export async function acknowledgeOwnedCompanyTaxComment(accessToken: string, commentId: string) {
  try { return await client(accessToken).companyTaxAcknowledgeReviewComment(commentId, { signal: AbortSignal.timeout(10_000) }); }
  catch (error) {
    if (error instanceof TalliApiError && error.status === 404 && error.problem?.code === "COMPANY_TAX_NOT_FOUND") return null;
    throw error;
  }
}

export function companyTaxActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    if (error.problem?.code === "COMPANY_TAX_MFA_REQUIRED") return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
    if (["COMPANY_TAX_INVALID_INPUT", "COMPANY_TAX_HARD_REVIEW_BLOCK"].includes(error.problem?.code ?? "") && error.problem?.detail) return error.problem.detail;
  }
  return "Skattemeldingen kunne ikke oppdateres. Prøv igjen.";
}

export function companyTaxRecordOverride(accessToken: string, input: CompanyTaxOverrideRequest) {
  return client(accessToken).companyTaxRecordOverride(input, { signal: AbortSignal.timeout(10_000) });
}

export function companyTaxAddReviewComment(accessToken: string, input: CompanyTaxReviewRequest) {
  return client(accessToken).companyTaxAddReviewComment(input, { signal: AbortSignal.timeout(10_000) });
}

export function companyTaxConfirmPermission(accessToken: string, input: CompanyTaxPermissionRequest) {
  return client(accessToken).companyTaxConfirmPermission(input, { signal: AbortSignal.timeout(10_000) });
}

export function companyTaxRecordTestEvidence(accessToken: string, input: CompanyTaxTestEvidenceRequest) {
  return client(accessToken).companyTaxRecordTestEvidence(input, { signal: AbortSignal.timeout(10_000) });
}

export function previewCompanyTaxReadiness(accessToken: string, facts: CompanyTaxReadinessPreviewRequest) {
  return client(accessToken).companyTaxPreviewReadiness(facts, { signal: AbortSignal.timeout(10_000) });
}

export function previewAnnualTaxEstimate(accessToken: string, facts: CompanyTaxAssessmentFactsRequest) {
  return client(accessToken).companyTaxPreviewAnnualEstimate(facts, { signal: AbortSignal.timeout(10_000) });
}
