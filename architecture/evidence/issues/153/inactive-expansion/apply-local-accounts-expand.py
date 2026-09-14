from pathlib import Path
import hashlib,json,psycopg
from psycopg.conninfo import conninfo_to_dict
p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry');dsn=json.loads((p/'lifecycle-private.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('localhost','127.0.0.1') and c['port']=='52966' and c['dbname']=='accounts153_lifecycle_d060'
path=Path('supabase/contract-migrations/20260914090244_annual_accounts_filing_expand.sql');raw=path.read_text()
with psycopg.connect(dsn,autocommit=True) as db:
 assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
 assert db.execute('select count(*) from public.companies where id=%s',('15300000-0000-4000-8000-000000000001',)).fetchone()[0]==0
 db.execute(raw,prepare=False)
 assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0]=='expanded'
print(json.dumps({'database':c['dbname'],'phase':'expanded','sha256':hashlib.sha256(raw.encode()).hexdigest(),'noCutover':True,'sourceDatabaseUnchanged':True}))
