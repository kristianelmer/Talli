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

async function taxReadOriginal(value: {purpose: unknown;content_type: unknown;http_status: unknown;body_base64: unknown},purpose: "finite_admission" | "instance") {
  if (!value || Object.keys(value).sort().join(",") !== "body_base64,content_type,http_status,purpose"
      || value.purpose !== purpose || value.content_type !== "application/json"
      || value.http_status !== (purpose === "finite_admission" ? null : 200)
      || typeof value.body_base64 !== "string" || value.body_base64.length > 12*1024*1024) throw new Error("Tax read original is invalid.");
  const decoded=atob(value.body_base64);
  if (!decoded.length || decoded.length > 8*1024*1024 || btoa(decoded) !== value.body_base64) throw new Error("Tax read original encoding changed.");
  const bytes=Uint8Array.from(decoded,char => char.charCodeAt(0));
  const text=new TextDecoder("utf-8",{fatal:true}).decode(bytes);
  const sha256=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))
    .map(byte => byte.toString(16).padStart(2,"0")).join("");
  return {text,sha256};
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
  const approvals = new Map<string,{hash: string;actor: string;context: string;draft: string;organization: string | undefined}>();
  const requests = new Map<string,string>();
  const completed = new Set<string>();
  const instances = new Map<string,string>();
  const latest = new Map<string,typeof journal.events[number]>();
  const effects = new Map<string,typeof journal.events[number]>();
  const admissions = new Set<string>();
  const slots = new Set<string>();
  const drafts = new Map<string,{envelope?: {source?: {organization_number?: string}}}>();
  for (const draft of journal.drafts) drafts.set(draft.filingId,(await exactTaxOriginal(draft.canonicalJson,draft.draftSha256)).draft);
  for (const record of journal.events) {
    const slot=record.filingId+":"+record.slot;
    if (slots.has(slot)) throw new Error("Tax journal has duplicate slots.");
    slots.add(slot);
    const value = await exactTaxOriginal(record.canonicalJson,record.eventSha256);
    const evidence=record.slot === "admission" || record.slot.startsWith("observation:");
    if (evidence) {
      if (!journal.sourceFacts.evidence.version.startsWith("company-tax-source-v4:")) throw new Error("Tax reads require the V4 source.");
      const admission=record.slot === "admission";
      const binding=admission ? value.admission : value.observation;
      const approval=approvals.get(record.filingId);
      if (value.version !== (admission ? "company-tax-delivery-admission-v1" : "company-tax-delivery-instance-observation-v1")
          || !approval || binding?.filing_id !== record.filingId || binding?.company_id?.value !== companyId
          || binding?.income_year?.value !== incomeYear || binding?.approval_sha256 !== approval.hash
          || record.recordedBy !== approval.actor || binding?.approved_by?.kind !== "USER"
          || binding?.approved_by?.subject?.value !== approval.actor) throw new Error("Tax read scope mismatch.");
      const original=await taxReadOriginal(binding.original,admission ? "finite_admission" : "instance");
      if (admission) {
        const context=JSON.parse(original.text);
        const keys="actorId,companyId,credentialSha256,databaseScopeSha256,draftSha256,expiresAt,filingId,incomeYear,issuedAt,maximumRequests,organizationNumber,origin,runId,version";
        const ttl=Date.parse(context.expiresAt)-Date.parse(context.issuedAt);
        const port=typeof context.origin === "string" && /^http:\/\/127\.0\.0\.1:[0-9]{4,5}$/u.test(context.origin)
          ? Number(context.origin.split(":")[2]) : 0;
        if (Object.keys(context).sort().join(",") !== keys || context.version !== "tax-loopback-admission-v1"
            || original.sha256 !== approval.context || context.companyId !== companyId || context.incomeYear !== incomeYear
            || context.actorId !== approval.actor || context.filingId !== record.filingId || context.draftSha256 !== approval.draft
            || context.organizationNumber !== approval.organization || !Number.isInteger(context.maximumRequests)
            || context.maximumRequests < 1 || context.maximumRequests > 1000 || !Number.isFinite(ttl) || ttl <= 0 || ttl > 3600000
            || port < 1024 || port > 65535 || context.origin !== "http://127.0.0.1:"+port
            || typeof context.runId !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(context.runId)
            || !/^[0-9a-f]{64}$/u.test(context.credentialSha256) || !/^[0-9a-f]{64}$/u.test(context.databaseScopeSha256)) throw new Error("Tax finite admission mismatch.");
        admissions.add(record.filingId);
      } else {
        if (!admissions.has(record.filingId) || !instances.has(record.filingId)
            || binding.instance_id !== instances.get(record.filingId) || binding.organization_number !== approval.organization
            || typeof binding.observed_at?.value !== "string" || !Number.isFinite(Date.parse(binding.observed_at.value))) throw new Error("Tax instance read has no known target.");
        const identity=JSON.stringify(["tax-instance-read-identity-v1",record.filingId,companyId,incomeYear,
          approval.actor,approval.hash,binding.organization_number,binding.instance_id,original.sha256]);
        const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(identity))))
          .map(byte => byte.toString(16).padStart(2,"0")).join("");
        if (record.slot !== "observation:instance:"+digest) throw new Error("Tax read identity mismatch.");
      }
      latest.set(record.filingId,record);
      continue;
    }
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
      approvals.set(record.filingId,{hash:record.eventSha256,actor:record.recordedBy,context:binding.authority_context_sha256,
        draft:binding.draft_sha256,organization:drafts.get(record.filingId)?.envelope?.source?.organization_number});
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
    effects.set(record.filingId,record);
  }
  if (journal.journals.length !== latest.size || journal.journals.some(fact => {
    const record=latest.get(fact.filingId);const effect=effects.get(fact.filingId);const approval=approvals.get(fact.filingId);
    return !record || !effect || !approval || fact.approvalSha256 !== approval.hash || fact.approvedBy !== approval.actor
      || fact.latestEventSha256 !== record.eventSha256 || fact.recordedAt !== record.recordedAt
      || fact.status !== (effect.slot === "review" ? "reviewed" : effect.slot.startsWith("intent:") ? "uncertain" : "mutation_completed")
      || fact.mutationKind !== (effect.slot === "review" ? null : effect.slot.split(":")[1]);
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
    if (/^company-tax-source-v[34]:[0-9a-f]{64}$/u.test(source.evidence.version)
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
