from pathlib import Path
import hashlib,json,os,subprocess
import psycopg
from psycopg.conninfo import make_conninfo,conninfo_to_dict

p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry')
environment=json.loads((p.parent/'issue146-entry/local-environment-private.json').read_text())
connection=conninfo_to_dict(environment['DB_URL'])
assert connection['host'] in ('127.0.0.1','localhost') and connection['port']=='52966'
name='accounts153_lifecycle_d060'
with psycopg.connect(environment['DB_URL'],autocommit=True) as db:
 assert not db.execute('select 1 from pg_database where datname=%s',(name,)).fetchone(),'clone already exists'
 db.execute('create database '+name)
runenv={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock'}
with (p/'pre-accounts-entry.dump').open('rb') as data:
 result=subprocess.run(['docker','exec','-i','-u','postgres','supabase_db_tallig6753','pg_restore','-U','supabase_admin','-d',name,'--exit-on-error'],stdin=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=runenv)
(p/'lifecycle-clone-restore.log').write_bytes(result.stdout+result.stderr)
assert result.returncode==0,'restore failed; inspect private log'
dsn=make_conninfo(environment['DB_URL'],dbname=name)
(p/'lifecycle-private.json').write_text(json.dumps({'DB_URL':dsn}))
os.chmod(p/'lifecycle-private.json',0o600)
catalog=Path('architecture/evidence/issues/153/entry/database-catalog.json')
inventory=json.loads(catalog.read_text())
assert hashlib.sha256((p/'pre-accounts-entry.dump').read_bytes()).hexdigest()==inventory['rollbackAsset']['sha256']
with psycopg.connect(dsn) as db:
 assert db.execute('select current_database()').fetchone()[0]==name
 assert db.execute('select phase from backend_system.company_tax_return_migration_state where singleton').fetchone()[0]=='contracted'
 for table,expected in inventory['tables'].items():
  assert db.execute('select count(*) from '+table).fetchone()[0]==expected['rowCounts']['total']
 assert not db.execute("select 1 from pg_namespace where nspname='annual_accounts_filing'").fetchone()
inventory['rollbackAsset']['restoreRehearsal']='PASS: disposable '+name+', six table counts and contracted predecessor state match; no Accounts schema exists'
inventory['rollbackAsset']['restoreLogSha256']=hashlib.sha256((p/'lifecycle-clone-restore.log').read_bytes()).hexdigest()
catalog.write_text(json.dumps(inventory,indent=2,ensure_ascii=False)+'\n')
print({'clone':name,'restoreExit':result.returncode,'predecessorPhase':'contracted','legacyCountsMatched':6})
