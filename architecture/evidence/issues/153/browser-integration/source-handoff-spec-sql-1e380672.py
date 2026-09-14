from pathlib import Path
import sys,json,hashlib,psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
p=Path(__file__).parent;root=p/'spec-source-handoff-1e380672';sys.path[:0]=[str(root/'apps/backend/tests'),str(root/'apps/backend/src')]
from test_annual_accounts_filing_lifecycle import EXPANSION,CUTOVER,CONTRACT,apply,actor,memberships,environment
from accounts_database_fixtures import seed,ACTORS,COMPANY,IDS
from test_annual_accounts_source_facts import parse
from talli_backend.modules.annual_accounts_filing.public import project_annual_accounts_source
c=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text());dsn=c['DB_URL'];guard=conninfo_to_dict(dsn)
assert guard['host'] in ('localhost','127.0.0.1') and guard['port']=='52966' and guard['dbname']=='accounts153_setup_fix_d060'
report={'revision':'1e38067282e144996b455e428c267f6be3534421','mode':'ROLLBACK_ONLY_INDEPENDENT_SOURCE_CONTRACT','cases':[],'artifacts':{name:hashlib.sha256((root/'supabase/contract-migrations'/name).read_bytes()).hexdigest()for name in [*EXPANSION,CUTOVER,CONTRACT]}}
def observe(db,year=2025,name='owner'):
 with actor(db,name) as identity:
  raw=db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,%s,%s)',(COMPANY,year,identity)).fetchone()[0]
 query,snapshot=parse(raw);return project_annual_accounts_source(query,snapshot)
with psycopg.connect(dsn,autocommit=True) as db:
 before=memberships(db);schema_acl=db.execute("select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall()
 for mode in ['repeatable read','read committed']:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];db.execute('begin isolation level '+mode)
  try:
   seed(db)
   for f in EXPANSION:apply(db,f)
   apply(db,CUTOVER);apply(db,CONTRACT)
   if mode=='read committed':
    try:observe(db)
    except psycopg.Error as e:assert e.diag.message_primary=='annual_accounts_unavailable';report['cases'].append({'name':'read-committed rejected','result':'PASS'})
    else:raise AssertionError('read committed accepted')
   else:
    for year,count in [(2025,2),(2024,0)]:
     facts=observe(db,year);assert facts.history_coverage.status=='complete' and facts.history_coverage.submission_count==count and facts.production_attempts==() and facts.readiness_status=='blocked'
     report['cases'].append({'name':f'positive year {year}','result':'PASS','submissions':count,'coverage':'complete','production':'none in recorded extent','readiness':'blocked'})
    for name in ['reviewer','unaccepted','outsider']:
     try:observe(db,name=name)
     except psycopg.Error as e:assert e.diag.message_primary=='annual_accounts_not_found';report['cases'].append({'name':name+' denied','result':'PASS'})
     else:raise AssertionError('unauthorized source read')
    runner=db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant annual_accounts_filing_store_owner to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
    claims=json.dumps({'sub':ACTORS['owner'],'role':'authenticated','aal':'aal2'})
    db.execute("select set_config('request.jwt.claims',%s,true)",(claims,));db.execute("select set_config('talli.verified_actor_id',%s,true)",(ACTORS['owner'],));db.execute("select set_config('talli.verified_actor_claims',%s,true)",(claims,))
    for name,statement,reason in [('production-label',"update annual_accounts_filing.filing_submissions set adapter_mode='production' where id=%s",'production_journal_unavailable'),('retained-deletion','delete from annual_accounts_filing.filing_submissions where id=%s','retained_submission_history_missing')]:
     db.execute('savepoint mutation');db.execute('set local role annual_accounts_filing_store_owner');db.execute('create policy accounts_spec_mutation on annual_accounts_filing.filing_submissions for all to annual_accounts_filing_store_owner using(true) with check(true)');cur=db.execute(statement,(IDS['filing_submissions'],));assert cur.rowcount==1;db.execute('drop policy accounts_spec_mutation on annual_accounts_filing.filing_submissions');db.execute('reset role');facts=observe(db);assert facts.history_coverage.status=='incomplete' and reason in facts.history_coverage.reasons
     if name=='production-label':assert len(facts.production_attempts)==1 and facts.production_attempts[0].effect_status=='unknown'
     report['cases'].append({'name':name,'result':'PASS','reason':reason});db.execute('rollback to savepoint mutation');db.execute('release savepoint mutation')
  finally:
   db.execute('rollback');assert memberships(db)==before;assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];assert db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0;assert db.execute("select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall()==schema_acl
report.update(status='PASS',allTransactionsRolledBack=True,globalMembershipsRestored=True,schemaAndFixtureRestored=True,sourceSchemaAclRestored=True)
(p/'source-handoff-spec-sql-1e380672.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
