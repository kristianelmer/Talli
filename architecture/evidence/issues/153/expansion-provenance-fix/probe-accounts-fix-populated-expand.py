from pathlib import Path
import hashlib,json,psycopg,sys
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
sys.path.insert(0,str(Path.cwd()/'apps/backend/tests'))
from accounts_database_fixtures import seed,FAMILIES,ACTORS,COMPANY,IDS,insert
p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry');dsn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
path=Path('supabase/contract-migrations/20260914090244_annual_accounts_filing_expand.sql');raw=path.read_text();assert raw.startswith('-- #153') and raw.endswith('commit;\n')
script=raw.replace('begin;\n','',1)[:-len('commit;\n')]
report={'artifact':str(path),'sha256':hashlib.sha256(raw.encode()).hexdigest(),'database':c['dbname'],'transaction':'ROLLBACK_ONLY','cases':[]}
with psycopg.connect(dsn,autocommit=True) as db:
 db.execute('begin')
 try:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  rows=seed(db)
  quarantined_ids=[]
  if '--quarantine' in sys.argv:
   unknown='15300000-0000-4000-8000-000000000080'
   comment='15300000-0000-4000-8000-000000000081'
   insert(db,'public','filing_previews',dict(rows['filing_previews'],id=unknown,filing='unrecognized_synthetic_obligation'))
   insert(db,'public','filing_review_comments',dict(rows['filing_review_comments'],id=comment,preview_id=unknown))
   quarantined_ids=[unknown,comment]
  before={f:db.execute(sql.SQL('select to_jsonb(t)::text from public.{} t order by id').format(sql.Identifier(f))).fetchall() for f in FAMILIES}
  members=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
  old_roles=[r[0] for r in db.execute('select oid from pg_roles').fetchall()]
  db.execute(script,prepare=False)
  after_members=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members where roleid=any(%s) order by 1,2,3',(old_roles,)).fetchall()
  assert after_members==members,'existing role memberships changed'
  for f in FAMILIES:
   after=db.execute(sql.SQL('select to_jsonb(t)::text from public.{} t order by id').format(sql.Identifier(f))).fetchall()
   assert after==before[f],f
  reconciliations=db.execute('select family,source_count,target_count,source_digest=target_digest from backend_system.annual_accounts_reconciliations order by family').fetchall()
  assert len(reconciliations)==6 and all(c==sum(json.loads(row[0])['id'] not in quarantined_ids for row in before[f]) and t==c and match for f,c,t,match in reconciliations)
  quarantine=db.execute('select source_id::text,payload,source_sha256 from backend_system.annual_accounts_quarantine order by source_id').fetchall()
  assert [r[0] for r in quarantine]==quarantined_ids
  for source_id,payload,digest in quarantine:
   assert any(json.loads(row[0])==payload for values in before.values() for row in values)
   assert db.execute("select encode(extensions.digest(%s::jsonb::text,'sha256'),'hex')",(json.dumps(payload),)).fetchone()[0]==digest
  report['quarantineRowsPreserved']=len(quarantine)
  report['reconciliations']=reconciliations;report['legacyRowsUnchanged']=True;report['existingRoleMembershipsUnchanged']=True
  # Test-only SET privileges, after proving migration restored memberships.
  # These grants are rolled back and are not part of the migration artifact.
  runner=db.execute('select current_user').fetchone()[0]
  db.execute(sql.SQL('grant annual_accounts_filing_store_owner,annual_accounts_filing_workflow_executor to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
  report['roleProbeSetup']='Temporary test-only SET after membership restoration check; rolled back.'
  db.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({'sub':ACTORS['owner'],'role':'authenticated','aal':'aal2'}),))
  for role in ([] if quarantined_ids else ['anon','authenticated','service_role','annual_accounts_filing_workflow_executor','annual_accounts_filing_store_owner']):
   for f in FAMILIES:
    for operation in ['read','insert']:
     db.execute('savepoint probe')
     try:
      db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
      if operation=='read':outcome={'count':db.execute(sql.SQL('select count(*) from annual_accounts_filing.{}').format(sql.Identifier(f))).fetchone()[0]}
      else:
       row=dict(rows[f],id='15300000-0000-4000-8000-000000000100')
       insert(db,'annual_accounts_filing',f,row);outcome={'inserted':True}
     except psycopg.Error as e:outcome={'sqlstate':e.sqlstate,'error':e.diag.message_primary}
     finally:db.execute('rollback to savepoint probe');db.execute('release savepoint probe')
     assert outcome=={'count':0} if role=='annual_accounts_filing_store_owner' and operation=='read' else outcome.get('sqlstate')=='42501',(role,f,operation,outcome)
     report['cases'].append({'role':role,'family':f,'operation':operation,'outcome':outcome})
  # Original accepted owner can still write the legacy preview after expansion.
  db.execute('set local role authenticated');candidate=dict(rows['filing_previews'],id='15300000-0000-4000-8000-000000000101')
  insert(db,'public','filing_previews',candidate);db.execute('reset role')
  report['legacyWriterStillActive']=True
  # Classifier is migration-local and every adversarial probe leaves source rows unchanged.
  for family,alteration in [('filing_previews',{'filing':'unknown_obligation'}),('authority_test_runs',{'obligation':'unknown'}),('filing_review_comments',{'preview_id':None}),('filing_overrides',{'field_target':'skattemelding.field'}),('filing_submissions',{'company_id':ACTORS['outsider']}),('filing_submissions',{'income_year':2024}),('filing_submissions',{'authority_test_run_id':ACTORS['outsider']})]:
   value=dict(rows[family],**alteration)
   classified=db.execute('select pg_temp.accounts153_classify(%s,%s::jsonb)',(family,json.dumps(value))).fetchone()[0]
   assert classified=='quarantine';report['cases'].append({'classificationProbe':family,'alteration':alteration,'result':classified})
  report['status']='PASS'
 except Exception as error:
  report['status']='FAIL';report['error']=str(error);report['sqlstate']=getattr(error,'sqlstate',None)
 finally:
  if db.closed:
   db=psycopg.connect(dsn,autocommit=True)
  else:
   db.execute('rollback')
  report['fixtureRollbackVerified']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0
  report['schemaRollbackVerified']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':sys.exit(1)
