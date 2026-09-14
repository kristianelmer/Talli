from pathlib import Path
import hashlib,json,sys,psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
sys.path.insert(0,str(Path.cwd()/'apps/backend/tests'))
from accounts_database_fixtures import seed,FAMILIES,ACTORS,COMPANY,IDS
p=Path(__file__).parent;dsn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
paths=[Path('supabase/contract-migrations')/n for n in ['20260914090244_annual_accounts_filing_expand.sql','20260914092018_annual_accounts_filing_read_contracts.sql','20260914092924_annual_accounts_filing_preparation_contracts.sql','20260914093204_annual_accounts_filing_import_contract.sql','20260914101625_annual_accounts_filing_dependency_contracts.sql','20260914101805_annual_accounts_filing_cutover.sql','20260914101842_annual_accounts_filing_contract.sql']]+[Path('supabase/rollback/20260914101842_annual_accounts_filing_contract.sql'),Path('supabase/rollback/20260914101805_annual_accounts_filing_cutover.sql')]
paths += [paths[5],paths[6]]
report={'database':c['dbname'],'mode':'ROLLBACK_ONLY_REAL_FULL_ROLLBACK_SYNTHETIC_ROWS','artifacts':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths},'phases':[]}
with psycopg.connect(dsn,autocommit=True) as db:
 original=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
 schemas=db.execute("select nspname,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall();db.execute('begin')
 try:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];seed(db)
  for phase_index,path in enumerate(paths):
   schemas=db.execute("select nspname,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall()
   raw=path.read_text();assert raw.endswith('commit;\n');db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
   assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==original
   if path in paths[5:]: assert db.execute("select nspname,nspacl::text from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing') order by 1").fetchall()==schemas
   report['phases'].append({'artifact':str(path),'genericPresent':db.execute("select to_regclass('public.filing_submissions') is not null").fetchone()[0]})
   # Match real commit lifetime for temp tables while keeping all mutations
   # rollback-only. Temp functions may survive on the same real connection.
   for schema,name in db.execute("select n.nspname,c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.oid=pg_my_temp_schema() and c.relkind='r'").fetchall():
    db.execute(sql.SQL('drop table {}.{} cascade').format(sql.Identifier(schema),sql.Identifier(name)))
   if phase_index==5:
    actor=ACTORS['owner']; runner=db.execute('select current_user').fetchone()[0]
    claims={'sub':actor,'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':int(db.execute('select extract(epoch from transaction_timestamp())').fetchone()[0])-1}]}
    for key,value in [('talli.verified_actor_id',actor),('talli.verified_actor_claims',json.dumps(claims))]:db.execute('select set_config(%s,%s,true)',(key,value))
    db.execute(sql.SQL('grant annual_accounts_filing_workflow_executor to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
    db.execute('set local role annual_accounts_filing_workflow_executor')
    payload=dict(environment='manual_evidence',status='pending',test_reference='latest-after-cutover',feedback_summary='new canonical record',receipt_reference=None,archive_reference=None,evidence_url=None,payload_hash=None)
    latest=db.execute('select annual_accounts_filing.record_test_evidence_v1(%s,%s::jsonb,%s)',(COMPANY,json.dumps(payload),actor)).fetchone()[0]
    db.execute('select annual_accounts_filing.acknowledge_review_comment_v1(%s,%s)',(IDS['filing_review_comments'],actor))
    db.execute('reset role');db.execute(sql.SQL('revoke annual_accounts_filing_workflow_executor from {} granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
    report['latestRecordId']=latest['id']
   if phase_index==8:
    restored=db.execute('select to_jsonb(r) from public.authority_test_runs r where id=%s',(latest['id'],)).fetchone()[0]
    assert restored==latest
    assert str(db.execute('select acknowledged_by from public.filing_review_comments where id=%s',(IDS['filing_review_comments'],)).fetchone()[0])==ACTORS['owner']
    report['latestRowsRestored']=True

  report['status']='PASS'
 except Exception as e:report.update(status='FAIL',error=str(e),sqlstate=getattr(e,'sqlstate',None))
 finally:
  db.execute('rollback');report['schemaRollbackVerified']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];report['fixtureRollbackVerified']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0
  report['globalMembershipsRestored']=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==original
(p/'latest-state-recutover-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n');print(json.dumps(report,ensure_ascii=False))
if report['status']!='PASS':sys.exit(1)
