import hashlib,json
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
P=Path('/Users/kristianelmer/.codex/issue-192-private/issue152-entry');root=Path.cwd()
dsn=json.loads((P/'lifecycle-private.json').read_text())['DB_URL'];info=conninfo_to_dict(dsn)
assert info['dbname']=='tax152_lifecycle_d060' and info['host'] in ('127.0.0.1','localhost','::1')
fixture=json.loads((root/'architecture/evidence/issues/152/legacy-characterization.json').read_text());case=next(c for c in fixture['evidenceCases'] if c['id']=='synthetic-completed-pending-feedback');payload=case['output']['value'];company=payload['authorityRun']['company_id'];owner=payload['authorityRun']['recorded_by']
path=root/'supabase/contract-migrations/20260914022608_company_tax_return_source_contract.sql';script=path.read_text().replace('begin;\n','',1).removesuffix('commit;\n')
with psycopg.connect(dsn,autocommit=True) as db:
 try:
  db.execute('begin isolation level read committed');db.execute(script)
  claims={'sub':owner,'role':'authenticated','aal':'aal2'}
  for key,value in [('request.jwt.claims',json.dumps(claims)),('talli.verified_actor_id',owner),('talli.verified_actor_claims',json.dumps(claims))]:db.execute('select set_config(%s,%s,true)',(key,value))
  db.execute('grant company_tax_filing_workflow_executor to postgres with inherit false,set true')
  try:
   with db.transaction():
    db.execute('set local role company_tax_filing_workflow_executor')
    db.execute('select company_tax_filing.read_source_snapshot_v1(%s,2025,%s)',(company,owner))
   raise AssertionError('Read-committed source proof was accepted')
  except psycopg.Error as error:
   assert error.diag.message_primary=='company_tax_return_unavailable',error.diag.message_primary
 finally:db.execute('rollback')
report={'status':'PASS','check':'READ COMMITTED cannot produce positive source coverage','migrationSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'scope':'Owned local synthetic clone; transaction rolled back; no HTTP/provider claim'}
(P/'tax-source-read-committed.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'])
