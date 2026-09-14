from pathlib import Path
import hashlib,json,os,subprocess
from datetime import datetime,timezone
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

root=Path.cwd()
p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry')
environment=json.loads((p.parent/'issue146-entry/local-environment-private.json').read_text())
connection=conninfo_to_dict(environment['DB_URL'])
assert connection['host'] in ('127.0.0.1','localhost') and connection['port']=='52966' and connection['dbname']=='postgres'
tables=['authority_permissions','authority_test_runs','filing_previews','filing_submissions','filing_overrides','filing_review_comments']
with psycopg.connect(environment['DB_URL'],row_factory=dict_row) as db:
 db.execute('set transaction isolation level repeatable read read only')
 states={name:db.execute('select phase from backend_system.'+name+' where singleton').fetchone()['phase'] for name in ['tax_settlement_migration_state','company_tax_return_migration_state']}
 assert set(states.values())=={'contracted'}
 result={'status':'READ_ONLY_PREDECESSOR_CATALOG_CAPTURE','capturedAt':datetime.now(timezone.utc).isoformat(),'baselineRevision':'5b74340ca75f215b43d754c6bf0fc49ef5974b0b','localDatabase':'supabase_db_tallig6753/postgres','serverVersion':db.execute('show server_version').fetchone()['server_version'],'predecessorStates':states,'tables':{}}
 for table in tables:
  info=db.execute("select c.relrowsecurity,c.relforcerowsecurity,c.relkind,pg_get_userbyid(c.relowner) as owner from pg_class c where c.oid=%s::regclass",('public.'+table,)).fetchone()
  info['columns']=db.execute("select a.attname as name,format_type(a.atttypid,a.atttypmod) as type,a.attnotnull as not_null,pg_get_expr(d.adbin,d.adrelid) as default from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid=%s::regclass and a.attnum>0 and not a.attisdropped order by a.attnum",('public.'+table,)).fetchall()
  info['constraints']=db.execute("select conname,contype,pg_get_constraintdef(oid) as definition from pg_constraint where conrelid=%s::regclass order by conname",('public.'+table,)).fetchall()
  info['policies']=db.execute("select policyname,permissive,roles,cmd,qual,with_check from pg_policies where schemaname='public' and tablename=%s order by policyname",(table,)).fetchall()
  info['grants']=db.execute("select grantee,privilege_type,is_grantable from information_schema.role_table_grants where table_schema='public' and table_name=%s order by grantee,privilege_type",(table,)).fetchall()
  info['indexes']=db.execute("select indexname,indexdef from pg_indexes where schemaname='public' and tablename=%s order by indexname",(table,)).fetchall()
  info['triggers']=db.execute("select t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) as definition,n.nspname||'.'||p.proname as function from pg_trigger t join pg_proc p on p.oid=t.tgfoid join pg_namespace n on n.oid=p.pronamespace where t.tgrelid=%s::regclass and not t.tgisinternal order by t.tgname",('public.'+table,)).fetchall()
  info['referencingForeignKeys']=db.execute("select conrelid::regclass::text as source,conname,pg_get_constraintdef(oid) as definition from pg_constraint where confrelid=%s::regclass order by conrelid::regclass::text,conname",('public.'+table,)).fetchall()
  if table=='filing_review_comments':
   counts=db.execute("select count(*) as total,count(*) filter(where p.filing='årsregnskap') as accounts from public.filing_review_comments c left join public.filing_previews p on p.id=c.preview_id").fetchone()
  else:
   key='obligation' if table.startswith('authority_') else 'filing'
   value='aarsregnskap' if key=='obligation' else 'årsregnskap'
   counts=db.execute('select count(*) as total,count(*) filter(where '+key+'=%s) as accounts from public.'+table,(value,)).fetchone()
  info['rowCounts']={**counts,'other':counts['total']-counts['accounts']}
  result['tables']['public.'+table]=info
 result['sourceFunctions']=db.execute("select n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')' as name,p.prosecdef as security_definer,pg_get_userbyid(p.proowner) as owner,p.proacl::text as acl,pg_get_functiondef(p.oid) as definition from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.prokind='f' and n.nspname in ('public','documents','backend_system','company_tax_filing','shareholder_register_filing') and p.prosrc ~ '(filing_previews|filing_submissions|filing_overrides|filing_review_comments|authority_permissions|authority_test_runs)' order by 1").fetchall()
 for f in result['sourceFunctions']:
  f['definitionSha256']=hashlib.sha256(f.pop('definition').encode()).hexdigest()
 db.rollback()
dump=p/'pre-accounts-entry.dump'
assert not dump.exists()
runenv={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock'}
with dump.open('xb') as output:
 os.chmod(dump,0o600)
 r=subprocess.run(['docker','exec','-u','postgres','supabase_db_tallig6753','pg_dump','-U','postgres','-d','postgres','-Fc'],stdout=output,stderr=subprocess.PIPE,env=runenv)
assert r.returncode==0,r.stderr.decode()
result['rollbackAsset']={'privatePath':str(dump),'sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'bytes':dump.stat().st_size,'format':'PostgreSQL custom dump','restoreRehearsal':'pending disposable clone','containsRows':'private only; no row payloads in committed catalog inventory'}
target=root/'architecture/evidence/issues/153/entry/database-catalog.json'
target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':result['status'],'states':states,'tables':{k:v['rowCounts'] for k,v in result['tables'].items()},'sourceFunctionCount':len(result['sourceFunctions']),'privateRollbackBytes':result['rollbackAsset']['bytes']}))
