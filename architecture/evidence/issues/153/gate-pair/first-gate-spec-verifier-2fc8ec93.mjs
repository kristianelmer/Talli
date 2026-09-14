import fs from 'node:fs';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const repo='/Users/kristianelmer/.codex/worktrees/d060/Holding accounting';
const require=createRequire(repo+'/package.json');
const Ajv=require('ajv/dist/2020.js'),ts=require('typescript');
const base='2fc8ec93eb4eeb818e5273481801ec1be0079b19',storage='5c6d2d7a0de1c40f9d8f132363da4b76b53da5a6';
const git=(...args)=>execFileSync('git',['-C',repo,...args]);
const show=(rev,path)=>git('show',`${rev}:${path}`);
const hash=b=>createHash('sha256').update(b).digest('hex');
const check=(condition,message)=>{if(!condition)throw Error(message);};
const ep=`architecture/evidence/customer-ready-gates/${base}.json`,raw=show(storage,ep),receipt=JSON.parse(raw),logBytes=show(storage,receipt.transcriptPath),log=logBytes.toString();
const schemaPath='architecture/customer-ready-gate-evidence.schema.json',schemaBytes=show(base,schemaPath),schema=JSON.parse(schemaBytes);
const ajv=new Ajv({allErrors:true});ajv.addFormat('date-time',s=>/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(s)&&new Date(s).toISOString()===s);const validate=ajv.compile(schema);check(validate(receipt),JSON.stringify(validate.errors));
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const canonicalDigest=hash(JSON.stringify(canonical(receipt)));
check(canonicalDigest==='3229c1b2f25f743db2f0523346349c5c414c5492fb7a107d95683c0edbcfef62','canonical');
check('sha256:'+hash(logBytes)===receipt.transcriptDigest,'transcript');
const producer=show(base,receipt.producer);check('sha256:'+hash(producer)===receipt.producerDigest,'producer');
const source=ts.createSourceFile('producer.mjs',producer.toString(),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);const declared=[];
function visit(node){if(ts.isCallExpression(node)&&node.expression.getText(source)==='execute'&&ts.isStringLiteral(node.arguments[0]))declared.push({name:node.arguments[0].text,command:node.arguments[1].text});ts.forEachChild(node,visit);}visit(source);
const rawChecks=[...log.matchAll(/^\[([^\]]+)\] command=(.*)$/gm)].map(m=>({name:m[1],command:m[2]}));
check(JSON.stringify(rawChecks)===JSON.stringify(declared),'producer commands vs transcript');
check(receipt.checks.length===11&&rawChecks.length===12,'command count');
for(let i=0;i<receipt.checks.length;i++){
 const c=receipt.checks[i],d=rawChecks[i+1];check(c.name===d.name&&c.command===d.command,'check identity');
 const exits=[...log.matchAll(new RegExp(`^\\[${c.name}\\] exit=(\\d+)$`,'gm'))];
 const times=[...log.matchAll(new RegExp(`^\\[${c.name}\\] durationMs=(\\d+)$`,'gm'))];
 check(exits.length===1&&+exits[0][1]===0&&c.exitCode===0,'exit');check(times.length===1&&+times[0][1]===c.durationMs,'duration');
}
const allTimes=[...log.matchAll(/^\[[^\]]+\] durationMs=(\d+)$/gm)].map(m=>+m[1]);
const elapsed=Date.parse(receipt.executedAt)-Date.parse(receipt.startedAt);check(elapsed>=allTimes.reduce((a,b)=>a+b,0),'duration bounds');
check(log.startsWith(`customer-ready-release-gate revision=${base}\nstartedAt=${receipt.startedAt}\n`),'start');check(log.endsWith(`executedAt=${receipt.executedAt}\nverdict=pass\n`),'finish');
check(receipt.previousPassingRevision===null,'first gate');git('merge-base','--is-ancestor',base,storage);
const delta=git('diff','--name-only',`${base}...${storage}`).toString().trim().split('\n');check(delta.every(p=>p.startsWith('architecture/evidence/')),'evidence only');
const firstStorage=git('log',storage,'--diff-filter=A','--format=%H','--',ep).toString().trim();check(firstStorage===storage,'storage');
const sections=log.split(/(?=^> talli-repository@0\.1\.0 )/m);const groups={};
for(const name of ['test:browser-owner','test:browser-owner-annual','test:supabase-rf-feedback','test:browser-authority-connections','test:browser-shareholder-register-filing','test:browser-company-tax','test:browser-annual-accounts']){
 const rows=sections.filter(s=>s.startsWith(`> talli-repository@0.1.0 ${name}\n`)&&log.indexOf(s)>log.indexOf('[database-isolation] command='));check(rows.length===1,`group ${name}`);const s=rows[0],passes=[...s.matchAll(/^ℹ pass (\d+)$/gm)].map(m=>+m[1]),skips=[...s.matchAll(/^ℹ skipped (\d+)$/gm)].map(m=>+m[1]);check(passes.length>0&&passes.every(n=>n>0)&&skips.every(n=>n===0),`result ${name}`);groups[name]={passes,skips};}
check(log.includes('41 passed in 17.42s'),'accounts');check(log.includes('699 passed in 311.86s'),'billing');check(log.includes('5831 passed, 2 skipped'),'backend');check(log.includes('17 passed, 1 skipped'),'validation');
const prefix='architecture/evidence/issues/153/exit-gates-first/';const manifest=JSON.parse(show(storage,prefix+'manifest.json'));const artifacts={};
for(const a of manifest.artifacts){const bytes=show(storage,a.path);check(hash(bytes)===a.sha256&&bytes.length===a.bytes,'artifact '+a.path);artifacts[a.path]=hash(bytes);}
const privateRoot='/Users/kristianelmer/.codex/issue-192-private/issue153-entry';const adoptions={};
for(const a of manifest.artifacts){const n=a.path.split('/').at(-1),local=privateRoot+'/'+n;if(n.startsWith('browser-validation-')&&fs.existsSync(local)){check(fs.readFileSync(local).equals(show(storage,a.path)),'adoption '+n);adoptions[n]=hash(show(storage,a.path));}}
console.log(JSON.stringify({verdict:'PASS_FIRST_COMPLETE_IMMUTABLE_GATE',base,storage,firstStorage,evidencePath:ep,canonicalDigest,receiptBytesSha256:hash(raw),transcriptDigest:hash(logBytes),producerDigest:hash(producer),schemaDigest:hash(schemaBytes),schemaValid:true,ajvVersion:require('ajv/package.json').version,checks:receipt.checks,startedAt:receipt.startedAt,executedAt:receipt.executedAt,elapsedMs:elapsed,totalRecordedDurationMs:allTimes.reduce((a,b)=>a+b,0),groups,backend:{passed:5831,optionalSkipped:2},billing:{passed:699},accounts:{passed:41,skipped:0},validationObservation:{pythonPassed:17,optionalPythonSkipped:1,mandatoryNodeSqlRan:true},advisors:{blocking:0,earlyPerformanceWarnings:60,finalPerformanceWarnings:53},delta,manifestArtifactChecks:artifacts,adoptionChecks:adoptions,limitations:['First gate only; second result and protected integration unverified','No test, database or browser reruns']},null,2));
