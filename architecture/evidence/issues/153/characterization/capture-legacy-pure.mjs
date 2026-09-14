import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
import {execFileSync} from 'node:child_process';

const baseline='5b74340ca75f215b43d754c6bf0fc49ef5974b0b';
const out=process.argv[2];
if(!out) throw new Error('Explicit output file required');
if(process.version!=='v24.20.0') throw new Error('Pinned Node v24.20.0 required');
const digest=x=>createHash('sha256').update(x).digest('hex');
const paths=['apps/web/app/lib/annual-accounts.ts','apps/web/app/lib/annual-accounts-xml.ts','apps/web/app/lib/authority-test-evidence.ts','apps/web/app/lib/annual-readiness.ts','tests/annual_accounts_payload.test.mjs','docs/filing/evidence/annual-accounts-tt02-2026-07-14.json'];
const sources={};
for(const path of paths){const bytes=readFileSync(path);const original=execFileSync('git',['show',`${baseline}:${path}`]);if(!bytes.equals(original))throw new Error(`Changed source: ${path}`);sources[path]=digest(bytes);}
const lib=name=>import(pathToFileURL(resolve('apps/web/app/lib',name)).href);
const {buildAnnualAccountsPayload}=await lib('annual-accounts.ts');
const {renderAnnualAccountsXml}=await lib('annual-accounts-xml.ts');
const {buildAnnualAccountsAuthorityTestRunFromEvidence}=await lib('authority-test-evidence.ts');
// Export one private function without altering its body; redirect only imports.
const readinessSource=readFileSync(paths[3],'utf8');
const exposed=stripTypeScriptTypes(readinessSource.replace('function aarsregnskapIssues(', 'export function aarsregnskapIssues('));
const rewritten=exposed.replace(/from "(\.\/[^"]+)"/g,(_,p)=>`from ${JSON.stringify(pathToFileURL(resolve('apps/web/app/lib',p)).href)}`);
const {aarsregnskapIssues}=await import('data:text/javascript;base64,'+Buffer.from(rewritten).toString('base64'));
const fixture=readFileSync(paths[4],'utf8');
const fixturePrefix=fixture.slice(fixture.indexOf('const annualData'),fixture.indexOf('test("builds'));
const {annualData,ledgerEntries}=new Function(fixturePrefix+';return {annualData,ledgerEntries};')();
const base=()=>structuredClone({incomeYear:2025,annualData,ledgerEntries});
const capture=fn=>{try{const value=fn();const numericSpecials=[];function visit(v,path=[]){if(typeof v==='number'&&(!Number.isFinite(v)||Object.is(v,-0)))numericSpecials.push({path,kind:Object.is(v,-0)?'-0':String(v)});else if(v&&typeof v==='object')for(const [key,item] of Object.entries(v))visit(item,[...path,key]);}visit(value);return numericSpecials.length?{value,numericSpecials}:{value};}catch(e){return {error:{name:e.name,message:e.message}};}};
const payloadCases=[];
function payloadCase(id,mutate){const input=base();mutate?.(input);payloadCases.push({id,input,output:capture(()=>buildAnnualAccountsPayload(input))});}
payloadCase('supported-dividend');
payloadCase('no-annual-data',x=>x.annualData=null);
payloadCase('empty-ledger',x=>x.ledgerEntries=[]);
for(const value of [null,-1,0,0.5,1,2.675,'2','',false,true])payloadCase(`fte-${JSON.stringify(value)}`,x=>x.annualData.annual_full_time_equivalents=value);
for(const flag of ['annual_accounts_audit_required','annual_accounts_not_small_enterprise','annual_accounts_annual_report_required'])payloadCase(flag,x=>x.annualData.confirmations.push(flag));
payloadCase('ordered-feedback',x=>{x.annualData.annual_full_time_equivalents=null;x.annualData.confirmations=['annual_accounts_annual_report_required','annual_accounts_not_small_enterprise','annual_accounts_audit_required'];});
const accounts=['1300','1310','1350','1800','1810','1815','1920','7770','6700','6705','6420','7790','6720','7795','8070','8071','8074','8050','8090','8171','8174','8300','2500','2000','2050','2255','1370','2990'];
for(const account of accounts)payloadCase(`account-${account}`,x=>x.ledgerEntries[0].lines=[{account,debit:13.755,credit:3.225}]);
for(const value of [0.005,-0.005,0.015,-0.015,1.005,2.675,9007199254740991,'0x10','0b10','0o10',' 3.5 ','','Infinity','NaN',null,false,true])payloadCase(`number-${String(value)}`,x=>x.ledgerEntries[0].lines=[{account:'1920',debit:value,credit:0}]);
payloadCase('ordered-large-small-cancellation',x=>x.ledgerEntries[0].lines=[1e16,1,-1e16].map(debit=>({account:'1920',debit,credit:0})));
payloadCase('separate-debit-credit-reduction',x=>x.ledgerEntries[0].lines=[{account:'1920',debit:1e16,credit:1e16},{account:'1920',debit:1,credit:0}] );
payloadCase('split-rounded-investment-accounts',x=>x.ledgerEntries[0].lines=['1300','1310','1350','1800','1810','1815'].map(account=>({account,debit:0.005,credit:0})));
payloadCase('string-nonmatching-account',x=>x.ledgerEntries[0].lines=[{account:1920,debit:42,credit:0}]);
payloadCase('tax-expense-payable',x=>x.ledgerEntries[0].lines.push({account:'8300',debit:20000,credit:0},{account:'2500',debit:0,credit:20000}));
const xmlBase=()=>({payload:buildAnnualAccountsPayload(base()),companyOrgNumber:'310279617',companyName:'Synthetic & <Holding> "AS"',contactEmail:'owner@example.test',approvalDate:'2026-06-30',confirmingRepresentative:"Synthetic & <Owner> 'Person'"});
const xmlCases=[];
function xmlCase(id,mutate){const input=xmlBase();mutate?.(input);xmlCases.push({id,input,output:capture(()=>renderAnnualAccountsXml(input))});}
const field=(x,tag)=>x.payload.fields.find(f=>f.tag===tag);
xmlCase('supported-escaped-bytes');
for(const key of ['schemaType','hovedskjemaDataFormatId','hovedskjemaDataFormatVersion','selskapsregnskapDataFormatId','selskapsregnskapDataFormatVersion'])xmlCase(`header-${key}`,x=>x.payload[key]='wrong');
for(const f of xmlBase().payload.fields){xmlCase(`missing-${f.tag}`,x=>x.payload.fields=x.payload.fields.filter(v=>v.tag!==f.tag));xmlCase(`orid-${f.tag}`,x=>field(x,f.tag).orid='wrong');xmlCase(`duplicate-${f.tag}`,x=>x.payload.fields.push({...field(x,f.tag)}));}
xmlCase('extra-fields-ignored',x=>x.payload.fields.push({tag:'unknown',orid:'unknown',value:'anything',source:'synthetic'}));
xmlCase('sorted-blocks-before-contact',x=>{x.payload.feedback=[{level:'block',code:'z'},{level:'warning',code:'a'},{level:'block',code:'A'},{level:'block',code:'z'}];x.companyOrgNumber='';});
xmlCase('header-before-fields-before-blocks',x=>{x.payload.schemaType='wrong';x.payload.fields=[];x.payload.feedback=[{level:'block',code:'x'}];});
for(const key of ['companyOrgNumber','companyName','contactEmail','approvalDate','confirmingRepresentative'])for(const value of ['', ' x ', '\ufeffx', '\u0085x', 'x\u0000',null])xmlCase(`contact-${key}-${JSON.stringify(value)}`,x=>x[key]=value);
for(const [key,limit] of [['companyName',175],['confirmingRepresentative',70]])for(const length of [limit,limit+1])xmlCase(`utf16-${key}-${length}`,x=>x[key]='😀'.repeat(Math.floor(length/2))+(length%2?'x':''));
for(const date of ['2026-02-29','2024-02-29','2025-12-30','2025-12-31','2026-13-01','0000-01-01','0099-01-01','0100-01-01','2026-01-01T00:00:00Z'])xmlCase(`date-${date}`,x=>x.approvalDate=date);
for(const value of [0.5,'0x10','0b10',' 0 ','','Infinity','NaN',9007199254740992,-1])xmlCase(`whole-number-${String(value)}`,x=>field(x,'antallAarsverk').value=value);
for(const tag of xmlBase().payload.fields.filter(f=>f.tag.endsWith('/aarets')).map(f=>f.tag)){xmlCase(`fraction-${tag}`,x=>field(x,tag).value=0.5);xmlCase(`negative-${tag}`,x=>field(x,tag).value=-1);xmlCase(`mismatch-${tag}`,x=>field(x,tag).value+=1);}
xmlCase('wrong-calendar-start',x=>field(x,'regnskapsstart').value='2025-02-01');
xmlCase('wrong-calendar-end',x=>field(x,'regnskapsslutt').value='2025-12-30');
xmlCase('wrong-currency',x=>field(x,'valuta').value='EUR');
const archived=JSON.parse(readFileSync(paths[5],'utf8'));
const evidenceCases=[];
function evidenceCase(id,mutate){const input={companyId:'00000000-0000-0000-0000-000000000153',expectedCompanyOrgNumber:archived.companyOrgNumber,evidence:structuredClone(archived),evidenceUrl:'https://evidence.example.test/annual.json',recordedBy:'00000000-0000-0000-0000-000000000154',recordedAt:'2026-07-14T12:00:00.000Z'};mutate?.(input);evidenceCases.push({id,input,output:capture(()=>buildAnnualAccountsAuthorityTestRunFromEvidence(input))});}
evidenceCase('archived-tt02-pending');
for(const [path,value] of [['environment','production'],['productionEnabled',true],['systemUserResource','wrong'],['status','locked_for_person_signing'],['signed',false],['submitted',false],['validation.hasErrors',true],['instance.id','bad'],['submission.processCompleted',false],['submission.signed',false],['submission.submitted',false],['submission.archived',false],['submission.processEndedAt','bad'],['submission.archiveReference','https://example.test'],['submission.receipt.dataId','bad'],['submission.receipt.dataType','wrong'],['submission.receipt.contentType','text/plain'],['submission.receipt.reference','https://example.test'],['payloadHashes.mainForm','A'.repeat(64)],['payloadHashes.companyAccounts',''],['inbox.status',''],['inbox.displayStatus',''],['inbox.confirmation','']]) evidenceCase(`invalid-${path}`,x=>{const keys=path.split('.');let target=x.evidence;for(const key of keys.slice(0,-1))target=target[key];target[keys.at(-1)]=value;});
for(const path of ['validation','instance','submission','payloadHashes','inbox'])evidenceCase(`missing-${path}`,x=>delete x.evidence[path]);
for(const value of ['2026-02-30','2026-07-14','July 14, 2026','0','0099-01-01','+010000-01-01T00:00:00Z'])evidenceCase(`date-parse-${value}`,x=>x.evidence.submission.processEndedAt=value);
for(const value of ['',null,' data:text/plain,synthetic ','\ufeffhttps://example.test\ufeff'])evidenceCase(`url-${String(value)}`,x=>x.evidenceUrl=value);
evidenceCase('wrong-company',x=>x.expectedCompanyOrgNumber='000000000');
evidenceCase('blank-company',x=>x.companyId='');
evidenceCase('blank-actor',x=>x.recordedBy='');
evidenceCase('unused-year-and-secrets-flags',x=>{x.evidence.incomeYear=2026;x.evidence.secretsStored=true;});
const readinessCases=[];
function readinessCase(id,mutate){const input={...base(),company:{id:'company-id'}};mutate?.(input);readinessCases.push({id,input,output:capture(()=>aarsregnskapIssues(input))});}
readinessCase('supported');readinessCase('missing-annual',x=>x.annualData=null);readinessCase('missing-ledger',x=>x.ledgerEntries=[]);readinessCase('other-company',x=>x.ledgerEntries[0].company_id='other');readinessCase('other-year',x=>x.ledgerEntries[0].income_year=2024);readinessCase('unapproved-close',x=>x.annualData.answers.general_meeting_approved=false);
for(const enabled of [false,true])readinessCase(`corporate-enabled-${enabled}`,x=>x.corporateDocuments={enabled,readiness:{blockers:[{code:'unsigned',message:'Signed artifact missing'},{code:'close_missing',message:'Corporate close missing'}],annualSubmissionReady:false,state:null}});
readinessCase('unaccepted-warning',x=>x.ledgerEntries[0].risk_flags=['manual']);readinessCase('accepted-warning',x=>{x.ledgerEntries[0].risk_flags=['manual'];x.ledgerEntries[0].warning_accepted_at='2026-01-01T00:00:00Z';});
readinessCase('ordered-all-blocks-warnings',x=>{x.corporateDocuments={enabled:true,readiness:{blockers:[{code:'unsigned',message:'Signed artifact missing'}]}};x.annualData.answers.general_meeting_approved=false;x.annualData.annual_full_time_equivalents=null;x.annualData.confirmations.push('annual_accounts_audit_required');x.ledgerEntries[0].risk_flags=['manual'];x.ledgerEntries.push({...structuredClone(x.ledgerEntries[0]),warning_accepted_at:'2026-01-01T00:00:00Z'});});
const data={schemaVersion:'1.0',sourceRevision:baseline,runtime:process.version,sources,fixturePrefixSha256:digest(fixturePrefix),privateReadinessExposure:'Exact original function body; export keyword and absolute import URLs only. Common Annual aggregation is excluded.',payloadCases,xmlCases,evidenceCases,readinessCases};
const bytes=JSON.stringify(data,null,2)+'\n';writeFileSync(out,bytes,{flag:'wx',mode:0o600});
console.log(JSON.stringify({payloadCases:payloadCases.length,xmlCases:xmlCases.length,evidenceCases:evidenceCases.length,readinessCases:readinessCases.length,sha256:digest(bytes)}));
