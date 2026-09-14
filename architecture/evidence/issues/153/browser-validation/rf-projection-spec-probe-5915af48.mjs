import assert from 'node:assert/strict';
import { rfPublicProjectionRelations } from './rf-projection-spec-snapshot-5915af48/tests/support/rf1086-fixture-access.mjs';
const names=['filing_review_comments','filing_overrides','filing_submissions','authority_test_runs','authority_permissions','filing_previews'];
const results=[];
for(const [label,opts,ok] of [
 ['legacy',{publicKind:'r',state:false},true],['expanded',{publicKind:'r',phase:'expanded'},true],
 ['contracted',{publicKind:null,phase:'contracted'},true],['partitioned_owned',{publicKind:null,phase:'contracted',ownedKind:'p'},true],
 ['contradictory_contract',{publicKind:'r',phase:'contracted'},false],['partial',{publicKind:null,partial:true,phase:'contracted'},false],
 ['missing_state',{publicKind:null,state:false},false],['no_phase_row',{publicKind:null,phase:null},false],
 ['public_view',{publicKind:'v',state:false},false],['owned_view',{publicKind:null,phase:'contracted',ownedKind:'v'},false],
 ['missing_owned',{publicKind:null,phase:'contracted',ownedKind:null},false],['remote',{host:'remote.invalid'},false]]) {
 const queries=[];
 const db={connectionParameters:{host:opts.host??'127.0.0.1'},query:async(sql,args=[])=>{
 queries.push(sql);
 if(sql.includes('unnest'))return {rows:args[0].map((name,i)=>({name,relkind:name.startsWith('public.')?(opts.partial&&i===0?'r':opts.publicKind):(Object.hasOwn(opts,'ownedKind')?opts.ownedKind:'r')}))};
 if(sql.includes('to_regclass'))return {rows:[{present:opts.state!==false}]};
 if(sql.startsWith('select phase'))return {rows:opts.phase===null?[]:[{phase:opts.phase}]};
 throw new Error('unexpected mutation or query');}};
 let result,error;try{result=await rfPublicProjectionRelations(db);}catch(e){error=e;}
 assert.equal(!error,ok,label);
 if(ok)assert.deepEqual(result,opts.publicKind===null?[]:names.map(n=>'public.'+n));
 assert.ok(queries.every(q=>q.startsWith('select ')));
 if(label==='remote')assert.equal(queries.length,0);
 results.push({label,passed:true,accepted:!error,queryCount:queries.length});
}
console.log(JSON.stringify({status:'PASS',count:results.length,scope:'Pinned actual selector with synthetic catalog responses; no database',results},null,2));
