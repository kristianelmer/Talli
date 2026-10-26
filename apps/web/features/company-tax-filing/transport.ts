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

async function taxTextSha(raw: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw))))
    .map(byte => byte.toString(16).padStart(2,"0")).join("");
}

function taxReviewCanonical(value: unknown): string {
  // Review contract keys are ASCII, quantities are integer counts, and all
  // statutory values are strings. Match the backend's sorted UTF-8 JSON.
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return "["+value.map(taxReviewCanonical).join(",")+"]";
  if (typeof value === "object" && value !== null) return "{"+Object.keys(value).sort().map(key =>
    JSON.stringify(key)+":"+taxReviewCanonical((value as Record<string,unknown>)[key])).join(",")+"}";
  throw new Error("Tax owner review contains unsupported values.");
}

export async function loadTaxDeliveryOwnerReview(accessToken: string,companyId: string,incomeYear: number,filingId: string,approvalSha256: string) {
  const result=await client(accessToken).companyTaxGetDeliveryOwnerReview(companyId,incomeYear,filingId,approvalSha256,
    {signal:AbortSignal.timeout(10_000)});
  const review=result.review;const response=review.response;const inspection=response.inspection;
  const responseOriginal=await taxReadOriginal(review.response_original,"validation_result");
  const raw=taxReviewCanonical({version:result.version,review});
  if (new TextEncoder().encode(raw).length>24*1024*1024 || await taxTextSha(raw)!==result.artifactSha256
      || await taxTextSha(taxReviewCanonical({version:"company-tax-delivery-review-approval-v1",approval:review.approval}))!==approvalSha256
      || responseOriginal.sha256!==inspection.original_sha256
      || review.calculated_context.schema_sha256!=="c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769"
      || inspection.schema_sha256!=="eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1"
      || review.approval.schema_sha256!=="56668da96711b664843df91d518bb127eb79bddf93c9635765bbd28d35bdda1b"
      || inspection.result_code!=="validertOK" || inspection.validation_deviation_count!==0 || inspection.failure_reason_count!==0
      || inspection.calculation_deviation_count!==response.calculation_deviations.length
      || inspection.validation_deviation_count!==response.validation_deviations.length
      || inspection.guidance_count!==response.guidance.length || inspection.failure_reason_count!==response.failure_reasons.length
      || new Set(response.subject_flags.map(value=>value.name)).size!==response.subject_flags.length
      || inspection.calculated_documents.length!==review.documents.length) throw new Error("Tax owner review content commitment changed.");
  const types=new Set<string>();
  for (let index=0;index<review.documents.length;index++) {
    const document=review.documents[index];const original=inspection.calculated_documents[index];
    const decoded=await taxEncodedOriginal(original.body_base64);
    if (types.has(document.document_type) || document.document_type!==original.document_type || decoded.sha256!==document.original_sha256
        || new Set(document.fields.map(field=>field.path)).size!==document.fields.length
        || document.fields.some(field=>!field.path.startsWith("/"))) throw new Error("Tax owner review calculated original changed.");
    types.add(document.document_type);
  }
  if (!types.has("skattemeldingUpersonligEtterBeregning") || !types.has("naeringsspesifikasjonEtterBeregning")) {
    throw new Error("Tax owner review is missing its calculated document pair.");
  }
  // This read preserves backend-owned projections and every original. It grants
  // no XML/schema verdict, owner confirmation or submission authority.
  return result;
}

function taxJsonObject(raw: string,integerFields: readonly string[]=[],integerDepth=1) {
  const value=JSON.parse(raw);
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("Tax JSON original is not an object.");
  // JSON.parse validates grammar; this iterative token walk additionally
  // refuses duplicate keys, including differently escaped equal names.
  const stack: {keys: Set<string> | null;expectKey: boolean;key?: string}[]=[];
  for (const match of raw.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]:,]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/gu)) {
    const token=match[0];const top=stack.at(-1);
    if (token === "{") stack.push({keys:new Set(),expectKey:true});
    else if (token === "[") stack.push({keys:null,expectKey:false});
    else if (token === "}" || token === "]") stack.pop();
    else if (token === "," && top?.keys) top.expectKey=true;
    else if (token.startsWith('"') && top?.keys && top.expectKey) {
      const key=JSON.parse(token);
      if (top.keys.has(key)) throw new Error("Tax JSON original has duplicate keys.");
      top.keys.add(key);top.expectKey=false;top.key=key;
    } else if (stack.length === integerDepth && top?.key && integerFields.includes(top.key) && /^-?[0-9]/u.test(token)
        && !/^-?(?:0|[1-9][0-9]*)$/u.test(token)) {
      throw new Error("Tax JSON timing field is not an integer original.");
    }
  }
  return value;
}

function taxHasKeys(value: unknown,keys: string) {
  return value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === keys;
}

function taxTimeWrapper(value: {value?: unknown} | undefined) {
  return taxHasKeys(value,"value") && typeof value?.value === "string"
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value.value)
    && Number.isFinite(Date.parse(value.value));
}

async function exactTaxOriginal(raw: string, expected: string) {
  if (await taxTextSha(raw) !== expected) throw new Error("Tax original bytes changed.");
  return taxJsonObject(raw);
}

async function taxEncodedOriginal(encoded: string) {
  if (typeof encoded !== "string" || encoded.length > 12*1024*1024) throw new Error("Tax original exceeds its limit.");
  const decoded=atob(encoded);
  if (!decoded.length || decoded.length > 8*1024*1024 || btoa(decoded) !== encoded) throw new Error("Tax read original encoding changed.");
  const bytes=Uint8Array.from(decoded,char => char.charCodeAt(0));
  const text=new TextDecoder("utf-8",{fatal:true}).decode(bytes);
  const sha256=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))
    .map(byte => byte.toString(16).padStart(2,"0")).join("");
  return {text,sha256,size:bytes.length};
}

async function taxReadOriginal(value: {purpose: unknown;content_type: unknown;http_status: unknown;body_base64: unknown},purpose: "finite_admission" | "instance" | "envelope" | "validation_job" | "validation_result" | "process_response") {
  if (!value || Object.keys(value).sort().join(",") !== "body_base64,content_type,http_status,purpose"
      || typeof value.content_type !== "string"
      || value.purpose !== purpose || (["envelope","validation_result"].includes(purpose) ? !["application/xml","text/xml"].includes(String(value.content_type)) : value.content_type !== "application/json")
      || value.http_status !== (purpose === "finite_admission" ? null : 200)
      || typeof value.body_base64 !== "string" || value.body_base64.length > 12*1024*1024) throw new Error("Tax read original is invalid.");
  return taxEncodedOriginal(value.body_base64);
}

type TaxOriginalScope = {filing: string;company: string;year: number;actor: string;approval: string;organization: string | undefined;instance: string};

async function taxBoundRead(raw: string,sha256: string,kind: "instance" | "envelope",scope: TaxOriginalScope,strict=false) {
  if (typeof scope.organization !== "string" || !/^[0-9]{9}$/u.test(scope.organization)) throw new Error("Tax original organization is invalid.");
  const value=await exactTaxOriginal(raw,sha256);const binding=value.observation;
  if (strict && (!taxHasKeys(value,"observation,version") || !taxHasKeys(binding,
      "approval_sha256,approved_by,company_id,"+(kind === "envelope" ? "data_id," : "")+"filing_id,income_year,"+(kind === "envelope" ? "instance_evidence_sha256," : "")+"instance_id,observed_at,organization_number,original")
      || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
      || !taxHasKeys(binding.approved_by,"kind,subject") || !taxHasKeys(binding.approved_by?.subject,"value")
      || !taxTimeWrapper(binding.observed_at))) throw new Error("Tax process read has an unsupported shape.");
  if (value.version !== "company-tax-delivery-"+kind+"-observation-v1" || binding?.filing_id !== scope.filing
      || binding?.company_id?.value !== scope.company || binding?.income_year?.value !== scope.year
      || binding?.approved_by?.kind !== "USER" || binding?.approved_by?.subject?.value !== scope.actor
      || binding?.approval_sha256 !== scope.approval || binding?.organization_number !== scope.organization
      || binding?.instance_id !== scope.instance || typeof binding.observed_at?.value !== "string"
      || !Number.isFinite(Date.parse(binding.observed_at.value))) throw new Error("Tax bound read scope mismatch.");
  const original=await taxReadOriginal(binding.original,kind);
  if (kind === "envelope" && (typeof binding.data_id !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(binding.data_id)
      || typeof binding.instance_evidence_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(binding.instance_evidence_sha256))) throw new Error("Tax envelope identity mismatch.");
  const identity=JSON.stringify([kind === "instance" ? "tax-instance-read-identity-v1" : "tax-envelope-read-identity-v1",
    scope.filing,scope.company,scope.year,scope.actor,scope.approval,scope.organization,scope.instance,
    ...(kind === "envelope" ? [binding.data_id,binding.instance_evidence_sha256] : []),original.sha256]);
  const digest=await taxTextSha(identity);
  return {binding,original,identity:digest};
}

function taxProcessFile(text: string,scope: TaxOriginalScope,task: string,element: string,data: string,size: number) {
  const body=taxJsonObject(text,["flow"],3);const current=body.process?.currentTask;const rows=body.data;
  if (body.id !== scope.instance || body.appId !== "skd/formueinntekt-skattemelding-v2"
      || body.instanceOwner?.organisationNumber !== scope.organization || ![scope.year,String(scope.year)].includes(body.dataValues?.inntektsaar)
      || current?.altinnTaskType !== task || current?.elementId !== element || !Number.isInteger(current?.flow)
      || current.flow < 1 || current.flow > 2147483647 || body.process?.ended != null || body.status?.isArchived !== false || body.status?.archived != null
      || !Array.isArray(rows) || rows.length !== 1 || rows[0]?.id !== data || rows[0]?.dataType !== "skattemeldingOgNaeringsspesifikasjon"
      || rows[0].fileScanResult !== "Clean" || rows[0].size !== size || typeof rows[0].contentType !== "string"
      || !["application/xml","text/xml"].includes(rows[0].contentType.split(";",1)[0].trim().toLowerCase())) throw new Error("Tax process read is not the ordinary active stage and reviewed Clean file.");
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
  const requestOriginals = new Map<string,{bodyBase64: string;recordedAt: string;version: string;confirmation?: {data: string;fileHash: string}}>();
  const completed = new Set<string>();
  const instances = new Map<string,string>();
  const latest = new Map<string,typeof journal.events[number]>();
  const effects = new Map<string,typeof journal.events[number]>();
  const admissions = new Set<string>();
  const slots = new Set<string>();
  const instanceReads = new Map<string,{hash: string;identity: string;observedAt: string;instance: string;text: string}>();
  const envelopeReads = new Map<string,{hash: string;identity: string;observedAt: string;instance: string;data: string;metadata: string;fileHash: string;size: number}>();
  const knownJobs = new Map<string,{job: string;request: string;recordedAt: string}>();
  const jobReads = new Map<string,{hash: string;identity: string;observedAt: string;finished: boolean}>();
  const resultReads = new Map<string,{hash: string;identity: string;observedAt: string;originalHash: string;job: string}>();
  const latestJob = new Map<string,string>();const latestResult = new Map<string,string>();
  const completedAt = new Map<string,string>();
  const drafts = new Map<string,{envelope?: {source?: {organization_number?: string};envelope_xml?: string};current_document?: {party_number?: string}}>();
  for (const draft of journal.drafts) drafts.set(draft.filingId,(await exactTaxOriginal(draft.canonicalJson,draft.draftSha256)).draft);
  for (const record of journal.events) {
    const slot=record.filingId+":"+record.slot;
    if (slots.has(slot)) throw new Error("Tax journal has duplicate slots.");
    slots.add(slot);
    const value = await exactTaxOriginal(record.canonicalJson,record.eventSha256);
    const evidence=record.slot === "admission" || record.slot.startsWith("observation:");
    const validationJob=record.slot.startsWith("observation:validation-job:");
    const validationResult=record.slot.startsWith("observation:validation-result:");
    if (validationJob || validationResult) {
      const approval=approvals.get(record.filingId);const job=knownJobs.get(record.filingId);const binding=value.observation;
      const kind=validationJob ? "validation-job" : "validation-result";
      const keys="approval_sha256,approved_by,company_id,filing_id,income_year,instance_id,job_id,observed_at,organization_number,original,start_request_sha256";
      const expectedKeys=validationJob ? keys : keys.split(",").concat("job_status_evidence_sha256","schema_sha256").sort().join(",");
      const observed=Date.parse(binding?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
      if (!/^company-tax-source-v[67]:/u.test(journal.sourceFacts.evidence.version) || !approval || !job
          || value.version !== "company-tax-delivery-"+kind+"-observation-v1" || !taxHasKeys(value,"observation,version")
          || !taxHasKeys(binding,expectedKeys) || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
          || !taxHasKeys(binding.approved_by,"kind,subject") || !taxHasKeys(binding.approved_by?.subject,"value") || !taxTimeWrapper(binding.observed_at)
          || binding.filing_id !== record.filingId || binding.company_id?.value !== companyId || binding.income_year?.value !== incomeYear
          || binding.approved_by?.kind !== "USER" || binding.approved_by?.subject?.value !== approval.actor || record.recordedBy !== approval.actor
          || binding.approval_sha256 !== approval.hash || binding.organization_number !== approval.organization
          || binding.instance_id !== instances.get(record.filingId) || binding.job_id !== job.job || binding.start_request_sha256 !== job.request
          || ![observed,recorded].every(Number.isFinite) || observed < Date.parse(job.recordedAt) || observed > recorded) throw new Error("Tax validation read scope or known-job predecessor mismatch.");
      const original=await taxReadOriginal(binding.original,validationJob ? "validation_job" : "validation_result");
      const identity=await taxTextSha(JSON.stringify([validationJob ? "tax-validation-job-read-identity-v1" : "tax-validation-result-read-identity-v1",
        record.filingId,companyId,incomeYear,approval.actor,approval.hash,approval.organization,binding.instance_id,job.job,job.request,
        ...(validationResult ? [binding.job_status_evidence_sha256,binding.schema_sha256] : []),original.sha256]));
      if (record.slot !== "observation:"+kind+":"+identity) throw new Error("Tax validation read identity mismatch.");
      if (validationJob) {
        let body=null;
        try {body=taxJsonObject(original.text);} catch { /* Exact unknown status remains retained. */ }
        if (body && typeof body.jobbId === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u.test(body.jobbId)
            && body.jobbId !== job.job) throw new Error("Tax status original names another job.");
        // Identity rejection precedes classifying malformed timing as unknown.
        let timingValid=false;
        if (body) {
          try {taxJsonObject(original.text,["sekunderSidenOpprettelse","sekunderSidenEndring"]);timingValid=true;}
          catch { /* Keep this exact status original unknown. */ }
        }
        const statuses=["OPPRETTET","NY","KJOERER","VENTER","AVBRUTT","FEILET","FERDIG"];
        const finished=Boolean(body && timingValid && body.jobbStatus === "FERDIG" && Object.hasOwn(body,"forrigeStatus")
          && (body.forrigeStatus === null || statuses.includes(body.forrigeStatus))
          && (!Object.hasOwn(body,"jobbId") || body.jobbId === job.job)
          && Number.isInteger(body.sekunderSidenOpprettelse) && Number.isInteger(body.sekunderSidenEndring)
          && body.sekunderSidenEndring >= 0 && body.sekunderSidenEndring <= body.sekunderSidenOpprettelse && body.sekunderSidenOpprettelse <= 2147483647);
        jobReads.set(record.filingId+":"+identity,{hash:record.eventSha256,identity,observedAt:binding.observed_at.value,finished});
        latestJob.set(record.filingId,identity);
      } else {
        const status=jobReads.get(record.filingId+":"+binding.job_status_evidence_sha256);
        if (!status?.finished || observed < Date.parse(status.observedAt)
            || binding.schema_sha256 !== "eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1") throw new Error("Tax result has no finished known-job original or supported schema pin.");
        resultReads.set(record.filingId+":"+identity,{hash:record.eventSha256,identity,observedAt:binding.observed_at.value,
          originalHash:original.sha256,job:binding.job_status_evidence_sha256});
        latestResult.set(record.filingId,identity);
        // XML remains an exact original here. A retained read is not an XSD,
        // inner-document scope, owner-confirmation or Tax-acceptance verdict.
      }
      latest.set(record.filingId,record);
      continue;
    }
    if (evidence) {
      if (!/^company-tax-source-v[4567]:/u.test(journal.sourceFacts.evidence.version)) throw new Error("Tax reads require a supported evidence source.");
      const admission=record.slot === "admission";
      const envelopeRead=record.slot.startsWith("observation:envelope:");
      const binding=admission ? value.admission : value.observation;
      const approval=approvals.get(record.filingId);
      if (value.version !== (admission ? "company-tax-delivery-admission-v1" : envelopeRead ? "company-tax-delivery-envelope-observation-v1" : "company-tax-delivery-instance-observation-v1")
          || !approval || binding?.filing_id !== record.filingId || binding?.company_id?.value !== companyId
          || binding?.income_year?.value !== incomeYear || binding?.approval_sha256 !== approval.hash
          || record.recordedBy !== approval.actor || binding?.approved_by?.kind !== "USER"
          || binding?.approved_by?.subject?.value !== approval.actor) throw new Error("Tax read scope mismatch.");
      const original=await taxReadOriginal(binding.original,admission ? "finite_admission" : envelopeRead ? "envelope" : "instance");
      if (admission) {
        const context=taxJsonObject(original.text);
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
        const read=await taxBoundRead(record.canonicalJson,record.eventSha256,envelopeRead ? "envelope" : "instance",
          {filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,approval:approval.hash,organization:approval.organization,instance:binding.instance_id});
        if (record.slot !== "observation:"+(envelopeRead ? "envelope:" : "instance:")+read.identity) throw new Error("Tax read identity mismatch.");
        if (envelopeRead) {
          const predecessor=instanceReads.get(record.filingId+":"+binding.instance_evidence_sha256);
          if (!/^company-tax-source-v[567]:/u.test(journal.sourceFacts.evidence.version) || !predecessor
              || predecessor.instance !== binding.instance_id || Date.parse(binding.observed_at.value) < Date.parse(predecessor.observedAt)) throw new Error("Tax envelope has no retained metadata predecessor.");
          envelopeReads.set(record.filingId+":"+read.identity,{hash:record.eventSha256,identity:read.identity,observedAt:binding.observed_at.value,
            instance:binding.instance_id,data:binding.data_id,metadata:binding.instance_evidence_sha256,fileHash:read.original.sha256,size:read.original.size});
        } else instanceReads.set(record.filingId+":"+read.identity,{hash:record.eventSha256,identity:read.identity,observedAt:binding.observed_at.value,instance:binding.instance_id,text:read.original.text});
      }
      latest.set(record.filingId,record);
      continue;
    }
    if (record.slot === "acknowledgment:prepare_confirmation") {
      const binding=value.acknowledgment;const approval=approvals.get(record.filingId);
      const request=requestOriginals.get(record.filingId+":prepare_confirmation");
      const observed=Date.parse(binding?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
      if (!journal.sourceFacts.evidence.version.startsWith("company-tax-source-v7:") || !approval || request?.version !== "company-tax-delivery-mutation-request-v4"
          || value.version !== "company-tax-delivery-process-acknowledgment-v1" || !taxHasKeys(value,"acknowledgment,version")
          || !taxHasKeys(binding,"approval_sha256,approved_by,company_id,filing_id,income_year,instance_id,observed_at,organization_number,original,request_sha256")
          || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value") || !taxHasKeys(binding.approved_by,"kind,subject")
          || !taxHasKeys(binding.approved_by?.subject,"value") || !taxTimeWrapper(binding.observed_at)
          || binding.filing_id !== record.filingId || binding.company_id.value !== companyId || binding.income_year.value !== incomeYear
          || binding.approved_by.kind !== "USER" || binding.approved_by.subject.value !== approval.actor || record.recordedBy !== approval.actor
          || binding.approval_sha256 !== approval.hash || binding.organization_number !== approval.organization
          || binding.instance_id !== instances.get(record.filingId) || binding.request_sha256 !== requests.get(record.filingId+":prepare_confirmation")
          || ![observed,recorded].every(Number.isFinite) || observed < Date.parse(request.recordedAt) || observed > recorded) throw new Error("Tax acknowledgment is not bound to the committed preparation.");
      await taxReadOriginal(binding.original,"process_response");latest.set(record.filingId,record);continue;
    }
    const mode = record.slot === "review" ? "review" : record.slot.startsWith("intent:") ? "intent" : "completion";
    const expected = {review:["company-tax-delivery-review-approval-v1"],intent:["company-tax-delivery-mutation-request-v1","company-tax-delivery-mutation-request-v2","company-tax-delivery-mutation-request-v3","company-tax-delivery-mutation-request-v4"],completion:["company-tax-delivery-mutation-completion-v1","company-tax-delivery-mutation-completion-v2","company-tax-delivery-mutation-completion-v3"]}[mode];
    const binding = mode === "review" ? value.approval : mode === "intent" ? value.request : value.completion?.intent;
    if (!expected.includes(value.version) || binding?.filing_id !== record.filingId
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
        requestOriginals.set(record.filingId+":"+binding.kind,{bodyBase64:binding.body_base64,recordedAt:record.recordedAt,version:value.version});
        if (value.version === "company-tax-delivery-mutation-request-v2") {
          const proof=binding.upload_prerequisite;const reference=proof?.instance_read;
          const original=instanceReads.get(record.filingId+":"+reference?.evidence_sha256);
          const start=Date.parse(proof?.observed_from?.value);const end=Date.parse(proof?.observed_until?.value);const read=Date.parse(reference?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
          if (!/^company-tax-source-v[567]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "upload_envelope"
              || !proof || Object.keys(proof).sort().join(",") !== "instance_id,instance_read,observed_from,observed_until"
              || !reference || Object.keys(reference).sort().join(",") !== "event_sha256,evidence_sha256,observed_at"
              || !original || original.hash !== reference.event_sha256 || original.instance !== binding.target_instance
              || proof.instance_id !== binding.target_instance || ![start,end,read,recorded].every(Number.isFinite)
              || end < start || end-start > 30000 || read < start || read > end || end < Date.parse(original.observedAt)
              || recorded < end || recorded-start > 30000) throw new Error("Tax guarded upload prerequisite mismatch.");
        }
        if (value.version === "company-tax-delivery-mutation-request-v3") {
          const proof=binding.validation_prerequisite;const metadataRef=proof?.instance_read;const fileRef=proof?.envelope_read;
          const metadata=instanceReads.get(record.filingId+":"+metadataRef?.evidence_sha256);
          const file=envelopeReads.get(record.filingId+":"+fileRef?.evidence_sha256);
          const start=Date.parse(proof?.observed_from?.value);const end=Date.parse(proof?.observed_until?.value);
          const metadataTime=Date.parse(metadataRef?.observed_at?.value);const fileTime=Date.parse(fileRef?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
          const uploadRecorded=Date.parse(completedAt.get(record.filingId+":upload_envelope") ?? "");
          const referenceKeys="event_sha256,evidence_sha256,observed_at";
          if (!/^company-tax-source-v[67]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "start_validation"
              || !taxHasKeys(value,"request,version") || !taxHasKeys(binding,"approval_sha256,body_base64,company_id,filing_id,income_year,kind,organization_number,target_instance,validation_prerequisite")
              || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
              || !proof || Object.keys(proof).sort().join(",") !== "data_id,envelope_read,instance_id,instance_read,observed_from,observed_until"
              || !metadataRef || !fileRef || Object.keys(metadataRef).sort().join(",") !== referenceKeys || Object.keys(fileRef).sort().join(",") !== referenceKeys
              || !taxTimeWrapper(proof.observed_from) || !taxTimeWrapper(proof.observed_until)
              || !taxTimeWrapper(metadataRef.observed_at) || !taxTimeWrapper(fileRef.observed_at)
              || !metadata || !file || metadata.hash !== metadataRef.event_sha256 || file.hash !== fileRef.event_sha256
              || metadata.instance !== binding.target_instance || file.instance !== binding.target_instance || proof.instance_id !== binding.target_instance
              || file.metadata !== metadata.identity || file.data !== proof.data_id
              || ![start,end,metadataTime,fileTime,recorded,uploadRecorded].every(Number.isFinite) || end < start || end-start > 30000
              || metadataTime < start || fileTime < metadataTime || fileTime > end || end < Date.parse(metadata.observedAt) || end < Date.parse(file.observedAt)
              || recorded < end || recorded-start > 30000 || start < uploadRecorded) throw new Error("Tax validation prerequisite references or freshness mismatch.");
          const body=taxJsonObject(metadata.text);const rows=body.data;const wire=await taxEncodedOriginal(binding.body_base64);
          const target=taxJsonObject(wire.text);const approved=drafts.get(record.filingId)?.envelope?.envelope_xml;
          if (body.id !== binding.target_instance || body.appId !== "skd/formueinntekt-skattemelding-v2"
              || body.instanceOwner?.organisationNumber !== approval.organization || ![incomeYear,String(incomeYear)].includes(body.dataValues?.inntektsaar)
              || body.process?.currentTask?.altinnTaskType !== "data" || body.process?.ended != null || body.status?.isArchived !== false || body.status?.archived != null
              || !Array.isArray(rows) || rows.length !== 1 || rows[0]?.id !== file.data || rows[0]?.dataType !== "skattemeldingOgNaeringsspesifikasjon"
              || rows[0].fileScanResult !== "Clean" || rows[0].size !== file.size || typeof rows[0].contentType !== "string"
              || !["application/xml","text/xml"].includes(rows[0].contentType.split(";",1)[0].trim().toLowerCase())
              || typeof approved !== "string" || await taxTextSha(approved) !== file.fileHash
              || Object.keys(target).sort().join(",") !== "appId,instansId" || target.appId !== "skd/formueinntekt-skattemelding-v2"
              || target.instansId !== binding.target_instance) throw new Error("Tax validation original is not the reviewed Clean envelope.");
        }
        if (value.version === "company-tax-delivery-mutation-request-v4") {
          const proof=binding.confirmation_prerequisite;const clean=proof?.clean_file;const calculated=proof?.calculated;const response=calculated?.response;
          const jobRef=proof?.job_read;const resultRef=proof?.result_read;const metadataRef=clean?.instance_read;const fileRef=clean?.envelope_read;
          const job=jobReads.get(record.filingId+":"+jobRef?.evidence_sha256);const result=resultReads.get(record.filingId+":"+resultRef?.evidence_sha256);
          const metadata=instanceReads.get(record.filingId+":"+metadataRef?.evidence_sha256);const file=envelopeReads.get(record.filingId+":"+fileRef?.evidence_sha256);
          const refs=[jobRef,resultRef,metadataRef,fileRef];const referenceKeys="event_sha256,evidence_sha256,observed_at";
          if (!journal.sourceFacts.evidence.version.startsWith("company-tax-source-v7:") || binding.kind !== "prepare_confirmation" || binding.body_base64 !== ""
              || !taxHasKeys(value,"request,version") || !taxHasKeys(binding,"approval_sha256,body_base64,company_id,confirmation_prerequisite,filing_id,income_year,kind,organization_number,target_instance")
              || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
              || !taxHasKeys(proof,"calculated,clean_file,envelope_sha256,job_read,observed_from,observed_until,result_read")
              || !taxHasKeys(clean,"data_id,envelope_read,instance_id,instance_read,observed_from,observed_until")
              || refs.some(ref => !taxHasKeys(ref,referenceKeys) || !taxTimeWrapper(ref.observed_at))
              || ![proof,clean].every(item => taxTimeWrapper(item.observed_from) && taxTimeWrapper(item.observed_until))
              || !job?.finished || !result || !metadata || !file || job.hash !== jobRef.event_sha256 || result.hash !== resultRef.event_sha256
              || latestJob.get(record.filingId) !== job.identity || latestResult.get(record.filingId) !== result.identity || result.job !== job.identity
              || metadata.hash !== metadataRef.event_sha256 || file.hash !== fileRef.event_sha256 || file.metadata !== metadata.identity
              || clean.instance_id !== binding.target_instance || metadata.instance !== binding.target_instance || file.instance !== binding.target_instance
              || clean.data_id !== file.data || proof.envelope_sha256 !== file.fileHash) throw new Error("Tax confirmation prerequisite originals or closed codec mismatch.");
          const times=[proof.observed_from.value,jobRef.observed_at.value,resultRef.observed_at.value,clean.observed_from.value,
            metadataRef.observed_at.value,fileRef.observed_at.value,clean.observed_until.value,proof.observed_until.value,record.recordedAt].map(Date.parse);
          const startRecorded=Date.parse(completedAt.get(record.filingId+":start_validation") ?? "");
          if (!times.every(Number.isFinite) || !Number.isFinite(startRecorded) || times[0] < startRecorded || times[8]-times[0] > 30000
              || times.some((time,index) => index > 0 && time < times[index-1])
              || [job.observedAt,result.observedAt,metadata.observedAt,file.observedAt].some(time => Date.parse(time) > times[7])) throw new Error("Tax confirmation read sequence is stale or noncausal.");
          const approved=drafts.get(record.filingId)?.envelope?.envelope_xml;
          const party=drafts.get(record.filingId)?.current_document?.party_number;
          if (typeof approved !== "string" || await taxTextSha(approved) !== file.fileHash
              || !taxHasKeys(calculated,"company_id,draft_sha256,income_year,party_number,response,schema_sha256")
              || !taxHasKeys(calculated.company_id,"value") || !taxHasKeys(calculated.income_year,"value")
              || calculated.schema_sha256 !== "c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769"
              || calculated.draft_sha256 !== approval.draft || calculated.company_id.value !== companyId || calculated.income_year.value !== incomeYear
              || typeof party !== "string" || calculated.party_number !== party
              || !taxHasKeys(response,"calculated_documents,calculation_deviation_count,failure_reason_count,guidance_count,original_sha256,result_code,schema_sha256,validation_deviation_count")
              || response.schema_sha256 !== "eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1"
              || response.original_sha256 !== result.originalHash || response.result_code !== "validertOK"
              || response.validation_deviation_count !== 0 || response.failure_reason_count !== 0
              || [response.calculation_deviation_count,response.guidance_count].some(count => !Number.isInteger(count) || count < 0 || count > 100000)
              || !Array.isArray(response.calculated_documents) || response.calculated_documents.length < 2 || response.calculated_documents.length > 4) throw new Error("Tax calculated projection does not bind the retained result and draft.");
          const kinds=new Set<string>();
          for (const document of response.calculated_documents) {
            if (!taxHasKeys(document,"body_base64,document_type") || kinds.has(document.document_type)
                || !["skattemeldingUpersonligEtterBeregning","naeringsspesifikasjonEtterBeregning","beregnetSkattUpersonlig","summertSkattegrunnlagForVisningUpersonlig"].includes(document.document_type)) throw new Error("Tax calculated document projection is unsupported.");
            await taxEncodedOriginal(document.body_base64);kinds.add(document.document_type);
          }
          if (!kinds.has("skattemeldingUpersonligEtterBeregning") || !kinds.has("naeringsspesifikasjonEtterBeregning")) throw new Error("Tax statutory calculated pair is incomplete.");
          taxProcessFile(metadata.text,{filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,
            approval:approval.hash,organization:approval.organization,instance:binding.target_instance},"data","Task_1",file.data,file.size);
          requestOriginals.set(record.filingId+":"+binding.kind,{bodyBase64:"",recordedAt:record.recordedAt,version:value.version,
            confirmation:{data:file.data,fileHash:file.fileHash}});
          // The browser binds retained projection/original identities. Pinned
          // XSD and XML projection checks remain backend inspection, not a new
          // browser readiness or Tax-acceptance verdict.
        }
      } else {
        if (!requests.has(record.filingId+":"+binding.kind)
            || typeof binding.request_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(binding.request_sha256)
            || binding.request_sha256 !== requests.get(record.filingId+":"+binding.kind)
            || binding.approved_by?.kind !== "USER" || binding.approved_by?.subject?.value !== approval.actor) throw new Error("Tax journal request binding mismatch.");
        const instance = value.completion?.result?.instanceId;
        if (typeof instance !== "string" || !/^[0-9]{1,19}\/[0-9a-f-]{36}$/u.test(instance)
            || (binding.kind !== "create_instance" && instance !== instances.get(record.filingId))) throw new Error("Tax journal instance mismatch.");
        if (binding.kind === "create_instance") instances.set(record.filingId,instance);
        if (binding.kind === "start_validation") {
          const request=requestOriginals.get(record.filingId+":"+binding.kind);
          const job=value.completion.result.jobId;
          if (typeof job !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u.test(job)) throw new Error("Tax start result has no known job ID.");
          if (typeof value.completion.response_base64 === "string") {
            const response=taxJsonObject((await taxEncodedOriginal(value.completion.response_base64)).text);
            if (value.completion.origin !== "mutation_response" || response.jobbId !== job
                || (request?.version === "company-tax-delivery-mutation-request-v3" && response.jobbStatus !== "OPPRETTET")) throw new Error("Tax start result differs from its exact response.");
            knownJobs.set(record.filingId,{job,request:binding.request_sha256,recordedAt:record.recordedAt});
          } else if (request?.version === "company-tax-delivery-mutation-request-v3") throw new Error("Tax start response original is missing.");
        }
        if (value.version === "company-tax-delivery-mutation-completion-v2") {
          const proof=value.completion.upload_read_evidence;const request=requestOriginals.get(record.filingId+":"+binding.kind);
          if (!/^company-tax-source-v[567]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "upload_envelope"
              || value.completion.origin !== "envelope_read" || "response_base64" in value.completion || !request || !proof
              || Object.keys(proof).sort().join(",") !== "envelope_canonical_json,envelope_sha256,instance_canonical_json,instance_sha256") throw new Error("Tax upload recovery proof is incomplete.");
          const scope={filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,approval:approval.hash,organization:approval.organization,instance};
          const metadata=await taxBoundRead(proof.instance_canonical_json,proof.instance_sha256,"instance",scope);
          const file=await taxBoundRead(proof.envelope_canonical_json,proof.envelope_sha256,"envelope",scope);
          const wire=await taxEncodedOriginal(request.bodyBase64);const body=taxJsonObject(metadata.original.text);
          const files=Array.isArray(body.data) ? body.data.filter((row: {dataType?: unknown}) => row?.dataType === "skattemeldingOgNaeringsspesifikasjon") : [];
          const metadataTime=Date.parse(metadata.binding.observed_at.value);const fileTime=Date.parse(file.binding.observed_at.value);const resultTime=Date.parse(value.completion.observed_at?.value);
          if (body.id !== instance || body.appId !== "skd/formueinntekt-skattemelding-v2" || body.instanceOwner?.organisationNumber !== approval.organization
              || ![incomeYear,String(incomeYear)].includes(body.dataValues?.inntektsaar) || files.length !== 1 || files[0].id !== file.binding.data_id
              || files[0].size !== file.original.size || typeof files[0].contentType !== "string"
              || !["application/xml","text/xml"].includes(files[0].contentType.split(";",1)[0].trim().toLowerCase())
              || file.binding.instance_evidence_sha256 !== metadata.identity || value.completion.result.dataId !== file.binding.data_id
              || value.completion.result.envelopeSha256 !== file.original.sha256 || wire.sha256 !== file.original.sha256
              || !Number.isFinite(resultTime) || metadataTime < Date.parse(request.recordedAt) || fileTime < metadataTime || resultTime < fileTime) throw new Error("Tax upload recovery originals differ from the request.");
        }
        const processRequest=requestOriginals.get(record.filingId+":"+binding.kind);
        if (processRequest?.version === "company-tax-delivery-mutation-request-v4" && value.version !== "company-tax-delivery-mutation-completion-v3") throw new Error("Tax confirmation completion is missing complete read originals.");
        if (value.version === "company-tax-delivery-mutation-completion-v3") {
          const result=value.completion;const proof=result.confirmation_read_evidence;const expected=processRequest?.confirmation;
          if (!journal.sourceFacts.evidence.version.startsWith("company-tax-source-v7:") || binding.kind !== "prepare_confirmation" || !expected
              || !taxHasKeys(value,"completion,version") || !taxHasKeys(result,"confirmation_read_evidence,intent,observed_at,origin,result")
              || !taxHasKeys(binding,"approval_sha256,approved_by,company_id,filing_id,income_year,kind,request_sha256")
              || !taxHasKeys(binding.approved_by,"kind,subject") || !taxHasKeys(binding.approved_by?.subject,"value")
              || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value") || !taxTimeWrapper(result.observed_at)
              || !taxHasKeys(result.result,"instanceId,processTask") || result.result.processTask !== "confirmation" || result.origin !== "confirmation_read"
              || !taxHasKeys(proof,"envelope_canonical_json,envelope_sha256,instance_canonical_json,instance_sha256")) throw new Error("Tax confirmation completion codec is unsupported.");
          const scope={filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,approval:approval.hash,organization:approval.organization,instance};
          const metadata=await taxBoundRead(proof.instance_canonical_json,proof.instance_sha256,"instance",scope,true);
          const file=await taxBoundRead(proof.envelope_canonical_json,proof.envelope_sha256,"envelope",scope,true);
          const times=[processRequest.recordedAt,metadata.binding.observed_at.value,file.binding.observed_at.value,result.observed_at.value,record.recordedAt].map(Date.parse);
          if (file.binding.instance_evidence_sha256 !== metadata.identity || file.binding.data_id !== expected.data || file.original.sha256 !== expected.fileHash
              || !times.every(Number.isFinite) || times.some((time,index) => index > 0 && time < times[index-1])) throw new Error("Tax confirmation result reads differ from the committed request.");
          taxProcessFile(metadata.original.text,scope,"confirmation","Task_2",expected.data,file.original.size);
        }
        completed.add(record.filingId+":"+binding.kind);
        completedAt.set(record.filingId+":"+binding.kind,record.recordedAt);
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
    if (/^company-tax-source-v[34567]:[0-9a-f]{64}$/u.test(source.evidence.version)
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
