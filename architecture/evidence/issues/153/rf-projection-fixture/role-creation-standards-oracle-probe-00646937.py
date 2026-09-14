"""Execute pinned lifecycle apply() against a deterministic catalog stub, never PostgreSQL."""
import importlib.util,json,sys
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'apps/backend/tests'))
spec=importlib.util.spec_from_file_location('reviewed_lifecycle',root/'apps/backend/tests/test_annual_accounts_filing_lifecycle.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
roles=mod.ACCOUNTS_ROLES
class Cursor:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def fetchall(self):return self.rows
 def __iter__(self):return iter(self.rows)
class Catalog:
 def __init__(self,before,after,existing=(),superuser=False,createrole=True,bootstrap=True):
  self.before=before;self.after=after;self.existing=existing;self.changed=False;self.superuser=superuser;self.createrole=createrole;self.bootstrap=bootstrap
 def execute(self,q,args=None,**kw):
  if q.startswith('select roleid,member,grantor,admin_option'):return Cursor(self.after if self.changed else self.before)
  if q.startswith('select oid,rolsuper'):return Cursor([(77,self.superuser,self.createrole)])
  if q.startswith('select rolname from pg_roles'):return Cursor([(r,) for r in self.existing])
  if q.startswith('select rolsuper from pg_roles'):return Cursor([(self.bootstrap,)])
  if q.startswith('select oid from pg_roles'):return Cursor([(101+roles.index(args[0]),)])
  if q.startswith('select n.nspname,c.relname'):return Cursor([])
  if 'annual_accounts' in q and not q.startswith('select'):self.changed=True;return Cursor([])
  raise AssertionError('Unexpected query '+str(q))
old=[(80,77,77,False,True,False)]
a=(101,77,10,True,False,False);b=(102,77,10,True,False,False)
results=[]
def check(name,db,valid,artifact=None,rollback=False):
 try:mod.apply(db,artifact or mod.EXPANSION[0],rollback=rollback);accepted=True
 except AssertionError:accepted=False
 assert accepted==valid,(name,accepted,valid)
 results.append({'case':name,'expectedAccepted':valid,'actualAccepted':accepted,'status':'PASS'})
check('two fresh roles exact bootstrap grants',Catalog(old,old+[a,b]),True)
check('one fresh role',Catalog(old,old+[b],existing=(roles[0],)),True)
check('both existing no delta',Catalog(old,old,existing=roles),True)
check('existing roles additional management grant',Catalog(old,old+[a],existing=roles),False)
check('superuser creation no delta',Catalog(old,old,superuser=True),True)
check('superuser unexpected management grant',Catalog(old,old+[a,b],superuser=True),False)
check('noncreator rejected',Catalog(old,old+[a,b],createrole=False),False)
check('bootstrap role not superuser',Catalog(old,old+[a,b],bootstrap=False),False)
for name,row in [('wrong grantor',(101,77,11,True,False,False)),('wrong recipient',(101,78,10,True,False,False)),('wrong role',(103,77,10,True,False,False)),('SET leak',(101,77,10,True,False,True)),('INHERIT leak',(101,77,10,True,True,False)),('ADMIN changed',(101,77,10,False,False,False))]:
 check(name,Catalog(old,old+[row,b]),False)
check('old membership removed',Catalog(old,[a,b]),False)
check('old membership changed',Catalog(old,[(80,77,77,True,True,False),a,b]),False)
check('additional self-granted management',Catalog(old,old+[a,b,(101,77,77,True,False,False)]),False)
check('missing mandatory creation grant',Catalog(old,old+[a]),False)
check('other artifact exact state',Catalog(old,old,existing=roles),True,artifact=mod.EXPANSION[1])
check('other artifact added bootstrap grant',Catalog(old,old+[a,b]),False,artifact=mod.EXPANSION[1])
check('rollback added bootstrap grant',Catalog(old,old+[a,b]),False,artifact=mod.CUTOVER,rollback=True)
print(json.dumps({'mode':'PINNED_ACTUAL_APPLY_FUNCTION_WITH_PURE_CATALOG_STUB_NO_DB','count':len(results),'results':results},indent=2))
