from pathlib import Path
import sys,json,hashlib,psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
p=Path(__file__).parent;root=p/'spec-source-fix-900472a0';sys.path[:0]=[str(root/'apps/backend/tests'),str(root/'apps/backend/src')]
from test_annual_accounts_filing_lifecycle import EXPANSION,CUTOVER,CONTRACT,apply,actor,memberships,environment
from accounts_database_fixtures import seed,ACTORS,COMPANY,IDS
from test_annual_accounts_source_facts import parse
from talli_backend.modules.annual_accounts_filing.public import project_annual_accounts_source
c=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text());dsn=c['DB_URL'];guard=conninfo_to_dict(dsn)
assert guard['host'] in ('localhost','127.0.0.1') and guard['port']=='52966' and guard['dbname']=='accounts153_setup_fix_d060'
report={'revision':'900472a0ecfbf5e8d7fc4996f4f641e33575103c','mode':'ROLLBACK_ONLY_PREEXISTING_BINDING_ADMIN_OPTION','cases':[]}
artifact=root/'supabase/contract-migrations/20260914112549_annual_accounts_filing_backend_binding.sql'
report['bindingSha256']=hashlib.sha256(artifact.read_bytes()).hexdigest()
def binding(db):
 raw=artifact.read_text();db.execute(raw.replace('begin;\n','',1).removesuffix('commit;\n'),prepare=False)
def membership(db):
 return db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid='annual_accounts_filing_workflow_executor'::regrole and member='talli_ledger_backend'::regrole").fetchall()
with psycopg.connect(dsn,autocommit=True) as db:
 before=memberships(db);assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];db.execute('begin isolation level repeatable read')
 try:
  seed(db)
  for f in EXPANSION:apply(db,f)
  apply(db,CUTOVER)
  assert membership(db)==[]
  binding(db);assert membership(db)==[(False,False,True)];report['cases'].append({'case':'fresh membership','actual':membership(db),'status':'PASS'})
  db.execute('grant annual_accounts_filing_workflow_executor to talli_ledger_backend with admin true,inherit false,set true')
  assert membership(db)==[(True,False,True)]
  binding(db);report['cases'].append({'case':'existing admin membership','actual':membership(db),'expected':[(False,False,True)]})
  assert membership(db)==[(True,False,True)];report['status']='REPRODUCED_ADMIN_OPTION_RETAINED'
 finally:
  db.execute('rollback');report['globalMembershipsRestored']=memberships(db)==before;report['schemaRollbackVerified']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];report['fixtureRollbackVerified']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0
assert all(report[k]for k in ['globalMembershipsRestored','schemaRollbackVerified','fixtureRollbackVerified'])
(p/'source-fix-spec-binding-admin-900472a0.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
