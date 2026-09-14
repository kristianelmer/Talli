from pathlib import Path
import hashlib,json,os,sys
from psycopg.conninfo import conninfo_to_dict
p=Path(__file__).parent;dsn=json.loads((p/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'];c=conninfo_to_dict(dsn)
assert c['host'] in ('localhost','127.0.0.1') and c['port']=='52966' and c['dbname']=='accounts153_setup_fix_d060'
os.environ['DATABASE_URL']=dsn;sys.path.insert(0,str(Path.cwd()/'apps/backend/tests'))
from test_annual_accounts_filing_lifecycle import database,apply,actor,EXPANSION,CUTOVER,CONTRACT,COMPANY
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsFilingRows,AnnualAccountsSourceSnapshot,AnnualAccountsSourceQuery,project_annual_accounts_source
from talli_backend.shared.kernel import CompanyId,IncomeYear,ActorId,ActorKind,UserId,Timestamp
from datetime import datetime
artifacts={n:hashlib.sha256((Path('supabase/contract-migrations')/n).read_bytes()).hexdigest() for n in [*EXPANSION,CUTOVER,CONTRACT]}
fixture=database.__wrapped__();db=next(fixture)
try:
 apply(db,CUTOVER);apply(db,CONTRACT)
 snapshots=[]
 with actor(db) as identity:
  for year in [2025,2024]:
   value=db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,%s,%s)',(COMPANY,year,identity)).fetchone()[0]
   query=AnnualAccountsSourceQuery(CompanyId(COMPANY),IncomeYear(year),ActorId(ActorKind.USER,UserId(identity)))
   rows=AnnualAccountsFilingRows(query.company_id,query.income_year,**value['workspace'])
   source=AnnualAccountsSourceSnapshot(rows,value['coverage'],Timestamp(datetime.fromisoformat(value['asOf'])),value['completeEnumeration'])
   facts=project_annual_accounts_source(query,source)
   assert facts.history_coverage.status=='complete',facts.history_coverage
   assert facts.readiness_status=='blocked'
   snapshots.append(value)
finally:
 try:next(fixture)
 except StopIteration:pass
result={'artifacts':artifacts,'snapshot':snapshots[0],'emptyYearSnapshot':snapshots[1],'status':'PASS','mode':'ROLLBACK_ONLY_SYNTHETIC_SOURCE_CAPTURE'}
(p/'accounts-source-snapshot.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS source snapshots: populated and empty year; schema/fixtures/global grants restored')
