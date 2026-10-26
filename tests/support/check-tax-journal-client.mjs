/** Validate an actual signed-topology archive through generated + web readers. */
import assert from "node:assert/strict";
import {webcrypto,createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import {createTalliApiClient,TalliApiError,verifyCompanyTaxDeliveryJournalArchive,verifyCompanyTaxDeliveryDraftArchive,verifyCompanyTaxOwnerReviewArtifact} from "../../packages/talli-api-client/src/index.ts";

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
const dependencies={verifyCompanyTaxDeliveryJournalArchive,verifyCompanyTaxDeliveryDraftArchive,verifyCompanyTaxOwnerReviewArtifact,backendBaseUrl:()=>"https://finite-client.invalid",TalliApiError,createTalliApiClient:()=>api};
const source=readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts",import.meta.url),"utf8");
vm.runInNewContext(ts.transpileModule(source+"\nexport {verifyTaxJournalOriginals};",{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
  {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
await exports.verifyTaxJournalOriginals(value,value.companyId,value.incomeYear);
const result=await exports.loadTaxDeliveryDraftArchiveSource("synthetic-local-check",value.companyId,value.incomeYear);
assert.equal(result.error,null,"actual retained archive must survive the browser reader");
assert.equal(JSON.stringify(result.data.journal),JSON.stringify(value));
if(input.testCorrectionCorruptions) {
  const pristine=value;
  const canonical=v=>v!==null&&typeof v==='object'?Array.isArray(v)?'['+v.map(canonical).join(',')+']'
    :'{'+Object.keys(v).sort().map(key=>JSON.stringify(key)+':'+canonical(v[key])).join(',')+'}':JSON.stringify(v);
  const sha=raw=>createHash('sha256').update(raw).digest('hex');
  const child=archive=>archive.drafts.find(row=>JSON.parse(row.canonicalJson).version==='company-tax-delivery-draft-v3');
  const envelopeSpan=raw=>{
    const start=raw.indexOf('"envelope":{')+'"envelope":'.length;
    assert.equal(raw[start],'{');let depth=0,string=false,escape=false;
    for(let index=start;index<raw.length;index++) {
      const char=raw[index];
      if(string){if(escape)escape=false;else if(char==='\\')escape=true;else if(char==='"')string=false;continue;}
      if(char==='"')string=true;else if(char==='{')depth++;else if(char==='}'&&--depth===0)return [start,index+1];
    }
    throw new Error('fixture envelope is incomplete');
  };
  const serializeChild=(root,original)=>{
    assert.deepEqual(root.draft.envelope,JSON.parse(original).draft.envelope,'corruption case must preserve the approved envelope');
    const raw=canonical(root);const [start,end]=envelopeSpan(raw);const [oldStart,oldEnd]=envelopeSpan(original);
    return raw.slice(0,start)+original.slice(oldStart,oldEnd)+raw.slice(end);
  };
  const change=(archive,mutate)=>{
    const row=child(archive);assert.ok(row);assert.ok(!archive.events.some(event=>event.filingId===row.filingId),'correction negatives exercise a prepared child before review');
    const root=JSON.parse(row.canonicalJson);mutate(root.draft.correction_parent,root.draft,archive);
    row.canonicalJson=serializeChild(root,row.canonicalJson);row.draftSha256=sha(row.canonicalJson);
    const fact=archive.sourceFacts.deliveryDrafts?.find(fact=>fact.filingId===row.filingId);
    if(fact)fact.draftSha256=row.draftSha256;
  };
  const cases=[
    ...['draft_sha256','approval_sha256','submission_request_sha256','submission_completion_sha256',
      'calculated_tax_sha256','calculated_business_sha256'].map(key=>archive=>change(archive,link=>{link[key]='d'.repeat(64);})),
    archive=>change(archive,link=>{link.filing_id='00000000-0000-4000-8000-000000000099';}),
    archive=>change(archive,(link,draft)=>{link.filing_id=draft.filing_id;}),
    archive=>change(archive,link=>{link.terminal.feedback_canonical_json=link.terminal.feedback_sha256=null;}),
    archive=>change(archive,link=>{link.terminal.feedback_sha256='d'.repeat(64);}),
    archive=>change(archive,link=>{const proof=link.terminal;const row=JSON.parse(proof.instance_canonical_json);
      row.observation.observed_at.value='2025-01-01T00:00:00+00:00';proof.instance_canonical_json=canonical(row);proof.instance_sha256=sha(proof.instance_canonical_json);}),
    archive=>change(archive,link=>{const proof=link.terminal;const row=JSON.parse(proof.feedback_canonical_json);
      row.observation.data_id='00000000-0000-4000-8000-000000000099';proof.feedback_canonical_json=canonical(row);proof.feedback_sha256=sha(proof.feedback_canonical_json);}),
    archive=>change(archive,link=>{const proof=link.terminal;const row=JSON.parse(proof.envelope_canonical_json);
      row.observation.original.body_base64=Buffer.concat([Buffer.from(row.observation.original.body_base64,'base64'),Buffer.from('\n')]).toString('base64');
      proof.envelope_canonical_json=canonical(row);proof.envelope_sha256=sha(proof.envelope_canonical_json);}),
    archive=>change(archive,(_,draft)=>{draft.prepared_by.subject.value='00000000-0000-4000-8000-000000000099';}),
    archive=>change(archive,(_,draft)=>{draft.current_document.tax_xml_sha256='d'.repeat(64);}),
    archive=>change(archive,(_,draft)=>{draft.validation=null;}),
    archive=>change(archive,(_,draft)=>{draft.current_document.schema_sha256='d'.repeat(64);}),
    ...['schema_sha256','source_sha256','review_sha256','tax_xml_sha256','business_xml_sha256','envelope_xml_sha256'].map(key=>archive=>change(archive,(_,draft)=>{draft.validation[key]='d'.repeat(64);})),
    ...['pair','reference','locked','guidance','entity'].map(kind=>archive=>change(archive,(_,draft)=>{
      let text=Buffer.from(draft.current_document.response.raw_base64,'base64').toString('utf8');
      if(kind==='pair')text=text.replace(/<content>[^<]+<\/content>/u,'<content>eA==</content>');
      else if(kind==='reference')text=text.replace('<id>current-after-terminal-parent</id>','<id>different-current-reference</id>');
      else if(kind==='locked')text=text.replace('</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>','<laasteFelt><laastFeltSkattemelding><sti>unknown</sti></laastFeltSkattemelding></laasteFelt></skattemeldingOgNaeringsspesifikasjonforespoerselResponse>');
      else if(kind==='guidance')text=text.replace('</dokumenter>','<utvidetVeiledningdokument><id>unknown</id><encoding>utf-8</encoding><content>eA==</content></utvidetVeiledningdokument></dokumenter>');
      else text=text.replace(/(<skattemeldingOgNaeringsspesifikasjonforespoerselResponse)/u,'<!DOCTYPE forbidden [<!ENTITY leak SYSTEM "file:///no-read">]>$1');
      draft.current_document.response.raw_base64=Buffer.from(text).toString('base64');
    })),
    archive=>{archive.sourceFacts.evidence.version='company-tax-source-v8:'+archive.sourceSha256;},
    archive=>{const row=structuredClone(child(archive));const root=JSON.parse(row.canonicalJson);row.filingId=root.draft.filing_id='00000000-0000-4000-8000-000000000099';
      row.canonicalJson=serializeChild(root,row.canonicalJson);row.draftSha256=sha(row.canonicalJson);archive.drafts.push(row);archive.draftCount++;},
  ];
  for(const [index,mutate] of cases.entries()) {
    value=structuredClone(pristine);mutate(value);
    await assert.rejects(exports.verifyTaxJournalOriginals(value,value.companyId,value.incomeYear));
    await assert.rejects(api.companyTaxGetDeliveryJournalArchive(value.companyId,value.incomeYear),error=>error instanceof TalliApiError && error.status===502,"correction case "+index);
    const blocked=await exports.loadTaxDeliveryDraftArchiveSource('synthetic-local-check',value.companyId,value.incomeYear);
    assert.equal(blocked.data,null);assert.ok(blocked.error);
  }
  value=pristine;
}
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
