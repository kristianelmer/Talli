from pathlib import Path
import hashlib,json,psycopg,sys
from psycopg.conninfo import conninfo_to_dict
p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry')
dsn=json.loads((p/'lifecycle-private.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c['dbname']=='accounts153_lifecycle_d060'
path=Path('supabase/contract-migrations/20260914090244_annual_accounts_filing_expand.sql');raw=path.read_text();assert raw.endswith('commit;\n')
result={'artifact':str(path),'sha256':hashlib.sha256(raw.encode()).hexdigest(),'localDatabase':c['dbname'],'mode':'rollback-only'}
with psycopg.connect(dsn,autocommit=True) as db:
 try:
  assert not db.execute("select to_regnamespace('annual_accounts_filing')").fetchone()[0]
  before=db.execute("select count(*) from pg_auth_members").fetchone()[0]
  db.execute(raw[:-len('commit;\n')],prepare=False)
  result['phase']=db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0]
  result['ownedTables']=db.execute("select relname,relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) from pg_class where relnamespace='annual_accounts_filing'::regnamespace and relkind='r' order by relname").fetchall()
  result['reconciliations']=db.execute('select family,source_count,target_count,source_digest=target_digest from backend_system.annual_accounts_reconciliations order by family').fetchall()
  result['sourceFunctions']=db.execute("select count(*) from backend_system.annual_accounts_migration_inventory where resource like 'function:%'").fetchone()[0]
  result['status']='PASS'
 except Exception as error:
  result['status']='FAIL';result['error']=str(error);result['sqlstate']=getattr(error,'sqlstate',None)
 finally:
  db.execute('rollback')
  result['rolledBack']=db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  result['roleMembershipCountRestored']=db.execute('select count(*) from pg_auth_members').fetchone()[0]==before
print(json.dumps(result,ensure_ascii=False,indent=2))
if result['status']!='PASS':sys.exit(1)
