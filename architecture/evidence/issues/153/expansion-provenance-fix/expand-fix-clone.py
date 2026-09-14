from pathlib import Path
import hashlib,json,os,subprocess,psycopg
from psycopg.conninfo import make_conninfo,conninfo_to_dict
from psycopg import sql
p=Path(__file__).parent;pin=Path('/Users/kristianelmer/.codex/worktrees/d060/Holding accounting');name='accounts153_setup_fix_d060'
e=json.loads((p.parent/'issue146-entry/local-environment-private.json').read_text());c=conninfo_to_dict(e['DB_URL']);assert c['host'] in ('127.0.0.1','localhost') and c['port']=='52966' and c.get('dbname','postgres')=='postgres'
dump=p/'pre-accounts-entry.dump';expected=json.loads((pin/'architecture/evidence/issues/153/entry/database-catalog.json').read_text())['rollbackAsset']['sha256'];assert hashlib.sha256(dump.read_bytes()).hexdigest()==expected
with psycopg.connect(e['DB_URL'],autocommit=True) as db:
 assert not db.execute('select 1 from pg_database where datname=%s',(name,)).fetchone()
 db.execute(sql.SQL('create database {}').format(sql.Identifier(name)))
with dump.open('rb') as f:
 r=subprocess.run(['docker','exec','-i','-u','postgres','supabase_db_tallig6753','pg_restore','-U','supabase_admin','-d',name,'--exit-on-error'],stdin=f,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock'})
(p/'expand-fix-clone-restore-04e682b6.log').write_bytes(r.stdout+r.stderr);assert r.returncode==0
conn=make_conninfo(e['DB_URL'],dbname=name);private=p/'expand-fix-clone-private-04e682b6.json';private.write_text(json.dumps({'DB_URL':conn}));private.chmod(0o600)
with psycopg.connect(conn) as db:
 assert db.execute('select current_database()').fetchone()[0]==name
 assert db.execute("select phase from backend_system.company_tax_return_migration_state where singleton").fetchone()[0]=='contracted'
 assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
 print(json.dumps({'clone':name,'restoreExit':r.returncode,'dumpSha256':expected,'openingColumns':db.execute("select attname,format_type(atttypid,atttypmod),attnotnull,pg_get_expr(d.adbin,d.adrelid) from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid='shareholder_register_filing.opening_balance_setups'::regclass and a.attnum>0 and not a.attisdropped order by a.attnum").fetchall()},default=str))
