import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const {default:ts}=await import(pathToFileURL(resolve('node_modules/typescript/lib/typescript.js')).href);
const {buildAnnualAccountsAuthorityTestRunFromEvidence}=await import(pathToFileURL(resolve('apps/web/app/lib/authority-test-evidence.ts')).href);
const baseline='5b74340ca75f215b43d754c6bf0fc49ef5974b0b';
if(process.version!=='v24.20.0')throw new Error('Pinned runtime required');
const digest=x=>createHash('sha256').update(x).digest('hex');
const source=readFileSync('apps/web/app/actions.ts','utf8');
if(source!==execFileSync('git',['show',`${baseline}:apps/web/app/actions.ts`],{encoding:'utf8'}))throw new Error('Changed action source');
const parsed=ts.createSourceFile('actions.ts',source,ts.ScriptTarget.Latest,true);
const fixtures=readFileSync('tests/rf1086_mixed_actions.test.mjs','utf8');
const prefix=fixtures.slice(fixtures.indexOf('const redirectSignal'),fixtures.indexOf('for (const name'));
const {setup}=new Function(prefix+';return {setup};')();
const archived=JSON.parse(readFileSync('docs/filing/evidence/annual-accounts-tt02-2026-07-14.json','utf8'));
const names=['addFilingOverride','addFilingReviewComment','acknowledgeFilingReviewComment','confirmAuthorityPermission','recordAuthorityTestEvidence','recordAnnualAccountsTt02Evidence'];
const actionHashes={},cases=[];
for(const name of names){
 const node=parsed.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name.text===name);
 const body=node.getText(parsed);actionHashes[name]=digest(body);
 const code=ts.transpileModule(body.replace('export async','async'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
 for(const fault of ['none','unauthenticated','step-up','rf-unavailable','tax-unavailable','read-failure','write-failure','audit-returned-error','audit-throws',...(name==='recordAnnualAccountsTt02Evidence'?['missing-file','wrong-extension','empty-file','oversized-file','invalid-json','missing-company','invalid-evidence']:[])]){
  const {dependencies,form,effects}=setup();const trace=[];
  const companyId=form.get('companyId');
  form.set('evidenceFile',new File([JSON.stringify(archived)],'evidence.json'));
  const preview={id:'preview',company_id:companyId,income_year:2025,filing:'årsregnskap'};
  dependencies.createSupabaseServerClient=async()=>({auth:{getUser:async()=>{trace.push({operation:'get-user'});return{data:{user:fault==='unauthenticated'?null:{id:'owner'}}};}},from(table){
   let kind='read';const operations=[];
   const chain=new Proxy({}, {get(_,method){if(method==='then')return(resolve,reject)=>{trace.push({table,kind,operations});if(table==='audit_events'&&fault==='audit-throws')return reject(new Error('synthetic-audit-failure'));const failed=(fault==='read-failure'&&kind==='read')||(fault==='write-failure'&&kind!=='read'&&table!=='audit_events')||(fault==='audit-returned-error'&&table==='audit_events');resolve({data:table==='filing_review_comments'?{id:'comment',company_id:companyId,severity:'advisory'}:preview,error:failed?{message:`synthetic-${fault}`} :null});};return(...args)=>{operations.push({method,args});if(['insert','update','upsert'].includes(method))kind=method;return chain;};}});return chain;
  }});
  const originalStep=dependencies.requireSensitiveActionStepUp;
  dependencies.requireSensitiveActionStepUp=async(...args)=>{await originalStep(...args);trace.push({operation:'step-up',companyId:args[2],purpose:args[3]});if(fault==='step-up')throw new Error('synthetic-step-up');};
  for(const key of ['findRf1086Preview','acknowledgeOwnedRf1086Comment']){const prior=dependencies[key];dependencies[key]=async(...args)=>{if(fault==='rf-unavailable')throw new Error('synthetic-rf-unavailable');return prior(...args);};}
  for(const key of ['findCompanyTaxPreview','acknowledgeOwnedCompanyTaxComment']){const prior=dependencies[key];dependencies[key]=async(...args)=>{if(fault==='tax-unavailable')throw new Error('synthetic-tax-unavailable');return prior(...args);};}
  dependencies.loadAcceptedMembershipCompany=async id=>{trace.push({operation:'accepted-company',companyId:id});return fault==='missing-company'?null:{org_number:archived.companyOrgNumber};};
  dependencies.buildAnnualAccountsAuthorityTestRunFromEvidence=input=>buildAnnualAccountsAuthorityTestRunFromEvidence({...input,recordedAt:'2026-07-14T12:00:00.000Z'});
  dependencies.revalidatePath=path=>trace.push({operation:'revalidate',path});
  dependencies.redirect=location=>{throw Object.assign(new Error('redirect'),{location});};
  dependencies.Date=class extends Date{constructor(...args){super(...(args.length?args:['2026-07-14T12:00:00.000Z']));}};
  if(fault==='missing-file')form.delete('evidenceFile');
  if(fault==='wrong-extension')form.set('evidenceFile',new File(['{}'],'evidence.txt'));
  if(fault==='empty-file')form.set('evidenceFile',new File([],'evidence.json'));
  if(fault==='oversized-file')form.set('evidenceFile',new File([' '.repeat(512*1024+1)],'evidence.json'));
  if(fault==='invalid-json')form.set('evidenceFile',new File(['{'],'evidence.json'));
  if(fault==='invalid-evidence')form.set('evidenceFile',new File(['{}'],'evidence.json'));
  const invoke=new Function(...Object.keys(dependencies),code+`;return ${name};`)(...Object.values(dependencies));
  let output;try{output={value:await invoke(form)};}catch(error){output=error.location?{redirect:error.location}:{error:{name:error.name,message:error.message}};}
  cases.push({action:name,fault,effects,trace,output});
 }
}
const data={schemaVersion:'1.0',sourceRevision:baseline,runtime:process.version,sourceSha256:digest(source),fixturePrefixSha256:digest(prefix),actionHashes,scope:'Exact original action bodies with deterministic time and synthetic dependencies. No SQL, HTTP, JWT/MFA ceremony or provider evidence; records original after-commit Audit continuation including returned-error behavior.',cases};
const bytes=JSON.stringify(data,null,2)+'\n';writeFileSync(process.argv[2],bytes,{flag:'wx',mode:0o600});
console.log(JSON.stringify({cases:cases.length,sha256:digest(bytes)}));
