from pathlib import Path
import hashlib,json,sys,psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
p=Path(__file__).parent;pin=Path('/Users/kristianelmer/.codex/worktrees/d060/Holding accounting');sys.path.insert(0,str(pin/'apps/backend/tests'))
from accounts_database_fixtures import seed,insert,FAMILIES,COMPANY,ACTORS,IDS
conn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(conn);assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
path=pin/'supabase/contract-migrations/20260914090244_annual_accounts_filing_expand.sql';raw=path.read_text();script=raw.replace('begin;\n','',1)[:-len('commit;\n')]
report={'baseRevision':'04e682b69e5426408932233d05328134e8e997f8','migrationSha256':hashlib.sha256(raw.encode()).hexdigest(),'database':c['dbname'],'mode':'ROLLBACK_ONLY'}
with psycopg.connect(conn,autocommit=True) as db:
 membership_sql='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
 original=db.execute(membership_sql).fetchall();db.execute('begin')
 try:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  rows=seed(db);company_b='15300000-0000-4000-8000-000000000090'
  db.execute("insert into public.companies(id,org_number,name,entity_type,created_by) values (%s,'000000154','Synthetic setup provenance B','AS',%s)",(company_b,ACTORS['owner']))
  db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",(company_b,ACTORS['owner']))
  runner=db.execute('select current_user').fetchone()[0]
  db.execute(sql.SQL('grant shareholder_register_filing_store_owner to {} with set true granted by {}').format(sql.Identifier(runner),sql.Identifier(runner)))
  db.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({'sub':ACTORS['owner'],'role':'authenticated','aal':'aal2'}),))
  db.execute('set local role shareholder_register_filing_store_owner')
  db.execute(sql.SQL('grant insert on shareholder_register_filing.opening_balance_setups to {}').format(sql.Identifier(runner)))
  db.execute('reset role')
  setups={}
  for suffix,company,year in [(91,company_b,2025),(92,COMPANY,2024),(93,COMPANY,2025)]:
   id=f'15300000-0000-4000-8000-{suffix:012d}';setups[suffix]=id
   insert(db,'shareholder_register_filing','opening_balance_setups',dict(id=id,company_id=company,income_year=year,share_capital=30000,share_count=30,nominal_value=1000,created_by=ACTORS['owner']))
  db.execute('reset role')
  db.execute('update public.filing_previews set setup_id=%s where id=%s',(setups[91],IDS['filing_previews']))
  for suffix,setup in [(94,setups[92]),(95,setups[93]),(96,None)]:
   insert(db,'public','filing_previews',dict(rows['filing_previews'],id=f'15300000-0000-4000-8000-{suffix:012d}',setup_id=setup))
  db.execute('update public.filing_submissions set setup_id=%s where id=%s',(setups[91],'15300000-0000-4000-8000-000000000026'))
  for suffix,setup in [(97,setups[93]),(98,None)]:
   insert(db,'public','filing_submissions',dict(rows['filing_submissions'],id=f'15300000-0000-4000-8000-{suffix:012d}',preview_id=f'15300000-0000-4000-8000-{suffix-2:012d}',setup_id=setup))
  scope_state_sql="select c.relacl::text,(select jsonb_agg(to_jsonb(p) order by polname) from pg_policy p where p.polrelid=c.oid) from pg_class c where c.oid='shareholder_register_filing.opening_balance_setups'::regclass"
  original_scope_state=db.execute(scope_state_sql).fetchall()
  report['legacyTriggersEnabled']=db.execute("select tgrelid::regclass::text,tgname,tgenabled from pg_trigger where tgrelid in ('public.filing_previews'::regclass,'public.filing_submissions'::regclass) and not tgisinternal order by 1,2").fetchall()
  before={f:db.execute(sql.SQL('select to_jsonb(t)::text from public.{} t order by id').format(sql.Identifier(f))).fetchall() for f in FAMILIES};members=db.execute(membership_sql).fetchall()
  db.execute(script,prepare=False)
  report['migrationRestoredMemberships']=db.execute(membership_sql).fetchall()==members
  report['legacyRowsUnchanged']=all(db.execute(sql.SQL('select to_jsonb(t)::text from public.{} t order by id').format(sql.Identifier(f))).fetchall()==before[f] for f in FAMILIES)
  report['sourceClassifications']=db.execute("select family,source_id::text,payload->>'setup_id',classification from backend_system.annual_accounts_source_rows order by family,source_id").fetchall()
  report['setupAclAndPoliciesUnchanged']=db.execute(scope_state_sql).fetchall()==original_scope_state
  assert report['setupAclAndPoliciesUnchanged']
  report['quarantineCount']=db.execute('select count(*) from backend_system.annual_accounts_quarantine').fetchone()[0]
  report['canonicalPreviewScopes']=db.execute('select p.id::text,p.company_id::text,p.income_year,s.company_id::text,s.income_year from annual_accounts_filing.filing_previews p left join shareholder_register_filing.opening_balance_setups s on s.id=p.setup_id order by p.id').fetchall()
  report['canonicalSubmissionScopes']=db.execute('select p.id::text,p.company_id::text,p.income_year,s.company_id::text,s.income_year from annual_accounts_filing.filing_submissions p left join shareholder_register_filing.opening_balance_setups s on s.id=p.setup_id order by p.id').fetchall()
  report['reconciliations']=db.execute('select family,source_count,target_count,source_digest=target_digest from backend_system.annual_accounts_reconciliations order by family').fetchall()
  report['sourceFunctions']=db.execute("select count(*) from backend_system.annual_accounts_migration_inventory where resource like 'function:%'").fetchone()[0]
  assert len(report['canonicalSubmissionScopes'])==2
  assert report['quarantineCount']==6, report['sourceClassifications']
  assert all(row[3] in (None,row[1]) and row[4] in (None,row[2]) for row in report['canonicalPreviewScopes']+report['canonicalSubmissionScopes'])
  assert report['legacyRowsUnchanged'] and report['migrationRestoredMemberships']
  report['status']='PASS'
 except Exception as e:
  report['status']='PROBE_ERROR';report['error']=str(e);report['sqlstate']=getattr(e,'sqlstate',None)
 finally:
  db.execute('rollback');report['rollbackSchemaAbsent']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];report['rollbackFixtureAbsent']=db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0;report['globalMembershipsRestored']=db.execute(membership_sql).fetchall()==original
(p/'expand-fix-setup-provenance-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if report['status']=='PROBE_ERROR':sys.exit(1)
