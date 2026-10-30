/** Exact retained Tax artifact verification shared by SDK and web readers. */
import type {CompanyTaxDeliveryOriginalWire,CompanyTaxDeliveryDraftArchiveWire,CompanyTaxDeliveryJournalArchiveWire,CompanyTaxOwnerReviewArtifactWire} from "./generated/client.ts";
import {SaxesParser} from "saxes";

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

export async function verifyCompanyTaxOwnerReviewArtifact(result: CompanyTaxOwnerReviewArtifactWire,approvalSha256: string) {
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

async function taxEncodedBytes(encoded: string) {
  if (typeof encoded !== "string" || encoded.length > 12*1024*1024) throw new Error("Tax original exceeds its limit.");
  const decoded=atob(encoded);
  if (!decoded.length || decoded.length > 8*1024*1024 || btoa(decoded) !== encoded) throw new Error("Tax read original encoding changed.");
  const bytes=Uint8Array.from(decoded,char => char.charCodeAt(0));
  const sha256=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))
    .map(byte => byte.toString(16).padStart(2,"0")).join("");
  return {bytes,sha256,size:bytes.length};
}

async function taxEncodedOriginal(encoded: string) {
  const value=await taxEncodedBytes(encoded);
  return {text:new TextDecoder("utf-8",{fatal:true}).decode(value.bytes),sha256:value.sha256,size:value.size};
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

async function taxFeedbackRead(raw: string,sha256: string,scope: TaxOriginalScope,metadata: {identity: string;text: string;observedAt: string}) {
  const value=await exactTaxOriginal(raw,sha256);const binding=value.observation;
  if (value.version!=="company-tax-delivery-feedback-observation-v1" || !taxHasKeys(value,"observation,version")
      || !taxHasKeys(binding,"approval_sha256,approved_by,company_id,data_id,filing_id,income_year,instance_evidence_sha256,instance_id,observed_at,organization_number,original")
      || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
      || !taxHasKeys(binding.approved_by,"kind,subject") || !taxHasKeys(binding.approved_by.subject,"value") || !taxTimeWrapper(binding.observed_at)
      || binding.filing_id!==scope.filing || binding.company_id.value!==scope.company || binding.income_year.value!==scope.year
      || binding.approved_by.kind!=="USER" || binding.approved_by.subject.value!==scope.actor || binding.approval_sha256!==scope.approval
      || binding.organization_number!==scope.organization || binding.instance_id!==scope.instance || binding.instance_evidence_sha256!==metadata.identity
      || typeof binding.data_id!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(binding.data_id)
      || !taxHasKeys(binding.original,"body_base64,content_type,http_status,purpose") || binding.original.purpose!=="feedback"
      || binding.original.http_status!==200 || !["application/xml","text/xml"].includes(binding.original.content_type)) throw new Error("Tax receipt original scope changed.");
  const original=await taxEncodedBytes(binding.original.body_base64);
  const body=taxJsonObject(metadata.text,["size"],3);const rows=body.data;
  const files=Array.isArray(rows)?rows.filter((row: {dataType?: unknown})=>row?.dataType==="tilbakemelding"):[];
  if (files.length!==1 || files[0].id!==binding.data_id || files[0].size!==original.size || typeof files[0].contentType!=="string"
      || !["application/xml","text/xml"].includes(files[0].contentType.split(";",1)[0].trim().toLowerCase())
      || Date.parse(binding.observed_at.value)<Date.parse(metadata.observedAt)) throw new Error("Tax receipt differs from its exact known metadata.");
  const identity=await taxTextSha(JSON.stringify(["tax-feedback-read-identity-v1",scope.filing,scope.company,scope.year,scope.actor,
    scope.approval,scope.organization,scope.instance,binding.data_id,metadata.identity,original.sha256]));
  return {binding,original,identity,scan:files[0].fileScanResult};
}

function taxSubmittedFile(text: string,scope: TaxOriginalScope,data: string,size: number,observedAt: string,receiptClean: boolean) {
  const body=taxJsonObject(text,["flow","size"],3);const rows=body.data;const task=body.process?.currentTask;
  if (body.id!==scope.instance || body.appId!=="skd/formueinntekt-skattemelding-v2" || body.instanceOwner?.organisationNumber!==scope.organization
      || ![scope.year,String(scope.year)].includes(body.dataValues?.inntektsaar) || !Array.isArray(rows) || rows.length<1 || rows.length>2
      || rows.some(row=>!row || !["skattemeldingOgNaeringsspesifikasjon","tilbakemelding"].includes(row.dataType)
        || !Number.isInteger(row.size) || row.size<0 || row.size>8*1024*1024 || typeof row.contentType!=="string" || !row.contentType
        || typeof row.fileScanResult!=="string" || !row.fileScanResult)
      || new Set(rows.map(row=>row.id)).size!==rows.length || new Set(rows.map(row=>row.dataType)).size!==rows.length) throw new Error("Tax submitted metadata is incomplete.");
  const file=rows.find(row=>row.dataType==="skattemeldingOgNaeringsspesifikasjon");
  if (!file || file.id!==data || file.size!==size || file.fileScanResult!=="Clean"
      || !["application/xml","text/xml"].includes(file.contentType.split(";",1)[0].trim().toLowerCase())) throw new Error("Tax submitted file is not the exact Clean original.");
  const active=task?.altinnTaskType==="feedback" && task.elementId==="Task_3" && Number.isInteger(task.flow) && task.flow>=1 && task.flow<=2147483647
    && body.process.ended==null && body.status?.isArchived===false && body.status.archived==null;
  const terminal=task==null && taxTimeWrapper({value:body.process?.ended}) && body.status?.isArchived===true
    && taxTimeWrapper({value:body.status.archived}) && Date.parse(body.status.archived)>=Date.parse(body.process.ended)
    && Date.parse(body.status.archived)<=Date.parse(observedAt) && receiptClean;
  if (!active && !terminal) throw new Error("Tax submission has no ordinary feedback or complete terminal receipt proof.");
}

export async function verifyCompanyTaxDeliveryDraftArchive(originals: CompanyTaxDeliveryDraftArchiveWire,companyId: string,incomeYear: number,correctionEvidence=false) {
  for (const record of originals.records) {
    const value = await exactTaxOriginal(record.canonicalJson,record.draftSha256);
    if (!["company-tax-delivery-draft-v1","company-tax-delivery-draft-v2",...(correctionEvidence?["company-tax-delivery-draft-v3"]:[])].includes(value.version)
        || value.version!=="company-tax-delivery-draft-v3" && Object.hasOwn(value.draft ?? {},"correction_parent")
        || value.draft?.filing_id !== record.filingId
        || value.draft?.envelope?.source?.company_id?.value !== companyId
        || value.draft?.envelope?.source?.income_year?.value !== incomeYear) throw new Error("Tax draft original mismatch.");
  }
}

export async function verifyCompanyTaxDeliveryJournalArchive(journal: CompanyTaxDeliveryJournalArchiveWire,companyId: string,incomeYear: number) {
  await verifyCompanyTaxDeliveryDraftArchive({companyId,incomeYear,codec:"company-tax-delivery-draft-archive-v1",coverage:"complete",
    sourceSha256:journal.sourceSha256,observedAt:journal.observedAt,recordCount:journal.draftCount,records:journal.drafts},
    companyId,incomeYear,/^company-tax-source-v9:/u.test(journal.sourceFacts.evidence.version));
  const approvals = new Map<string,{hash: string;actor: string;context: string;draft: string;organization: string | undefined}>();
  const requests = new Map<string,string>();
  const requestOriginals = new Map<string,{bodyBase64: string;recordedAt: string;version: string;confirmation?: {data: string;fileHash: string;responseHash: string};submission?: {data: string;fileHash: string}}>();
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
    if (record.slot.startsWith("observation:feedback:")) {
      const approval=approvals.get(record.filingId);const request=requestOriginals.get(record.filingId+":confirm_submission");
      const metadata=instanceReads.get(record.filingId+":"+value.observation?.instance_evidence_sha256);
      if (!/^company-tax-source-v[89]:/u.test(journal.sourceFacts.evidence.version) || !approval || request?.version!=="company-tax-delivery-mutation-request-v5"
          || !metadata || record.recordedBy!==approval.actor) throw new Error("Tax receipt has no known submission and metadata prefix.");
      const scope={filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,approval:approval.hash,
        organization:approval.organization,instance:metadata.instance};
      const receipt=await taxFeedbackRead(record.canonicalJson,record.eventSha256,scope,metadata);
      if (record.slot!=="observation:feedback:"+receipt.identity || Date.parse(metadata.observedAt)<Date.parse(request.recordedAt)
          || Date.parse(receipt.binding.observed_at.value)>Date.parse(record.recordedAt)) throw new Error("Tax receipt original identity or time changed.");
      latest.set(record.filingId,record);continue;
    }
    if (validationJob || validationResult) {
      const approval=approvals.get(record.filingId);const job=knownJobs.get(record.filingId);const binding=value.observation;
      const kind=validationJob ? "validation-job" : "validation-result";
      const keys="approval_sha256,approved_by,company_id,filing_id,income_year,instance_id,job_id,observed_at,organization_number,original,start_request_sha256";
      const expectedKeys=validationJob ? keys : keys.split(",").concat("job_status_evidence_sha256","schema_sha256").sort().join(",");
      const observed=Date.parse(binding?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
      if (!/^company-tax-source-v[6789]:/u.test(journal.sourceFacts.evidence.version) || !approval || !job
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
      if (!/^company-tax-source-v[456789]:/u.test(journal.sourceFacts.evidence.version)) throw new Error("Tax reads require a supported evidence source.");
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
          if (!/^company-tax-source-v[56789]:/u.test(journal.sourceFacts.evidence.version) || !predecessor
              || predecessor.instance !== binding.instance_id || Date.parse(binding.observed_at.value) < Date.parse(predecessor.observedAt)) throw new Error("Tax envelope has no retained metadata predecessor.");
          envelopeReads.set(record.filingId+":"+read.identity,{hash:record.eventSha256,identity:read.identity,observedAt:binding.observed_at.value,
            instance:binding.instance_id,data:binding.data_id,metadata:binding.instance_evidence_sha256,fileHash:read.original.sha256,size:read.original.size});
        } else instanceReads.set(record.filingId+":"+read.identity,{hash:record.eventSha256,identity:read.identity,observedAt:binding.observed_at.value,instance:binding.instance_id,text:read.original.text});
      }
      latest.set(record.filingId,record);
      continue;
    }
    if (record.slot === "acknowledgment:prepare_confirmation" || record.slot === "acknowledgment:confirm_submission") {
      const binding=value.acknowledgment;const approval=approvals.get(record.filingId);
      const kind=record.slot.split(":")[1];const submission=kind==="confirm_submission";
      const request=requestOriginals.get(record.filingId+":"+kind);
      const observed=Date.parse(binding?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
      if (!(submission?/^company-tax-source-v[89]:/u.test(journal.sourceFacts.evidence.version):/^company-tax-source-v[789]:/u.test(journal.sourceFacts.evidence.version))
          || !approval || request?.version !== "company-tax-delivery-mutation-request-v"+(submission?"5":"4")
          || value.version !== "company-tax-delivery-process-acknowledgment-v"+(submission?"2":"1") || !taxHasKeys(value,"acknowledgment,version")
          || !taxHasKeys(binding,"approval_sha256,approved_by,company_id,filing_id,income_year,instance_id,"+(submission?"kind,":"")+"observed_at,organization_number,original,request_sha256")
          || submission && binding.kind!==kind
          || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value") || !taxHasKeys(binding.approved_by,"kind,subject")
          || !taxHasKeys(binding.approved_by?.subject,"value") || !taxTimeWrapper(binding.observed_at)
          || binding.filing_id !== record.filingId || binding.company_id.value !== companyId || binding.income_year.value !== incomeYear
          || binding.approved_by.kind !== "USER" || binding.approved_by.subject.value !== approval.actor || record.recordedBy !== approval.actor
          || binding.approval_sha256 !== approval.hash || binding.organization_number !== approval.organization
          || binding.instance_id !== instances.get(record.filingId) || binding.request_sha256 !== requests.get(record.filingId+":"+kind)
          || ![observed,recorded].every(Number.isFinite) || observed < Date.parse(request.recordedAt) || observed > recorded) throw new Error("Tax acknowledgment is not bound to the committed preparation.");
      await taxReadOriginal(binding.original,"process_response");latest.set(record.filingId,record);continue;
    }
    const mode = record.slot === "review" ? "review" : record.slot.startsWith("intent:") ? "intent" : "completion";
    const expected = {review:["company-tax-delivery-review-approval-v1"],intent:["company-tax-delivery-mutation-request-v1","company-tax-delivery-mutation-request-v2","company-tax-delivery-mutation-request-v3","company-tax-delivery-mutation-request-v4","company-tax-delivery-mutation-request-v5"],completion:["company-tax-delivery-mutation-completion-v1","company-tax-delivery-mutation-completion-v2","company-tax-delivery-mutation-completion-v3","company-tax-delivery-mutation-completion-v4"]}[mode];
    const binding = mode === "review" ? value.approval : mode === "intent" ? value.request : value.completion?.intent;
    if (binding?.kind==="confirm_submission" && value.version!==(mode==="intent"
        ?"company-tax-delivery-mutation-request-v5":"company-tax-delivery-mutation-completion-v4")) {
      throw new Error("Tax submission cannot use a legacy codec without owner confirmation or complete read evidence.");
    }
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
        const predecessors = {create_instance:null,upload_envelope:"create_instance",start_validation:"upload_envelope",prepare_confirmation:"start_validation",confirm_submission:"prepare_confirmation"};
        const predecessor = predecessors[binding.kind as keyof typeof predecessors];
        if (predecessor === undefined || (predecessor !== null
            && (!completed.has(record.filingId+":"+predecessor) || binding.target_instance !== instances.get(record.filingId)))) throw new Error("Tax journal predecessor is incomplete.");
        requests.set(record.filingId+":"+binding.kind,record.eventSha256);
        requestOriginals.set(record.filingId+":"+binding.kind,{bodyBase64:binding.body_base64,recordedAt:record.recordedAt,version:value.version});
        if (value.version === "company-tax-delivery-mutation-request-v2") {
          const proof=binding.upload_prerequisite;const reference=proof?.instance_read;
          const original=instanceReads.get(record.filingId+":"+reference?.evidence_sha256);
          const start=Date.parse(proof?.observed_from?.value);const end=Date.parse(proof?.observed_until?.value);const read=Date.parse(reference?.observed_at?.value);const recorded=Date.parse(record.recordedAt);
          if (!/^company-tax-source-v[56789]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "upload_envelope"
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
          if (!/^company-tax-source-v[6789]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "start_validation"
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
          if (!/^company-tax-source-v[789]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "prepare_confirmation" || binding.body_base64 !== ""
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
            confirmation:{data:file.data,fileHash:file.fileHash,responseHash:result.originalHash}});
          // The browser binds retained projection/original identities. Pinned
          // XSD and XML projection checks remain backend inspection, not a new
          // browser readiness or Tax-acceptance verdict.
        }
        if (value.version === "company-tax-delivery-mutation-request-v5") {
          const proof=binding.submission_prerequisite;const decision=proof?.owner_confirmation;
          const prep=requestOriginals.get(record.filingId+":prepare_confirmation");const prepared=effects.get(record.filingId);
          const refs=[proof?.job_read,proof?.result_read,proof?.instance_read,proof?.envelope_read];
          const job=jobReads.get(record.filingId+":"+refs[0]?.evidence_sha256);const result=resultReads.get(record.filingId+":"+refs[1]?.evidence_sha256);
          const metadata=instanceReads.get(record.filingId+":"+refs[2]?.evidence_sha256);const file=envelopeReads.get(record.filingId+":"+refs[3]?.evidence_sha256);
          if (!/^company-tax-source-v[89]:/u.test(journal.sourceFacts.evidence.version) || binding.kind!=="confirm_submission" || binding.body_base64!==""
              || !taxHasKeys(value,"request,version") || !taxHasKeys(binding,"approval_sha256,body_base64,company_id,filing_id,income_year,kind,organization_number,submission_prerequisite,target_instance")
              || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value")
              || !taxHasKeys(proof,"data_id,envelope_read,envelope_sha256,instance_id,instance_read,job_read,observed_from,observed_until,owner_confirmation,result_read")
              || !taxHasKeys(decision,"documents_confirmed,owner_review_sha256,preparation_request_sha256,preparation_result_sha256,response_original_sha256,warnings_acknowledged")
              || !taxTimeWrapper(proof.observed_from) || !taxTimeWrapper(proof.observed_until)
              || refs.some(ref=>!taxHasKeys(ref,"event_sha256,evidence_sha256,observed_at") || !taxTimeWrapper(ref.observed_at))
              || !job?.finished || !result || !metadata || !file || job.hash!==refs[0].event_sha256 || result.hash!==refs[1].event_sha256
              || metadata.hash!==refs[2].event_sha256 || file.hash!==refs[3].event_sha256 || result.job!==job.identity
              || latestJob.get(record.filingId)!==job.identity || latestResult.get(record.filingId)!==result.identity
              || file.metadata!==metadata.identity || proof.instance_id!==binding.target_instance || metadata.instance!==binding.target_instance
              || file.instance!==binding.target_instance || proof.data_id!==file.data || proof.envelope_sha256!==file.fileHash
              || prep?.version!=="company-tax-delivery-mutation-request-v4" || !prep.confirmation
              || prep.confirmation.data!==file.data || prep.confirmation.fileHash!==file.fileHash
              || decision.documents_confirmed!==true || decision.warnings_acknowledged!==true
              || typeof decision.owner_review_sha256!=="string" || !/^[0-9a-f]{64}$/u.test(decision.owner_review_sha256)
              || decision.preparation_request_sha256!==requests.get(record.filingId+":prepare_confirmation")
              || prepared?.slot!=="completion:prepare_confirmation" || decision.preparation_result_sha256!==prepared.eventSha256
              || decision.response_original_sha256!==result.originalHash || decision.response_original_sha256!==prep.confirmation.responseHash) {
            throw new Error("Tax submission is not bound to explicit owner confirmation and known preparation originals.");
          }
          const times=[proof.observed_from.value,...refs.map(ref=>ref.observed_at.value),proof.observed_until.value,record.recordedAt].map(Date.parse);
          const originals=[job.observedAt,result.observedAt,metadata.observedAt,file.observedAt].map(Date.parse);
          if (!times.every(Number.isFinite) || !originals.every(Number.isFinite) || times[0]<Date.parse(prepared.recordedAt)
              || times[6]-times[0]>30000 || times.some((time,index)=>index>0 && time<times[index-1])
              || originals.some((time,index)=>time>times[index+1])) throw new Error("Tax submission read freshness changed.");
          taxProcessFile(metadata.text,{filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,
            approval:approval.hash,organization:approval.organization,instance:binding.target_instance},"confirmation","Task_2",file.data,file.size);
          requestOriginals.set(record.filingId+":"+binding.kind,{bodyBase64:"",recordedAt:record.recordedAt,version:value.version,
            submission:{data:file.data,fileHash:file.fileHash}});
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
          if (!/^company-tax-source-v[56789]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "upload_envelope"
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
        if (processRequest?.version === "company-tax-delivery-mutation-request-v5" && value.version !== "company-tax-delivery-mutation-completion-v4") throw new Error("Tax submission completion is missing complete read originals.");
        if (value.version === "company-tax-delivery-mutation-completion-v3") {
          const result=value.completion;const proof=result.confirmation_read_evidence;const expected=processRequest?.confirmation;
          if (!/^company-tax-source-v[789]:/u.test(journal.sourceFacts.evidence.version) || binding.kind !== "prepare_confirmation" || !expected
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
        if (value.version === "company-tax-delivery-mutation-completion-v4") {
          const result=value.completion;const proof=result.submission_read_evidence;const expected=processRequest?.submission;
          if (!/^company-tax-source-v[89]:/u.test(journal.sourceFacts.evidence.version) || binding.kind!=="confirm_submission" || !expected
              || !taxHasKeys(value,"completion,version") || !taxHasKeys(result,"intent,observed_at,origin,result,submission_read_evidence")
              || !taxHasKeys(binding,"approval_sha256,approved_by,company_id,filing_id,income_year,kind,request_sha256")
              || !taxHasKeys(binding.approved_by,"kind,subject") || !taxHasKeys(binding.approved_by.subject,"value")
              || !taxHasKeys(binding.company_id,"value") || !taxHasKeys(binding.income_year,"value") || !taxTimeWrapper(result.observed_at)
              || !taxHasKeys(result.result,"instanceId,processTask") || result.result.processTask!=="feedback" || result.origin!=="submission_read"
              || !taxHasKeys(proof,"envelope_canonical_json,envelope_sha256,feedback_canonical_json,feedback_sha256,instance_canonical_json,instance_sha256")
              || (proof.feedback_canonical_json===null)!==(proof.feedback_sha256===null)) throw new Error("Tax submission completion codec is unsupported.");
          const scope={filing:record.filingId,company:companyId,year:incomeYear,actor:approval.actor,approval:approval.hash,organization:approval.organization,instance};
          const metadata=await taxBoundRead(proof.instance_canonical_json,proof.instance_sha256,"instance",scope,true);
          const file=await taxBoundRead(proof.envelope_canonical_json,proof.envelope_sha256,"envelope",scope,true);
          const receipt=proof.feedback_canonical_json===null?null:await taxFeedbackRead(proof.feedback_canonical_json,proof.feedback_sha256,scope,
            {identity:metadata.identity,text:metadata.original.text,observedAt:metadata.binding.observed_at.value});
          const times=[processRequest.recordedAt,metadata.binding.observed_at.value,file.binding.observed_at.value,
            result.observed_at.value,record.recordedAt].map(Date.parse);
          const receiptTime=receipt?Date.parse(receipt.binding.observed_at.value):null;
          if (file.binding.instance_evidence_sha256!==metadata.identity || file.binding.data_id!==expected.data || file.original.sha256!==expected.fileHash
              || !times.every(Number.isFinite) || times.some((time,index)=>index>0 && time<times[index-1])
              || receipt && (receipt.scan!=="Clean" || receiptTime===null || !Number.isFinite(receiptTime) || receiptTime<times[1] || receiptTime>times[3])) throw new Error("Tax submission result differs from its exact committed intent and known originals.");
          taxSubmittedFile(metadata.original.text,scope,expected.data,file.original.size,metadata.binding.observed_at.value,receipt?.scan==="Clean");
        }
        completed.add(record.filingId+":"+binding.kind);
        completedAt.set(record.filingId+":"+binding.kind,record.recordedAt);
      }
    }
    latest.set(record.filingId,record);
    effects.set(record.filingId,record);
  }
  await verifyTaxCorrectionLineage(journal,companyId,incomeYear);
  if (journal.journals.length !== latest.size || journal.journals.some(fact => {
    const record=latest.get(fact.filingId);const effect=effects.get(fact.filingId);const approval=approvals.get(fact.filingId);
    return !record || !effect || !approval || fact.approvalSha256 !== approval.hash || fact.approvedBy !== approval.actor
      || fact.latestEventSha256 !== record.eventSha256 || fact.recordedAt !== record.recordedAt
      || fact.status !== (effect.slot === "review" ? "reviewed" : effect.slot.startsWith("intent:") ? "uncertain" : "mutation_completed")
      || fact.mutationKind !== (effect.slot === "review" ? null : effect.slot.split(":")[1]);
  })) throw new Error("Tax journal summary mismatch.");
}

type TaxXmlNode={name: string;uri: string;text: string;children: TaxXmlNode[]};

function taxDraftCommittedSubtrees(raw: string) {
  // Python's retained JSON preserves distinctions such as 0 and 0.0. Hash
  // exact canonical subtrees; JSON.parse/stringify would change their bytes.
  const wanted=new Set(["draft/envelope","draft/envelope/source"]);const found=new Map<string,string>();
  const stack: {path: string[];object: boolean;key: string | null;expectKey: boolean;index: number;start: number}[]=[];
  const path=()=>{const parent=stack.at(-1);return parent?[...parent.path,parent.object?String(parent.key):String(parent.index)]:[];};
  const finish=()=>{const parent=stack.at(-1);if (parent) {parent.key=null;if (!parent.object) parent.index++;}};
  for (const match of raw.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]:,]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/gu)) {
    const token=match[0];const top=stack.at(-1);
    if (token==="{" || token==="[") stack.push({path:path(),object:token==="{",key:null,expectKey:token==="{",index:0,start:match.index});
    else if (token==="}" || token==="]") {
      const frame=stack.pop();if (!frame) throw new Error("Tax draft subtree is incomplete.");
      const key=frame.path.join("/");if (wanted.has(key)) found.set(key,raw.slice(frame.start,match.index+token.length));
      finish();
    } else if (token===",") {if (top?.object) top.expectKey=true;}
    else if (token!==":") {
      if (top?.object && top.expectKey) {top.key=JSON.parse(token);top.expectKey=false;}
      else finish();
    }
  }
  if (stack.length || found.size!==wanted.size) throw new Error("Tax draft committed source or envelope is missing.");
  return found;
}

async function verifyTaxCorrectionDraftCommitments(raw: string,draft: ReturnType<typeof taxJsonObject>) {
  const pin="56668da96711b664843df91d518bb127eb79bddf93c9635765bbd28d35bdda1b";
  const proof=draft.validation;const envelope=draft.envelope;const current=draft.current_document;
  if (!taxHasKeys(proof,"business_xml_sha256,envelope_xml_sha256,review_sha256,schema_sha256,source_sha256,tax_xml_sha256")
      || Object.values(proof).some(value=>typeof value!=="string" || !/^[0-9a-f]{64}$/u.test(value))
      || !taxHasKeys(envelope,"business_xml,current_document_reference,envelope_xml,schema_sha256,source,tax_xml")
      || !taxHasKeys(envelope.source,"annual_data,company_id,holding_actions,income_year,ledger_entries,organization_number,upstream_sha256")
      || !taxHasKeys(current,"document_kind,document_reference,party_number,response,schema_sha256,tax_xml_sha256")
      || proof.schema_sha256!==pin || envelope.schema_sha256!==pin || current.schema_sha256!==pin
      || [envelope.tax_xml,envelope.business_xml,envelope.envelope_xml].some(value=>typeof value!=="string" || !value || new TextEncoder().encode(value).length>8*1024*1024)) throw new Error("Tax correction validation or schema commitment is incomplete.");
  const source=envelope.source;
  if (!taxHasKeys(source.company_id,"value") || !taxHasKeys(source.income_year,"value")
      || !taxHasKeys(source.upstream_sha256,"annual,investments,ledger") || Object.values(source.upstream_sha256).some(value=>typeof value!=="string" || !/^[0-9a-f]{64}$/u.test(value))
      || !taxHasKeys(draft.command_key,"value") || typeof draft.command_key.value!=="string" || !draft.command_key.value || draft.command_key.value.length>255
      || !taxHasKeys(draft.prepared_by,"kind,subject") || !taxHasKeys(draft.prepared_by.subject,"value")
      || !taxHasKeys(current.response,"income_year,observed_at,organization_number,raw_base64") || !taxHasKeys(current.response.income_year,"value")
      || !taxTimeWrapper(current.response.observed_at) || !source.annual_data || typeof source.annual_data!=="object" || Array.isArray(source.annual_data)
      || source.annual_data.company_id!==source.company_id.value || source.annual_data.income_year!==source.income_year.value
      || [source.ledger_entries,source.holding_actions].some(rows=>!Array.isArray(rows)
        || rows.some(row=>!row || typeof row!=="object" || Array.isArray(row) || typeof row.id!=="string" || !row.id
          || row.company_id!==source.company_id.value || row.income_year!==source.income_year.value)
        || new Set(rows.map(row=>row.id)).size!==rows.length)) throw new Error("Tax correction source or identity codec is incomplete.");
  const subtrees=taxDraftCommittedSubtrees(raw);
  if (proof.source_sha256!==await taxTextSha(subtrees.get("draft/envelope/source")!)
      || proof.review_sha256!==await taxTextSha(subtrees.get("draft/envelope")!)
      || proof.tax_xml_sha256!==await taxTextSha(envelope.tax_xml)
      || proof.business_xml_sha256!==await taxTextSha(envelope.business_xml)
      || proof.envelope_xml_sha256!==await taxTextSha(envelope.envelope_xml)) throw new Error("Tax correction validation differs from its exact source and statutory bytes.");
}

function taxXmlOriginal(text: string): TaxXmlNode {
  if (typeof text!=="string" || new TextEncoder().encode(text).length>8*1024*1024) throw new Error("Tax XML original exceeds its limit.");
  const parser=new SaxesParser({xmlns:true});const stack: TaxXmlNode[]=[];let root: TaxXmlNode | undefined;let nodes=0;
  parser.on("error",error=>{throw error;});
  parser.on("doctype",()=>{throw new Error("Tax XML DTD is unsupported.");});
  parser.on("processinginstruction",()=>{throw new Error("Tax XML processing instructions are unsupported.");});
  parser.on("xmldecl",declaration=>{
    if (declaration.encoding && declaration.encoding.toUpperCase().replaceAll("-","")!=="UTF8") throw new Error("Tax XML encoding differs from its retained bytes.");
  });
  parser.on("opentag",tag=>{
    if (++nodes>100000 || stack.length>=64 || Object.values(tag.attributes).some(attribute=>
      attribute.uri!=="http://www.w3.org/2000/xmlns/" && !(attribute.uri==="http://www.w3.org/2001/XMLSchema-instance" && attribute.local==="schemaLocation"))) throw new Error("Tax XML structure is unsupported.");
    const node={name:tag.local,uri:tag.uri,text:"",children:[] as TaxXmlNode[]};
    if (stack.length) stack[stack.length-1].children.push(node);
    else {if (root) throw new Error("Tax XML has multiple roots.");root=node;}
    stack.push(node);
  });
  const append=(text: string)=>{const node=stack.at(-1);if (node) node.text+=text;else if (text.trim()) throw new Error("Tax XML has unscoped content.");};
  parser.on("text",append);parser.on("cdata",append);parser.on("closetag",()=>{stack.pop();});
  parser.write(text).close();
  if (!root || stack.length) throw new Error("Tax XML original is incomplete.");
  return root;
}

function taxXmlChildren(node: TaxXmlNode,names: readonly string[],uri=node.uri) {
  if (node.text.trim() || node.children.length!==names.length || node.children.some((child,index)=>child.name!==names[index] || child.uri!==uri)) throw new Error("Tax XML original has unknown, duplicate or reordered content.");
  return node.children;
}

function taxXmlLeaf(node: TaxXmlNode,name: string,uri=node.uri) {
  const nodes=node.children.filter(child=>child.name===name && child.uri===uri);
  if (nodes.length!==1 || nodes[0].children.length) throw new Error("Tax XML identity is missing or ambiguous.");
  return nodes[0].text;
}

async function verifyTaxCorrectionCurrent(draft: ReturnType<typeof taxJsonObject>,link: ReturnType<typeof taxJsonObject>,incomeYear: number) {
  const current=draft.current_document;const response=current?.response;
  if (!response || response.organization_number!==draft.envelope.source.organization_number || response.income_year?.value!==incomeYear) throw new Error("Tax correction current response has a different scope.");
  const original=await taxEncodedOriginal(response.raw_base64);const root=taxXmlOriginal(original.text);
  const ns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2";
  if (root.name!=="skattemeldingOgNaeringsspesifikasjonforespoerselResponse" || root.uri!==ns) throw new Error("Tax current response namespace differs.");
  const outer=taxXmlChildren(root,root.children.length===1?["dokumenter"]:["dokumenter","laasteFelt"],ns);
  if (outer[1] && (outer[1].children.length || outer[1].text.trim())) throw new Error("Tax correction current fields are locked.");
  const [tax,business]=taxXmlChildren(outer[0],["skattemeldingdokument","naeringsspesifikasjondokument"],ns);
  taxXmlChildren(tax,["id","encoding","content","type"],ns);taxXmlChildren(business,["id","encoding","content"],ns);
  const reference=taxXmlLeaf(tax,"id",ns);const kind=taxXmlLeaf(tax,"type",ns);
  if (!reference.trim() || reference!==reference.trim() || reference!==current.document_reference
      || reference!==draft.envelope.current_document_reference || kind!==current.document_kind
      || !["skattemeldingUpersonligUtkast","skattemeldingUpersonligFastsatt"].includes(kind)
      || taxXmlLeaf(tax,"encoding",ns)!=="utf-8" || taxXmlLeaf(business,"encoding",ns)!=="utf-8") throw new Error("Tax correction current identity differs from its retained XML.");
  const taxBytes=await taxEncodedOriginal(taxXmlLeaf(tax,"content",ns).replace(/[\t\n\r ]+/gu,""));
  const businessBytes=await taxEncodedOriginal(taxXmlLeaf(business,"content",ns).replace(/[\t\n\r ]+/gu,""));
  if (taxBytes.sha256!==link.calculated_tax_sha256 || taxBytes.sha256!==current.tax_xml_sha256
      || businessBytes.sha256!==link.calculated_business_sha256) throw new Error("Tax correction current statutory originals differ from the known parent.");
  const taxDocument=taxXmlOriginal(taxBytes.text);const businessDocument=taxXmlOriginal(businessBytes.text);
  if (taxDocument.uri!=="urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5"
      || businessDocument.uri!=="urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6"
      || taxXmlLeaf(taxDocument,"partsnummer")!==current.party_number || businessDocument.children.filter(node=>node.name==="partsreferanse").length!==1
      || taxXmlLeaf(businessDocument,"partsreferanse")!==current.party_number || taxXmlLeaf(taxDocument,"inntektsaar")!==String(incomeYear)
      || taxXmlLeaf(businessDocument,"inntektsaar")!==String(incomeYear)) throw new Error("Tax correction statutory scope differs from its current identity.");
  // Bind the fresh authority reference to the actual complete request bytes,
  // rather than relying on the draft's cached envelope label.
  const request=taxXmlOriginal(draft.envelope.envelope_xml);const requestNs="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2";
  if (request.uri!==requestNs) throw new Error("Tax correction request namespace differs.");
  const references=request.children.filter(node=>node.name==="dokumentreferanseTilGjeldendeDokument" && node.uri===requestNs);
  if (references.length!==1 || taxXmlLeaf(references[0],"dokumenttype",requestNs)!=="skattemeldingUpersonlig"
      || taxXmlLeaf(references[0],"dokumentidentifikator",requestNs)!==reference) throw new Error("Tax correction complete request does not bind the fresh authority reference.");
}

async function verifyTaxCorrectionLineage(journal: CompanyTaxDeliveryJournalArchiveWire,companyId: string,incomeYear: number) {
  const drafts=new Map(journal.drafts.map(row=>[row.filingId,{row,root:taxJsonObject(row.canonicalJson)}]));
  const events=new Map(journal.events.map(row=>[row.filingId+":"+row.slot,{row,root:taxJsonObject(row.canonicalJson)}]));
  const children=new Map<string,string>();const participating=new Set(journal.events.map(row=>row.filingId));
  for (const {row,root} of drafts.values()) {
    if (!["company-tax-delivery-draft-v1","company-tax-delivery-draft-v2","company-tax-delivery-draft-v3"].includes(root.version)) throw new Error("Unknown Tax draft codec.");
    const link=root.draft?.correction_parent;
    if (root.version!=="company-tax-delivery-draft-v3") {
      if (link!==undefined) throw new Error("Tax parent link requires its positive draft codec.");
      continue;
    }
    if (!/^company-tax-source-v9:/u.test(journal.sourceFacts.evidence.version)
        || !taxHasKeys(root,"draft,version") || !taxHasKeys(root.draft,"command_key,correction_parent,current_document,envelope,filing_id,prepared_by,validation")
        || !taxHasKeys(link,"approval_sha256,calculated_business_sha256,calculated_tax_sha256,draft_sha256,filing_id,submission_completion_sha256,submission_request_sha256,terminal")
        || typeof link.filing_id!=="string" || children.has(link.filing_id) || link.filing_id===row.filingId) throw new Error("Tax correction lineage codec or parent is invalid.");
    const parent=drafts.get(link.filing_id);const review=events.get(link.filing_id+":review");
    const request=events.get(link.filing_id+":intent:confirm_submission");const completion=events.get(link.filing_id+":completion:confirm_submission");
    const preparation=events.get(link.filing_id+":intent:prepare_confirmation");
    const approval=review?.root.approval;const child=root.draft;
    if (!parent || !review || !request || !completion || !preparation || !approval
        || parent.row.draftSha256!==link.draft_sha256 || review.row.eventSha256!==link.approval_sha256
        || request.row.eventSha256!==link.submission_request_sha256 || completion.row.eventSha256!==link.submission_completion_sha256
        || request.root.version!=="company-tax-delivery-mutation-request-v5" || completion.root.version!=="company-tax-delivery-mutation-completion-v4"
        || preparation.root.version!=="company-tax-delivery-mutation-request-v4" || child.prepared_by?.kind!=="USER"
        || child.prepared_by?.subject?.value!==approval.approved_by?.subject?.value
        || child.envelope?.source?.company_id?.value!==companyId || child.envelope.source.income_year?.value!==incomeYear
        || child.envelope.source.organization_number!==parent.root.draft.envelope.source.organization_number) throw new Error("Tax correction parent differs from its complete submitted history.");
    const docs=preparation.root.request.confirmation_prerequisite?.calculated?.response?.calculated_documents;
    if (!Array.isArray(docs)) throw new Error("Tax parent calculated documents are unavailable.");
    const tax=docs.find(doc=>doc.document_type==="skattemeldingUpersonligEtterBeregning");
    const business=docs.find(doc=>doc.document_type==="naeringsspesifikasjonEtterBeregning");
    if (!tax || !business || (await taxEncodedOriginal(tax.body_base64)).sha256!==link.calculated_tax_sha256
        || (await taxEncodedOriginal(business.body_base64)).sha256!==link.calculated_business_sha256
        || child.current_document?.tax_xml_sha256!==link.calculated_tax_sha256) throw new Error("Tax current correction pair differs from its known parent.");
    await verifyTaxCorrectionDraftCommitments(row.canonicalJson,child);
    await verifyTaxCorrectionCurrent(child,link,incomeYear);
    const childReview=events.get(row.filingId+":review")?.root.approval;
    if (childReview && (childReview.review_sha256!==child.validation.review_sha256 || childReview.source_sha256!==child.validation.source_sha256
        || childReview.schema_sha256!==child.validation.schema_sha256
        || childReview.current_original_sha256!==(await taxEncodedBytes(child.current_document.response.raw_base64)).sha256)) throw new Error("Tax correction review differs from its complete draft commitments.");
    const proof=link.terminal;
    if (!taxHasKeys(proof,"envelope_canonical_json,envelope_sha256,feedback_canonical_json,feedback_sha256,instance_canonical_json,instance_sha256")
        || typeof proof.feedback_canonical_json!=="string" || typeof proof.feedback_sha256!=="string") throw new Error("Tax correction has no exact parent receipt.");
    const scope={filing:link.filing_id,company:companyId,year:incomeYear,actor:approval.approved_by.subject.value,
      approval:link.approval_sha256,organization:parent.root.draft.envelope.source.organization_number,instance:request.root.request.target_instance};
    const metadata=await taxBoundRead(proof.instance_canonical_json,proof.instance_sha256,"instance",scope,true);
    const file=await taxBoundRead(proof.envelope_canonical_json,proof.envelope_sha256,"envelope",scope,true);
    const receipt=await taxFeedbackRead(proof.feedback_canonical_json,proof.feedback_sha256,scope,
      {identity:metadata.identity,text:metadata.original.text,observedAt:metadata.binding.observed_at.value});
    const expected=request.root.request.submission_prerequisite;const body=taxJsonObject(metadata.original.text);
    if (body.process?.currentTask!=null || body.status?.isArchived!==true || receipt.scan!=="Clean"
        || file.binding.instance_evidence_sha256!==metadata.identity || file.binding.data_id!==expected.data_id
        || file.original.sha256!==expected.envelope_sha256 || file.original.sha256!==await taxTextSha(parent.root.draft.envelope.envelope_xml)) throw new Error("Tax correction parent is active, unresolved or a different approved file.");
    taxSubmittedFile(metadata.original.text,scope,expected.data_id,file.original.size,metadata.binding.observed_at.value,true);
    const times=[completion.row.recordedAt,metadata.binding.observed_at.value,file.binding.observed_at.value,
      receipt.binding.observed_at.value,child.current_document.response?.observed_at?.value,row.recordedAt].map(Date.parse);
    if (!times.every(Number.isFinite) || times[1]<times[0] || times[2]<times[1] || times[3]<times[1]
        || times[4]<Math.max(times[2],times[3]) || times[5]<times[4] || times[5]-times[1]>30000) throw new Error("Tax correction terminal proof is stale or noncausal.");
    const created=events.get(row.filingId+":completion:create_instance");
    if (created?.root.completion?.result?.instanceId===scope.instance) throw new Error("Tax correction creation reused its parent instance.");
    children.set(link.filing_id,row.filingId);participating.add(row.filingId);
  }
  if (participating.size>64 || !children.size && /^company-tax-source-v9:/u.test(journal.sourceFacts.evidence.version) && participating.size>1) throw new Error("Tax correction history exceeds its finite chain or has unrelated attempts.");
  if (!children.size) return;
  const roots=[...participating].filter(id=>![...children.values()].includes(id));
  if (roots.length!==1) throw new Error("Tax correction history has unrelated roots.");
  const seen=new Set<string>();let current=roots[0];
  while (!seen.has(current)) {seen.add(current);const next=children.get(current);if (!next) break;current=next;}
  if (children.has(current) || seen.size!==participating.size) throw new Error("Tax correction history is cyclic or incomplete.");
}


export async function verifyCompanyTaxDeliveryOriginal(original: CompanyTaxDeliveryOriginalWire) {
  const bytes=await taxEncodedBytes(original.bodyBase64);
  if (bytes.sha256!==original.sha256 || original.key!==original.purpose+":"+original.sha256) throw new Error("Tax download original bytes differ from their retained commitment.");
}
