import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import { BILLING_LOCK_SNAPSHOT_SQL, runBillingObservationReapply, summarizeBillingLockRows } from '../scripts/billing_checkout_deadlock_diagnostic.mjs';

const url = 'postgresql://postgres:synthetic-private@127.0.0.1:51001/postgres';
const sql = 'begin; /* unchanged synthetic observation */ commit;';
const rows = () => [{ pid: 11, backend_type: 'client backend', state: 'active', wait_event_type: 'Lock',
  query_start: new Date('2026-10-11T00:00:00Z'), observed_at: new Date('2026-10-11T00:00:01Z'),
  query_prefix: "SELECT pg_get_viewdef(1); -- synthetic-private-query-canary", blocker_count: 1, blockers: [22],
  locks: [{ locktype:'relation', mode:'AccessExclusiveLock', granted:false, database:5, relation:17,
    transactionid:null, schema_name:'backend_system', relation_name:'annual_checkout_observation_work' }] },
  { pid:22, backend_type:'background worker', state:'active', wait_event_type:'Lock',
    query_start:new Date('2026-10-11T00:00:00Z'), observed_at:new Date('2026-10-11T00:00:01Z'),
    query_prefix:'UPDATE synthetic-private-table SET secret=1', blocker_count:1, blockers:[11],
    locks:[{ locktype:'transactionid', mode:'ShareLock', granted:false, transactionid:'42' }] }];

function fixture({ primaryFailure, snapshotFailure, identityChange, setupFailure, closeFailure, sameObserver = false } = {}) {
  const events = [], configs = [];
  const primaryStream = { remoteAddress:'127.0.0.1', remotePort:51001, destroy(){ events.push('primary-destroy'); } };
  const primary = { processID:11, connectionParameters:{host:'127.0.0.1',port:51001,database:'postgres'},
    connection:{stream:primaryStream}, async query(statement){
      events.push('primary-query'); assert.equal(statement,sql);
      await new Promise(resolve => setTimeout(resolve, 5));
      if (primaryFailure !== undefined) throw primaryFailure;
      return { rows:[{ original:true }] };
    }, async end(){ events.push('primary-end'); } };
  class Observer extends EventEmitter {
    constructor(){ super();this.connection={stream:{remoteAddress:'127.0.0.1',remotePort:51001,
      destroy(){events.push('observer-destroy');}}}; }
    async connect(){events.push('observer-connect');if(setupFailure)throw new Error('synthetic-private-setup');}
    async query(configuration,parameters){
      const statement=typeof configuration==='string'?configuration:configuration.text;
      parameters ??= configuration.values;
      assert.deepEqual(parameters,[11]);
      if(statement!==BILLING_LOCK_SNAPSHOT_SQL){
        events.push('identity');return {rows:[{pid:22,database_name:'postgres',database_oid:5,
          server_started_at:new Date('2026-10-10T00:00:00Z'),primary_present:true,...identityChange}]};
      }
      events.push('snapshot');if(snapshotFailure)throw new Error('synthetic-private-snapshot');return{rows:rows()};
    }
    async end(){events.push('observer-end');if(closeFailure)throw new Error('synthetic-private-close');}
  }
  const observer = new Observer();
  return {primary,observer,events,configs,factory(config){configs.push(config);return sameObserver?primary:observer;}};
}

function capture(t){ const output=[];t.mock.method(console,'error',value=>output.push(value));return output; }

 test('bounded lock classifier retains a cycle and technical labels without raw private metadata',()=>{
  const input=rows();input[0].application_name='synthetic-private-app';input[0].username='synthetic-private-user';
  const result=summarizeBillingLockRows(input);const text=JSON.stringify(result);
  assert.deepEqual(result.map(row=>[row.pid,row.blockers]),[[11,[22]],[22,[11]]]);
  assert.equal(result[0].locks[0].relation,'backend_system.annual_checkout_observation_work');
  assert.deepEqual(result[0].catalogReaders,['pg_get_viewdef']);assert.equal(result[0].queryCommand,'SELECT');
  assert.match(result[0].queryPrefixSha256,/^[a-f0-9]{64}$/);
  for(const value of ['synthetic-private-query-canary','synthetic-private-table','synthetic-private-app','synthetic-private-user'])assert(!text.includes(value));
 });

for(const mutation of ['rows-overflow','locks-overflow','blockers-overflow','query-overflow','null-lock']){
  test(`classifier refuses ${mutation} within fixed bounds`,()=>{
    let input=rows();
    if(mutation==='rows-overflow')input=Array.from({length:10},()=>input[0]);
    if(mutation==='locks-overflow')input[0].locks=Array.from({length:9},()=>input[0].locks[0]);
    if(mutation==='blockers-overflow')input[0].blockers=Array.from({length:9},()=>22);
    if(mutation==='query-overflow')input[0].query_prefix='private'.repeat(700);
    if(mutation==='null-lock')input[0].locks=[null];
    assert.throws(()=>summarizeBillingLockRows(input),{message:'billing_deadlock_metadata_unavailable'});
  });
}

test('unknown labels and nonnumeric IDs cannot echo supplied values',()=>{
  const input=rows();Object.assign(input[0],{pid:'private-pid',backend_type:'private-backend',state:'private-state',wait_event_type:'private-wait',blockers:['private-pid']});
  Object.assign(input[0].locks[0],{mode:'private-mode',schema_name:'private-schema',relation_name:'private-relation',transactionid:{toString(){throw new Error('private-coercion');}}});
  const result=summarizeBillingLockRows(input)[0];assert.equal(result.pid,null);assert.deepEqual(result.blockers,[]);
  assert.equal(result.locks[0].transactionId,null);assert.equal(result.locks[0].relation,'unclassified');
  assert(!JSON.stringify(result).includes('private-'));
});

test('original deadlock error is propagated after sampler and independent observer drain',async t=>{
  const output=capture(t), failure=Object.assign(new Error('original-synthetic-private-error'),{code:'40P01'});
  const value=fixture({primaryFailure:failure});
  await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),error=>error===failure);
  assert.equal(value.events.filter(x=>x==='primary-query').length,1);assert(value.events.includes('snapshot'));
  assert.equal(value.events.at(-1),'observer-end');assert(!value.events.includes('primary-end'));
  assert(!value.events.includes('primary-destroy'));assert.equal(output.length,1);
  const report=JSON.parse(output[0].replace('billing_checkout_deadlock_diagnostic ',''));
  assert.equal(report.stage,'observation-reapply');assert.equal(report.snapshots.length,1);
  assert.equal(report.snapshots[0].completedBeforeSettlement,true);
  assert(!output[0].includes('synthetic-private'));assert(!output[0].includes(url));
  assert.equal(value.configs[0].connectionTimeoutMillis,1000);assert.equal(value.configs[0].query_timeout,500);
  assert.equal(value.configs[0].statement_timeout,250);assert.equal(value.configs[0].lock_timeout,100);
});

test('successful primary remains quiet and observer closes before return',async t=>{
  const output=capture(t),value=fixture();
  assert.deepEqual(await runBillingObservationReapply(value.primary,url,sql,value.factory),{rows:[{original:true}]});
  assert.deepEqual(output,[]);assert.equal(value.events.at(-1),'observer-end');
});

for(const problem of ['setup','snapshot','identity']){
  test(`${problem} observer failure does not mask original deadlock or leak observer`,async t=>{
    const output=capture(t), failure=Object.assign(new Error('original-private'),{code:'40P01'});
    const value=fixture({primaryFailure:failure,setupFailure:problem==='setup',snapshotFailure:problem==='snapshot',
      identityChange:problem==='identity'?{database_name:'unrelated-private-database'}:undefined});
    await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),error=>error===failure);
    assert.equal(value.events.filter(event=>event==='observer-end').length,1);assert(!output[0].includes('private'));
    assert.equal(JSON.parse(output[0].replace('billing_checkout_deadlock_diagnostic ','')).unavailable,true);
    if(problem==='identity')assert(!value.events.includes('snapshot'));
  });
}

test('cannot close or sample the primary through an invalid observer factory',async t=>{
  capture(t);const value=fixture({sameObserver:true});
  await runBillingObservationReapply(value.primary,url,sql,value.factory);
  assert(!value.events.includes('primary-end'));assert(!value.events.includes('primary-destroy'));
  assert(!value.events.includes('snapshot'));
});

test('non-deadlock original failure is unchanged and produces no diagnostic text',async t=>{
  const output=capture(t),failure=Object.assign(new Error('private-original'),{code:'55P03'}),value=fixture({primaryFailure:failure});
  await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),error=>error===failure);
  assert.deepEqual(output,[]);assert.equal(value.events.at(-1),'observer-end');
});

test('cleanup failure disconnects only owned observer and denies successful acceptance',async t=>{
  capture(t);const value=fixture({closeFailure:true});
  await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),{message:'billing_deadlock_observer_cleanup_unavailable'});
  assert(value.events.includes('observer-destroy'));assert(!value.events.includes('primary-destroy'));
});

test('cleanup failure preserves the original deadlock error',async t=>{
  const output=capture(t),failure=Object.assign(new Error('original-private'),{code:'40P01'}),value=fixture({closeFailure:true,primaryFailure:failure});
  await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),error=>error===failure);
  assert(value.events.includes('observer-destroy'));assert(!output[0].includes('original-private'));
  assert.equal(JSON.parse(output[0].replace('billing_checkout_deadlock_diagnostic ','')).cleanupFailure,true);
});

for(const unsafe of ['postgresql://postgres@other.example/postgres','postgresql://postgres@127.0.0.1:51001/other','postgresql://postgres@127.0.0.1:51001/postgres?host=other.example','postgresql://postgres@127.0.0.1:51002/postgres']){
  test('unsafe or mismatched target refuses before migration/observer access',async()=>{
    const value=fixture();await assert.rejects(runBillingObservationReapply(value.primary,unsafe,sql,value.factory),{
      message:'billing_deadlock_diagnostic_requires_same_disposable_loopback_target'});assert.deepEqual(value.events,[]);
  });
}

test('close deadline drains timer and disconnects only owned observer',async t=>{
  capture(t);t.mock.timers.enable({apis:['setTimeout']});const value=fixture();
  value.primary.query=async statement=>{assert.equal(statement,sql);return{rows:[]};};
  value.observer.end=()=>new Promise(()=>{});
  const pending=runBillingObservationReapply(value.primary,url,sql,value.factory);
  const rejection=assert.rejects(pending,{message:'billing_deadlock_observer_cleanup_unavailable'});
  await new Promise(resolve=>setImmediate(resolve));t.mock.timers.tick(1000);await rejection;
  assert(value.events.includes('observer-destroy'));assert(!value.events.includes('primary-destroy'));
});

test('sampling stops at sixty attempts and bounded snapshots even while primary is pending',async t=>{
  const output=capture(t);t.mock.timers.enable({apis:['setTimeout']});const value=fixture();let finish, samples=0;
  value.primary.query=()=>new Promise((_,reject)=>{finish=reject;});
  const originalQuery=value.observer.query.bind(value.observer);
  value.observer.query=async(statement,parameters)=>{
    const result=await originalQuery(statement,parameters);
    if((statement.text??statement)===BILLING_LOCK_SNAPSHOT_SQL){samples+=1;result.rows[0].query_prefix+=' variation'+samples;}
    return result;
  };
  const failure=Object.assign(new Error('private-original'),{code:'40P01'});
  const pending=runBillingObservationReapply(value.primary,url,sql,value.factory);
  const rejected=assert.rejects(pending,error=>error===failure);
  await new Promise(resolve=>setImmediate(resolve));
  for(let i=0;i<65;i+=1){t.mock.timers.tick(100);await new Promise(resolve=>setImmediate(resolve));}
  assert.equal(samples,60);
  assert.equal(value.events.filter(event=>event==='observer-end').length,1);
  finish(failure);await rejected;
  const report=JSON.parse(output[0].replace('billing_checkout_deadlock_diagnostic ',''));
  assert.equal(report.snapshots.length,16);assert(Buffer.byteLength(output[0])<65536);
  assert.equal(value.events.at(-1),'observer-end');assert(!output[0].includes('private-original'));
});

test('cancellation reason is preserved and all observer work settles before rejection',async t=>{
  const output=capture(t),failure=new DOMException('synthetic-private-cancel','AbortError');
  const value=fixture({primaryFailure:failure});
  await assert.rejects(runBillingObservationReapply(value.primary,url,sql,value.factory),error=>error===failure);
  assert.equal(value.events.at(-1),'observer-end');assert.deepEqual(output,[]);
});

test('a falsy thrown primary value is never converted to success',async t=>{
  capture(t);const value=fixture({primaryFailure:null});let caught=false;
  try{await runBillingObservationReapply(value.primary,url,sql,value.factory);}catch(error){assert.equal(error,null);caught=true;}
  assert(caught);assert.equal(value.events.at(-1),'observer-end');
});

test('six-second elapsed budget stops acquisition before another snapshot',async t=>{
  const {performance}=await import('node:perf_hooks');capture(t);let calls=0;
  t.mock.method(performance,'now',()=>calls++===0?0:6001);
  const value=fixture();await runBillingObservationReapply(value.primary,url,sql,value.factory);
  assert(!value.events.includes('snapshot'));
  assert.equal(value.events.filter(event=>event==='observer-end').length,1);
});

test('classifier accepts exact metadata cardinalities and never expands unknown relation names',()=>{
  const input=Array.from({length:9},(_,i)=>({...rows()[0],pid:i+1,
    blockers:Array.from({length:8},(_,j)=>j+20),locks:Array.from({length:8},()=>({...rows()[0].locks[0],relation_name:'synthetic-private-table-canary'}))}));
  const result=summarizeBillingLockRows(input);assert.equal(result.length,9);
  assert(result.every(row=>row.locks.length===8&&row.blockers.length===8));
  assert(!JSON.stringify(result).includes('synthetic-private-table-canary'));
});

test('elapsed-budget expiry closes observer while primary remains pending and closes only once',async t=>{
  const {performance}=await import('node:perf_hooks');const output=capture(t);let calls=0,finish;
  t.mock.method(performance,'now',()=>calls++===0?0:6001);
  const value=fixture();value.primary.query=()=>new Promise((_,reject)=>{finish=reject;});
  const failure=Object.assign(new Error('private-primary-still-pending'),{code:'40P01'});
  const pending=runBillingObservationReapply(value.primary,url,sql,value.factory);
  const rejected=assert.rejects(pending,error=>error===failure);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(value.events.filter(event=>event==='observer-end').length,1);
  assert(!value.events.includes('primary-end'));assert(!value.events.includes('primary-destroy'));
  finish(failure);await rejected;
  assert.equal(value.events.filter(event=>event==='observer-end').length,1);
  assert(!output[0].includes('private-primary-still-pending'));
});

test('last snapshot read timeout cannot exceed remaining sampling budget',async t=>{
  const {performance}=await import('node:perf_hooks');capture(t);let calls=0,timeout;
  t.mock.method(performance,'now',()=>calls++===0?0:5990);
  const value=fixture(),query=value.observer.query.bind(value.observer);
  value.observer.query=async(configuration,parameters)=>{
    if(configuration.text===BILLING_LOCK_SNAPSHOT_SQL)timeout=configuration.query_timeout;
    return query(configuration,parameters);
  };
  await runBillingObservationReapply(value.primary,url,sql,value.factory);
  assert.equal(timeout,10);assert.equal(value.events.filter(event=>event==='observer-end').length,1);
});

test('setup failure closes observer before beginning unchanged primary statement',async t=>{
  capture(t);const value=fixture({setupFailure:true});
  await runBillingObservationReapply(value.primary,url,sql,value.factory);
  assert(value.events.indexOf('observer-end')<value.events.indexOf('primary-query'));
  assert.equal(value.events.filter(event=>event==='observer-end').length,1);
});
