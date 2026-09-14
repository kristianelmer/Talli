from pathlib import Path
import sys,json,hashlib,psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql
p=Path(__file__).parent;root=p/'spec-source-handoff-1e380672';sys.path[:0]=[str(root/'apps/backend/tests'),str(root/'apps/backend/src')]
from test_annual_accounts_filing_lifecycle import EXPANSION,CUTOVER,CONTRACT,apply,actor,memberships,environment
from accounts_database_fixtures import seed,ACTORS,COMPANY,IDS
from test_annual_accounts_source_facts import parse
from talli_backend.modules.annual_accounts_filing.public import project_annual_accounts_source
c=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text());dsn=c['DB_URL'];guard=conninfo_to_dict(dsn)
assert guard['host'] in ('localhost','127.0.0.1') and guard['port']=='52966' and guard['dbname']=='accounts153_setup_fix_d060'
report={'revision':'1e38067282e144996b455e428c267f6be3534421','mode':'ROLLBACK_ONLY_INDEPENDENT_SOURCE_CONTRACT','cases':[],'artifacts':{name:hashlib.sha256((root/'supabase/contract-migrations'/name).read_bytes()).hexdigest()for name in [*EXPANSION,CUTOVER,CONTRACT]}}
def observe(db,year=2025,name='owner'):
 with actor(db,name) as identity:
  raw=db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,%s,%s)',(COMPANY,year,identity)).fetchone()[0]
 query,snapshot=parse(raw);return project_annual_accounts_source(query,snapshot)
report['mode']='ROLLBACK_ONLY_MALFORMED_LEGACY_JSON_PRESERVATION'
with psycopg.connect(dsn,autocommit=True) as db:
 before=memberships(db)
 for value in ['doc-id',{'doc-id':True},0,[]]:
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];db.execute('begin isolation level repeatable read')
  try:
   seed(db)
   db.execute('update public.filing_submissions set feedback_document_ids=%s::jsonb where id=%s',(json.dumps(value),IDS['filing_submissions']))
   for f in EXPANSION:apply(db,f)
   apply(db,CUTOVER);apply(db,CONTRACT)
   facts=observe(db);fact=next(x for x in facts.recorded_submissions if x.source_id==IDS['filing_submissions'])
   report['cases'].append({'storedLegacyValue':value,'projectedIds':list(fact.feedback_document_ids),'coverage':facts.history_coverage.status,'readiness':facts.readiness_status})
  finally:
   db.execute('rollback');assert memberships(db)==before;assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0];assert db.execute('select count(*) from public.companies where id=%s',(COMPANY,)).fetchone()[0]==0
report.update(status='REPRODUCED_STD_153_SOURCE_1',allTransactionsRolledBack=True,globalMembershipsRestored=True,schemaAndFixtureRestored=True)
(p/'source-handoff-spec-malformed-sql-1e380672.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
