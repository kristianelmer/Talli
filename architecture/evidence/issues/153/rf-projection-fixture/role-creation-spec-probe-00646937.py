"""Execute exact apply()/membership assertion using catalog-result fakes, no SQL."""
import ast,json
from pathlib import Path
ROOT=Path(__file__).parent/'role-creation-spec-snapshot-00646937'
source=ROOT/'apps/backend/tests/test_annual_accounts_filing_lifecycle.py'
tree=ast.parse(source.read_text());wanted={'memberships','apply'}
constants={}
for node in tree.body:
 if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('EXPANSION','ACCOUNTS_ROLES') for t in node.targets):
  constants[node.targets[0].id]=ast.literal_eval(node.value)
ns={'ROOT':ROOT,**constants};exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[]),str(source),'exec'),ns)
ROLES=constants['ACCOUNTS_ROLES'];IDS=dict(zip(ROLES,[1001,1002]));original=(55,42,7,False,False,True)
class Cursor:
 def __init__(self,rows):self.rows=rows
 def fetchall(self):return self.rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
class Database:
 def __init__(self,before,after,existing,superuser=False,createrole=True,bootstrap=True):self.before=before;self.after=after;self.existing=existing;self.creator=(42,superuser,createrole);self.boot=bootstrap;self.applied=False
 def execute(self,query,params=None,**kw):
  if query.startswith('select roleid,member,grantor'):return Cursor(self.after if self.applied else self.before)
  if query.startswith('select oid,rolsuper'):return Cursor([self.creator])
  if query.startswith('select rolname'):return Cursor([(r,) for r in self.existing])
  if query.startswith('select rolsuper'):return Cursor([(self.boot,)])
  if query.startswith('select oid from pg_roles'):return Cursor([(IDS[params[0]],)])
  if query.startswith('select n.nspname'):return Cursor([])
  assert 'create temporary table' in query
  self.applied=True;return Cursor([])
auto=lambda role:(IDS[role],42,10,True,False,False)
fresh=[original,auto(ROLES[0]),auto(ROLES[1])]
cases=[('fresh_exact',fresh,[],{},True),('missing_auto',[original],[],{},False),('extra_recipient',fresh+[(1001,43,42,False,False,True)],[],{},False),('wrong_grantor',[original,(1001,42,42,True,False,False),auto(ROLES[1])],[],{},False),('inherited_access',[original,(1001,42,10,True,True,False),auto(ROLES[1])],[],{},False),('set_access',[original,(1001,42,10,True,False,True),auto(ROLES[1])],[],{},False),('extra_unrelated',fresh+[(888,42,10,True,False,False)],[],{},False),('existing_exact',[original],list(ROLES),{},True),('existing_mutated',[(55,42,7,False,True,True)],list(ROLES),{},False),('mixed_exact',[original,auto(ROLES[1])],[ROLES[0]],{},True),('superuser_exact',[original],[],{'superuser':True},True),('superuser_extra',fresh,[],{'superuser':True},False),('not_createrole',fresh,[],{'createrole':False},False),('wrong_bootstrap',fresh,[],{'bootstrap':False},False)]
results=[]
for name,after,existing,options,expected in cases:
 accepted=True
 try:ns['apply'](Database([original],after,existing,**options),constants['EXPANSION'][0])
 except AssertionError:accepted=False
 assert accepted==expected,(name,accepted,expected)
 results.append({'case':name,'accepted':accepted,'expected':expected})
print(json.dumps({'status':'PASS','count':len(results),'cases':results,'scope':'Exact Python assertion only; synthetic catalog results, no database execution.'},indent=2))
