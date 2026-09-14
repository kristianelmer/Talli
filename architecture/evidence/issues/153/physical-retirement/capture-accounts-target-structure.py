from pathlib import Path
import hashlib,json,sys
import psycopg
from psycopg.conninfo import conninfo_to_dict
sys.path.insert(0,str(Path.cwd()/'apps/backend/tests'))
from test_annual_accounts_filing_lifecycle import EXPANSION,apply,memberships,FAMILIES
p=Path(__file__).parent;dsn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('localhost','127.0.0.1') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
query=(p/'accounts-target-structure.sql').read_text()
report={'producerQuerySha256':hashlib.sha256(query.encode()).hexdigest(),'artifacts':{str(n):hashlib.sha256((Path('supabase/contract-migrations')/n).read_bytes()).hexdigest() for n in EXPANSION},'targets':{}}
with psycopg.connect(dsn,autocommit=True) as db:
 before=memberships(db);db.execute('begin')
 try:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  for n in EXPANSION:apply(db,n)
  for f in FAMILIES:
   definition=db.execute(query,('annual_accounts_filing.'+f,)).fetchone()[0]
   digest=db.execute("select encode(extensions.digest(%s::jsonb::text,'sha256'),'hex')",(json.dumps(definition),)).fetchone()[0]
   report['targets'][f]={'definition':definition,'sha256':digest}
 finally:
  db.execute('rollback');assert memberships(db)==before;assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
(p/'accounts-target-structure.json').write_text(json.dumps(report,indent=2)+'\n');print({f:t['sha256'] for f,t in report['targets'].items()})
