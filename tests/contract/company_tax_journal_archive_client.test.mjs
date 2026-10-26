import assert from "node:assert/strict";
import {createHash,webcrypto} from "node:crypto";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/generated/client.ts";
import {buildPersistedCompanyArchive} from "../../apps/web/app/lib/archive.ts";

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
  const exports={};const dependencies={backendBaseUrl:()=>"https://backend.example",TalliApiError,createTalliApiClient:()=>api};
  const source=readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts",import.meta.url),"utf8");
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
    {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
  return exports;
}

function readBundle() {
  const value=bundle();const draft=JSON.parse(value.drafts[0].canonicalJson);
  draft.draft.envelope.source.organization_number="999888777";
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
