import assert from "node:assert/strict";
import {createHash,webcrypto} from "node:crypto";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import {createTalliApiClient,TalliApiError,verifyCompanyTaxDeliveryJournalArchive,verifyCompanyTaxDeliveryDraftArchive,verifyCompanyTaxOwnerReviewArtifact} from "../../packages/talli-api-client/src/index.ts";
import {buildPersistedCompanyArchive} from "../../apps/web/app/lib/archive.ts";
import {restoreCompanyYearArchive,assertRestoreIntegrity} from "../../apps/web/app/lib/backup-restore.ts";

const company="10000000-0000-4000-8000-000000000001";
const filing="10000000-0000-4000-8000-000000000002";
const actor="10000000-0000-4000-8000-000000000003";
const observedAt="2026-10-26T10:00:00Z";
const hash=raw=>createHash("sha256").update(raw).digest("hex");
const scope={filing_id:filing,company_id:{value:company},income_year:{value:2025}};
function bundle() {
  const raw=JSON.stringify({version:"company-tax-delivery-draft-v2",draft:{filing_id:filing,
    envelope:{source:{company_id:{value:company},income_year:{value:2025}}},current_document:{original:"å\n"}}});
  const draft={filingId:filing,recordedAt:observedAt,canonicalJson:raw,draftSha256:hash(raw)};
  const approvalRaw=JSON.stringify({version:"company-tax-delivery-review-approval-v1",approval:{...scope,
    approved_by:{kind:"USER",subject:{value:actor}},draft_sha256:draft.draftSha256,authority_mode:"finite_loopback_rehearsal"}});
  const review={filingId:filing,slot:"review",recordedBy:actor,recordedAt:observedAt,
    canonicalJson:approvalRaw,eventSha256:hash(approvalRaw)};
  const requestRaw=JSON.stringify({version:"company-tax-delivery-mutation-request-v1",request:{...scope,
    approval_sha256:review.eventSha256,kind:"create_instance",body_base64:"e30="}});
  const request={filingId:filing,slot:"intent:create_instance",recordedBy:actor,recordedAt:observedAt,
    canonicalJson:requestRaw,eventSha256:hash(requestRaw)};
  const source={evidence:{companyId:company,incomeYear:2025,obligation:"skattemelding",scope:"talli_recorded_company_tax",
    reference:"retained-source",version:"company-tax-source-v3:"+"a".repeat(64),digest:"a".repeat(64),evaluatedAt:observedAt},
    historyCoverage:{status:"complete",reasons:[],evidenceReference:"retained-source",asOf:observedAt,submissionCount:0,scope:"talli_recorded_company_tax"},
    readinessStatus:"blocked",hardBlocks:["company_tax_production_disabled"],recordedSubmissions:[],productionAttempts:[],correctionLinks:[],incidents:[],outcomes:[],
    deliveryDrafts:[{filingId:filing,preparedBy:actor,recordedAt:observedAt,draftSha256:draft.draftSha256,reviewSha256:"b".repeat(64),schemaSha256:"c".repeat(64),status:"prepared_only"}]};
  return {companyId:company,incomeYear:2025,codec:"company-tax-delivery-journal-archive-v1",coverage:"complete",
    sourceSha256:source.evidence.digest,observedAt,sourceFacts:source,draftCount:1,drafts:[draft],eventCount:2,events:[review,request],
    journals:[{filingId:filing,approvedBy:actor,authorityMode:"finite_loopback_rehearsal",status:"uncertain",mutationKind:"create_instance",
      approvalSha256:review.eventSha256,latestEventSha256:request.eventSha256,recordedAt:observedAt}]};
}
function client(value) {
  return createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json(value)});
}
function feature(api) {
  const exports={};const dependencies={verifyCompanyTaxDeliveryJournalArchive,verifyCompanyTaxDeliveryDraftArchive,verifyCompanyTaxOwnerReviewArtifact,backendClientOptions: () => ({ baseUrl: "https://backend.example" }),TalliApiError,createTalliApiClient:()=>api};
  const source=readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts",import.meta.url),"utf8");
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
    {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
  return exports;
}

function readBundle(envelopeXml,partyNumber) {
  const value=bundle();const draft=JSON.parse(value.drafts[0].canonicalJson);
  draft.draft.envelope.source.organization_number="999888777";
  if(envelopeXml!==undefined)draft.draft.envelope.envelope_xml=envelopeXml;
  if(partyNumber!==undefined)draft.draft.current_document.party_number=partyNumber;
  value.drafts[0].canonicalJson=JSON.stringify(draft);value.drafts[0].draftSha256=hash(value.drafts[0].canonicalJson);
  value.sourceFacts.deliveryDrafts[0].draftSha256=value.drafts[0].draftSha256;
  const context={version:"tax-loopback-admission-v1",runId:filing,companyId:company,incomeYear:2025,actorId:actor,
    filingId:filing,draftSha256:value.drafts[0].draftSha256,organizationNumber:"999888777",issuedAt:observedAt,
    expiresAt:"2026-10-26T10:10:00Z",origin:"http://127.0.0.1:17829",credentialSha256:"d".repeat(64),
    databaseScopeSha256:"e".repeat(64),maximumRequests:20};
  const contextRaw=JSON.stringify(context);
  const approval=JSON.parse(value.events[0].canonicalJson);
  approval.approval.draft_sha256=value.drafts[0].draftSha256;approval.approval.authority_context_sha256=hash(contextRaw);
  value.events[0].canonicalJson=JSON.stringify(approval);value.events[0].eventSha256=hash(value.events[0].canonicalJson);
  const binding={...scope,approved_by:{kind:"USER",subject:{value:actor}},approval_sha256:value.events[0].eventSha256};
  const event=(slot,body)=>{const raw=JSON.stringify(body);return{filingId:filing,slot,recordedBy:actor,recordedAt:observedAt,canonicalJson:raw,eventSha256:hash(raw)};};
  const admission=event("admission",{version:"company-tax-delivery-admission-v1",admission:{...binding,
    original:{purpose:"finite_admission",body_base64:Buffer.from(contextRaw).toString("base64"),content_type:"application/json",http_status:null}}});
  const request=JSON.parse(value.events[1].canonicalJson);request.request.approval_sha256=binding.approval_sha256;
  const intent=event("intent:create_instance",request);
  const instance="123456/10000000-0000-4000-8000-000000000004";
  const completed=event("completion:create_instance",{version:"company-tax-delivery-mutation-completion-v1",
    completion:{intent:{...binding,kind:"create_instance",request_sha256:intent.eventSha256},result:{instanceId:instance}}});
  const raw="\ufeff{\"metadata\":\"unavailable\"}\n";
  const identity=JSON.stringify(["tax-instance-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",instance,hash(raw)]);
  const observation=event("observation:instance:"+hash(identity),{version:"company-tax-delivery-instance-observation-v1",
    observation:{...binding,organization_number:"999888777",instance_id:instance,observed_at:{value:observedAt},
      original:{purpose:"instance",body_base64:Buffer.from(raw).toString("base64"),content_type:"application/json",http_status:200}}});
  value.events=[value.events[0],admission,intent,completed,observation];value.eventCount=value.events.length;
  value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v3:","v4:");
  Object.assign(value.journals[0],{status:"mutation_completed",approvalSha256:binding.approval_sha256,latestEventSha256:observation.eventSha256});
  return value;
}

function guardedBundle({complete=true,fileBody="<approved/>",partyNumber}={}) {
  const wire="<approved/>";const value=readBundle(wire,partyNumber);
  const approval=value.events[0].eventSha256;const instance=JSON.parse(value.events[3].canonicalJson).completion.result.instanceId;
  const data="10000000-0000-4000-8000-000000000005";
  const binding={...scope,approved_by:{kind:"USER",subject:{value:actor}},approval_sha256:approval,organization_number:"999888777",instance_id:instance};
  const event=(slot,payload)=>{const raw=JSON.stringify(payload);return{filingId:filing,slot,recordedBy:actor,recordedAt:observedAt,canonicalJson:raw,eventSha256:hash(raw)};};
  const metadata=withFile=>({id:instance,appId:"skd/formueinntekt-skattemelding-v2",instanceOwner:{organisationNumber:"999888777"},
    dataValues:{inntektsaar:2025},process:{currentTask:{altinnTaskType:"data"}},status:{isArchived:false},
    data:withFile?[{id:data,dataType:"skattemeldingOgNaeringsspesifikasjon",contentType:"application/xml",size:Buffer.byteLength(fileBody),fileScanResult:"Pending"}]:[]});
  const read=(kind,raw,predecessor)=>{
    const body={...binding,observed_at:{value:observedAt},original:{purpose:kind,body_base64:Buffer.from(raw).toString("base64"),
      content_type:kind==="instance"?"application/json":"application/xml",http_status:200},
      ...(kind==="envelope"?{data_id:data,instance_evidence_sha256:predecessor}:{})};
    const identity=hash(JSON.stringify([kind==="instance"?"tax-instance-read-identity-v1":"tax-envelope-read-identity-v1",
      filing,company,2025,actor,approval,"999888777",instance,...(kind==="envelope"?[data,predecessor]:[]),hash(raw)]));
    return{record:event("observation:"+kind+":"+identity,{version:"company-tax-delivery-"+kind+"-observation-v1",observation:body}),identity};
  };
  const before=read("instance","\ufeff"+JSON.stringify(metadata(false))+"\n");
  const request=event("intent:upload_envelope",{version:"company-tax-delivery-mutation-request-v2",request:{...scope,
    organization_number:"999888777",approval_sha256:approval,kind:"upload_envelope",target_instance:instance,
    body_base64:Buffer.from(wire).toString("base64"),upload_prerequisite:{instance_id:instance,
      instance_read:{event_sha256:before.record.eventSha256,evidence_sha256:before.identity,observed_at:{value:observedAt}},
      observed_from:{value:observedAt},observed_until:{value:observedAt}}}});
  const after=read("instance","\ufeff"+JSON.stringify(metadata(true))+"\n");const envelope=read("envelope",fileBody,after.identity);
  value.events=[...value.events.slice(0,4),before.record,request,after.record,envelope.record];
  if(complete)value.events.push(event("completion:upload_envelope",{version:"company-tax-delivery-mutation-completion-v2",completion:{
    intent:{...scope,approved_by:binding.approved_by,approval_sha256:approval,kind:"upload_envelope",request_sha256:request.eventSha256},
    result:{instanceId:instance,dataId:data,envelopeSha256:hash(fileBody)},observed_at:{value:observedAt},origin:"envelope_read",
    upload_read_evidence:{instance_canonical_json:after.record.canonicalJson,instance_sha256:after.record.eventSha256,
      envelope_canonical_json:envelope.record.canonicalJson,envelope_sha256:envelope.record.eventSha256}}}));
  value.eventCount=value.events.length;value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v4:","v5:");
  Object.assign(value.journals[0],{status:complete?"mutation_completed":"uncertain",mutationKind:"upload_envelope",latestEventSha256:value.events.at(-1).eventSha256});
  return value;
}

function validationBundle({known=true,status="FERDIG",scan="Clean",fileBody="<approved/>",jobBody,
  includeResult=known&&status==="FERDIG",schema="eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1",
  resultStatusReference,resultJob,resultAt=3,jobAt=2,startStatus="OPPRETTET",resultBody="<unknown-result/>",partyNumber}={}) {
  const value=guardedBundle({partyNumber});const previous=JSON.parse(value.events.find(row=>row.slot.startsWith("observation:envelope:")).canonicalJson).observation;
  const {original,observed_at,data_id,instance_evidence_sha256,...binding}=previous;
  const time=seconds=>new Date(Date.parse(observedAt)+seconds*1000).toISOString();
  const event=(slot,payload,seconds)=>{const raw=JSON.stringify(payload);return{filingId:filing,slot,recordedBy:actor,recordedAt:time(seconds),canonicalJson:raw,eventSha256:hash(raw)};};
  const metadataRaw="\ufeff"+JSON.stringify({id:binding.instance_id,appId:"skd/formueinntekt-skattemelding-v2",instanceOwner:{organisationNumber:"999888777"},
    dataValues:{inntektsaar:2025},process:{currentTask:{altinnTaskType:"data"}},status:{isArchived:false},data:[{id:data_id,
      dataType:"skattemeldingOgNaeringsspesifikasjon",contentType:"application/xml",size:Buffer.byteLength(fileBody),fileScanResult:scan}]})+"\n";
  const metadataIdentity=hash(JSON.stringify(["tax-instance-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,hash(metadataRaw)]));
  const metadata=event("observation:instance:"+metadataIdentity,{version:"company-tax-delivery-instance-observation-v1",observation:{...binding,
    observed_at:{value:time(1)},original:{purpose:"instance",body_base64:Buffer.from(metadataRaw).toString("base64"),content_type:"application/json",http_status:200}}},1.01);
  const envelopeIdentity=hash(JSON.stringify(["tax-envelope-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,data_id,metadataIdentity,hash(fileBody)]));
  const envelope=event("observation:envelope:"+envelopeIdentity,{version:"company-tax-delivery-envelope-observation-v1",observation:{...binding,
    data_id,instance_evidence_sha256:metadataIdentity,observed_at:{value:time(1.1)},original:{purpose:"envelope",body_base64:Buffer.from(fileBody).toString("base64"),content_type:"application/xml",http_status:200}}},1.11);
  const request=event("intent:start_validation",{version:"company-tax-delivery-mutation-request-v3",request:{...scope,
    organization_number:"999888777",approval_sha256:binding.approval_sha256,kind:"start_validation",target_instance:binding.instance_id,
    body_base64:Buffer.from(JSON.stringify({appId:"skd/formueinntekt-skattemelding-v2",instansId:binding.instance_id})).toString("base64"),
    validation_prerequisite:{instance_id:binding.instance_id,data_id,observed_from:{value:time(1)},observed_until:{value:time(1.2)},
      instance_read:{event_sha256:metadata.eventSha256,evidence_sha256:metadataIdentity,observed_at:{value:time(1)}},
      envelope_read:{event_sha256:envelope.eventSha256,evidence_sha256:envelopeIdentity,observed_at:{value:time(1.1)}}}}},1.3);
  value.events.push(metadata,envelope,request);
  if(known) {
    const job="storeDokument-client-v1";
    const completion=event("completion:start_validation",{version:"company-tax-delivery-mutation-completion-v1",completion:{
      intent:{...scope,approved_by:binding.approved_by,approval_sha256:binding.approval_sha256,kind:"start_validation",request_sha256:request.eventSha256},
      result:{instanceId:binding.instance_id,jobId:job},observed_at:{value:time(1.4)},origin:"mutation_response",
      response_base64:Buffer.from(JSON.stringify({jobbId:job,jobbStatus:startStatus})).toString("base64")}},1.5);
    const context={...binding,job_id:job,start_request_sha256:request.eventSha256};
    const raw=jobBody??("\ufeff"+JSON.stringify({jobbStatus:status,forrigeStatus:"KJOERER",sekunderSidenOpprettelse:0,sekunderSidenEndring:0})+"\n");
    const identity=hash(JSON.stringify(["tax-validation-job-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,job,request.eventSha256,hash(raw)]));
    const read=event("observation:validation-job:"+identity,{version:"company-tax-delivery-validation-job-observation-v1",observation:{...context,
      observed_at:{value:time(jobAt)},original:{purpose:"validation_job",body_base64:Buffer.from(raw).toString("base64"),content_type:"application/json",http_status:200}}},2.1);
    value.events.push(completion,read);
    if(includeResult) {
      const statusIdentity=resultStatusReference??identity;const resultJobId=resultJob??job;const xml="\ufeff"+resultBody+"\n";
      const resultIdentity=hash(JSON.stringify(["tax-validation-result-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,resultJobId,request.eventSha256,statusIdentity,schema,hash(xml)]));
      value.events.push(event("observation:validation-result:"+resultIdentity,{version:"company-tax-delivery-validation-result-observation-v1",observation:{...context,
        job_id:resultJobId,job_status_evidence_sha256:statusIdentity,schema_sha256:schema,observed_at:{value:time(resultAt)},
        original:{purpose:"validation_result",body_base64:Buffer.from(xml).toString("base64"),content_type:"application/xml",http_status:200}}},3.1));
    }
  }
  value.eventCount=value.events.length;value.observedAt=time(4);value.sourceFacts.evidence.evaluatedAt=time(4);value.sourceFacts.historyCoverage.asOf=time(4);
  value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v5:","v6:");
  Object.assign(value.journals[0],{status:known?"mutation_completed":"uncertain",mutationKind:"start_validation",latestEventSha256:value.events.at(-1).eventSha256,recordedAt:value.events.at(-1).recordedAt});
  return value;
}

// Client binding fixture only. Native/signed tests separately run the actual
// pinned XSD adapter and storage's XML projection checks.
function confirmationBundle({complete=true,acknowledgment=true,task="confirmation",element="Task_2",flow=2,
  flowLiteral,scan="Clean",fileBody="<approved/>",ackBody="\ufeff not JSON\n",editProof}={}) {
  const docs=["skattemeldingUpersonligEtterBeregning","naeringsspesifikasjonEtterBeregning"].map(kind=>({
    document_type:kind,body_base64:Buffer.from("<scoped-calculated-document/>").toString("base64")}));
  const responseBody='<skattemeldingOgNaeringsspesifikasjonResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2"><dokumenter>'+
    docs.map(doc=>'<dokument><type>'+doc.document_type+'</type><encoding>utf-8</encoding><content>'+doc.body_base64+'</content></dokument>').join("")+
    '</dokumenter><resultatAvValidering>validertOK</resultatAvValidering></skattemeldingOgNaeringsspesifikasjonResponse>';
  const value=validationBundle({partyNumber:"123456",resultBody:responseBody});
  const firstJob=value.events.find(row=>row.slot.startsWith("observation:validation-job:"));
  const firstResult=value.events.find(row=>row.slot.startsWith("observation:validation-result:"));
  const jobId=firstJob.slot.split(":")[2];const resultId=firstResult.slot.split(":")[2];
  const {job_id,start_request_sha256,job_status_evidence_sha256,schema_sha256,original,observed_at,...binding}=JSON.parse(firstResult.canonicalJson).observation;
  const time=n=>new Date(Date.parse(observedAt)+n*1000).toISOString();
  const event=(slot,payload,n)=>{const raw=JSON.stringify(payload);return{filingId:filing,slot,recordedBy:actor,recordedAt:time(n),canonicalJson:raw,eventSha256:hash(raw)};};
  const data="10000000-0000-4000-8000-000000000005";
  function reads(task,element,flow,scan,fileBody,n,flowLiteral) {
    let raw="\ufeff"+JSON.stringify({id:binding.instance_id,appId:"skd/formueinntekt-skattemelding-v2",instanceOwner:{organisationNumber:"999888777"},
      dataValues:{inntektsaar:2025},process:{currentTask:{altinnTaskType:task,elementId:element,flow}},status:{isArchived:false},data:[{id:data,
        dataType:"skattemeldingOgNaeringsspesifikasjon",contentType:"text/xml",size:Buffer.byteLength(fileBody),fileScanResult:scan}]})+"\n";
    if(flowLiteral)raw=raw.replace('"flow":'+flow,'"flow":'+flowLiteral);
    const identity=hash(JSON.stringify(["tax-instance-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,hash(raw)]));
    const metadata=event("observation:instance:"+identity,{version:"company-tax-delivery-instance-observation-v1",observation:{...binding,
      observed_at:{value:time(n)},original:{purpose:"instance",body_base64:Buffer.from(raw).toString("base64"),content_type:"application/json",http_status:200}}},n+.01);
    const fileIdentity=hash(JSON.stringify(["tax-envelope-read-identity-v1",filing,company,2025,actor,binding.approval_sha256,"999888777",binding.instance_id,data,identity,hash(fileBody)]));
    const envelope=event("observation:envelope:"+fileIdentity,{version:"company-tax-delivery-envelope-observation-v1",observation:{...binding,
      data_id:data,instance_evidence_sha256:identity,observed_at:{value:time(n+.1)},original:{purpose:"envelope",body_base64:Buffer.from(fileBody).toString("base64"),content_type:"application/xml",http_status:200}}},n+.11);
    return{metadata,envelope,identity,fileIdentity};
  }
  const before=reads("data","Task_1",1,"Clean","<approved/>",4.3);
  value.events.push(before.metadata,before.envelope);
  const proof={clean_file:{instance_id:binding.instance_id,data_id:data,
    instance_read:{event_sha256:before.metadata.eventSha256,evidence_sha256:before.identity,observed_at:{value:time(4.3)}},
    envelope_read:{event_sha256:before.envelope.eventSha256,evidence_sha256:before.fileIdentity,observed_at:{value:time(4.4)}},
    observed_from:{value:time(4.2)},observed_until:{value:time(4.5)}},envelope_sha256:hash("<approved/>"),
    job_read:{event_sha256:firstJob.eventSha256,evidence_sha256:jobId,observed_at:{value:time(4)}},
    result_read:{event_sha256:firstResult.eventSha256,evidence_sha256:resultId,observed_at:{value:time(4.1)}},
    calculated:{schema_sha256:"c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769",draft_sha256:value.drafts[0].draftSha256,
      company_id:{value:company},income_year:{value:2025},party_number:"123456",response:{schema_sha256,
        original_sha256:hash(Buffer.from(original.body_base64,"base64")),result_code:"validertOK",calculation_deviation_count:0,
        validation_deviation_count:0,guidance_count:0,failure_reason_count:0,calculated_documents:docs}},
    observed_from:{value:time(4)},observed_until:{value:time(4.6)}};
  if(editProof)editProof(proof);
  const request=event("intent:prepare_confirmation",{version:"company-tax-delivery-mutation-request-v4",request:{...scope,
    organization_number:"999888777",approval_sha256:binding.approval_sha256,kind:"prepare_confirmation",target_instance:binding.instance_id,
    body_base64:"",confirmation_prerequisite:proof}},4.7);
  value.events.push(request);
  if(acknowledgment)value.events.push(event("acknowledgment:prepare_confirmation",{version:"company-tax-delivery-process-acknowledgment-v1",acknowledgment:{...binding,
    request_sha256:request.eventSha256,observed_at:{value:time(4.8)},original:{purpose:"process_response",body_base64:Buffer.from(ackBody).toString("base64"),content_type:"application/json",http_status:200}}},4.9));
  if(complete) {
    const after=reads(task,element,flow,scan,fileBody,5,flowLiteral);
    value.events.push(event("completion:prepare_confirmation",{version:"company-tax-delivery-mutation-completion-v3",completion:{
      intent:{...scope,approved_by:binding.approved_by,approval_sha256:binding.approval_sha256,kind:"prepare_confirmation",request_sha256:request.eventSha256},
      result:{instanceId:binding.instance_id,processTask:"confirmation"},observed_at:{value:time(5.2)},origin:"confirmation_read",
      confirmation_read_evidence:{instance_canonical_json:after.metadata.canonicalJson,instance_sha256:after.metadata.eventSha256,
        envelope_canonical_json:after.envelope.canonicalJson,envelope_sha256:after.envelope.eventSha256}}},5.3));
  }
  value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v6:","v7:");value.eventCount=value.events.length;
  value.observedAt=time(6);value.sourceFacts.evidence.evaluatedAt=time(6);value.sourceFacts.historyCoverage.asOf=time(6);
  Object.assign(value.journals[0],{status:complete?"mutation_completed":"uncertain",mutationKind:"prepare_confirmation",
    latestEventSha256:value.events.at(-1).eventSha256,recordedAt:value.events.at(-1).recordedAt});
  return value;
}

for(const [name,options] of [["known preparation",{}],["opaque acknowledgment only",{complete:false}],
  ["missing acknowledgment, known read result",{acknowledgment:false}]])test(`confirmation archive retains ${name} without submission claims`,async()=>{
  const value=confirmationBundle(options);const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  const projected=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(projected.error,null);assert.deepEqual(projected.data.journal.events,value.events);
});

for(const [name,options] of [
  ["auditor stage",{element:"Task_2Revisor"}],["feedback stage",{task:"feedback",element:"Task_3"}],
  ["pending scan",{scan:"Pending"}],["drifted file",{fileBody:"<different/>"}],
  ["boolean flow",{flow:true}],["float flow",{flowLiteral:"2.0"}],["exponent flow",{flowLiteral:"2e0"}],
  ["foreign calculated party",{editProof:p=>p.calculated.party_number="other"}],
  ["foreign calculated year",{editProof:p=>p.calculated.income_year.value=2026}],
  ["wrong calculated pin",{editProof:p=>p.calculated.schema_sha256="d".repeat(64)}],
  ["wrong response pin",{editProof:p=>p.calculated.response.schema_sha256="d".repeat(64)}],
  ["wrong result original",{editProof:p=>p.calculated.response.original_sha256="d".repeat(64)}],
  ["hard validation error",{editProof:p=>p.calculated.response.validation_deviation_count=1}],
  ["rejected validation",{editProof:p=>p.calculated.response.result_code="validertMedFeil"}],
  ["borrowed job original",{editProof:p=>p.job_read.event_sha256="d".repeat(64)}],
  ["stale job read",{editProof:p=>p.job_read.observed_at.value="2026-10-26T09:59:59Z"}],
  ["extra prerequisite flag",{editProof:p=>p.ready=true}],
  ["extra calculated field",{editProof:p=>p.calculated.response.calculated_documents[0].ready=true}],
])test(`confirmation archive refuses consistently hashed ${name}`,async()=>{
  const value=confirmationBundle(options);const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  assert.equal((await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025)).data,null);
});

for(const [name,options] of [
  ["unknown start",{known:false}],["running known job",{status:"KJOERER"}],["finished known result",{}],
  ["unknown exact status",{jobBody:"{",includeResult:false}],["unknown malformed job identity",{jobBody:'{"jobbId":[],"jobbStatus":"FERDIG"}',includeResult:false}],
  ["huge unrelated numeric original",{jobBody:'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":0,"sekunderSidenEndring":0,"extra":1e200000}'}],
])test(`validation archive preserves ${name} without inventing Tax acceptance`,async()=>{
  const value=validationBundle(options);const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(result.error,null);assert.deepEqual(result.data.journal.events,value.events);
  assert.equal(result.data.journal.journals[0].status,options.known===false?"uncertain":"mutation_completed");
  assert.equal(result.data.journal.journals[0].mutationKind,"start_validation");
});

for(const [name,options] of [
  ["pending scan",{scan:"Pending"}],["infected scan",{scan:"Infected"}],["changed approved file",{fileBody:"<different/>"}],
  ["unsupported schema pin",{schema:"f".repeat(64)}],["missing status reference",{resultStatusReference:"f".repeat(64)}],
  ["foreign result job",{resultJob:"another-job"}],["job read before start commit",{jobAt:1.4}],
  ["result before status",{resultAt:1.9}],["start response not created",{startStatus:"FERDIG"}],
  ["nonfinished job result",{status:"KJOERER",includeResult:true}],
  ["ambiguous status result",{jobBody:'{"jobbStatus":"KJOERER","jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":0,"sekunderSidenEndring":0}'}],
  ["escaped duplicate status",{jobBody:'{"jobbStatus":"KJOERER","\\u006aobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":0,"sekunderSidenEndring":0}'}],
  ["foreign job with malformed timing",{jobBody:'{"jobbId":"another-job","jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":10.0,"sekunderSidenEndring":0}',includeResult:false}],
  ["decimal timing",{jobBody:'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":1.0,"sekunderSidenEndring":0}'}],
  ["exponent timing",{jobBody:'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":1e1,"sekunderSidenEndring":0}'}],
])test(`validation archive refuses consistently hashed ${name}`,async()=>{
  const value=validationBundle(options);const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(result.data,null);assert.ok(result.error);
});

for(const name of ["old-reader","duplicate-root-key","escaped-duplicate-root-key","extra-root-field","extra-company-wrapper","extra-income-wrapper","extra-actor-wrapper","extra-subject-wrapper","extra-time-wrapper"])test(`validation archive refuses ${name}`,async()=>{
  const value=validationBundle();
  if(name==="old-reader")value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v6:","v5:");
  else if(name.startsWith("extra-")) {
    const record=value.events.at(-1);const raw=JSON.parse(record.canonicalJson);const binding=raw.observation;
    if(name==="extra-root-field")raw.unsupported=true;
    else if(name==="extra-company-wrapper")binding.company_id.unsupported=true;
    else if(name==="extra-income-wrapper")binding.income_year.unsupported=true;
    else if(name==="extra-actor-wrapper")binding.approved_by.unsupported=true;
    else if(name==="extra-subject-wrapper")binding.approved_by.subject.unsupported=true;
    else binding.observed_at.unsupported=true;
    record.canonicalJson=JSON.stringify(raw);record.eventSha256=hash(record.canonicalJson);value.journals[0].latestEventSha256=record.eventSha256;
  } else {
    const record=value.events.at(-1);const key=name==="duplicate-root-key"?"version":"\\u0076ersion";
    record.canonicalJson=record.canonicalJson.slice(0,-1)+',"'+key+'":"company-tax-delivery-validation-result-observation-v1"}';
    record.eventSha256=hash(record.canonicalJson);value.journals[0].latestEventSha256=record.eventSha256;
  }
  const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  assert.equal((await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025)).data,null);
});

test("validation-capable frontend keeps the previous backend's bounded version and complete V5 archive",async()=>{
  const value=guardedBundle();let called=false;
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async url=>{
    const query=new URL(url).searchParams;called=true;
    assert.equal(query.get("readEvidenceVersion"),"2");
    assert.equal(query.get("validationEvidence"),"true");
    // The predecessor ignores the additive query but rejects a version >2.
    assert.ok(Number(query.get("readEvidenceVersion"))<=2);
    return Response.json(value);
  }});
  const result=await api.companyTaxGetDeliveryJournalArchive(company,2025);
  assert.ok(called);assert.deepEqual(result.events,value.events);
  assert.ok(result.sourceFacts.evidence.version.startsWith("company-tax-source-v5:"));
});

for(const complete of [false,true])test(`guarded archive retains exact originals with upload completion=${complete}`,async()=>{
  const value=guardedBundle({complete});const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(result.error,null);assert.deepEqual(result.data.journal.events,value.events);
  assert.equal(result.data.journal.journals[0].status,complete?"mutation_completed":"uncertain");
});

for(const change of ["old-reader","missing-admission","missing-create","borrowed-read","foreign-actor","foreign-company",
  "old-metadata","proof-hash","proof-missing","origin","carrier","wrong-file","false-outcome"]) {
  test(`guarded archive refuses ${change} without dropping or substituting originals`,async()=>{
    const value=guardedBundle(change==="wrong-file"?{fileBody:"<different/>"}:{});
    if(change==="old-reader")value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v5:","v4:");
    else if(change==="missing-admission")value.events.splice(1,1);
    else if(change==="missing-create")value.events.splice(3,1);
    else if(change==="false-outcome")value.journals[0].status="uncertain";
    else if(change!=="wrong-file"){
      const index=change==="borrowed-read"?5:value.events.length-1;const root=JSON.parse(value.events[index].canonicalJson);
      if(change==="borrowed-read")root.request.upload_prerequisite.instance_read.event_sha256="f".repeat(64);
      else if(change==="origin")root.completion.origin="mutation_response";
      else if(change==="carrier")root.completion.response_base64="e30=";
      else if(change==="proof-hash")root.completion.upload_read_evidence.envelope_sha256="f".repeat(64);
      else if(change==="proof-missing")delete root.completion.upload_read_evidence.envelope_canonical_json;
      else {
        const proof=root.completion.upload_read_evidence;const inner=JSON.parse(proof.instance_canonical_json);
        if(change==="foreign-actor")inner.observation.approved_by.subject.value=company;
        else if(change==="foreign-company")inner.observation.company_id.value=filing;
        else inner.observation.observed_at.value="2026-10-26T09:59:59Z";
        proof.instance_canonical_json=JSON.stringify(inner);proof.instance_sha256=hash(proof.instance_canonical_json);
      }
      value.events[index].canonicalJson=JSON.stringify(root);value.events[index].eventSha256=hash(value.events[index].canonicalJson);
    }
    value.eventCount=value.events.length;value.journals[0].latestEventSha256=value.events.at(-1).eventSha256;
    let fallbacks=0;const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,companyTaxGetDeliveryJournalArchive:async()=>value,
      companyTaxGetDeliveryDraftArchive:async()=>{fallbacks++;return{};}};
    const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
    assert.ok(result.error);assert.equal(result.data,null);assert.equal(fallbacks,0);
  });
}

test("V4 export preserves exact read evidence without treating it as another completed mutation",async()=>{
  const value=readBundle();const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,
    companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025)};
  const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(result.error,null);assert.deepEqual(result.data.journal.events,value.events);
  assert.equal(result.data.journal.journals[0].status,"mutation_completed");
  assert.equal(result.data.journal.journals[0].mutationKind,"create_instance");
  const observation=JSON.parse(value.events[4].canonicalJson).observation;
  assert.equal(Buffer.from(observation.original.body_base64,"base64").toString(),"\ufeff{\"metadata\":\"unavailable\"}\n");
});

for(const change of ["old-source","missing-admission","missing-create","identity","purpose","utf8","admission-hash","foreign-actor","false-outcome"]) {
  test(`read-evidence export refuses ${change} without fallback`,async()=>{
    const value=readBundle();
    if(change==="old-source")value.sourceFacts.evidence.version=value.sourceFacts.evidence.version.replace("v4:","v3:");
    else if(change==="missing-admission")value.events.splice(1,1);
    else if(change==="missing-create")value.events.splice(3,1);
    else if(change==="identity")value.events[4].slot="observation:instance:"+"0".repeat(64);
    else if(change==="false-outcome")value.journals[0].status="reviewed";
    else {
      const index=change==="admission-hash"?1:4;const raw=JSON.parse(value.events[index].canonicalJson);
      const binding=raw.observation??raw.admission;
      if(change==="purpose")binding.original.purpose="envelope";
      else if(change==="utf8")binding.original.body_base64="/w==";
      else if(change==="foreign-actor")binding.approved_by.subject.value=company;
      else binding.original.body_base64=Buffer.from("{}").toString("base64");
      value.events[index].canonicalJson=JSON.stringify(raw);value.events[index].eventSha256=hash(value.events[index].canonicalJson);
    }
    value.eventCount=value.events.length;
    let fallbacks=0;
    const api={companyTaxGetSourceFacts:async()=>value.sourceFacts,companyTaxGetDeliveryJournalArchive:async()=>value,
      companyTaxGetDeliveryDraftArchive:async()=>{fallbacks++;return{};}};
    const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
    assert.ok(result.error);assert.equal(result.data,null);assert.equal(fallbacks,0);
  });
}

test("generated journal archive client binds one complete source and exact scope",async()=>{
  const value=bundle();let called;
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async(url,request)=>{
    called={url:new URL(url),request};return Response.json(value);
  }});
  assert.deepEqual(await api.companyTaxGetDeliveryJournalArchive(company,2025,{headers:{Authorization:"Bearer fixture"}}),value);
  assert.equal(called.url.pathname,"/api/v1/company-tax/archive-source/delivery-journal-v1");
  assert.equal(called.url.searchParams.get("companyId"),company);
  assert.equal(called.url.searchParams.get("readEvidence"),"true");
  assert.equal(called.url.searchParams.get("readEvidenceVersion"),"2");
  assert.equal(new Headers(called.request.headers).get("Authorization"),"Bearer fixture");
});

for (const change of ["scope","version","source-hash","observation","coverage","draft-count","event-count","duplicate","orphan","summary","draft-proof","duplicate-fact","extra"]) {
  test(`generated journal archive refuses ${change}`,async()=>{
    const value=bundle();
    if(change==="scope")value.companyId=filing;
    else if(change==="version")value.sourceFacts.evidence.version="company-tax-source-v2:"+value.sourceSha256;
    else if(change==="source-hash")value.sourceFacts.evidence.digest="f".repeat(64);
    else if(change==="observation")value.observedAt="2026-10-27T10:00:00Z";
    else if(change==="coverage")value.sourceFacts.historyCoverage.reasons=["journal_enumeration_incomplete"];
    else if(change==="draft-count")value.draftCount=0;
    else if(change==="event-count")value.eventCount=0;
    else if(change==="duplicate")value.events[1]={...value.events[0]};
    else if(change==="orphan")value.events[1].filingId=company;
    else if(change==="summary")value.journals[0].filingId=company;
    else if(change==="draft-proof")value.sourceFacts.deliveryDrafts[0].draftSha256="f".repeat(64);
    else if(change==="duplicate-fact"){
      const second=structuredClone(value.drafts[0]);second.filingId=actor;
      value.drafts.push(second);value.draftCount=2;
      value.sourceFacts.deliveryDrafts.push({...value.sourceFacts.deliveryDrafts[0]});
    }
    else value.events[1].unowned="extra";
    await assert.rejects(client(value).companyTaxGetDeliveryJournalArchive(company,2025),error=>error instanceof TalliApiError&&error.status===502);
  });
}

test("company export preserves exact unknown journal originals alongside draft originals",async()=>{
  const value=bundle();const old=structuredClone(value.sourceFacts);
  old.evidence.version=old.evidence.version.replace("v3:","v2:");old.historyCoverage.status="incomplete";
  old.historyCoverage.reasons=["declaredDeliveryExtentValid_unproven"];
  const api={companyTaxGetSourceFacts:async()=>old,companyTaxGetDeliveryJournalArchive:async()=>client(value).companyTaxGetDeliveryJournalArchive(company,2025),
    companyTaxGetDeliveryDraftArchive:async()=>{throw new Error("No predecessor fallback.");}};
  const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
  assert.equal(result.error,null);assert.equal(result.data.journal.events[1].canonicalJson,value.events[1].canonicalJson);
  const archive=buildPersistedCompanyArchive({company:{id:company},incomeYear:2025,setups:[],shareholders:[],ledgerEntries:[],documents:[],
    permissions:[],testEvidence:[],filingPreviews:[],filingSubmissions:[],reviewComments:[],auditEvents:[],taxDeliveryDrafts:result.data});
  assert.equal(archive.companyTaxDeliveryJournal.events[1].canonicalJson,value.events[1].canonicalJson);
  assert.equal(archive.companyTaxDeliveryDrafts.originals.records[0].canonicalJson,value.drafts[0].canonicalJson);
  assert.equal(archive.companyTaxDeliveryDrafts.journal,undefined);
  assert.equal(archive.companyTaxDeliveryJournal.journals[0].status,"uncertain");
  const intact=restoreCompanyYearArchive(archive,{targetCompanyId:company});
  assert.equal(intact.manifest.counts.companyTaxDeliveryJournalEvents,value.eventCount);
  assert.equal(intact.restored.companyTaxDeliveryJournal.events[1].canonicalJson,value.events[1].canonicalJson);
  assert.equal(assertRestoreIntegrity(intact).failures.includes("company_tax_delivery_journal_mismatch"),false);
  const missing=restoreCompanyYearArchive({...archive,companyTaxDeliveryJournal:null},{targetCompanyId:company});
  assert.equal(assertRestoreIntegrity(missing).failures.includes("company_tax_delivery_journal_missing"),true);
  const changed=restoreCompanyYearArchive({...archive,companyTaxDeliveryJournal:{...archive.companyTaxDeliveryJournal,eventCount:0}},{targetCompanyId:company});
  assert.equal(assertRestoreIntegrity(changed).failures.includes("company_tax_delivery_journal_mismatch"),true);
  const mismatchedOriginal=restoreCompanyYearArchive({...archive,companyTaxDeliveryDrafts:{...archive.companyTaxDeliveryDrafts,
    originals:{...archive.companyTaxDeliveryDrafts.originals,records:[{...archive.companyTaxDeliveryDrafts.originals.records[0],canonicalJson:"{}"}]}}},{targetCompanyId:company});
  assert.equal(assertRestoreIntegrity(mismatchedOriginal).failures.includes("company_tax_delivery_journal_mismatch"),true);
});

for(const change of ["original","codec","scope","actor","approval","summary","order","missing-summary","skipped-predecessor","uncertain-predecessor","orphan-completion","mfa-failure"]) {
  test(`archive projection refuses ${change} without a predecessor fallback`,async()=>{
    const value=bundle();const source=structuredClone(value.sourceFacts);source.historyCoverage.status="incomplete";
    source.evidence.version=source.evidence.version.replace("v3:","v2:");source.historyCoverage.reasons=["declaredDeliveryExtentValid_unproven"];
    if(change==="original")value.events[1].canonicalJson+=" ";
    else if(["codec","scope","approval"].includes(change)){
      const raw=JSON.parse(value.events[1].canonicalJson);
      if(change==="codec")raw.version="future";
      else if(change==="scope")raw.request.company_id.value=filing;
      else raw.request.approval_sha256="f".repeat(64);
      value.events[1].canonicalJson=JSON.stringify(raw);value.events[1].eventSha256=hash(value.events[1].canonicalJson);
    } else if(change==="actor")value.events[1].recordedBy=filing;
    else if(change==="summary")value.journals[0].status="mutation_completed";
    else if(change==="order")value.events.reverse();
    else if(change==="missing-summary")value.journals=[];
    else if(change==="orphan-completion"){
      const raw={version:"company-tax-delivery-mutation-completion-v1",completion:{intent:{...scope,
        kind:"create_instance",approval_sha256:value.events[0].eventSha256,approved_by:{kind:"USER",subject:{value:actor}}},
        result:{instanceId:"123456/10000000-0000-4000-8000-000000000004"}}};
      value.events[1]={...value.events[1],slot:"completion:create_instance",canonicalJson:JSON.stringify(raw)};
      value.events[1].eventSha256=hash(value.events[1].canonicalJson);
      value.journals[0].status="mutation_completed";value.journals[0].latestEventSha256=value.events[1].eventSha256;
    }
    else if(change==="skipped-predecessor"||change==="uncertain-predecessor"){
      const raw=JSON.parse(value.events[1].canonicalJson);raw.request.kind="upload_envelope";
      raw.request.target_instance="123456/10000000-0000-4000-8000-000000000004";
      const next={...value.events[1],slot:"intent:upload_envelope",canonicalJson:JSON.stringify(raw)};
      next.eventSha256=hash(next.canonicalJson);
      if(change==="skipped-predecessor")value.events[1]=next;
      else{value.events.push(next);value.eventCount=3;}
      value.journals[0].mutationKind="upload_envelope";value.journals[0].latestEventSha256=next.eventSha256;
    }
    let predecessorCalls=0;
    const api={companyTaxGetSourceFacts:async()=>source,companyTaxGetDeliveryJournalArchive:async()=>{
      if(change==="mfa-failure")throw new TalliApiError(403,undefined);
      return value;
    },companyTaxGetDeliveryDraftArchive:async()=>{predecessorCalls++;return{};}};
    const result=await feature(api).loadTaxDeliveryDraftArchiveSource("fixture",company,2025);
    assert.ok(result.error);assert.equal(result.data,null);assert.equal(predecessorCalls,0);
  });
}
