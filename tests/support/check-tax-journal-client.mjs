/** Validate an actual signed-topology archive through generated + web readers. */
import assert from "node:assert/strict";
import {webcrypto,createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/generated/client.ts";

const input=JSON.parse(readFileSync(0,"utf8"));
let value=input.archive;
const api=createTalliApiClient({baseUrl:"https://finite-client.invalid",fetch:async url=>{
  const parsed=new URL(url);
  if(parsed.pathname.endsWith("/delivery-journal-v1")) {
    assert.equal(parsed.searchParams.get("readEvidence"),"true");
    assert.equal(parsed.searchParams.get("readEvidenceVersion"),"2");
    assert.equal(parsed.searchParams.get("validationEvidence"),"true");
    return Response.json(value);
  }
  assert.ok(parsed.pathname.endsWith("/source-facts"));
  return Response.json(input.source);
}});
const exports={};
const dependencies={backendBaseUrl:()=>"https://finite-client.invalid",TalliApiError,createTalliApiClient:()=>api};
const source=readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts",import.meta.url),"utf8");
vm.runInNewContext(ts.transpileModule(source+"\nexport {verifyTaxJournalOriginals};",{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
  {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
await exports.verifyTaxJournalOriginals(value,value.companyId,value.incomeYear);
const result=await exports.loadTaxDeliveryDraftArchiveSource("synthetic-local-check",value.companyId,value.incomeYear);
assert.equal(result.error,null,"actual retained archive must survive the browser reader");
assert.equal(JSON.stringify(result.data.journal),JSON.stringify(value));
if(input.testSubmissionCorruptions) {
  const pristine=value;
  const canonical=value=>value!==null&&typeof value==='object'?Array.isArray(value)?'['+value.map(canonical).join(',')+']'
    :'{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
  const sha=raw=>createHash('sha256').update(raw).digest('hex');
  const event=(archive,slot)=>archive.events.find(row=>typeof slot==='string'?row.slot===slot:slot(row.slot));
  const change=(archive,slot,mutate)=>{
    const row=event(archive,slot);assert.ok(row,'test needs its actual original');const body=JSON.parse(row.canonicalJson);
    mutate(body);row.canonicalJson=canonical(body);row.eventSha256=sha(row.canonicalJson);
  };
  const changedProcess=(archive,mutate,lexical)=>change(archive,'completion:confirm_submission',value=>{
    const proof=value.completion.submission_read_evidence;const metadata=JSON.parse(proof.instance_canonical_json);
    const binding=metadata.observation;const body=JSON.parse(Buffer.from(binding.original.body_base64,'base64').toString('utf8').replace(/^\ufeff/u,''));
    mutate(body);let raw=JSON.stringify(body);if(lexical)raw=raw.replace('"flow":3','"flow":'+lexical);
    binding.original.body_base64=Buffer.from(raw).toString('base64');proof.instance_canonical_json=canonical(metadata);
    proof.instance_sha256=sha(proof.instance_canonical_json);
    const identity=sha(JSON.stringify(['tax-instance-read-identity-v1',binding.filing_id,binding.company_id.value,binding.income_year.value,
      binding.approved_by.subject.value,binding.approval_sha256,binding.organization_number,binding.instance_id,sha(Buffer.from(binding.original.body_base64,'base64'))]));
    const file=JSON.parse(proof.envelope_canonical_json);file.observation.instance_evidence_sha256=identity;
    proof.envelope_canonical_json=canonical(file);proof.envelope_sha256=sha(proof.envelope_canonical_json);
  });
  const cases=[
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.owner_confirmation.documents_confirmed=false;}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.owner_confirmation.warnings_acknowledged=1;}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.owner_confirmation.preparation_result_sha256='0'.repeat(64);}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.owner_confirmation.response_original_sha256='0'.repeat(64);}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.owner_confirmation.owner_review_sha256='invalid';}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.instance_read.event_sha256='0'.repeat(64);}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.observed_from.value='2025-01-01T00:00:00+00:00';}),
    a=>change(a,'intent:confirm_submission',v=>{v.request.submission_prerequisite.extra=true;}),
    a=>changedProcess(a,b=>{b.process.currentTask={altinnTaskType:'confirmation',elementId:'Task_2Revisor',flow:3};}),
    a=>changedProcess(a,()=>{},'3.0'),
    a=>changedProcess(a,()=>{},'3e0'),
    a=>change(a,'completion:confirm_submission',v=>{v.completion.origin='mutation_response';}),
    a=>change(a,'completion:confirm_submission',v=>{v.completion.submission_read_evidence.feedback_sha256='0'.repeat(64);}),
    a=>change(a,s=>s.startsWith('observation:feedback:'),v=>{v.observation.original.purpose='envelope';}),
    a=>change(a,s=>s.startsWith('observation:feedback:'),v=>{v.observation.data_id='00000000-0000-4000-8000-000000008888';}),
    a=>{a.sourceFacts.evidence.version='company-tax-source-v7:'+a.sourceSha256;},
    a=>change(a,'intent:confirm_submission',v=>{v.version='company-tax-delivery-mutation-request-v1';delete v.request.submission_prerequisite;}),
    a=>change(a,'completion:confirm_submission',v=>{v.version='company-tax-delivery-mutation-completion-v1';
      v.completion.response_base64=Buffer.from('{}').toString('base64');v.completion.origin='mutation_response';delete v.completion.submission_read_evidence;}),
  ];
  for(const [index,mutate]of cases.entries()) {
    value=structuredClone(pristine);mutate(value);
    await assert.rejects(exports.verifyTaxJournalOriginals(value,value.companyId,value.incomeYear),undefined,`new codec corruption ${index}`);
    const failed=await exports.loadTaxDeliveryDraftArchiveSource('synthetic-local-check',value.companyId,value.incomeYear);
    assert.ok(failed.error,`corruption ${index} cannot be a successful archive`);assert.equal(failed.data,null);
  }
  value=pristine;process.stdout.write(`Submission archive rejected ${cases.length} consistently rehashed corruptions.\n`);
}
process.stdout.write("Actual Tax archive accepted with every original unchanged.\n");
