import hashlib,json,time
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
P=Path('/Users/kristianelmer/.codex/issue-192-private/issue152-entry'); ROOT=Path.cwd()
dsn=json.loads((P/'lifecycle-private.json').read_text())['DB_URL'];info=conninfo_to_dict(dsn)
assert info['dbname']=='tax152_lifecycle_d060' and info['host'] in ('127.0.0.1','localhost','::1')
fixture=json.loads((ROOT/'architecture/evidence/issues/152/legacy-characterization.json').read_text());case=next(c for c in fixture['evidenceCases'] if c['id']=='synthetic-completed-pending-feedback');payload=case['output']['value'];company=payload['authorityRun']['company_id'];owner=payload['authorityRun']['recorded_by']
path=ROOT/'supabase/contract-migrations/20260914022608_company_tax_return_source_contract.sql';script=path.read_text();script=script.replace('begin;\n','',1).removesuffix('commit;\n')
report={'migrationSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'scope':'Owned synthetic clone; rollback only; no HTTP/provider/stage-exit credit','checks':[]}
def check(name,value):
 assert value,name
 report['checks'].append(name)
def context(db):
 claims={'sub':owner,'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':int(time.time())}]}
 for key,value in [('request.jwt.claims',json.dumps(claims)),('talli.verified_actor_id',owner),('talli.verified_actor_claims',json.dumps(claims))]:db.execute('select set_config(%s,%s,true)',(key,value))
def read(db,year=2025):
 db.execute('set local role company_tax_filing_workflow_executor')
 try:return db.execute('select company_tax_filing.read_source_snapshot_v1(%s,%s,%s)',(company,year,owner)).fetchone()[0]
 finally:db.execute('reset role')
with psycopg.connect(dsn,autocommit=True) as db:
 try:
  db.execute('begin isolation level repeatable read')
  before=db.execute('select jsonb_agg(to_jsonb(m) order by roleid,member,grantor) from pg_auth_members m').fetchone()[0]
  db.execute(script)
  after=db.execute('select jsonb_agg(to_jsonb(m) order by roleid,member,grantor) from pg_auth_members m').fetchone()[0]
  check('exact migration role memberships restored',before==after)
  db.execute('grant company_tax_filing_workflow_executor to postgres with inherit false,set true');context(db)
  snapshot=read(db);coverage=snapshot['coverage']
  for field in ('inventoryValid','quarantineClear','sourceRowsValid','legacyFencesValid','modeChecksValid','declaredExtentValid'):
   check(field,coverage[field] is True)
  check('all six current families positively enumerated',len(coverage['familyCounts'])==6 and len(coverage['reconciledFamilies'])==6)
  check('nonempty retained synthetic filing history',bool(coverage['retainedSubmissionIds']))
  empty=read(db,2024)
  check('zero-submission year still has positive coverage',empty['coverage']['familyCounts']['filing_submissions']==0 and empty['coverage']['inventoryValid'])
  report['snapshot']=snapshot;report['emptyYearSnapshot']=empty
 finally:db.execute('rollback')
(P/'tax-source-snapshot-probe.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'checks':len(report['checks']),'status':'PASS'}))
