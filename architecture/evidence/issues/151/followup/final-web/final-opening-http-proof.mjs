// Run only after the exclusive disposable-database owner releases it.
import assert from 'node:assert/strict';
import { createHash,randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFileSync,writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const root=process.cwd();
const require=createRequire(root+'/package.json');
const pg=require('pg');
const {createClient}=require('@supabase/supabase-js');
const {startWorkspaceRfApi,seedHistoricalRfOpening,rfFixtureTransaction,apiRequest}=await import(pathToFileURL(root+'/tests/support/rf1086-workspace-api.mjs'));
const {fixtureTableTransaction,deleteRfFixtureCompanies}=await import(pathToFileURL(root+'/tests/support/rf1086-fixture-access.mjs'));
const {isLoopbackPostgresUrl,isLoopbackSupabaseUrl}=await import(pathToFileURL(root+'/tests/support/supabase_fixture_safety.mjs'));
assert.ok(isLoopbackPostgresUrl(process.env.DATABASE_URL));assert.ok(isLoopbackSupabaseUrl(process.env.SUPABASE_URL));
const report={scope:'Synthetic local final-schema source fixture; actual local Supabase Auth and shipped FastAPI/SupabaseLedgerSession reads. No provider operations or statutory filing evidence.',startedAt:new Date().toISOString(),passed:false,checks:[],sourceHashes:{}};
for(const file of ['apps/backend/src/talli_backend/main.py','apps/backend/src/talli_backend/adapters/supabase_ledger.py','tests/support/rf1086-workspace-api.mjs','tests/support/rf1086-fixture-access.mjs','tests/fixtures/start_rf1086_workspace_backend.py','tests/fixtures/start_talli_backend.py','supabase/migrations/20260909190548_shareholder_register_filing_capability.sql','supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql','supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql'])report.sourceHashes[file]=createHash('sha256').update(readFileSync(root+'/'+file)).digest('hex');
const database=new pg.Client({connectionString:process.env.DATABASE_URL});await database.connect();
const admin=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_SERVICE_ROLE_KEY,{auth:{persistSession:false,autoRefreshToken:false}});
const users=[];const companies=[];let api;let primary;
try {
 const {rows:[topology]}=await database.query(`select to_regclass('public.opening_balance_setups') is null opening_absent,
  to_regclass('public.opening_shareholders') is null holders_absent,
  not exists(select 1 from pg_attribute where attrelid='ledger.entries'::regclass and attname='setup_id' and not attisdropped) ledger_link_absent,
  (select phase from shareholder_register_filing.migration_state where singleton) phase`);
 assert.equal(topology.opening_absent,true);assert.equal(topology.holders_absent,true);assert.equal(topology.ledger_link_absent,true);assert.equal(topology.phase,'contracted');report.topology=topology;
 for(let index=0;index<2;index++) {
  const password='Local-'+randomUUID()+'!';const email='rf-final-read-'+randomUUID()+'@example.test';
  const {data,error}=await admin.auth.admin.createUser({email,password,email_confirm:true});assert.ifError(error);
  const user={id:data.user.id,client:createClient(process.env.SUPABASE_URL,process.env.SUPABASE_ANON_KEY,{auth:{persistSession:false,autoRefreshToken:false}})};users.push(user);
  assert.ifError((await user.client.auth.signInWithPassword({email,password})).error);
  const id=randomUUID();companies.push(id);
  assert.ifError((await admin.from('companies').insert({id,org_number:String(100000000+Math.floor(Math.random()*899999999)),name:'Synthetic final opening read',entity_type:'AS',created_by:user.id})).error);
  assert.ifError((await admin.from('company_memberships').insert({company_id:id,user_id:user.id,role:'owner',invited_by:user.id,accepted_at:new Date().toISOString()})).error);
 }
 const setup=await seedHistoricalRfOpening(database,companies[0],users[0].id,{shareCapital:30000,shareCount:100,nominalValue:300,bankBalance:31000,shareholders:[{name:'Synthetic holder',shareholderKind:'norwegian_person',nationalId:'01017012345',shareCount:100}]});
 const url=new URL(process.env.DATABASE_URL);
 api=await startWorkspaceRfApi(database,{host:url.hostname,port:Number(url.port),database:url.pathname.slice(1),user:decodeURIComponent(url.username),password:decodeURIComponent(url.password)});
 const all=await api.client.ledgerListOpeningSnapshots(await apiRequest(users[0].client,{companyIds:[companies[0]]}));
 assert.equal(all.items.length,1);assert.equal(all.hasMore,false);assert.equal(all.items[0].setupId,setup);assert.equal(all.items[0].companyId,companies[0]);assert.equal(all.items[0].incomeYear,2025);
 assert.equal(all.items[0].bankBalance.amount,'31000.00');assert.equal(all.items[0].shareCapital.amount,'30000.00');assert.equal(all.items[0].shareholders.length,1);
 report.checks.push('Actual authenticated all-year HTTP read returns exact RF share identity plus independently stored Ledger bank amount');
 const year=await api.client.ledgerListOpeningSnapshotsForYear(await apiRequest(users[0].client,{companyId:companies[0],incomeYear:2025}));
 assert.deepEqual(year,all);report.checks.push('Actual year-scoped HTTP read equals the supported source row with complete identity and provenance');
 const otherYear=await api.client.ledgerListOpeningSnapshotsForYear(await apiRequest(users[0].client,{companyId:companies[0],incomeYear:2024}));
 assert.deepEqual(otherYear.items,[]);assert.equal(otherYear.hasMore,false);report.checks.push('Unselected income year returns no source row');
 for(const method of ['all','year']) {
  const concealed=method==='all'?await api.client.ledgerListOpeningSnapshots(await apiRequest(users[1].client,{companyIds:[companies[0]]})):await api.client.ledgerListOpeningSnapshotsForYear(await apiRequest(users[1].client,{companyId:companies[0],incomeYear:2025}));
  assert.deepEqual(concealed.items,[]);assert.equal(concealed.hasMore,false);
 }
 report.checks.push('Independent authenticated owner cannot enumerate the first company in either HTTP read');
 const priorMembership=(await database.query(`select m.admin_option,m.inherit_option,m.set_option from pg_auth_members m
  join pg_roles r on r.oid=m.roleid where r.rolname='ledger_executor' and m.member=(select oid from pg_roles where rolname=current_user)
  and m.grantor=m.member`)).rows;
 await database.query('begin');
 try {
  if(!(await database.query("select pg_has_role(current_user,'ledger_executor','SET') allowed")).rows[0].allowed)
   await database.query('grant ledger_executor to postgres with set true granted by postgres');
  await database.query('set local role ledger_executor');
  await database.query("select set_config('talli.verified_actor_id',$1,true),set_config('talli.verified_actor_claims',$2,true)",[users[0].id,JSON.stringify({sub:users[0].id,role:'authenticated',aal:'aal2'})]);
  const {rows:[authority]}=await database.query(`select has_function_privilege(current_user,'ledger.record_opening_bank_input_v1(uuid,uuid,integer,numeric,text)','EXECUTE') can_write,
   has_table_privilege(current_user,'ledger.opening_bank_inputs','SELECT') direct_bank_read,
   has_table_privilege(current_user,'ledger.opening_bank_inputs','INSERT') direct_bank_write`);
  assert.deepEqual(authority,{can_write:false,direct_bank_read:false,direct_bank_write:false});
  await assert.rejects(database.query('select * from ledger.record_opening_bank_input_v1($1,$2,2025,31000,$3)',[setup,companies[0],users[0].id]),error=>error.code==='42501');
 } finally {await database.query('rollback');}
 assert.deepEqual((await database.query(`select m.admin_option,m.inherit_option,m.set_option from pg_auth_members m
  join pg_roles r on r.oid=m.roleid where r.rolname='ledger_executor' and m.member=(select oid from pg_roles where rolname=current_user)
  and m.grantor=m.member`)).rows,priorMembership);
 report.checks.push('ledger_executor cannot execute the opening-bank writer or directly read/write the owned bank table');
 report.passed=true;
} catch(error){primary=error;report.failure={name:error.name,code:error.code??null};}
finally {
 const cleanupErrors=[];
 const attempt=async fn=>{try{await fn();}catch(error){cleanupErrors.push(error);}};
 if(api)await attempt(()=>api.close());
 if(companies.length) {
  await attempt(()=>rfFixtureTransaction(database,async()=>{
   for(const relation of ['shareholder_register_filing.opening_shareholders','shareholder_register_filing.opening_balance_setups','shareholder_register_filing.migration_inventory','shareholder_register_filing.migration_quarantine','ledger.opening_bank_inputs'])await database.query(`delete from ${relation} where company_id=any($1::uuid[])`,[companies]);
  }));
  await attempt(()=>fixtureTableTransaction(database,['public.audit_events','public.customer_agreement_acceptances','public.company_memberships','public.companies','public.company_archive_source_generations'],async()=>{
   for(const table of ['audit_events','customer_agreement_acceptances','company_memberships','company_archive_source_generations'])await database.query(`delete from public.${table} where company_id=any($1::uuid[])`,[companies]);
   await deleteRfFixtureCompanies(database,companies);
  }));
 }
 for(const user of users)await attempt(async()=>{await user.client.auth.signOut();assert.ifError((await admin.auth.admin.deleteUser(user.id)).error);});
 await attempt(async()=>{assert.equal((await database.query('select count(*)::int count from public.companies where id=any($1::uuid[])',[companies])).rows[0].count,0);});
 report.cleanup={passed:cleanupErrors.length===0,errorNames:cleanupErrors.map(error=>error.name)};
 if(cleanupErrors.length)report.passed=false;
 await database.end();report.finishedAt=new Date().toISOString();
 writeFileSync('/tmp/talli-151-final-opening-http-proof.json',JSON.stringify(report,null,2)+'\n',{mode:0o600});
 console.log(JSON.stringify({passed:report.passed,checks:report.checks.length,cleanup:report.cleanup.passed,receipt:'/tmp/talli-151-final-opening-http-proof.json'}));
 if(primary||cleanupErrors.length)process.exitCode=1;
}
