from pathlib import Path
import hashlib,json,sys,psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
p=Path(__file__).parent;snapshot=p/'spec-physical-sql-fixed';sys.path.insert(0,str(snapshot/'apps/backend/tests'))
from accounts_database_fixtures import seed,ACTORS,COMPANY,IDS
config=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text());dsn=config['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
files=['20260914090244_annual_accounts_filing_expand.sql','20260914092018_annual_accounts_filing_read_contracts.sql','20260914092924_annual_accounts_filing_preparation_contracts.sql','20260914093204_annual_accounts_filing_import_contract.sql','20260914101625_annual_accounts_filing_dependency_contracts.sql','20260914101805_annual_accounts_filing_cutover.sql'];report={'database':c['dbname'],'mode':'ROLLBACK_ONLY_FROZEN_WIP_PUBLIC_RLS_ROLLBACK_DRIFT','artifacts':{f:hashlib.sha256((snapshot/'supabase/contract-migrations'/f).read_bytes()).hexdigest()for f in files},'cases':[]}
with psycopg.connect(dsn,autocommit=True) as db:
 memberships=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall();schemas=db.execute("select nspname,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall();runner=db.execute('select current_user').fetchone()[0];assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];db.execute('begin')
 try:
  seed(db)
  for f in files[:-1]:
   raw=(snapshot/'supabase/contract-migrations'/f).read_text();assert raw.endswith('commit;\n');db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
  db.execute(sql.SQL('grant annual_accounts_filing_store_owner,annual_accounts_filing_workflow_executor to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
  raw=(snapshot/'supabase/contract-migrations'/files[-1]).read_text();db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
  db.execute('alter table public.filing_previews disable row level security')
  rollback=snapshot/'supabase/rollback/20260914101805_annual_accounts_filing_cutover.sql'
  report['rollbackSha256']=hashlib.sha256(rollback.read_bytes()).hexdigest()
  raw=rollback.read_text();db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
  report['rollbackOutcome']='COMPLETED_DESPITE_DISABLED_PUBLIC_RLS'
  report['publicRls']=db.execute("select relrowsecurity from pg_class where oid='public.filing_previews'::regclass").fetchone()[0]
  db.execute(sql.SQL('grant authenticated to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
  def call(actor):
   subject=ACTORS[actor];claims={'sub':subject,'role':'authenticated','aal':'aal2'}
   for k,v in [('request.jwt.claims',json.dumps(claims)),('request.jwt.claim.sub',subject),('talli.verified_actor_id',subject),('talli.verified_actor_claims',json.dumps(claims))]:db.execute('select set_config(%s,%s,true)',(k,v))
   db.execute('set local role authenticated');value=db.execute('select count(*) from public.filing_previews where id=%s::uuid',(IDS['filing_previews'],)).fetchone()[0];db.execute('reset role');return value
  for actor in ['owner','outsider']:
   report['cases'].append({'actor':actor,'visibleRows':call(actor)})
  db.execute('alter table public.filing_previews enable row level security')
  report['restoredRlsOutsiderVisible']=call('outsider')
  assert report['cases'][1]['visibleRows']==1 and report['restoredRlsOutsiderVisible']==0
  report['status']='REPRODUCED_P2_PUBLIC_RLS_DRIFT_ACTIVATES_FOREIGN_READ_ON_ROLLBACK'
 except Exception as e:report.update(status='PASS_EXPECTED_DRIFT_REJECTION' if str(e).splitlines()[0]=='annual_accounts_rollback_source_schema_changed' else 'PROBE_ERROR',error=str(e),sqlstate=getattr(e,'sqlstate',None))
 finally:
  db.execute('rollback');report['schemaRollbackVerified']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];report['fixtureRollbackVerified']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0;report['globalMembershipsRestored']=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==memberships;report['sourceSchemaAclRestored']=db.execute("select nspname,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall()==schemas
(p/'physical-sql-spec-fixed-public-rls-results.json').write_text(json.dumps(report,indent=2,default=str)+'\n');print(json.dumps(report,indent=2));assert report['status']=='PASS_EXPECTED_DRIFT_REJECTION';assert all(report[k]for k in ['schemaRollbackVerified','fixtureRollbackVerified','globalMembershipsRestored','sourceSchemaAclRestored'])
