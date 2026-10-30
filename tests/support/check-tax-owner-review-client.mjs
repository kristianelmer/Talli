/** Verify actual backend DTO bytes in the generated SDK and browser loader. */
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createTalliApiClient,TalliApiError,verifyCompanyTaxOwnerReviewArtifact} from '../../packages/talli-api-client/src/index.ts';

const pristine=JSON.parse(readFileSync(0,'utf8'));let value=pristine;let calls=0;
const api=createTalliApiClient({baseUrl:'https://finite-client.invalid',headers:{Authorization:'Bearer unit-owner'},fetch:async (url,request)=>{
  calls++;const parsed=new URL(url);
  assert.equal(parsed.pathname,'/api/v1/company-tax/delivery-owner-review');
  assert.equal(parsed.searchParams.get('filingId'),pristine.filingId);
  assert.equal(request.method,'GET');assert.equal(request.cache,'no-store');
  return Response.json(value);
}});
const exports={};const dependencies={verifyCompanyTaxOwnerReviewArtifact,backendClientOptions: () => ({ baseUrl: 'https://finite-client.invalid' }),TalliApiError,createTalliApiClient:()=>api};
const source=readFileSync(new URL('../../apps/web/features/company-tax-filing/transport.ts',import.meta.url),'utf8');
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
  {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
const read=()=>exports.loadTaxDeliveryOwnerReview('unit-owner',pristine.companyId,pristine.incomeYear,pristine.filingId,pristine.approvalSha256);
assert.equal(JSON.stringify(await read()),JSON.stringify(pristine));
assert.equal(calls,1);
const canonical=value=>value!==null&&typeof value==='object' ? Array.isArray(value)
  ? '['+value.map(canonical).join(',')+']'
  : '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}' : JSON.stringify(value);
const sha=value=>createHash('sha256').update(canonical(value)).digest('hex');
const corruptions=[
  r=>{r.review.response.guidance.push({type_code:'forged',occurrence_id:null,message:'Hidden warning',servicing_strategy:null,path:null});},
  r=>{r.review.documents[0].fields.pop();r.artifactSha256='0'.repeat(64);},
  r=>{r.companyId='10000000-0000-4000-8000-000000000099';},
  r=>{r.review.approval.draft_sha256='0'.repeat(64);r.review.calculated_context.draft_sha256='0'.repeat(64);},
  r=>{r.review.response.inspection.schema_sha256='0'.repeat(64);},
  r=>{r.review.calculated_context.schema_sha256='0'.repeat(64);},
  r=>{r.review.response.inspection.calculation_deviation_count++;},
  r=>{r.review.response.inspection.result_code='validertMedFeil';},
  r=>{r.review.response.subject_flags=[{name:'erFritattForFormuesskatt',value:true},{name:'erFritattForFormuesskatt',value:false}];},
  r=>{r.review.documents.pop();},
  r=>{r.review.documents.reverse();},
  r=>{r.review.documents[0].fields.push(r.review.documents[0].fields[0]);},
  r=>{r.review.documents[0].fields[0].path='not-absolute';},
  r=>{r.review.documents[0].original_sha256='0'.repeat(64);},
  r=>{r.review.response.inspection.calculated_documents[0].body_base64=btoa('changed');},
  r=>{r.review.extra=true;},
  r=>{r.review.response.inspection.guidance_count=1.5;},
  r=>{r.review.response_original.body_base64=btoa('changed validation response');},
  r=>{r.review.response_original.purpose='envelope';},
];
for(const [index,corrupt] of corruptions.entries()) {
  value=structuredClone(pristine);corrupt(value);
  // All except the deliberate changed-commitment case have a valid new hash.
  if(index!==1)value.artifactSha256=sha({version:value.version,review:value.review});
  const before=calls;await assert.rejects(read(),undefined,`corruption ${index} must fail`);assert.equal(calls,before+1);
}
process.stdout.write(`Owner-review readers passed: exact DTO and ${corruptions.length} negative cases.\n`);
