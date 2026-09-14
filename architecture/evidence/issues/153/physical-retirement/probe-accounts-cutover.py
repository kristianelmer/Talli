from pathlib import Path
import hashlib,json,sys,time,psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
sys.path.insert(0,str(Path.cwd()/'apps/backend/tests'))
from accounts_database_fixtures import seed,FAMILIES,ACTORS,COMPANY,IDS
p=Path(__file__).parent;dsn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
paths=[Path('supabase/contract-migrations')/n for n in ['20260914090244_annual_accounts_filing_expand.sql','20260914092018_annual_accounts_filing_read_contracts.sql','20260914092924_annual_accounts_filing_preparation_contracts.sql','20260914093204_annual_accounts_filing_import_contract.sql','20260914101625_annual_accounts_filing_dependency_contracts.sql']]
report={'database':c['dbname'],'mode':'ROLLBACK_ONLY_REAL_CUTOVER_SYNTHETIC_ROWS','artifacts':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths},'cases':[]}
with psycopg.connect(dsn,autocommit=True) as db:
 original=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall();db.execute('begin')
 try:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  seed(db)
  for path in paths:
   raw=path.read_text();assert raw.endswith('commit;\n');db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
  assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==original
  runner=db.execute('select current_user').fetchone()[0]
  db.execute(sql.SQL('grant annual_accounts_filing_store_owner,annual_accounts_filing_workflow_executor to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
  def call(name,actor,query,params,expected=None,fresh=True,aal='aal2',role='annual_accounts_filing_workflow_executor'):
   db.execute('savepoint test_case')
   try:
    claims={'sub':ACTORS[actor],'role':'authenticated','aal':aal,'amr':[{'method':'totp','timestamp':int(db.execute('select extract(epoch from transaction_timestamp())').fetchone()[0])-1 if fresh else 1}]}
    for key,value in [('talli.verified_actor_id',ACTORS[actor]),('talli.verified_actor_claims',json.dumps(claims))]: db.execute('select set_config(%s,%s,true)',(key,value))
    db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
    row=db.execute(query,(*params,ACTORS[actor])).fetchone();outcome={'value':row[0]}
   except psycopg.Error as e:outcome={'error':e.diag.message_primary,'sqlstate':e.sqlstate}
   finally:db.execute('rollback to savepoint test_case');db.execute('release savepoint test_case')
   report['cases'].append({'name':name,'actor':actor,'role':role,'fresh':fresh,'aal':aal,'outcome':outcome})
   if expected:assert outcome.get('error')==expected,(name,outcome)
   else:assert 'value' in outcome,(name,outcome)
   return outcome
  read='select annual_accounts_filing.read_workspace_v1(%s::uuid,%s::int,%s::text)'
  call('inactive read','owner',read,(COMPANY,2025),'annual_accounts_unavailable')
  cutover=Path('supabase/contract-migrations/20260914101805_annual_accounts_filing_cutover.sql');raw=cutover.read_text();report['artifacts'][str(cutover)]=hashlib.sha256(cutover.read_bytes()).hexdigest();db.execute(raw.replace('begin;\n','',1)[:-len('commit;\n')],prepare=False)
  for actor in ACTORS:
   call('workspace',actor,read,(COMPANY,2025),None if actor in ('owner','second','reviewer') else 'annual_accounts_not_found')
  queries={
   'override':('select annual_accounts_filing.record_override_v1(%s::uuid,%s,%s,%s,%s,%s,%s,%s)',(IDS['filing_previews'],'company.name','before','after','reason','warning',True)),
   'review':('select annual_accounts_filing.add_review_comment_v1(%s::uuid,%s,%s,%s)',(IDS['filing_previews'],'advisory','review')),
   'acknowledge':('select annual_accounts_filing.acknowledge_review_comment_v1(%s::uuid,%s)',(IDS['filing_review_comments'],)),
   'permission':('select annual_accounts_filing.confirm_filing_permission_v1(%s::uuid,%s,%s)',(COMPANY,False)),
   'manual evidence':('select annual_accounts_filing.record_test_evidence_v1(%s::uuid,%s::jsonb,%s)',(COMPANY,json.dumps(dict(environment='manual_evidence',status='pending',test_reference='synthetic-read-control',feedback_summary='',receipt_reference=None,archive_reference=None,evidence_url=None,payload_hash=None)))),
  }
  for name,(query,params) in queries.items():
   for actor in ACTORS:
    expected=None if actor in ('owner','second') or actor=='reviewer' and name=='review' else 'annual_accounts_forbidden' if actor=='reviewer' and name not in ('override','acknowledge') else 'annual_accounts_not_found'
    call(name,actor,query,params,expected)
   if name in ('permission','manual evidence'):
    call(name+' stale MFA','owner',query,params,'annual_accounts_mfa_required',fresh=False)
    call(name+' AAL1','owner',query,params,'annual_accounts_mfa_required',aal='aal1')
  reference='153/11111111-1111-4111-8111-111111111111';archive='https://platform.tt02.altinn.no/storage/api/v1/instances/'+reference
  payload=dict(company_id=COMPANY,obligation='aarsregnskap',environment='test',status='pending',test_reference='tt02:'+reference,feedback_summary='Synthetic pending',receipt_reference=archive+'/data/22222222-2222-4222-8222-222222222222',archive_reference=archive,evidence_url='legacy non-https value',payload_hash='sha256:'+'a'*64,recorded_by=ACTORS['owner'],recorded_at='2026-09-14T09:00:00.000Z')
  query='select annual_accounts_filing.import_tt02_evidence_v1(%s::jsonb,%s)'
  call('TT02 import','owner',query,(json.dumps(payload),))
  call('TT02 stale MFA','owner',query,(json.dumps(payload),),'annual_accounts_mfa_required',fresh=False)
  for key,value in [('status','accepted'),('recorded_by',ACTORS['second']),('obligation','skattemelding'),('archive_reference',archive+'bad')]:
   call('TT02 invalid '+key,'owner',query,(json.dumps(dict(payload,**{key:value})),),'annual_accounts_invalid_input')
  # Every business entry point stays unavailable before the real cutover.
  db.execute('set local role annual_accounts_filing_store_owner');db.execute("update backend_system.annual_accounts_migration_state set phase='expanded'");db.execute('reset role')
  for name,(inactive_query,params) in queries.items():
   call('inactive '+name,'owner',inactive_query,params,'annual_accounts_unavailable')
  call('inactive TT02','owner',query,(json.dumps(payload),),'annual_accounts_unavailable')
  # Runtime API roles cannot execute private business functions directly.
  functions=db.execute("select p.oid,p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='annual_accounts_filing' order by p.proname").fetchall()
  report['functionPrivileges']=[]
  for role in ('anon','authenticated','service_role'):
   for oid,name in functions:
    permitted=db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,oid)).fetchone()[0]
    assert not permitted,(role,name)
    report['functionPrivileges'].append({'role':role,'function':name,'execute':permitted})
  report['status']='PASS'
 except Exception as e:report.update(status='FAIL',error=str(e),sqlstate=getattr(e,'sqlstate',None))
 finally:
  db.execute('rollback');report['schemaRollbackVerified']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];report['fixtureRollbackVerified']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0
  report['globalMembershipsRestored']=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==original
(p/'cutover-database-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='cases'}));print('cases:',len(report['cases']))
if report['status']!='PASS':sys.exit(1)
