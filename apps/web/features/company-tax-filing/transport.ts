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

async function exactTaxOriginal(raw: string, expected: string) {
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw))))
    .map(byte => byte.toString(16).padStart(2,"0")).join("");
  if (digest !== expected) throw new Error("Tax original bytes changed.");
  return JSON.parse(raw);
}

async function verifyTaxDraftOriginals(originals: CompanyTaxDeliveryDraftArchiveWire,companyId: string,incomeYear: number) {
  for (const record of originals.records) {
    const value = await exactTaxOriginal(record.canonicalJson,record.draftSha256);
    if (!["company-tax-delivery-draft-v1","company-tax-delivery-draft-v2"].includes(value.version)
        || value.draft?.filing_id !== record.filingId
        || value.draft?.envelope?.source?.company_id?.value !== companyId
        || value.draft?.envelope?.source?.income_year?.value !== incomeYear) throw new Error("Tax draft original mismatch.");
  }
}

async function verifyTaxJournalOriginals(journal: CompanyTaxDeliveryJournalArchiveWire,companyId: string,incomeYear: number) {
  const approvals = new Map<string,{hash: string;actor: string}>();
  const requests = new Map<string,string>();
  const completed = new Set<string>();
  const instances = new Map<string,string>();
  const latest = new Map<string,typeof journal.events[number]>();
  for (const record of journal.events) {
    const value = await exactTaxOriginal(record.canonicalJson,record.eventSha256);
    const mode = record.slot === "review" ? "review" : record.slot.startsWith("intent:") ? "intent" : "completion";
    const expected = {review:"company-tax-delivery-review-approval-v1",intent:"company-tax-delivery-mutation-request-v1",completion:"company-tax-delivery-mutation-completion-v1"}[mode];
    const binding = mode === "review" ? value.approval : mode === "intent" ? value.request : value.completion?.intent;
    if (value.version !== expected || binding?.filing_id !== record.filingId
        || binding?.company_id?.value !== companyId || binding?.income_year?.value !== incomeYear
        || (mode !== "review" && binding?.kind !== record.slot.split(":")[1])) throw new Error("Tax event original mismatch.");
    if (mode === "review") {
      if (binding.approved_by?.kind !== "USER" || binding.approved_by?.subject?.value !== record.recordedBy
          || binding.authority_mode !== "finite_loopback_rehearsal"
          || !journal.drafts.some(draft => draft.filingId === record.filingId && draft.draftSha256 === binding.draft_sha256)) throw new Error("Tax approval original mismatch.");
      approvals.set(record.filingId,{hash:record.eventSha256,actor:record.recordedBy});
    } else {
      const approval = approvals.get(record.filingId);
      if (!approval || binding.approval_sha256 !== approval.hash || record.recordedBy !== approval.actor) throw new Error("Tax journal approval binding mismatch.");
      if (mode === "intent") {
        const predecessors = {create_instance:null,upload_envelope:"create_instance",start_validation:"upload_envelope",prepare_confirmation:"start_validation"};
        const predecessor = predecessors[binding.kind as keyof typeof predecessors];
        if (predecessor === undefined || (predecessor !== null
            && (!completed.has(record.filingId+":"+predecessor) || binding.target_instance !== instances.get(record.filingId)))) throw new Error("Tax journal predecessor is incomplete.");
        requests.set(record.filingId+":"+binding.kind,record.eventSha256);
      } else {
        if (!requests.has(record.filingId+":"+binding.kind)
            || typeof binding.request_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(binding.request_sha256)
            || binding.request_sha256 !== requests.get(record.filingId+":"+binding.kind)
            || binding.approved_by?.kind !== "USER" || binding.approved_by?.subject?.value !== approval.actor) throw new Error("Tax journal request binding mismatch.");
        const instance = value.completion?.result?.instanceId;
        if (typeof instance !== "string" || !/^[0-9]{1,19}\/[0-9a-f-]{36}$/u.test(instance)
            || (binding.kind !== "create_instance" && instance !== instances.get(record.filingId))) throw new Error("Tax journal instance mismatch.");
        if (binding.kind === "create_instance") instances.set(record.filingId,instance);
        completed.add(record.filingId+":"+binding.kind);
      }
    }
    latest.set(record.filingId,record);
  }
  if (journal.journals.length !== latest.size || journal.journals.some(fact => {
    const record=latest.get(fact.filingId);const approval=approvals.get(fact.filingId);
    return !record || !approval || fact.approvalSha256 !== approval.hash || fact.approvedBy !== approval.actor
      || fact.latestEventSha256 !== record.eventSha256 || fact.recordedAt !== record.recordedAt
      || fact.status !== (record.slot === "review" ? "reviewed" : record.slot.startsWith("intent:") ? "uncertain" : "mutation_completed")
      || fact.mutationKind !== (record.slot === "review" ? null : record.slot.split(":")[1]);
  })) throw new Error("Tax journal summary mismatch.");
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
    if (/^company-tax-source-v3:[0-9a-f]{64}$/u.test(source.evidence.version)
        || (/^company-tax-source-v2:[0-9a-f]{64}$/u.test(source.evidence.version)
          && source.historyCoverage.reasons.includes("declaredDeliveryExtentValid_unproven"))) {
      // The nine-table successor supplies facts and originals from one guarded
      // snapshot. No failed or incomplete successor read falls back to V2.
      const journal = await api.companyTaxGetDeliveryJournalArchive(companyId,incomeYear,request);
      const originals: CompanyTaxDeliveryDraftArchiveWire = {companyId,incomeYear,
        codec:"company-tax-delivery-draft-archive-v1",coverage:"complete",sourceSha256:journal.sourceSha256,
        observedAt:journal.observedAt,recordCount:journal.draftCount,records:journal.drafts};
      await verifyTaxDraftOriginals(originals,companyId,incomeYear);
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
