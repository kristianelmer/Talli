import pathlib,types,json,copy,os,hashlib
from talli_backend.authority_tools._filing import payload
p=pathlib.Path(__file__).parent;oldpin=p/'spec-evidence-57df4221';pin=p/'spec-authority-50bfe67a'
raw=(oldpin/'apps/backend/src/talli_backend/authority_tools/_filing.py').read_text();old=types.ModuleType('talli_backend.authority_tools.spec_original_filing');old.__package__='talli_backend.authority_tools';old.__file__=str(oldpin/'apps/backend/src/talli_backend/authority_tools/_filing.py');exec(compile(raw,old.__file__,'exec'),old.__dict__)
os.environ['PATH']='/Users/kristianelmer/.codex/issue-192-private/runtime/node-v24.20.0-darwin-arm64/bin:'+os.environ['PATH']
base=json.loads((pin/'architecture/evidence/issues/153/authority-ownership/legacy-annual-payload-bridge.json').read_text())['cases'][0]['input']
records=[]
for key,value in [('control',None),('annualData',False),('annualData',0),('annualData',-0.0),('annualData',''),('annualData',None),('ledgerEntries',{}),('ledgerEntries',''),('ledgerEntries',[]),('ledgerEntries',None)]:
 x=copy.deepcopy(base)
 if key!='control':x[key]=value
 result={'field':key,'value':value,'input':x}
 for name,fn in [('old',old.payload),('new',payload)]:
  try:
   output=fn('annual_accounts',x);result[name]={'value':output}
  except Exception as e:result[name]={'error':type(e).__name__,'message':str(e)}
 result['same']=result['old']==result['new'];records.append(result)
(p/'authority-spec-actual-bridge-results-50bfe67a.json').write_text(json.dumps(records,ensure_ascii=True,indent=2)+'\n')
print(json.dumps([{'field':r['field'],'value':r['value'],'same':r['same'],'old':list(r['old']),'new':list(r['new'])} for r in records]))
