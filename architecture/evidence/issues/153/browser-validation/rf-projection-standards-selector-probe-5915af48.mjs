import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { rfPublicProjectionRelations } = await import(pathToFileURL(process.argv[2]+'/tests/support/rf1086-fixture-access.mjs'));
const names=['filing_review_comments','filing_overrides','filing_submissions','authority_test_runs','authority_permissions','filing_previews'].map(n=>'public.'+n);
const results=[];
async function scenario(name,options={},accepted=false) {
 const calls=[];const error=new Error('catalog read failed');
 const db={connectionParameters:{host:options.host??'127.0.0.1'},query:async(q,params)=>{
  calls.push(q);assert.match(q,/^select /u);if(options.throwRead)throw error;
  if(q.includes('unnest')) {const kinds=params[0][0].startsWith('public.')?(options.publicKinds??Array(6).fill(null)):(options.ownedKinds??Array(6).fill('r'));return {rows:kinds.map((relkind,i)=>({name:params[0][i],relkind}))};}
  if(q.includes('to_regclass'))return {rows:[{present:options.stateExists??true}]};
  return {rows:[{phase:options.phase??'contracted'}]};
 }};
 let value,thrown;try{value=await rfPublicProjectionRelations(db);}catch(e){thrown=e;}
 if(accepted){assert.equal(thrown,undefined);assert.deepEqual(value,(options.publicKinds??[]).some(Boolean)?names:[]);}else assert.ok(thrown,name);
 if(options.throwRead)assert.equal(thrown,error);
 if(options.host==='hosted.invalid')assert.equal(calls.length,0);
 assert.ok(calls.every(q=>q.startsWith('select ')));
 results.push({case:name,expectedAccepted:accepted,status:'PASS',queries:calls.length});
}
await scenario('all public ordinary tables',{publicKinds:Array(6).fill('r'),phase:'expanded'},true);
await scenario('all public partitioned tables',{publicKinds:Array(6).fill('p'),stateExists:false},true);
await scenario('retired public, all owned ordinary',{},true);
await scenario('retired public, all owned partitioned',{ownedKinds:Array(6).fill('p')},true);
await scenario('contracted with public remains',{publicKinds:Array(6).fill('r')});
await scenario('absent state',{stateExists:false});
for(const phase of ['expanded','cutover','rolled_back','unexpected'])await scenario('absent public wrong phase '+phase,{phase});
for(let i=0;i<6;i++) {const k=Array(6).fill(null);k[i]='r';await scenario('partial public '+i,{publicKinds:k});const o=Array(6).fill('r');o[i]=null;await scenario('missing owned '+i,{ownedKinds:o});}
for(const kind of ['v','m','f','S','i']) {await scenario('public wrong kind '+kind,{publicKinds:['r','r',kind,'r','r','r'],phase:'expanded'});await scenario('owned wrong kind '+kind,{ownedKinds:['r','r',kind,'r','r','r']});}
await scenario('short public catalog',{publicKinds:Array(5).fill(null)});
await scenario('long public catalog',{publicKinds:Array(7).fill(null)});
await scenario('short owned catalog',{ownedKinds:Array(5).fill('r')});
await scenario('long owned catalog',{ownedKinds:Array(7).fill('r')});
await scenario('host denied before query',{host:'hosted.invalid'});
await scenario('catalog error preserved',{throwRead:true});
console.log(JSON.stringify({mode:'ACTUAL_SELECTOR_WITH_PURE_CATALOG_STUB_NO_DATABASE',passed:results.length,results},null,2));
