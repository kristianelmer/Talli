import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/generated/client.ts";

const companyId="10000000-0000-4000-8000-000000000001",filingId="10000000-0000-4000-8000-000000000002";
const raw=Buffer.concat([Buffer.from('\ufeff <receipt/>\n'),Buffer.from([255])]);
const sha256=createHash('sha256').update(raw).digest('hex'),key='feedback:'+sha256;
const original={key,purpose:'feedback',sourceFilingId:filingId,sha256,mediaType:'text/xml',companyId,incomeYear:2025,filingId,bodyBase64:raw.toString('base64')};
const api=value=>createTalliApiClient({baseUrl:'https://backend.example',fetch:async()=>Response.json(value)});
const rejected=promise=>assert.rejects(promise,error=>error instanceof TalliApiError&&error.status===502);

test('original download preserves binary bytes and binds requested identity and raw hash',async()=>{
  assert.deepEqual(await api(original).companyTaxGetDeliveryOriginal(companyId,2025,filingId,key),original);
  for(const change of [{bodyBase64:Buffer.from('changed').toString('base64')},{purpose:'envelope'},{companyId:filingId},
    {incomeYear:2024},{filingId:companyId},{sha256:'a'.repeat(64)},{key:'envelope:'+sha256},{bodyBase64:'!!!!'}]){
    await rejected(api({...original,...change}).companyTaxGetDeliveryOriginal(companyId,2025,filingId,key));
  }
});

const row={filingId,parentFilingId:null,recordedAt:'2026-10-26T12:00:00Z',draftSha256:'a'.repeat(64),reviewSha256:'b'.repeat(64),approvalSha256:null,
  state:'creation_uncertain',sourceCurrent:true,actions:[],fields:[],originals:[],validation:null};
const workspace={version:'company-tax-delivery-workspace-v1',companyId,incomeYear:2025,sourceSha256:'c'.repeat(64),observedAt:row.recordedAt,
  technicalMode:'unavailable',preparationAvailable:false,rows:[row]};

test('workspace rejects foreign scope, duplicate identities/actions, unknown state and unavailable authority claims',async()=>{
  assert.deepEqual(await api(workspace).companyTaxGetDeliveryWorkspace(companyId,2025),workspace);
  for(const change of [{companyId:filingId},{incomeYear:2024},{rows:[row,row]},{preparationAvailable:true},
    {rows:[{...row,state:'accepted'}]},{rows:[{...row,actions:['create']}]},
    {technicalMode:'finite_loopback',rows:[{...row,actions:['create','create']}]},
    {rows:[{...row,originals:[original,original]}]}]){
    await rejected(api({...workspace,...change}).companyTaxGetDeliveryWorkspace(companyId,2025));
  }
});
