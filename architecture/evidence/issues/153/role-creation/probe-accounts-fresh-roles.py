from pathlib import Path
import sys,json,uuid
import psycopg
from psycopg import sql
ROOT=Path('/Users/kristianelmer/.codex/worktrees/d060/Holding accounting')
sys.path.insert(0,str(ROOT/'apps/backend/tests'));sys.path.insert(0,str(ROOT/'apps/backend/src'))
import test_annual_accounts_filing_lifecycle as lifecycle
base=Path(__file__).resolve().parent
url=json.loads((base/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL']
with psycopg.connect(url,autocommit=True) as db:
 assert db.execute('select current_database()').fetchone()[0]=='accounts153_setup_fix_d060'
 before=lifecycle.memberships(db)
 names=['annual_accounts_filing_store_owner','annual_accounts_filing_workflow_executor']
 original=db.execute('select oid,rolname from pg_roles where rolname=any(%s) order by oid',(names,)).fetchall()
 db.execute('begin isolation level repeatable read')
 result={}
 try:
  for _,name in original:
   db.execute(sql.SQL('alter role {} rename to {}').format(sql.Identifier(name),sql.Identifier('accounts153_prior_'+uuid.uuid4().hex)))
  lifecycle.seed(db)
  try:
   lifecycle.apply(db,lifecycle.EXPANSION[0])
  except AssertionError:
   extra=set(lifecycle.memberships(db))-set(before)
   result={'status':'FRESH_ROLE_MEMBERSHIP_ASSERTION_REPRODUCED','newRows':[list(x) for x in sorted(extra)],'freshRoles':2}
  else:result={'status':'FRESH_ROLE_MEMBERSHIP_ASSERTION_PASS','freshRoles':2}
 finally:
  db.execute('rollback')
  assert lifecycle.memberships(db)==before
  assert db.execute('select oid,rolname from pg_roles where rolname=any(%s) order by oid',(names,)).fetchall()==original
  assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
  result.update(outerRollbackExact=True,originalRoleNamesAndOidsRestored=True,mode='OWNED_LOCAL_CLONE_UNCOMMITTED_ROLE_RENAMES_ONLY')
 print(json.dumps(result,indent=2))
