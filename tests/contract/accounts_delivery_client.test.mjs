import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/index.ts";

const companyId="15300000-0000-4000-8000-000000000001";
const filingId="15300000-0000-4000-8000-000000000020";
const other="15300000-0000-4000-8000-000000000021";
const sha="a".repeat(64);
const failed=error=>error instanceof TalliApiError && error.status===502;

test("Accounts workspace keeps all fields/issues and refuses foreign or invented state",async t=>{
  const row={filingId,recordedAt:"2026-10-27T12:00:00Z",draftSha256:sha,sourceSha256:sha,reviewSha256:sha,reviewStage:"sign",state:"person_review",
    knownInstance:"12345678/"+filingId,sourceCurrent:true,actions:["review_sign","reconcile"],fields:[{document:"Underskjema",path:"/all/fields[1]",value:"123"}],
    validationIssues:[{severity:"warning",code:"SOFT",description:"Retain every issue",additional:{nested:"raw"}}],
    originals:[{key:"original:"+sha,purpose:"pdf",sourceFilingId:filingId,sha256:sha,mediaType:"application/pdf"}]};
  const valid={version:"annual-accounts-delivery-workspace-v1",companyId,incomeYear:2025,sourceSha256:sha,observedAt:row.recordedAt,preparationAvailable:false,rows:[row]};
  let response=valid;t.mock.method(globalThis,"fetch",async (url,request)=>{
    assert.equal(new URL(url).pathname,"/api/v1/annual-accounts/delivery-workspace");assert.equal(request.cache,"no-store");
    assert.equal(new Headers(request.headers).get("Authorization"),"Bearer fixture");return Response.json(response);
  });
  const client=createTalliApiClient({baseUrl:"https://backend.example",headers:{Authorization:"Bearer fixture"}});
  assert.deepEqual(await client.annualAccountsGetDeliveryWorkspace(companyId,2025),valid);
  for (const changed of [{companyId:other},{incomeYear:2024},{rows:[row,row]},
    ...[{state:"accepted"},{parentFilingId:other},{parentFilingId:filingId},{actions:["production"]},{actions:["sign","sign"]},{signed:true},
      {originals:[{...row.originals[0],sourceFilingId:other}]},{originals:[...row.originals,...row.originals]}].map(change=>({rows:[{...row,...change}]}))]) {
    response={...valid,...changed};await assert.rejects(client.annualAccountsGetDeliveryWorkspace(companyId,2025),failed);
  }
});

test("Accounts opaque original verifies exact bytes, encoding, hash and scope",async t=>{
  const raw=Buffer.from([0xef,0xbb,0xbf,0x00,0xff,0x0a]);const digest=createHash("sha256").update(raw).digest("hex");
  const key="original:"+sha;const valid={companyId,incomeYear:2025,filingId,key,purpose:"signature",sourceFilingId:filingId,
    sha256:digest,mediaType:"application/json",bodyBase64:raw.toString("base64")};
  let response=valid;t.mock.method(globalThis,"fetch",async ()=>Response.json(response));
  const client=createTalliApiClient({baseUrl:"https://backend.example"});
  assert.deepEqual(await client.annualAccountsGetDeliveryOriginal(companyId,2025,filingId,key),valid);
  for (const change of [{companyId:other},{incomeYear:2024},{filingId:other},{sourceFilingId:other},{key:"original:"+digest},
      {bodyBase64:valid.bodyBase64+"\n"},{bodyBase64:Buffer.from("changed").toString("base64")},{sha256:sha}]) {
    response={...valid,...change};await assert.rejects(client.annualAccountsGetDeliveryOriginal(companyId,2025,filingId,key),failed);
  }
});

test("Accounts action responses cannot change the exact requested draft binding",async t=>{
  const command={companyId,incomeYear:2025,filingId,draftSha256:sha,action:"sign"};
  const valid={companyId,incomeYear:2025,filingId,draftSha256:sha,state:"signing_unknown"};let response=valid;let calls=0;
  t.mock.method(globalThis,"fetch",async (url,request)=>{calls++;assert.equal(new URL(url).pathname,"/api/v1/annual-accounts/delivery-advances");
    assert.equal(request.method,"POST");assert.equal(request.cache,"no-store");assert.deepEqual(JSON.parse(request.body),command);return Response.json(response);});
  const client=createTalliApiClient({baseUrl:"https://backend.example"});
  assert.deepEqual(await client.annualAccountsAdvanceDelivery(command),valid);
  for (const change of [{companyId:other},{incomeYear:2024},{filingId:other},{draftSha256:"b".repeat(64)},{state:"accepted"}]) {
    response={...valid,...change};await assert.rejects(client.annualAccountsAdvanceDelivery(command),failed);
  }
  assert.equal(calls,6);
});


test("Accounts correction preparation keeps the new child scope and explicit parent binding",async t=>{
  const command={companyId,incomeYear:2025,filingId:other,parentFilingId:filingId,parentDraftSha256:sha,
    contactEmail:"owner@example.test",confirmingRepresentative:"Synthetic Person"};
  let response={companyId,incomeYear:2025,filingId:other,draftSha256:sha,state:"draft"};
  t.mock.method(globalThis,"fetch",async (url,request)=>{
    assert.equal(new URL(url).pathname,"/api/v1/annual-accounts/delivery-corrections");
    assert.equal(new Headers(request.headers).get("Idempotency-Key"),"accounts-correction-command");
    assert.deepEqual(JSON.parse(request.body),command);return Response.json(response);
  });
  const client=createTalliApiClient({baseUrl:"https://backend.example"});
  assert.deepEqual(await client.annualAccountsPrepareDeliveryCorrection(command,{idempotencyKey:"accounts-correction-command"}),response);
  response={...response,filingId};
  await assert.rejects(client.annualAccountsPrepareDeliveryCorrection(command,{idempotencyKey:"accounts-correction-command"}),failed);
});
