"""Owned disposable clone only; preserve role state and drop the created clone."""
from pathlib import Path
import concurrent.futures,hashlib,json,os,sys,time
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
root=Path.cwd();private=Path(__file__).parent
source=conninfo_to_dict(json.loads((private/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'])
assert source['host'] in ('localhost','127.0.0.1') and source['port']=='52966' and source['dbname']=='accounts153_setup_fix_d060'
target='accounts153_runtime_900472a0'
sys.path.insert(0,str(root/'apps/backend/tests'))
from test_annual_accounts_filing_lifecycle import apply,EXPANSION,CUTOVER,CONTRACT,COMPANY,memberships
from accounts_database_fixtures import seed,ACTORS
artifacts={n:hashlib.sha256((root/'supabase/contract-migrations'/n).read_bytes()).hexdigest() for n in (*EXPANSION,CUTOVER,CONTRACT)}
admin=psycopg.connect(make_conninfo(**{**source,'dbname':'postgres'}),autocommit=True)
prior=memberships(admin);runner=admin.execute('select current_user').fetchone()[0]
created=False;borrowed=False;reader=None
checks=[]
def connect():return psycopg.connect(make_conninfo(**{**source,'dbname':target}),autocommit=True)
def claims(db):
 identity=ACTORS['owner'];now=int(time.time())
 value=json.dumps({'sub':identity,'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':now}]})
 for key,data in [('request.jwt.claims',value),('talli.verified_actor_id',identity),('talli.verified_actor_claims',value)]:
  db.execute('select set_config(%s,%s,true)',(key,data))
 db.execute('set local role annual_accounts_filing_workflow_executor')
def read(db):return db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,2025,%s)',(COMPANY,ACTORS['owner'])).fetchone()[0]
def rollback_store():
 with connect() as db:
  db.execute('begin')
  apply(db,CONTRACT,rollback=True);apply(db,CUTOVER,rollback=True)
  db.execute('commit')
try:
 assert not admin.execute('select exists(select 1 from pg_database where datname=%s)',(target,)).fetchone()[0]
 admin.execute(sql.SQL('create database {} template {}').format(sql.Identifier(target),sql.Identifier(source['dbname'])));created=True
 with connect() as db:
  db.execute('begin');seed(db)
  for artifact in EXPANSION:apply(db,artifact)
  apply(db,CUTOVER);apply(db,CONTRACT);db.execute('commit')
 assert memberships(admin)==prior
 assert not admin.execute("select pg_has_role(current_user,'annual_accounts_filing_workflow_executor','SET')").fetchone()[0]
 admin.execute(sql.SQL('grant annual_accounts_filing_workflow_executor to {} with inherit false,set true,admin false granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)));borrowed=True
 reader=connect();reader.execute('begin isolation level repeatable read');claims(reader)
 result=read(reader);assert result['coverage']['phase']=='contracted'
 with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
  future=pool.submit(rollback_store)
  deadline=time.monotonic()+3
  while time.monotonic()<deadline:
   blocked=admin.execute("select exists(select 1 from pg_stat_activity where datname=%s and wait_event_type='Lock')",(target,)).fetchone()[0]
   if blocked:break
   assert not future.done();time.sleep(.02)
  assert blocked and not future.done()
  checks.append('source read holds phase lock and blocks concurrent rollback')
  reader.execute('rollback');future.result(timeout=8)
 reader.close();reader=None
 with connect() as db:
  assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0]=='rolled_back'
  db.execute('begin');apply(db,CUTOVER);apply(db,CONTRACT);db.execute('commit')
 reader=connect();reader.execute('begin isolation level repeatable read');reader.execute('select count(*) from public.companies');claims(reader)
 rollback_store()
 try:read(reader);raise AssertionError('stale snapshot accepted')
 except psycopg.Error as error:
  assert error.sqlstate=='40001' or error.diag.message_primary=='annual_accounts_unavailable'
  checks.append('stale repeatable snapshot cannot read source after rollback')
 reader.execute('rollback');reader.close();reader=None
 with connect() as db:
  db.execute('begin isolation level repeatable read');claims(db)
  try:read(db);raise AssertionError('rolled back source accepted')
  except psycopg.Error as error:assert error.diag.message_primary=='annual_accounts_unavailable'
  db.execute('rollback')
 checks.append('fresh source read unavailable after rollback')
finally:
 if reader is not None:reader.close()
 if borrowed:admin.execute(sql.SQL('revoke annual_accounts_filing_workflow_executor from {} granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
 if created:
  assert not admin.execute('select exists(select 1 from pg_stat_activity where datname=%s)',(target,)).fetchone()[0]
  admin.execute(sql.SQL('drop database {}').format(sql.Identifier(target)))
 assert memberships(admin)==prior
 admin.close()
report={'status':'PASS','mode':'OWNED_DISPOSABLE_CLONE_DROPPED','checks':checks,'artifacts':artifacts,'allGlobalMembershipsRestored':True}
(private/'accounts-runtime-concurrency.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS',len(checks),'phase concurrency checks; clone dropped and all global memberships restored')
