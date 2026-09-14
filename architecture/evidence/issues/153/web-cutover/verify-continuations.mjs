import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root=process.cwd();const require=createRequire(root+'/package.json');const ts=require('typescript');
const base='5b74340ca75f215b43d754c6bf0fc49ef5974b0b',path='apps/web/app/actions.ts';
const old=execFileSync('git',['show',base+':'+path],{encoding:'utf8'}),current=readFileSync(path,'utf8');
const names=['addFilingOverride','addFilingReviewComment','acknowledgeFilingReviewComment','confirmAuthorityPermission','recordAuthorityTestEvidence','recordAnnualAccountsTt02Evidence','refreshAnnualReadinessSnapshots','queueDeadlineReminders'];
function chains(source,name){const sf=ts.createSourceFile(path,source,ts.ScriptTarget.Latest,true);const fn=sf.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);const rows=[];const printer=ts.createPrinter();function visit(n){if(ts.isCallExpression(n)&&ts.isPropertyAccessExpression(n.expression)&&n.expression.name.text==='from'&&ts.isStringLiteral(n.arguments[0])&&['audit_events','notification_outbox'].includes(n.arguments[0].text)){let top=n;while(ts.isPropertyAccessExpression(top.parent)&&ts.isCallExpression(top.parent.parent))top=top.parent.parent;rows.push({resource:n.arguments[0].text,source:printer.printNode(ts.EmitHint.Unspecified,top,sf)});}ts.forEachChild(n,visit);}visit(fn);return rows;}
const results=names.map(name=>{const original=chains(old,name),actual=chains(current,name);return {name,original,actual,equal:JSON.stringify(original)===JSON.stringify(actual)};});
const report={baseline:base,path,sourceSha256:createHash('sha256').update(current).digest('hex'),status:results.every(r=>r.equal)?'PASS':'FAIL',results};
writeFileSync('/Users/kristianelmer/.codex/issue-192-private/issue153-entry/web-continuation-proof.json',JSON.stringify(report,null,2)+'\n');console.log(report.status,results.map(r=>[r.name,r.equal,r.actual.length]));if(report.status!=='PASS')process.exitCode=1;
