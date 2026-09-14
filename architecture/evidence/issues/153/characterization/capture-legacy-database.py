"""Populated, rollback-only Accounts legacy RLS characterization on a disposable clone.

SQL actor claims are synthetic; this does not establish HTTP JWT/MFA/browser behavior.
"""
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

PRIVATE = Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry')
dsn = json.loads((PRIVATE/'lifecycle-private.json').read_text())['DB_URL']
connection = conninfo_to_dict(dsn)
assert connection['host'] in ('localhost','127.0.0.1','::1') and int(connection['port']) == 52966
assert connection['dbname'] == 'accounts153_lifecycle_d060'
company='15300000-0000-4000-8000-000000000001'
actors={name:f'15300000-0000-4000-8000-{index:012d}' for index,name in enumerate(('owner','second','reviewer','unaccepted','outsider'),10)}
preview='15300000-0000-4000-8000-000000000020'
tables=('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
rows={
 'filing_previews':dict(company_id=company,income_year=2025,filing='årsregnskap',status='ready',preview='Synthetic Accounts characterization'),
 'filing_submissions':dict(company_id=company,income_year=2025,filing='årsregnskap',status='ready',preview_id=preview),
 'filing_overrides':dict(company_id=company,income_year=2025,filing='årsregnskap',preview_id=preview,field_target='aarsregnskap.company.name',old_value='Before',new_value='After',reason='Synthetic reason',risk_level='warning',owner_confirmed_at='2026-07-14T12:00:00Z'),
 'filing_review_comments':dict(company_id=company,preview_id=preview,severity='advisory',body='Synthetic review',target='rf1086_preview'),
 'authority_permissions':dict(company_id=company,obligation='aarsregnskap'),
 'authority_test_runs':dict(company_id=company,obligation='aarsregnskap',status='pending',test_reference='synthetic-accounts153'),
}
report={'baselineRevision':'5b74340ca75f215b43d754c6bf0fc49ef5974b0b','scope':'Disposable clone; actual unchanged PostgreSQL RLS with synthetic SQL claims. No verified HTTP/MFA/browser/provider evidence.','transaction':'ROLLBACK_ONLY','cases':[]}
db=psycopg.connect(dsn,autocommit=True)

def claims(name,aal='aal2'):
 db.execute('reset role')
 db.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({'sub':actors.get(name),'role':'authenticated','aal':aal}),))
 db.execute('set local role authenticated')

def insert(table, row):
 return db.execute(sql.SQL('insert into public.{} ({}) values ({}) returning id').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,row)),sql.SQL(',').join(sql.Placeholder() for _ in row)),tuple(row.values())).fetchone()[0]

def attempt(name,table,operation,fn,aal='aal2'):
 db.execute('savepoint attempt')
 try:
  claims(name,aal)
  result=fn()
  outcome={'value':str(result) if isinstance(result,UUID) else result}
 except psycopg.Error as error:
  outcome={'error':error.diag.message_primary,'sqlstate':error.sqlstate}
 finally:
  db.execute('rollback to savepoint attempt');db.execute('release savepoint attempt')
 report['cases'].append({'actor':name,'aal':aal,'table':table,'operation':operation,'output':outcome})
 return outcome

def candidate(table,name,index):
 row=dict(rows[table]);row['id']=f'15300000-0000-4000-8000-{index:012d}'
 actor=actors.get(name)
 if table=='authority_permissions':row.update(submitter_user_id=actor,confirmed_by=actor)
 elif table=='authority_test_runs':row['recorded_by']=actor
 else:row['created_by']=actor
 if table=='filing_overrides':row['owner_confirmed_by']=actor
 return row

try:
 db.execute('begin')
 assert db.execute("select current_database()").fetchone()[0]=='accounts153_lifecycle_d060'
 assert db.execute("select count(*) from pg_namespace where nspname='annual_accounts_filing'").fetchone()[0]==0
 for actor in actors.values():db.execute('insert into auth.users(id) values (%s)',(actor,))
 db.execute("insert into public.companies(id,org_number,name,entity_type,created_by) values (%s,'000000153','Synthetic Accounts153','AS',%s)",(company,actors['owner']))
 for name,role,accepted in [('owner','owner',True),('second','owner',True),('reviewer','reviewer',True),('unaccepted','owner',False)]:
  db.execute('insert into public.company_memberships(company_id,user_id,role,accepted_at) values (%s,%s,%s,case when %s then now() else null end)',(company,actors[name],role,accepted))
 seeded={}
 for index,table in enumerate(tables,20):
  row=candidate(table,'owner',index)
  seeded[table]=insert(table,row)
 # Reads observe populated data; insert probes isolate uniqueness from access policy.
 for name in [*actors,'anonymous']:
  for table in tables:
   attempt(name,table,'select',lambda table=table:db.execute(sql.SQL('select count(*) from public.{} where company_id=%s').format(sql.Identifier(table)),(company,)).fetchone()[0])
   def write(table=table,name=name):
    if table=='authority_permissions':
     db.execute('reset role');db.execute('delete from public.authority_permissions where company_id=%s',(company,));claims(name)
    row=candidate(table,name,100)
    if table=='filing_submissions':
     db.execute('reset role');fresh=insert('filing_previews',candidate('filing_previews','owner',102));claims(name);row['preview_id']=fresh
    return insert(table,row)
   attempt(name,table,'insert',write)
 for table in tables:
  def write_aal1(table=table):
   if table=='authority_permissions':
    db.execute('reset role');db.execute('delete from public.authority_permissions where company_id=%s',(company,));claims('owner','aal1')
   row=candidate(table,'owner',101)
   if table=='filing_submissions':
    db.execute('reset role');fresh=insert('filing_previews',candidate('filing_previews','owner',102));claims('owner','aal1');row['preview_id']=fresh
   return insert(table,row)
  attempt('owner',table,'insert',write_aal1,aal='aal1')
 attempt('owner','filing_submissions','duplicate-preview',lambda:insert('filing_submissions',candidate('filing_submissions','owner',103)))
 for name in ['owner','second','reviewer','outsider']:
  attempt(name,'filing_review_comments','acknowledge',lambda name=name:db.execute('update public.filing_review_comments set acknowledged_by=%s,acknowledged_at=now() where id=%s',(actors[name],seeded['filing_review_comments'])).rowcount)
  attempt(name,'filing_submissions','update',lambda:db.execute("update public.filing_submissions set status='submitted' where id=%s",(seeded['filing_submissions'],)).rowcount)
 db.execute('reset role')
 report['seededRowCounts']={table:db.execute(sql.SQL('select count(*) from public.{} where company_id=%s').format(sql.Identifier(table)),(company,)).fetchone()[0] for table in tables}
 assert all(value==1 for value in report['seededRowCounts'].values())
 assert all(c['output']=={'value':1} for c in report['cases'] if c['actor']=='owner' and c['operation']=='select')
 assert all(c['output']=={'value':0} for c in report['cases'] if c['actor']=='outsider' and c['operation']=='select')
 report['status']='PASS_CAPTURED'
finally:
 db.execute('rollback')
 assert db.execute('select count(*) from public.companies where id=%s',(company,)).fetchone()[0]==0
 report['fixtureRollbackVerified']=True
 db.close()
raw=(json.dumps(report,indent=2,ensure_ascii=False)+'\n').encode()
with Path(sys.argv[1]).open('xb') as output:output.write(raw)
print(json.dumps({'status':report['status'],'cases':len(report['cases']),'sha256':hashlib.sha256(raw).hexdigest()}))
