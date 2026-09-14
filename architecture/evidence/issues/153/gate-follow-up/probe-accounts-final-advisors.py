"""Security/performance advisors on an owned final-topology clone, then drop."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
from urllib.parse import quote
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
root=Path.cwd();private=Path(__file__).parent
source=conninfo_to_dict(json.loads((private/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'])
assert source['host'] in ('localhost','127.0.0.1') and source['port']=='52966' and source['dbname']=='accounts153_setup_fix_d060'
target='accounts153_advisors_900472a0'
sys.path.insert(0,str(root/'apps/backend/tests'))
from test_annual_accounts_filing_lifecycle import apply,EXPANSION,CUTOVER,CONTRACT,memberships
admin=psycopg.connect(make_conninfo(**{**source,'dbname':'postgres'}),autocommit=True)
prior=memberships(admin);created=False
try:
 assert not admin.execute('select exists(select 1 from pg_database where datname=%s)',(target,)).fetchone()[0]
 admin.execute(sql.SQL('create database {} template {}').format(sql.Identifier(target),sql.Identifier(source['dbname'])));created=True
 with psycopg.connect(make_conninfo(**{**source,'dbname':target}),autocommit=True) as db:
  db.execute('begin')
  for artifact in EXPANSION:apply(db,artifact)
  apply(db,CUTOVER);apply(db,CONTRACT);db.execute('commit')
 url='postgresql://'+quote(source['user'],safe='')+':'+quote(source['password'],safe='')+'@'+source['host']+':'+source['port']+'/'+target+'?sslmode=disable'
 env={**os.environ,'PATH':'/Users/kristianelmer/.codex/issue-192-private/runtime/node-v24.20.0-darwin-arm64/bin:'+os.environ['PATH']}
 result=subprocess.run(['node_modules/.bin/supabase','db','advisors','--db-url',url,'--output','json'],env=env,capture_output=True,text=True)
 (private/'accounts-final-advisors-cli.log').write_text((result.stderr+'\n'+result.stdout).replace(url,'<owned-loopback-url>').replace(source['password'],'<redacted>'))
 assert result.returncode==0, 'advisor CLI failed (private stderr retained)'
 findings=json.loads(result.stdout);assert isinstance(findings,list)
 (private/'accounts-final-advisors-900472a0.json').write_text(json.dumps(findings,indent=2)+'\n')
 blocking=[f for f in findings if f.get('level')=='ERROR' or f.get('facing')=='EXTERNAL' and 'SECURITY' in f.get('categories',[])]
 assert not blocking, [f.get('name') for f in blocking]
 print('PASS final topology advisors:',len(findings),'findings, zero blocking security/errors')
finally:
 if created:
  assert not admin.execute('select exists(select 1 from pg_stat_activity where datname=%s)',(target,)).fetchone()[0]
  admin.execute(sql.SQL('drop database {}').format(sql.Identifier(target)))
 assert memberships(admin)==prior
 admin.close()
print('Owned clone dropped; all global memberships restored')
